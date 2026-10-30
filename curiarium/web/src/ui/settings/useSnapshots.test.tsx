// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";

vi.mock("../../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  listSnapshots: vi.fn(),
  takeSnapshot: vi.fn(),
  getSnapshotRetention: vi.fn(),
  updateSnapshotRetention: vi.fn(),
  browseSnapshot: vi.fn(),
  restoreSnapshot: vi.fn(),
  deleteSnapshot: vi.fn(),
}));

import {
  browseSnapshot,
  deleteSnapshot,
  getSnapshotRetention,
  listSnapshots,
  restoreSnapshot,
  takeSnapshot,
  updateSnapshotRetention,
  type SnapshotBrowse,
  type SnapshotCreated,
  type SnapshotDeleteResult,
  type SnapshotList,
  type SnapshotRestore,
  type SnapshotRetention,
} from "../../lib/api";
import { useSnapshots } from "./useSnapshots";

const listSnapshotsMock = vi.mocked(listSnapshots);
const takeSnapshotMock = vi.mocked(takeSnapshot);
const getSnapshotRetentionMock = vi.mocked(getSnapshotRetention);
const updateSnapshotRetentionMock = vi.mocked(updateSnapshotRetention);
const browseSnapshotMock = vi.mocked(browseSnapshot);
const restoreSnapshotMock = vi.mocked(restoreSnapshot);
const deleteSnapshotMock = vi.mocked(deleteSnapshot);

const snapshot = {
  name: "snap-1",
  created_at: "2024-01-01T00:00:00Z",
  age_seconds: 120,
  reason: "manual",
};

const snapshotList: SnapshotList = {
  snapshots: [snapshot],
  method: "cephfs_snapdir",
  supports_browse: true,
  supports_restore: true,
};

const created: SnapshotCreated = {
  snapshot,
  prune: { pruned: 0, kept: 1, names: [] },
};

const retention: SnapshotRetention = {
  keep_last_n: 5,
  keep_daily: 7,
  max_age_days: 30,
  hard_cap: 20,
};

const browse: SnapshotBrowse = { snapshot: "snap-1", path: "", entries: [] };

const restored: SnapshotRestore = {
  snapshot: "snap-1",
  path: "Props/readme.txt",
  destination: "/srv/curiarium/library/Props/readme.txt",
  files: 1,
  bytes: 42,
  scan_started: true,
};

const deleted: SnapshotDeleteResult = { ok: true, name: "snap-1" };

beforeEach(() => {
  listSnapshotsMock.mockReset().mockResolvedValue(snapshotList);
  takeSnapshotMock.mockReset().mockResolvedValue(created);
  getSnapshotRetentionMock.mockReset().mockResolvedValue(retention);
  updateSnapshotRetentionMock.mockReset().mockResolvedValue(retention);
  browseSnapshotMock.mockReset().mockResolvedValue(browse);
  restoreSnapshotMock.mockReset().mockResolvedValue(restored);
  deleteSnapshotMock.mockReset().mockResolvedValue(deleted);
});

afterEach(() => {
  cleanup();
});

describe("useSnapshots", () => {
  it("loads the snapshot list on mount", async () => {
    const { result } = renderHook(() => useSnapshots({ canManage: false }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(listSnapshotsMock).toHaveBeenCalledTimes(1);
    expect(result.current.list?.snapshots[0].name).toBe("snap-1");
    expect(result.current.error).toBeNull();
  });

  it("settles a rejected list into an error without throwing", async () => {
    listSnapshotsMock.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useSnapshots({ canManage: false }));

    await waitFor(() => expect(result.current.error).toBe("Snapshots are unavailable."));
    expect(result.current.list).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("contains a call that throws synchronously before returning a promise", async () => {
    listSnapshotsMock.mockImplementation(() => {
      throw new Error("missing export");
    });

    const { result } = renderHook(() => useSnapshots({ canManage: false }));

    await waitFor(() => expect(result.current.error).toBe("Snapshots are unavailable."));
    expect(result.current.loading).toBe(false);
  });

  it("never fetches retention for a non-admin and fetches it for an admin", async () => {
    const viewer = renderHook(() => useSnapshots({ canManage: false }));
    await waitFor(() => expect(viewer.result.current.loading).toBe(false));
    expect(getSnapshotRetentionMock).not.toHaveBeenCalled();

    const admin = renderHook(() => useSnapshots({ canManage: true }));
    await waitFor(() => expect(admin.result.current.retention).toEqual(retention));
    expect(getSnapshotRetentionMock).toHaveBeenCalledTimes(1);
  });

  it("takes a snapshot, then re-lists and sets a notice", async () => {
    const { result } = renderHook(() => useSnapshots({ canManage: false }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.take();
    });

    expect(takeSnapshotMock).toHaveBeenCalledTimes(1);
    expect(listSnapshotsMock).toHaveBeenCalledTimes(2);
    expect(result.current.notice).toContain("was taken; the reason recorded is manual");
    expect(result.current.busy).toBe(false);
  });

  it("restores a path and reports the destination and file count", async () => {
    const { result } = renderHook(() => useSnapshots({ canManage: false }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.restore("snap-1", "Props/readme.txt");
    });

    expect(restoreSnapshotMock).toHaveBeenCalledWith("snap-1", "Props/readme.txt");
    expect(result.current.notice).toContain("/srv/curiarium/library/Props/readme.txt");
    expect(result.current.notice).toContain("1 file");
  });

  it("saves the clamped policy and adopts the server response", async () => {
    const serverPolicy: SnapshotRetention = {
      keep_last_n: 10,
      keep_daily: 3,
      max_age_days: 1,
      hard_cap: 10,
    };
    updateSnapshotRetentionMock.mockResolvedValue(serverPolicy);

    const { result } = renderHook(() => useSnapshots({ canManage: true }));
    await waitFor(() => expect(result.current.retention).not.toBeNull());

    await act(async () => {
      await result.current.saveRetention({
        keep_last_n: 99,
        keep_daily: 0,
        max_age_days: 1,
        hard_cap: 10,
      });
    });

    expect(updateSnapshotRetentionMock).toHaveBeenCalledWith({
      keep_last_n: 10,
      keep_daily: 0,
      max_age_days: 1,
      hard_cap: 10,
    });
    expect(result.current.retention).toEqual(serverPolicy);
    expect(result.current.notice).toBe("Snapshot retention saved.");
  });

  it("surfaces the server detail when saving retention fails", async () => {
    updateSnapshotRetentionMock.mockRejectedValue(
      new Error("keep_last_n must not exceed hard_cap"),
    );

    const { result } = renderHook(() => useSnapshots({ canManage: true }));
    await waitFor(() => expect(result.current.retention).not.toBeNull());

    await act(async () => {
      await result.current.saveRetention(retention);
    });

    expect(result.current.retentionError).toBe("keep_last_n must not exceed hard_cap");
  });

  it("fetches retention late when canManage flips from false to true", async () => {
    const { result, rerender } = renderHook(
      ({ canManage }: { canManage: boolean }) => useSnapshots({ canManage }),
      { initialProps: { canManage: false } },
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getSnapshotRetentionMock).not.toHaveBeenCalled();

    rerender({ canManage: true });

    await waitFor(() => expect(result.current.retention).toEqual(retention));
    expect(getSnapshotRetentionMock).toHaveBeenCalledTimes(1);
  });
});
