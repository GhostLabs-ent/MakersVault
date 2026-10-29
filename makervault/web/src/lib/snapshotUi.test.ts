// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import type { StorageCapabilities, StorageVolumeCapability } from "./api";
import {
  DB_CAVEAT,
  clampRetention,
  formatSnapshotAge,
  libraryVolume,
  reasonLabel,
  snapshotMethodLabel,
  snapshotMethodLine,
  takeSnapshotDisabledReason,
} from "./snapshotUi";

function makeVolume(overrides: Partial<StorageVolumeCapability> = {}): StorageVolumeCapability {
  return {
    roles: ["library"],
    path: "/srv/makervault/library",
    fstype: "ceph",
    mount_point: "/srv/makervault",
    snapshot_method: "cephfs_snapdir",
    usable: true,
    reason: "",
    ...overrides,
  };
}

function makeCapabilities(...volumes: StorageVolumeCapability[]): StorageCapabilities {
  return { volumes };
}

describe("DB_CAVEAT", () => {
  it("matches the backend's wording exactly", () => {
    expect(DB_CAVEAT).toBe(
      "a library snapshot covers the filesystem only, not the SQLite database; " +
        "pair it with a database backup (see Mf-ljld)",
    );
  });
});

describe("libraryVolume", () => {
  it("picks the volume with the library role", () => {
    const database = makeVolume({ roles: ["database"], path: "/srv/db" });
    const library = makeVolume({ roles: ["library"], path: "/srv/lib" });

    expect(libraryVolume(makeCapabilities(database, library))).toBe(library);
  });

  it("returns null when no volume serves the library", () => {
    const database = makeVolume({ roles: ["database"] });

    expect(libraryVolume(makeCapabilities(database))).toBeNull();
    expect(libraryVolume(null)).toBeNull();
  });
});

describe("takeSnapshotDisabledReason", () => {
  it("is null when the library volume is usable", () => {
    expect(
      takeSnapshotDisabledReason({
        capabilities: makeCapabilities(makeVolume()),
        loading: false,
        error: null,
      }),
    ).toBeNull();
  });

  it("returns the server reason verbatim when the volume is unusable", () => {
    const reason = "No copy-on-write snapshot method is available here.";
    const state = {
      capabilities: makeCapabilities(makeVolume({ usable: false, reason })),
      loading: false,
      error: null,
    };

    expect(takeSnapshotDisabledReason(state)).toBe(reason);
  });

  it("falls back when an unusable volume carries no reason", () => {
    const state = {
      capabilities: makeCapabilities(makeVolume({ usable: false, reason: "" })),
      loading: false,
      error: null,
    };

    expect(takeSnapshotDisabledReason(state)).toBe("This volume cannot take snapshots.");
  });

  it("reports the loading text while the capability report is in flight", () => {
    const state = {
      capabilities: makeCapabilities(makeVolume()),
      loading: true,
      error: null,
    };

    expect(takeSnapshotDisabledReason(state)).toBe(
      "Checking whether this volume can take snapshots…",
    );
  });

  it("reports the error text when the capability read failed", () => {
    const state = {
      capabilities: null,
      loading: false,
      error: "Snapshot capability is unavailable.",
    };

    expect(takeSnapshotDisabledReason(state)).toBe(
      "The snapshot capability of this volume could not be read.",
    );
  });

  it("reports the missing library volume", () => {
    const state = {
      capabilities: makeCapabilities(makeVolume({ roles: ["database"] })),
      loading: false,
      error: null,
    };

    expect(takeSnapshotDisabledReason(state)).toBe(
      "No library volume was reported for this server.",
    );
  });

  it("keeps the loading text even when a usable volume is already present", () => {
    const state = {
      capabilities: makeCapabilities(makeVolume()),
      loading: true,
      error: null,
    };

    expect(takeSnapshotDisabledReason(state)).toBe(
      "Checking whether this volume can take snapshots…",
    );
  });
});

describe("formatSnapshotAge", () => {
  it("buckets seconds, minutes, hours and days", () => {
    expect(formatSnapshotAge(0)).toBe("0s ago");
    expect(formatSnapshotAge(59)).toBe("59s ago");
    expect(formatSnapshotAge(60)).toBe("1m ago");
    expect(formatSnapshotAge(3599)).toBe("59m ago");
    expect(formatSnapshotAge(3600)).toBe("1h ago");
    expect(formatSnapshotAge(86399)).toBe("23h ago");
    expect(formatSnapshotAge(86400)).toBe("1d ago");
  });

  it("clamps a negative age to zero", () => {
    expect(formatSnapshotAge(-10)).toBe("0s ago");
  });
});

describe("clampRetention", () => {
  it("clamps keep_last_n down to the hard cap", () => {
    expect(
      clampRetention({ keep_last_n: 99, keep_daily: 0, max_age_days: 1, hard_cap: 10 }),
    ).toEqual({ keep_last_n: 10, keep_daily: 0, max_age_days: 1, hard_cap: 10 });
  });

  it("clamps keep_last_n up to at least one", () => {
    expect(
      clampRetention({ keep_last_n: 0, keep_daily: 0, max_age_days: 1, hard_cap: 10 }),
    ).toEqual({ keep_last_n: 1, keep_daily: 0, max_age_days: 1, hard_cap: 10 });
  });

  it("clamps keep_daily, max_age_days and hard_cap to their floors", () => {
    expect(
      clampRetention({ keep_last_n: 1, keep_daily: -5, max_age_days: 0, hard_cap: -3 }),
    ).toEqual({ keep_last_n: 1, keep_daily: 0, max_age_days: 1, hard_cap: 1 });
  });

  it("returns an in-range policy unchanged", () => {
    const policy = { keep_last_n: 3, keep_daily: 2, max_age_days: 7, hard_cap: 10 };
    expect(clampRetention(policy)).toEqual(policy);
  });
});

describe("snapshot method labels", () => {
  it("labels each known method", () => {
    expect(snapshotMethodLabel("cephfs_snapdir")).toBe("CephFS .snap directory");
    expect(snapshotMethodLabel("zfs_dataset")).toBe("ZFS dataset");
    expect(snapshotMethodLabel("btrfs_subvol")).toBe("Btrfs subvolume");
    expect(snapshotMethodLabel("local_copy")).toBe("local copy");
    expect(snapshotMethodLabel("none")).toBe("none");
  });

  it("falls back to the raw method it does not know", () => {
    expect(snapshotMethodLabel("reflink_copy")).toBe("reflink_copy");
  });

  it("describes the active method and the no-method case", () => {
    expect(snapshotMethodLine("cephfs_snapdir")).toBe(
      "Snapshots use the CephFS .snap directory method.",
    );
    expect(snapshotMethodLine("none")).toBe(
      "No snapshot method is available on the library volume.",
    );
    expect(snapshotMethodLine("")).toBe(
      "No snapshot method is available on the library volume.",
    );
  });
});

describe("reasonLabel", () => {
  it("labels every known reason", () => {
    expect(reasonLabel("manual")).toBe("Manual");
    expect(reasonLabel("scheduled")).toBe("Scheduled");
    expect(reasonLabel("predelete")).toBe("Before a delete");
    expect(reasonLabel("prepurge")).toBe("Before a purge");
    expect(reasonLabel("prebulk")).toBe("Before a bulk change");
  });

  it("leaves an unknown reason raw", () => {
    expect(reasonLabel("imported")).toBe("imported");
  });
});
