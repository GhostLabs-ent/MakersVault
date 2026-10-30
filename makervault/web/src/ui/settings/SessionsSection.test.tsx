// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// `UnauthorizedError` stays a real subclass: the section branches on `instanceof`.
vi.mock("../../lib/api", () => {
  class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  }
  return {
    UnauthorizedError,
    listSessions: vi.fn(),
    revokeSession: vi.fn(),
  };
});

import SessionsSection from "./SessionsSection";
import { UnauthorizedError, listSessions, revokeSession, type UserSession } from "../../lib/api";

const listSessionsMock = vi.mocked(listSessions);
const revokeSessionMock = vi.mocked(revokeSession);

const currentSession: UserSession = {
  id: "sess-current",
  username: "ada",
  kind: "password",
  device: "Firefox on Linux",
  user_agent: "Mozilla/5.0 (X11; Linux x86_64)",
  client_ip: "10.0.0.5",
  created_at: 1735689600,
  last_used_at: 1735689600,
  current: true,
};

const otherSession: UserSession = {
  id: "sess-other",
  username: "ada",
  kind: "oidc",
  device: null,
  user_agent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
  client_ip: "203.0.113.9",
  created_at: 1735603200,
  last_used_at: 1735603200,
  current: false,
};

beforeEach(() => {
  listSessionsMock.mockReset();
  listSessionsMock.mockResolvedValue([currentSession, otherSession]);
  revokeSessionMock.mockReset();
  revokeSessionMock.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
});

describe("SessionsSection", () => {
  it("renders one card per session with its device label and address", async () => {
    render(<SessionsSection onBack={() => {}} />);

    expect(await screen.findByText("Firefox on Linux")).toBeTruthy();
    expect(
      screen.getByText("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"),
    ).toBeTruthy();
    expect(screen.getByText("10.0.0.5")).toBeTruthy();
    expect(screen.getByText("203.0.113.9")).toBeTruthy();
    expect(listSessionsMock).toHaveBeenCalledTimes(1);
  });

  it("marks the current session and offers no revoke button for it", async () => {
    render(<SessionsSection onBack={() => {}} />);

    expect(await screen.findByText("This device")).toBeTruthy();
    const revokeButtons = screen.getAllByRole("button", { name: "Revoke" });
    expect(revokeButtons.length).toBe(1);
  });

  it("says so when the current session is the only one", async () => {
    listSessionsMock.mockResolvedValue([currentSession]);

    render(<SessionsSection onBack={() => {}} />);

    expect(await screen.findByText(/No other devices are signed in to this account\./)).toBeTruthy();
  });

  it("revokes another session and re-reads the list", async () => {
    render(<SessionsSection onBack={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(revokeSessionMock).toHaveBeenCalledWith("sess-other"));
    await waitFor(() => expect(listSessionsMock).toHaveBeenCalledTimes(2));
  });

  it("shows an inline error instead of throwing when the list fails", async () => {
    listSessionsMock.mockRejectedValue(new Error("boom"));

    render(<SessionsSection onBack={() => {}} />);

    expect(await screen.findByText("Sessions are unavailable right now.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
  });

  it("shows an error and keeps the row when a revoke fails", async () => {
    revokeSessionMock.mockRejectedValue(new Error("nope"));

    render(<SessionsSection onBack={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    expect(await screen.findByText("That device could not be signed out.")).toBeTruthy();
    expect(screen.getByText("203.0.113.9")).toBeTruthy();
    expect(listSessionsMock).toHaveBeenCalledTimes(1);
  });

  it("hands an UnauthorizedError to the caller", async () => {
    const onUnauthorized = vi.fn();
    listSessionsMock.mockRejectedValue(new UnauthorizedError());

    render(<SessionsSection onBack={() => {}} onUnauthorized={onUnauthorized} />);

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Sessions are unavailable right now.")).toBeNull();
  });
});
