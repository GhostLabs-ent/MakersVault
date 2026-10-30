import type { MountImportSettingsState } from "./useMountImportSettings";

export default function MountImportCard({
  mountEnabled,
  mountCopyFiles,
  mountPath,
  mountInitial,
  mountLoading,
  mountSaving,
  setMountEnabled,
  setMountCopyFiles,
  saveMountSettings,
}: MountImportSettingsState) {
  const mountDirty = mountEnabled !== mountInitial.enabled || mountCopyFiles !== mountInitial.copy;

  return (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div>
        <div className="text-lg font-semibold">Mount import (server)</div>
        <p className="text-sm opacity-70">
          Index files from the server's mounted volume. Enable the no-copy option to keep
          files in place and avoid duplicates.
        </p>
      </div>
      <p className="text-xs opacity-70">
        Mount path: {mountPath || "Not configured"}
      </p>
      <p className="text-xs opacity-70">
        Changes apply on the next server restart. In no-copy mode, mounted files stay read-only and
        renaming is disabled.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={mountEnabled}
          onChange={e => setMountEnabled(e.target.checked)}
          className="w-4 h-4"
          disabled={mountLoading || mountSaving}
        />
        <span>Enable mount import on startup</span>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={mountCopyFiles}
          onChange={e => setMountCopyFiles(e.target.checked)}
          className="w-4 h-4"
          disabled={mountLoading || mountSaving}
        />
        <span>Copy files into Curiarium storage (disable to use mounted files directly)</span>
      </label>
      <div className="flex items-center gap-2 flex-wrap">
        <button
          className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
          disabled={!mountDirty || mountLoading || mountSaving}
          onClick={saveMountSettings}
        >
          {mountSaving ? "Saving..." : "Save"}
        </button>
        {mountLoading && <span className="text-xs opacity-70">Loading settings...</span>}
      </div>
    </div>
  );
}
