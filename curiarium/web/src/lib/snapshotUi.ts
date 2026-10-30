// Pure presentation helpers for the snapshot card. No React, no fetch: the
// card and the hook pass plain data in and render strings out.

import type {
  SnapshotRetention,
  StorageCapabilities,
  StorageVolumeCapability,
} from "./api";

/**
 * Rendered unconditionally inside the retention block: a library snapshot never
 * covers the SQLite database, whatever volume it lives on.
 */
export const DB_CAVEAT =
  "a library snapshot covers the filesystem only, not the SQLite database; " +
  "pair it with a database backup (see Mf-ljld)";

export type CapabilityGate = {
  capabilities: StorageCapabilities | null;
  loading: boolean;
  error: string | null;
};

/** The volume serving the `library` role, if the server reported one. */
export function libraryVolume(
  capabilities: StorageCapabilities | null,
): StorageVolumeCapability | null {
  const volumes = capabilities?.volumes ?? [];
  return volumes.find(volume => volume.roles.includes("library")) ?? null;
}

/**
 * Why "Take snapshot now" is disabled, or `null` when it is enabled. The
 * loading and error states win over any volume so the button stays disabled
 * while the first capability report is in flight or after it failed.
 */
export function takeSnapshotDisabledReason(state: CapabilityGate): string | null {
  if (state.loading) return "Checking whether this volume can take snapshots…";
  if (state.error) return "The snapshot capability of this volume could not be read.";
  const volume = libraryVolume(state.capabilities);
  if (!volume) return "No library volume was reported for this server.";
  if (!volume.usable) {
    return volume.reason || "This volume cannot take snapshots.";
  }
  return null;
}

/** Human label for the snapshot method the server reports. */
export function snapshotMethodLabel(method: string): string {
  switch (method) {
    case "cephfs_snapdir":
      return "CephFS .snap directory";
    case "zfs_dataset":
      return "ZFS dataset";
    case "btrfs_subvol":
      return "Btrfs subvolume";
    case "local_copy":
      return "local copy";
    case "none":
    case "":
      return "none";
    default:
      return method;
  }
}

/** One sentence describing the active snapshot method. */
export function snapshotMethodLine(method: string): string {
  if (method === "none" || method === "") {
    return "No snapshot method is available on the library volume.";
  }
  return `Snapshots use the ${snapshotMethodLabel(method)} method.`;
}

/** Compact age: `42s ago`, `5m ago`, `3h ago`, `2d ago`. Negative clamps to zero. */
export function formatSnapshotAge(ageSeconds: number): string {
  const seconds = Math.max(0, Math.floor(ageSeconds));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

/** Human label for the recorded snapshot reason; unknown reasons stay raw. */
export function reasonLabel(reason: string): string {
  switch (reason) {
    case "manual":
      return "Manual";
    case "scheduled":
      return "Scheduled";
    case "predelete":
      return "Before a delete";
    case "prepurge":
      return "Before a purge";
    case "prebulk":
      return "Before a bulk change";
    default:
      return reason;
  }
}

/** Truncate to an integer, falling back when the input is not finite. */
function truncOr(value: number, fallback: number): number {
  const truncated = Math.trunc(value);
  return Number.isFinite(truncated) ? truncated : fallback;
}

/**
 * Bring a retention draft back into the range the server accepts. The server
 * has no cross-field clamp, so this is the only guard keeping `keep_last_n`
 * at or below `hard_cap`.
 */
export function clampRetention(policy: SnapshotRetention): SnapshotRetention {
  const hardCap = Math.max(1, truncOr(policy.hard_cap, 1));
  const keepLastN = Math.min(Math.max(1, truncOr(policy.keep_last_n, 1)), hardCap);
  const keepDaily = Math.max(0, truncOr(policy.keep_daily, 0));
  const maxAgeDays = Math.max(1, truncOr(policy.max_age_days, 1));
  return {
    keep_last_n: keepLastN,
    keep_daily: keepDaily,
    max_age_days: maxAgeDays,
    hard_cap: hardCap,
  };
}
