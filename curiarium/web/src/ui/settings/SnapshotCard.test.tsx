// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("./useSnapshots", () => ({ useSnapshots: vi.fn() }));

import type {
  SnapshotBrowse,
  SnapshotList,
  SnapshotRetention,
  StorageCapabilities,
  StorageVolumeCapability,
} from "../../lib/api";
import { DB_CAVEAT } from "../../lib/snapshotUi";
import SnapshotCard from "./SnapshotCard";
import type { StorageCapabilitiesState } from "./useStorageCapabilities";
import { useSnapshots, type SnapshotsState } from "./useSnapshots";

const useSnapshotsMock = vi.mocked(useSnapshots);

function makeVolume(overrides: Partial<StorageVolumeCapability> = {}): StorageVolumeCapability {
  return {
    roles: ["library"],
    path: "/srv/curiarium/library",
    fstype: "ceph",
    mount_point: "/srv/curiarium",
    snapshot_method: "cephfs_snapdir",
    usable: true,
    reason: "",
    ...overrides,
  };
}

function makeCapabilities(...volumes: StorageVolumeCapability[]): StorageCapabilities {
  return { volumes };
}

function makeCapabilityState(
  capabilities: StorageCapabilities | null,
  loading = false,
  error: string | null = null,
): StorageCapabilitiesState {
  return { capabilities, loading, error, refresh: vi.fn(async () => {}) };
}

const retention: SnapshotRetention = {
  keep_last_n: 5,
  keep_daily: 7,
  max_age_days: 30,
  hard_cap: 20,
};

const snapshotList: SnapshotList = {
  snapshots: [
    {
      name: "snap-1",
      created_at: "2024-01-01T00:00:00Z",
      age_seconds: 120,
      reason: "manual",
    },
  ],
  method: "cephfs_snapdir",
  supports_browse: true,
  supports_restore: true,
};

const browse: SnapshotBrowse = { snapshot: "snap-1", path: "", entries: [] };

function makeState(overrides: Partial<SnapshotsState> = {}): SnapshotsState {
  return {
    list: null,
    loading: false,
    error: null,
    busy: false,
    actionError: null,
    notice: null,
    retention: null,
    retentionLoading: false,
    retentionError: null,
    retentionSaving: false,
    browse: null,
    browseError: null,
    refresh: vi.fn(async () => {}),
    take: vi.fn(async () => {}),
    browseInto: vi.fn(async () => {}),
    closeBrowse: vi.fn(),
    restore: vi.fn(async () => {}),
    remove: vi.fn(async () => {}),
    saveRetention: vi.fn(async () => {}),
    ...overrides,
  };
}

type RenderOptions = {
  state?: Partial<SnapshotsState>;
  capabilities?: StorageCapabilitiesState;
  canManage?: boolean;
};

function renderCard({
  state = {},
  capabilities = makeCapabilityState(makeCapabilities(makeVolume())),
  canManage = true,
}: RenderOptions = {}): void {
  useSnapshotsMock.mockReturnValue(makeState(state));
  render(
    <SnapshotCard
      capabilities={capabilities}
      canManage={canManage}
      onUnauthorized={vi.fn()}
    />,
  );
}

afterEach(() => {
  cleanup();
});

