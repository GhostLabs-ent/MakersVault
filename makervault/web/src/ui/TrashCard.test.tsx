// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  getTrash: vi.fn(),
  purgeTrash: vi.fn(),
}));

import TrashCard from "./TrashCard";
import { getTrash, purgeTrash } from "../lib/api";

const getTrashMock = vi.mocked(getTrash);
const purgeTrashMock = vi.mocked(purgeTrash);

describe("TrashCard", () => {
  beforeEach(() => {
    getTrashMock.mockReset();
    getTrashMock.mockResolvedValue({
      entries: [
        { path: ".trash/20261027-abc-old-folder", name: "old-folder", size: 2048, mtime: "2026-10-27T10:00:00Z" },
        { path: ".trash/20261027-def-bits", name: "bits", size: 1024, mtime: "2026-10-27T11:00:00Z" },
      ],
      total_size: 3072,
    });
    purgeTrashMock.mockReset();
    purgeTrashMock.mockResolvedValue({ purged: 2, bytes: 3072, failed: [] });
  });

  afterEach(() => {
    cleanup();
  });

  it("lists trashed folders with formatted sizes and the total", async () => {
    render(<TrashCard />);

    await screen.findByText("old-folder");
    expect(screen.getByText("bits")).toBeTruthy();
    expect(screen.getByText("2.0 KB")).toBeTruthy();
    expect(screen.getByText("1.0 KB")).toBeTruthy();
    expect(screen.getByText(/2 entries · 3\.0 KB/)).toBeTruthy();
  });

  it("only purges after the confirmation dialog is accepted, then refreshes the list", async () => {
    render(<TrashCard />);

    await screen.findByText("old-folder");
    fireEvent.click(screen.getByRole("button", { name: "Empty trash" }));

    expect(screen.getByText("Empty the trash?")).toBeTruthy();
    expect(purgeTrashMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Empty trash permanently" }));

    await waitFor(() => expect(purgeTrashMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getTrashMock).toHaveBeenCalledTimes(2));
    await screen.findByText(/2 entries removed \(3\.0 KB\)/);
  });

  it("renders the empty state when nothing has been deleted", async () => {
    getTrashMock.mockResolvedValue({ entries: [], total_size: 0 });

    render(<TrashCard />);

    await screen.findByText(/The trash is empty/i);
    expect((screen.getByRole("button", { name: "Empty trash" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
