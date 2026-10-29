import type { StorageVolumeCapability } from "../../lib/api";
import type { StorageCapabilitiesState } from "./useStorageCapabilities";

const SNAPSHOT_METHOD_LABELS: Record<string, string> = {
  cephfs_snapdir: "CephFS .snap directory",
  zfs_dataset: "ZFS dataset snapshot",
  btrfs_subvol: "Btrfs subvolume snapshot",
  none: "No snapshot method",
};

const ROLE_LABELS: Record<string, string> = {
  library: "Library",
  database: "Database",
};

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

function roleLine(volume: StorageVolumeCapability): string {
  const labels = volume.roles.map(roleLabel);
  return labels.length ? labels.join(" + ") : "Storage volume";
}

function methodLabel(method: string): string {
  return SNAPSHOT_METHOD_LABELS[method] ?? method;
}

function VolumeRow({ volume }: { volume: StorageVolumeCapability }) {
  const usableLabel = volume.usable ? "Usable" : "Not usable";
  const usableClass = volume.usable ? "text-emerald-400" : "text-red-400";

  return (
    <div className="flex flex-col gap-1 rounded-md border border-dashed border-panel-strong p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{roleLine(volume)}</span>
        <span className={`text-xs ${usableClass}`}>{usableLabel}</span>
      </div>
      <div className="flex flex-wrap gap-2 text-xs opacity-80">
        <span>{volume.fstype}</span>
        <span>{methodLabel(volume.snapshot_method)}</span>
      </div>
      <div className="font-mono text-[11px] break-all">{volume.path}</div>
      {volume.mount_point && (
        <div className="text-xs opacity-70">Mounted at {volume.mount_point}</div>
      )}
      {volume.reason && <div className="text-xs opacity-70">{volume.reason}</div>}
    </div>
  );
}

type Props = {
  state: StorageCapabilitiesState;
};

export default function StorageCapabilitiesCard({ state }: Props) {
  const volumes = state.capabilities?.volumes ?? [];
  const ready = !state.loading && !state.error;

  return (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div>
        <div className="text-lg font-semibold">Snapshot capability</div>
        <p className="text-sm opacity-70">
          Detected from the mounted filesystem. Reporting it creates nothing on disk and takes no
          snapshot.
        </p>
      </div>
      {state.loading && <p className="text-sm opacity-70">Checking snapshot capability…</p>}
      {!state.loading && state.error && <p className="text-sm text-red-400">{state.error}</p>}
      {ready && volumes.length === 0 && (
        <p className="text-sm opacity-70">No storage volumes were reported.</p>
      )}
      {ready && volumes.map(volume => <VolumeRow key={volume.path} volume={volume} />)}
    </div>
  );
}
