// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  listAuditEvents: vi.fn(),
}));

import AuditLog from "./AuditLog";
import { UnauthorizedError, listAuditEvents, type AuditEvent } from "../lib/api";

const listMock = vi.mocked(listAuditEvents);

const baseEvent: AuditEvent = {
  id: "e1",
  created_at: "2026-10-27T13:51:22.123456+00:00",
  actor: "root",
  actor_user_id: "u1",
  actor_role: "admin",
  actor_kind: "password",
  action: "asset.delete",
  target: "asset-1",
  detail: { filename: "cube.stl" },
  request_id: "3f2a1b2c3d4e5f60",
  method: "DELETE",
  path: "/asset/asset-1",
};

function makeEvents(count: number, start = 0): AuditEvent[] {
  return Array.from({ length: count }, (_, index) => {
    const number = start + index + 1;
    return {
      ...baseEvent,
      id: `e${number}`,
      target: `asset-${number}`,
      request_id: `request-${number}`,
      detail: null,
    };
  });
}

function page(events: AuditEvent[], total: number, offset = 0) {
  return { events, total, limit: 50, offset };
}

/** The last query the component sent, without the unset filter keys. */
function lastParams() {
  const calls = listMock.mock.calls;
  const params = calls.length ? calls[calls.length - 1][0] ?? {} : {};
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined));
}

/** Commit a free-text filter the way the page expects it (blur, not debounce). */
function commitFilter(label: string, value: string) {
  const input = screen.getByLabelText(label);
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
}

describe("AuditLog", () => {
  beforeEach(() => {
    listMock.mockReset();
    listMock.mockResolvedValue(page([baseEvent], 1));
  });

  afterEach(() => {
    cleanup();
  });

  it("renders a row from the API response", async () => {
    render(<AuditLog />);

    await screen.findByText("root");
    // The action name is also an option in the filter select, so scope to the table.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("admin · password")).toBeTruthy();
    expect(table.getByText("asset.delete")).toBeTruthy();
    expect(table.getByText("asset-1")).toBeTruthy();
    expect(table.getByText("3f2a1b2c")).toBeTruthy();
    expect(table.getByText('{"filename":"cube.stl"}')).toBeTruthy();
    expect(screen.getByText(new Date(baseEvent.created_at).toLocaleString())).toBeTruthy();
    expect(screen.getByText("Showing 1–1 of 1")).toBeTruthy();
  });

  it("refetches with the query string of each filter and keeps offset at 0", async () => {
    listMock.mockImplementation(async params =>
      page(makeEvents(50), 123, params?.offset ?? 0)
    );
    render(<AuditLog />);

    await screen.findByText("asset-1");

    // Move off the first page, so every filter below has to reset it.
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(lastParams()).toEqual({ limit: 50, offset: 50 }));

    commitFilter("Actor", "root");
    await waitFor(() => expect(lastParams()).toEqual({ actor: "root", limit: 50, offset: 0 }));

    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "asset.delete" } });
    await waitFor(() =>
      expect(lastParams()).toEqual({ actor: "root", action: "asset.delete", limit: 50, offset: 0 })
    );

    commitFilter("Target", "cube");
    await waitFor(() =>
      expect(lastParams()).toEqual({
        actor: "root",
        action: "asset.delete",
        target: "cube",
        limit: 50,
        offset: 0,
      })
    );

    fireEvent.change(screen.getByLabelText("Since"), { target: { value: "2026-10-01" } });
    await waitFor(() =>
      expect(lastParams()).toEqual({
        actor: "root",
        action: "asset.delete",
        target: "cube",
        since: "2026-10-01",
        limit: 50,
        offset: 0,
      })
    );

    fireEvent.change(screen.getByLabelText("Until"), { target: { value: "2026-10-31" } });
    await waitFor(() =>
      expect(lastParams()).toEqual({
        actor: "root",
        action: "asset.delete",
        target: "cube",
        since: "2026-10-01",
        until: "2026-10-31",
        limit: 50,
        offset: 0,
      })
    );

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(lastParams()).toEqual({ limit: 50, offset: 0 }));
  });

  it("pages with Previous/Next and labels the visible range", async () => {
    const total = 123;
    listMock.mockImplementation(async params => {
      const offset = params?.offset ?? 0;
      return page(makeEvents(Math.min(50, total - offset), offset), total, offset);
    });
    render(<AuditLog />);

    await screen.findByText("asset-1");
    expect(screen.getByText("Showing 1–50 of 123")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Showing 51–100 of 123");
    expect(lastParams()).toEqual({ limit: 50, offset: 50 });
    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Showing 101–123 of 123");
    expect(lastParams()).toEqual({ limit: 50, offset: 100 });
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await screen.findByText("Showing 51–100 of 123");
    expect(lastParams()).toEqual({ limit: 50, offset: 50 });
  });

  it("renders the empty state when nothing matches", async () => {
    listMock.mockResolvedValue(page([], 0));

    render(<AuditLog />);

    await screen.findByText("No audit entries match these filters.");
    expect(screen.getByText("Showing 0–0 of 0")).toBeTruthy();
  });

  it("renders the admin notice for a 403 instead of the raw error", async () => {
    listMock.mockRejectedValue(new Error("Your role does not allow this action."));

    render(<AuditLog />);

    await screen.findByText("Administrator access required.");
    expect(screen.queryByText(/Your role does not allow this action/)).toBeNull();
  });

  it("renders the message of any other failure", async () => {
    listMock.mockRejectedValue(new Error("Audit store unavailable"));

    render(<AuditLog />);

    await screen.findByText("Audit store unavailable");
  });

  it("reports an expired session through onUnauthorized", async () => {
    const onUnauthorized = vi.fn();
    listMock.mockRejectedValue(new UnauthorizedError());

    render(<AuditLog onUnauthorized={onUnauthorized} />);

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalledTimes(1));
  });
});