describe("SnapshotCard", () => {
  it("renders the list but no controls or retention editor for a non-admin", () => {
    renderCard({ canManage: false, state: { list: snapshotList } });

    expect(screen.getByText("snap-1")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Take snapshot now" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Browse" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByText("Retention policy")).toBeNull();
  });

  it("enables take-now on a usable library volume", () => {
    renderCard({ state: { list: snapshotList } });

    const take = screen.getByRole("button", { name: "Take snapshot now" }) as HTMLButtonElement;
    expect(take.disabled).toBe(false);
    expect(take.getAttribute("aria-describedby")).toBeNull();
  });

  it("takes a snapshot when take-now is clicked", () => {
    const take = vi.fn(async () => {});
    renderCard({ state: { list: snapshotList, take } });

    fireEvent.click(screen.getByRole("button", { name: "Take snapshot now" }));

    expect(take).toHaveBeenCalledTimes(1);
  });

  it("disables take-now on an unusable volume and shows the server reason verbatim", () => {
    const reason = "No copy-on-write snapshot method is available here.";
    renderCard({
      capabilities: makeCapabilityState(
        makeCapabilities(makeVolume({ usable: false, snapshot_method: "none", reason })),
      ),
    });

    const take = screen.getByRole("button", { name: "Take snapshot now" }) as HTMLButtonElement;
    expect(take.disabled).toBe(true);

    const paragraph = screen.getByText(reason);
    expect(paragraph.id).toBe("snapshot-take-reason");
    expect(take.getAttribute("aria-describedby")).toBe("snapshot-take-reason");
  });

  it("keeps take-now disabled while the capability report loads", () => {
    renderCard({ capabilities: makeCapabilityState(makeCapabilities(makeVolume()), true) });

    const take = screen.getByRole("button", { name: "Take snapshot now" }) as HTMLButtonElement;
    expect(take.disabled).toBe(true);
    expect(
      screen.getByText("Checking whether this volume can take snapshots…"),
    ).toBeTruthy();
  });

  it("keeps take-now disabled after the capability read failed", () => {
    renderCard({
      capabilities: makeCapabilityState(null, false, "Snapshot capability is unavailable."),
    });

    const take = screen.getByRole("button", { name: "Take snapshot now" }) as HTMLButtonElement;
    expect(take.disabled).toBe(true);
    expect(
      screen.getByText("The snapshot capability of this volume could not be read."),
    ).toBeTruthy();
  });

  it("follows the per-provider browse and restore flags, not the capability", () => {
    renderCard({
      state: { list: { ...snapshotList, supports_browse: false, supports_restore: true } },
    });
    expect(screen.queryByRole("button", { name: "Browse" })).toBeNull();
    expect(screen.getByRole("button", { name: "Restore" })).toBeTruthy();

    cleanup();

    renderCard({
      state: { list: { ...snapshotList, supports_browse: true, supports_restore: false } },
    });
    expect(screen.getByRole("button", { name: "Browse" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
  });

  it("renders the retention editor with three number inputs, the hard cap and the caveat", () => {
    renderCard({
      capabilities: makeCapabilityState(makeCapabilities(makeVolume())),
      state: { retention },
    });

    expect(screen.getByText("Retention policy")).toBeTruthy();
    expect(screen.getByLabelText("Keep last N snapshots")).toBeTruthy();
    expect(screen.getByLabelText("Keep daily snapshots for")).toBeTruthy();
    expect(screen.getByLabelText("Delete snapshots older than (days)")).toBeTruthy();
    expect(document.querySelectorAll('input[type="number"]')).toHaveLength(3);
    expect(screen.getByText(/Hard cap: 20 snapshots/)).toBeTruthy();
    expect(screen.getByText(DB_CAVEAT)).toBeTruthy();
  });

  it("renders the caveat even when no volume serves the database role", () => {
    renderCard({
      capabilities: makeCapabilityState(makeCapabilities(makeVolume({ roles: ["library"] }))),
      state: { retention },
    });

    expect(screen.getByText(DB_CAVEAT)).toBeTruthy();
  });

  it("confirms a delete before calling remove with the snapshot name", async () => {
    const remove = vi.fn(async () => {});
    renderCard({ state: { list: snapshotList, remove } });

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(screen.getByText("Delete the snapshot snap-1?")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Delete snapshot" }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith("snap-1"));
  });

  it("shows the empty state and renders each entry's name, reason and age", () => {
    renderCard({ state: { list: { ...snapshotList, snapshots: [] } } });
    expect(screen.getByText("No snapshots have been taken yet.")).toBeTruthy();

    cleanup();

    renderCard({ state: { list: snapshotList } });
    expect(screen.getByText("snap-1")).toBeTruthy();
    expect(screen.getByText(/Manual/)).toBeTruthy();
    expect(screen.getByText(/2m ago/)).toBeTruthy();
  });

  it("renders a browse panel with entries without crashing on an empty browse", () => {
    renderCard({ state: { list: snapshotList, browse } });

    expect(screen.getAllByText("snap-1").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Back to snapshot list" })).toBeTruthy();
  });

  it("descends into a directory, restores one file and walks back up", () => {
    const browseInto = vi.fn(async () => {});
    const restore = vi.fn(async () => {});
    const nested: SnapshotBrowse = {
      snapshot: "snap-1",
      path: "Props/Cable clip",
      entries: [
        { name: "Cable clip.3mf", path: "Props/Cable clip/Cable clip.3mf", is_dir: false, size: 42, modified_at: null },
        { name: "spares", path: "Props/Cable clip/spares", is_dir: true, size: null, modified_at: null },
      ],
    };
    renderCard({ state: { list: snapshotList, browse: nested, browseInto, restore } });

    fireEvent.click(screen.getByRole("button", { name: "spares/" }));
    expect(browseInto).toHaveBeenCalledWith("snap-1", "Props/Cable clip/spares");

    fireEvent.click(screen.getByRole("button", { name: "Restore Cable clip.3mf" }));
    expect(restore).toHaveBeenCalledWith("snap-1", "Props/Cable clip/Cable clip.3mf");

    fireEvent.click(screen.getByRole("button", { name: "Up one level" }));
    expect(browseInto).toHaveBeenCalledWith("snap-1", "Props");
  });
});
