// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import type { StorageCapabilities, StorageVolumeCapability } from "../../lib/api";
import StorageCapabilitiesCard from "./StorageCapabilitiesCard";
import type { StorageCapabilitiesState } from "./useStorageCapabilities";

function makeVolume(overrides: Partial<StorageVolumeCapability> = {}): StorageVolumeCapability {
  return {
    roles: ["library"],
    path: "/srv/makervault/library",
    fstype: "ceph",
    mount_point: "/srv/makervault",
    snapshot_method: "cephfs_snapdir",
    usable: true,
    reason: "The .snap directory is readable.",
    ...overrides,
  };
}

function makeCapabilities(...volumes: StorageVolumeCapability[]): StorageCapabilities {
  return { volumes };
}

function makeState(
  capabilities: StorageCapabilities | null,
  loading = false,
  error: string | null = null,
): StorageCapabilitiesState {
  return { capabilities, loading, error, refresh: vi.fn(async () => {}) };
}

function renderCard(state: StorageCapabilitiesState): void {
  render(<StorageCapabilitiesCard state={state} />);
}

afterEach(() => {
  cleanup();
});

describe("StorageCapabilitiesCard", () => {
  it("explains that the report is detection only", () => {
    renderCard(makeState(makeCapabilities()));

    expect(screen.getByText("Snapshot capability")).toBeTruthy();
    expect(screen.getByText(/Detected from the mounted filesystem/)).toBeTruthy();
    expect(screen.getByText(/creates nothing on disk and takes no snapshot/)).toBeTruthy();
  });

  it("shows a loading line while the first report runs", () => {
    renderCard(makeState(null, true));

    expect(screen.getByText("Checking snapshot capability…")).toBeTruthy();
    expect(screen.queryByText("No storage volumes were reported.")).toBeNull();
  });

  it("surfaces the detection error instead of the empty state", () => {
    renderCard(makeState(null, false, "Snapshot capability is unavailable."));

    expect(screen.getByText("Snapshot capability is unavailable.")).toBeTruthy();
    expect(screen.queryByText("No storage volumes were reported.")).toBeNull();
  });

  it("says so when no volumes are reported", () => {
    renderCard(makeState(makeCapabilities()));

    expect(screen.getByText("No storage volumes were reported.")).toBeTruthy();
  });

  it("reports a usable CephFS volume", () => {
    renderCard(makeState(makeCapabilities(makeVolume())));

    expect(screen.getByText("Library")).toBeTruthy();
    expect(screen.getByText("ceph")).toBeTruthy();
    expect(screen.getByText("CephFS .snap directory")).toBeTruthy();
    expect(screen.getByText("/srv/makervault/library")).toBeTruthy();
    expect(screen.getByText("/srv/makervault/library").className).toContain("font-mono");
    expect(screen.getByText("Mounted at /srv/makervault")).toBeTruthy();
    expect(screen.getByText("The .snap directory is readable.")).toBeTruthy();

    const usable = screen.getByText("Usable");
    expect(usable.className).toContain("text-emerald-400");
  });

  it("marks an unusable volume and keeps its reason", () => {
    const volume = makeVolume({
      usable: false,
      snapshot_method: "none",
      reason: "No copy-on-write snapshot method is available here.",
      mount_point: "",
    });
    renderCard(makeState(makeCapabilities(volume)));

    const notUsable = screen.getByText("Not usable");
    expect(notUsable.className).toContain("text-red-400");
    expect(screen.getByText("No snapshot method")).toBeTruthy();
    expect(screen.getByText("No copy-on-write snapshot method is available here.")).toBeTruthy();
    expect(screen.queryByText(/Mounted at/)).toBeNull();
  });

  it("labels a volume that serves both roles", () => {
    const volume = makeVolume({ roles: ["library", "database"], snapshot_method: "zfs_dataset" });
    renderCard(makeState(makeCapabilities(volume)));

    expect(screen.getByText("Library + Database")).toBeTruthy();
    expect(screen.getByText("ZFS dataset snapshot")).toBeTruthy();
  });

  it("falls back to the raw method name it does not know", () => {
    renderCard(makeState(makeCapabilities(makeVolume({ snapshot_method: "reflink_copy" }))));

    expect(screen.getByText("reflink_copy")).toBeTruthy();
    expect(screen.queryByText("No snapshot method")).toBeNull();
  });
});
