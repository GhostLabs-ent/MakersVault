import { SCAN_EXTS } from "./folderScan";
import type { FolderScanState } from "./useFolderScan";

export default function FolderScanCard({
  scanBusy,
  scanStripRoot,
  setScanStripRoot,
  folderInputRef,
  prepareFromFileInput,
  chooseFolder,
  rescan,
  resetScan,
  totalSelected,
  supportedSelected,
  newSelected,
  scanSkipped,
  scanRoot,
  scanStatus,
}: FolderScanState) {
  return (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div>
        <div className="text-lg font-semibold">Local folder scan</div>
        <p className="text-sm opacity-70">
          Select a folder from this device (USB included) and import supported files. The
          folder name becomes a top-level folder, and subfolders stay nested.
        </p>
      </div>
      <p className="text-xs opacity-70">
        Supported extensions: {SCAN_EXTS.join(", ")}. Selecting a folder uploads immediately.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={scanStripRoot}
          onChange={e => setScanStripRoot(e.target.checked)}
          className="w-4 h-4"
        />
        <span>Skip the top-level folder name</span>
      </label>
      <div className="flex items-center gap-2 flex-wrap">
        <input
          ref={folderInputRef}
          type="file"
          onChange={prepareFromFileInput}
          multiple
          className="hidden"
        />
        <button
          className="text-sm px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
          disabled={scanBusy}
          onClick={chooseFolder}
        >
          Choose folder
        </button>
        <button
          className="text-sm px-3 py-2 rounded-md bg-accent hover:bg-accent-strong disabled:opacity-60"
          disabled={scanBusy || supportedSelected === 0}
          onClick={rescan}
        >
          {scanBusy ? "Uploading..." : totalSelected ? "Rescan now" : "Scan now"}
        </button>
        <button
          className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
          disabled={scanBusy || totalSelected === 0}
          onClick={resetScan}
        >
          Clear
        </button>
      </div>
      <div className="text-xs opacity-70">
        {totalSelected
          ? `Selected ${totalSelected} file(s)${
              scanRoot ? ` from "${scanRoot}"` : ""
            }. Ready: ${supportedSelected}. New: ${newSelected}. Skipped: ${scanSkipped}.`
          : "No folder selected yet."}
      </div>
      {scanStatus && (
        <div className="text-xs font-medium">{scanStatus}</div>
      )}
    </div>
  );
}
