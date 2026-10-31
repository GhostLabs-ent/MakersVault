// @vitest-environment jsdom
import { renderHook, act, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLibraryScan } from "./useLibraryScan";

const getStatus = vi.fn();
const startScan = vi.fn();

vi.mock("../../lib/api", () => ({
  getLibraryScanStatus: () => getStatus(),
  startLibraryScan: () => startScan(),
}));

const finished = { running: false, finished_at: 100, registered: 3, known: 0, ignored: 0, missing: 0, failed: 0, errors: [] };
const running = { ...finished, running: true, finished_at: null };

afterEach(() => {
  vi.useRealTimers();
});

describe("useLibraryScan", () => {
  it("reloads the sidebar and the grid when a scan finishes", async () => {
    // Live-testing regression: a rescan registered the files and created the
    // folders, but the folder tree stayed stale until a manual page reload.
    vi.useFakeTimers();
    const onFoldersChanged = vi.fn();
    const onAssetsChanged = vi.fn();
    startScan.mockResolvedValue(running);
    getStatus.mockResolvedValue(finished);

    const { result } = renderHook(() => useLibraryScan({ onFoldersChanged, onAssetsChanged }));

    await act(async () => {
      await result.current.run();
    });
    // the hook polls 1.5 s after a running scan
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });

    expect(onFoldersChanged).toHaveBeenCalledTimes(1);
    expect(onAssetsChanged).toHaveBeenCalledTimes(1);
  });

  it("does not fire again while polling the same finished scan", async () => {
    const onFoldersChanged = vi.fn();
    startScan.mockResolvedValue(finished);
    getStatus.mockResolvedValue(finished);

    const { result, rerender } = renderHook(() => useLibraryScan({ onFoldersChanged, onAssetsChanged: vi.fn() }));

    await act(async () => {
      await result.current.run();
    });
    await waitFor(() => expect(onFoldersChanged).toHaveBeenCalledTimes(1));

    rerender();
    await new Promise(resolve => setTimeout(resolve, 50));
    expect(onFoldersChanged).toHaveBeenCalledTimes(1);
  });
});
