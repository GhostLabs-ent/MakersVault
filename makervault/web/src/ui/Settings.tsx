import React from "react";
import { AppSettings, ENGRAVER_OPTIONS, PreviewMode, SLICER_OPTIONS, THEME_OPTIONS, ThemeId } from "../lib/settings";
import {
  UnauthorizedError,
  createFolder,
  getMountImportSettings,
  getLibraryScanStatus,
  getStorageSettings,
  startLibraryScan,
  type LibraryScanStatus,
  updateMountImportSettings,
  updateStorageSettings,
} from "../lib/api";
import { entriesFromFileList, uploadEntriesToFolder, type UploadEntry } from "../lib/uploadTree";

type Props = {
  settings: AppSettings;
  onChange: (next: AppSettings) => void;
  onAssetsChanged?: () => void;
  onFoldersChanged?: () => void;
  onUnauthorized?: () => void;
  onSelectFolder?: (id: string | null) => void;
};

type Section = "root" | "slicer" | "engraving" | "theme" | "network" | "previews" | "storage" | "imports";

const THEME_SWATCHES: Record<ThemeId, string> = {
  system: "linear-gradient(135deg, #f8fafc 0%, #f8fafc 50%, #0b0f19 50%, #0b0f19 100%)",
  light: "linear-gradient(135deg, #ffffff, #e2e8f0)",
  dark: "linear-gradient(135deg, #0b0f19, #1f2937)",
  neon: "linear-gradient(135deg, #b6ff2b, #0a1508)",
  purple: "linear-gradient(135deg, #c77dff, #12091f)",
  blue: "linear-gradient(135deg, #74d4ff, #0a1324)",
};

const SCAN_EXTS = ["stl", "3mf", "step", "stp", "obj", "lbrn", "lbrn2"];
const SCAN_EXT_SET = new Set(SCAN_EXTS);
type FileSystemHandle = { kind: "file" | "directory"; name: string };
type FileSystemFileHandle = FileSystemHandle & { getFile: () => Promise<File> };
type FileSystemDirectoryHandle = FileSystemHandle & {
  entries: () => AsyncIterableIterator<[string, FileSystemHandle]>;
};
type DirectoryPicker = () => Promise<FileSystemDirectoryHandle>;

function extOf(name: string) {
  const match = /\.([^.]+)$/.exec(name || "");
  return (match?.[1] || "").toLowerCase();
}

function normalizeRelativePath(path: string) {
  return (path || "").replace(/\\/g, "/").replace(/^\/+/, "");
}

function findRootSegment(entries: UploadEntry[]) {
  if (!entries.length) return "";
  const first = normalizeRelativePath(entries[0].relativePath || entries[0].file.name);
  const parts = first.split("/").filter(Boolean);
  if (parts.length < 2) return "";
  const root = parts[0];
  if (!root) return "";
  for (const entry of entries) {
    const normalized = normalizeRelativePath(entry.relativePath || entry.file.name);
    if (!normalized.startsWith(`${root}/`)) {
      return "";
    }
  }
  return root;
}

function prepareScanEntries(entries: UploadEntry[], rootSegment: string, stripRoot: boolean) {
  const filtered: UploadEntry[] = [];
  let skipped = 0;
  for (const entry of entries) {
    const ext = extOf(entry.file.name);
    if (!SCAN_EXT_SET.has(ext)) {
      skipped += 1;
      continue;
    }
    let relativePath = normalizeRelativePath(entry.relativePath || entry.file.name);
    if (stripRoot && rootSegment) {
      const parts = relativePath.split("/").filter(Boolean);
      if (parts[0] === rootSegment) {
        parts.shift();
        relativePath = parts.join("/");
      }
    }
    if (!relativePath) {
      relativePath = entry.file.name;
    }
    filtered.push({ ...entry, relativePath });
  }
  return { entries: filtered, skipped };
}

async function entriesFromDirectoryHandle(root: FileSystemDirectoryHandle) {
  const output: UploadEntry[] = [];
  const walk = async (dir: FileSystemDirectoryHandle, basePath: string) => {
    for await (const [, handle] of dir.entries()) {
      if (handle.kind === "file") {
        const file = await (handle as FileSystemFileHandle).getFile();
        const relativePath = basePath ? `${basePath}/${handle.name}` : handle.name;
        output.push({ file, relativePath });
      } else if (handle.kind === "directory") {
        const nextPath = basePath ? `${basePath}/${handle.name}` : handle.name;
        await walk(handle as FileSystemDirectoryHandle, nextPath);
      }
    }
  };
  const rootPath = root.name || "";
  await walk(root, rootPath);
  return output;
}

function entryKey(entry: UploadEntry) {
  const relative = normalizeRelativePath(entry.relativePath || entry.file.name);
  return `${relative}::${entry.file.size}::${entry.file.lastModified}`;
}

export default function Settings({
  settings,
  onChange,
  onAssetsChanged,
  onFoldersChanged,
  onUnauthorized,
  onSelectFolder,
}: Props) {
  const [section, setSection] = React.useState<Section>("root");
  const [makerworldDraft, setMakerworldDraft] = React.useState(settings.makerworld.cookie);
  const [thingiverseDraft, setThingiverseDraft] = React.useState(settings.thingiverse.cookie);
  const [makerworldEditing, setMakerworldEditing] = React.useState(!settings.makerworld.cookie);
  const [thingiverseEditing, setThingiverseEditing] = React.useState(!settings.thingiverse.cookie);
  const [networkDraft, setNetworkDraft] = React.useState(settings.network.publicUrl);
  const [mountEnabled, setMountEnabled] = React.useState(false);
  const [mountCopyFiles, setMountCopyFiles] = React.useState(true);
  const [mountPath, setMountPath] = React.useState<string | null>(null);
  const [mountLoading, setMountLoading] = React.useState(false);
  const [mountSaving, setMountSaving] = React.useState(false);
  const [mountInitial, setMountInitial] = React.useState({ enabled: false, copy: true });
  const [storageTemplate, setStorageTemplate] = React.useState("{folder}/{model}/{filename}");
  const [storageInitial, setStorageInitial] = React.useState("{folder}/{model}/{filename}");
  const [storageTokens, setStorageTokens] = React.useState<string[]>([]);
  const [storageSample, setStorageSample] = React.useState("");
  const [storageApplyExisting, setStorageApplyExisting] = React.useState(false);
  const [storageLoading, setStorageLoading] = React.useState(false);
  const [storageSaving, setStorageSaving] = React.useState(false);
  const [storageStatus, setStorageStatus] = React.useState<string | null>(null);
  const [libraryScan, setLibraryScan] = React.useState<LibraryScanStatus | null>(null);
  const [libraryScanBusy, setLibraryScanBusy] = React.useState(false);
  const [libraryScanError, setLibraryScanError] = React.useState<string | null>(null);

  const refreshLibraryScan = React.useCallback(async () => {
    try {
      setLibraryScan(await getLibraryScanStatus());
    } catch {
      // scan status is advisory; a failure must not break the settings page
    }
  }, []);

  React.useEffect(() => {
    if (!libraryScan?.running) return;
    const timer = window.setTimeout(refreshLibraryScan, 1500);
    return () => window.clearTimeout(timer);
  }, [libraryScan, refreshLibraryScan]);

  const runLibraryScan = async () => {
    setLibraryScanBusy(true);
    setLibraryScanError(null);
    try {
      setLibraryScan(await startLibraryScan());
    } catch (err) {
      setLibraryScanError(err instanceof Error ? err.message : "Failed to start scan");
    } finally {
      setLibraryScanBusy(false);
    }
  };
  const [scanRawEntries, setScanRawEntries] = React.useState<UploadEntry[]>([]);
  const [scanEntries, setScanEntries] = React.useState<UploadEntry[]>([]);
  const [scanRoot, setScanRoot] = React.useState("");
  const [scanSkipped, setScanSkipped] = React.useState(0);
  const [scanStatus, setScanStatus] = React.useState<string | null>(null);
  const [scanBusy, setScanBusy] = React.useState(false);
  const [scanStripRoot, setScanStripRoot] = React.useState(false);
  const [scanHandle, setScanHandle] = React.useState<FileSystemDirectoryHandle | null>(null);
  const [scanFolderId, setScanFolderId] = React.useState<string | null>(null);
  const folderInputRef = React.useRef<HTMLInputElement | null>(null);
  const uploadedKeysRef = React.useRef<Set<string>>(new Set());

  const recordUploadedEntries = (entries: UploadEntry[]) => {
    for (const entry of entries) {
      uploadedKeysRef.current.add(entryKey(entry));
    }
  };

  const filterNewEntries = (entries: UploadEntry[]) => {
    return entries.filter(entry => !uploadedKeysRef.current.has(entryKey(entry)));
  };

  const updateScanSelection = (
    rawEntries: UploadEntry[],
    rootLabel: string,
    stripRoot: boolean,
    resetUploaded: boolean
  ) => {
    const { entries, skipped } = prepareScanEntries(rawEntries, rootLabel, stripRoot);
    if (resetUploaded) {
      uploadedKeysRef.current = new Set();
    }
    setScanRawEntries(rawEntries);
    setScanRoot(rootLabel);
    setScanEntries(entries);
    setScanSkipped(skipped);
    return entries;
  };

  const uploadScanEntries = async (
    entries: UploadEntry[],
    note?: string,
    parentFolderId?: string | null
  ) => {
    const fresh = filterNewEntries(entries);
    if (!fresh.length) {
      setScanStatus(note || "No new files to upload.");
      return;
    }
    setScanBusy(true);
    setScanStatus("Uploading...");
    try {
      const result = await uploadEntriesToFolder(fresh, parentFolderId || null, onUnauthorized);
      if (result.uploadedEntries?.length) {
        recordUploadedEntries(result.uploadedEntries);
      } else if (result.uploaded) {
        recordUploadedEntries(fresh);
      }
      if (result.uploaded) {
        onAssetsChanged?.();
        onFoldersChanged?.();
      }
      if (result.failed.length) {
        setScanStatus(`Uploaded ${result.uploaded} file(s). Failed: ${result.failed.length}.`);
      } else {
        setScanStatus(`Uploaded ${result.uploaded} file(s).`);
      }
    } catch (err) {
      console.error("Folder scan upload failed", err);
      setScanStatus("Upload failed. Please try again.");
    } finally {
      setScanBusy(false);
    }
  };

  const ensureRootFolder = async (name: string) => {
    if (!name || scanStripRoot) {
      setScanFolderId(null);
      return null;
    }
    if (scanFolderId && scanRoot === name) return scanFolderId;
    try {
      const created = await createFolder(name, [], undefined);
      const id = (created as { id: string }).id;
      setScanFolderId(id);
      return id;
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return null;
      }
      console.error("Root folder creation failed", err);
      setScanStatus("Failed to create the top-level folder.");
      return null;
    }
  };

  const updateSlicer = (patch: Partial<AppSettings["slicer"]>) => {
    onChange({
      ...settings,
      slicer: {
        ...settings.slicer,
        ...patch,
      },
    });
  };
  const updateEngraving = (patch: Partial<AppSettings["engraving"]>) => {
    onChange({
      ...settings,
      engraving: {
        ...settings.engraving,
        ...patch,
      },
    });
  };
  const updateTheme = (selected: ThemeId) => {
    onChange({
      ...settings,
      theme: {
        selected,
      },
    });
  };
  const updateMakerWorld = (patch: Partial<AppSettings["makerworld"]>) => {
    onChange({
      ...settings,
      makerworld: {
        ...settings.makerworld,
        ...patch,
      },
    });
  };
  const updateThingiverse = (patch: Partial<AppSettings["thingiverse"]>) => {
    onChange({
      ...settings,
      thingiverse: {
        ...settings.thingiverse,
        ...patch,
      },
    });
  };
  const saveMountSettings = async () => {
    setMountSaving(true);
    try {
      const data = await updateMountImportSettings({
        enabled: mountEnabled,
        copy_files: mountCopyFiles,
      });
      setMountEnabled(Boolean(data.enabled));
      setMountCopyFiles(Boolean(data.copy_files));
      setMountPath(data.path || null);
      setMountInitial({ enabled: Boolean(data.enabled), copy: Boolean(data.copy_files) });
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
      } else {
        console.error(err);
      }
    } finally {
      setMountSaving(false);
    }
  };
  const saveStorageSettings = async () => {
    setStorageSaving(true);
    setStorageStatus(null);
    try {
      const data = await updateStorageSettings({
        template: storageTemplate,
        apply_existing: storageApplyExisting,
      });
      setStorageTemplate(data.template);
      setStorageInitial(data.template);
      setStorageTokens(data.allowed_tokens || []);
      setStorageSample(data.sample_path || "");
      setStorageApplyExisting(false);
      setStorageStatus(
        storageApplyExisting
          ? `Saved. Moved ${data.moved} file(s)${data.skipped ? `; skipped ${data.skipped}` : ""}.`
          : "Storage structure saved for new and updated models."
      );
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
      } else {
        setStorageStatus(err instanceof Error ? err.message : "Failed to save storage settings.");
      }
    } finally {
      setStorageSaving(false);
    }
  };
  const updateNetwork = (patch: Partial<AppSettings["network"]>) => {
    onChange({
      ...settings,
      network: {
        ...settings.network,
        ...patch,
      },
    });
  };
  const updatePreviews = (mode: PreviewMode) => {
    onChange({
      ...settings,
      previews: { mode },
    });
  };

  React.useEffect(() => {
    if (section !== "imports") return;
    setMakerworldDraft(settings.makerworld.cookie || "");
    setThingiverseDraft(settings.thingiverse.cookie || "");
    setMakerworldEditing(!settings.makerworld.cookie);
    setThingiverseEditing(!settings.thingiverse.cookie);
  }, [section, settings.makerworld.cookie, settings.thingiverse.cookie]);

  React.useEffect(() => {
    if (section !== "imports") return;
    let active = true;
    setMountLoading(true);
    void (async () => {
      try {
        const data = await getMountImportSettings();
        if (!active) return;
        setMountEnabled(Boolean(data.enabled));
        setMountCopyFiles(Boolean(data.copy_files));
        setMountPath(data.path || null);
        setMountInitial({ enabled: Boolean(data.enabled), copy: Boolean(data.copy_files) });
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
        } else {
          console.error(err);
        }
      } finally {
        if (active) setMountLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [section, onUnauthorized]);

  React.useEffect(() => {
    if (section !== "network") return;
    setNetworkDraft(settings.network.publicUrl || "");
  }, [section, settings.network.publicUrl]);

  React.useEffect(() => {
    if (section !== "storage") return;
    let active = true;
    setStorageLoading(true);
    setStorageStatus(null);
    void (async () => {
      try {
        const data = await getStorageSettings();
        if (!active) return;
        setStorageTemplate(data.template);
        setStorageInitial(data.template);
        setStorageTokens(data.allowed_tokens || []);
        setStorageSample(data.sample_path || "");
      } catch (err) {
        if (err instanceof UnauthorizedError) onUnauthorized?.();
        else setStorageStatus("Failed to load storage settings.");
      } finally {
        if (active) setStorageLoading(false);
      }
    })();
    return () => { active = false; };
  }, [section, onUnauthorized]);

  React.useEffect(() => {
    if (!makerworldEditing) {
      setMakerworldDraft(settings.makerworld.cookie || "");
    }
  }, [settings.makerworld.cookie, makerworldEditing]);

  React.useEffect(() => {
    if (!thingiverseEditing) {
      setThingiverseDraft(settings.thingiverse.cookie || "");
    }
  }, [settings.thingiverse.cookie, thingiverseEditing]);

  React.useEffect(() => {
    if (section !== "imports") return;
    if (!folderInputRef.current) return;
    folderInputRef.current.setAttribute("webkitdirectory", "");
    folderInputRef.current.setAttribute("directory", "");
  }, [section]);

  React.useEffect(() => {
    if (!scanRawEntries.length) {
      setScanEntries([]);
      setScanSkipped(0);
      return;
    }
    const stripRoot = Boolean(scanRoot);
    const { entries, skipped } = prepareScanEntries(scanRawEntries, scanRoot, stripRoot);
    setScanEntries(entries);
    setScanSkipped(skipped);
  }, [scanRawEntries, scanRoot]);

  if (section === "slicer") {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Slicer</h2>
            <p className="text-sm opacity-70">Control the Open in Slicer button for 3D files.</p>
          </div>
          <button
            className="text-sm px-3 py-2 rounded-md border border-panel-strong"
            onClick={() => setSection("root")}
          >
            Back
          </button>
        </div>

        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-4">
          <p className="text-xs opacity-70">
            Requires the Slicer Bridge helper to be installed on each client to register
            the makersvault-slicer:// protocol. Download the installer from{" "}
            <a
              className="underline"
              href="https://github.com/VincentCinque/MakersVault/releases/latest"
              target="_blank"
              rel="noreferrer"
            >
              MakerVault releases
            </a>
            . On Linux, mark the download as executable if prompted.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.slicer.enabled}
              onChange={e => updateSlicer({ enabled: e.target.checked })}
              className="w-4 h-4"
            />
            <span>Enable Open in Slicer</span>
          </label>

          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase tracking-wide text-muted">
              Preferred slicer
            </label>
            <select
              value={settings.slicer.selected}
              onChange={e => updateSlicer({ selected: e.target.value })}
              disabled={!settings.slicer.enabled}
              className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
            >
              {SLICER_OPTIONS.map(opt => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <p className="text-xs opacity-70">
            The Open in Slicer button launches the custom protocol with a signed download URL.
          </p>
        </div>
      </div>
    );
  }

  if (section === "engraving") {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Engraving Software</h2>
            <p className="text-sm opacity-70">Control the Open in Engraving Software button for laser-ready files.</p>
          </div>
          <button
            className="text-sm px-3 py-2 rounded-md border border-panel-strong"
            onClick={() => setSection("root")}
          >
            Back
          </button>
        </div>

        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-4">
          <p className="text-xs opacity-70">
            Requires the Bridge helper to be installed on each client to register
            the makersvault-engrave:// protocol. Download the installer from{" "}
            <a
              className="underline"
              href="https://github.com/VincentCinque/MakersVault/releases/latest"
              target="_blank"
              rel="noreferrer"
            >
              MakerVault releases
            </a>
            . On Linux, mark the download as executable if prompted.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.engraving.enabled}
              onChange={e => updateEngraving({ enabled: e.target.checked })}
              className="w-4 h-4"
            />
            <span>Enable Open in Engraving Software</span>
          </label>

          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase tracking-wide text-muted">
              Preferred engraving software
            </label>
            <select
              value={settings.engraving.selected}
              onChange={e => updateEngraving({ selected: e.target.value })}
              disabled={!settings.engraving.enabled}
              className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
            >
              {ENGRAVER_OPTIONS.map(opt => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <p className="text-xs opacity-70">
            The Open in Engraving Software button launches the custom protocol with a signed download URL.
          </p>
        </div>
      </div>
    );
  }

  if (section === "theme") {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Theme</h2>
            <p className="text-sm opacity-70">Choose how MakerVault looks and feels.</p>
          </div>
          <button
            className="text-sm px-3 py-2 rounded-md border border-panel-strong"
            onClick={() => setSection("root")}
          >
            Back
          </button>
        </div>

        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
          {THEME_OPTIONS.map(option => {
            const selected = settings.theme.selected === option.id;
            return (
              <label
                key={option.id}
                className={`flex items-start gap-3 rounded-md border p-3 cursor-pointer transition ${
                  selected ? "border-accent bg-accent-soft" : "border-panel-strong bg-panel-strong"
                }`}
              >
                <input
                  type="radio"
                  name="theme"
                  value={option.id}
                  checked={selected}
                  onChange={() => updateTheme(option.id)}
                  className="mt-1"
                />
                <span
                  aria-hidden="true"
                  className={`mt-0.5 h-8 w-8 shrink-0 rounded-md border ${
                    selected ? "border-accent" : "border-panel-strong"
                  }`}
                  style={{ backgroundImage: THEME_SWATCHES[option.id] }}
                />
                <div>
                  <div className="font-medium">{option.label}</div>
                  <div className="text-sm text-muted">{option.description}</div>
                </div>
              </label>
            );
          })}
        </div>
      </div>
    );
  }

  if (section === "network") {
    const trimmedUrl = (networkDraft || "").trim().replace(/\/+$/, "");
    const apiPreview = trimmedUrl
      ? (trimmedUrl.endsWith("/api") ? trimmedUrl : `${trimmedUrl}/api`)
      : "Auto (same origin)";
    const isDirty = trimmedUrl !== (settings.network.publicUrl || "");
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Reverse Proxy</h2>
            <p className="text-sm opacity-70">Point the app at your public domain.</p>
          </div>
          <button
            className="text-sm px-3 py-2 rounded-md border border-panel-strong"
            onClick={() => setSection("root")}
          >
            Back
          </button>
        </div>

        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
          <div>
            <div className="text-lg font-semibold">Public URL</div>
            <p className="text-sm opacity-70">
              Use this when MakerVault is available at a reverse proxy domain like
              https://makersvault.local. The API will be called at /api.
            </p>
          </div>
          <p className="text-xs opacity-70">
            This setting is stored in your browser, so each device can point to a different URL if needed.
          </p>
          <div className="text-xs opacity-70 flex flex-col gap-1">
            <span>1) Configure your reverse proxy:</span>
            <span>/ → web:5173</span>
            <span>/api/* → api:8000</span>
            <span>2) Save the public URL below, then open it in your browser.</span>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase tracking-wide text-muted">
              Reverse proxy URL
            </label>
            <input
              type="text"
              value={networkDraft}
              onChange={e => setNetworkDraft(e.target.value)}
              placeholder="https://makersvault.local"
              className="px-3 py-2 rounded-md border border-panel-strong bg-panel-soft text-sm"
            />
          </div>
          <div className="text-xs opacity-70">
            API base: {apiPreview}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
              disabled={!isDirty}
              onClick={() => {
                const next = trimmedUrl;
                updateNetwork({ publicUrl: next });
                setNetworkDraft(next);
              }}
            >
              Save
            </button>
            <button
              className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
              disabled={!settings.network.publicUrl}
              onClick={() => {
                updateNetwork({ publicUrl: "" });
                setNetworkDraft("");
              }}
            >
              Clear
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (section === "storage") {
    const isDirty = storageTemplate.trim() !== storageInitial;
    const previewValues: Record<string, string> = {
      folder: "Props/Workshop",
      collection: "Tabletop",
      tags: "Print in place + Useful",
      creator: "Example creator",
      model: "Cable clip",
      name: "Cable clip",
      filename: "Cable clip.3mf",
      id: "a1b2c3d4",
    };
    const draftSample = Object.entries(previewValues).reduce(
      (value, [token, replacement]) => value.split(`{${token}}`).join(replacement),
      storageTemplate.trim()
    );
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Storage Structure</h2>
            <p className="text-sm opacity-70">Choose how managed model files are organized on disk.</p>
          </div>
          <button className="text-sm px-3 py-2 rounded-md border border-panel-strong" onClick={() => setSection("root")}>Back</button>
        </div>

        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-4">
          <div>
            <div className="text-lg font-semibold">Path template</div>
            <p className="text-sm opacity-70">
              The model name is unique inside its MakerVault folder. Renaming a model also renames its file while preserving the extension.
            </p>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-muted">Template</span>
            <input
              value={storageTemplate}
              onChange={e => { setStorageTemplate(e.target.value); setStorageStatus(null); }}
              className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong font-mono text-sm"
              placeholder="{folder}/{model}/{filename}"
              disabled={storageLoading || storageSaving}
            />
          </label>
          <div className="flex flex-wrap gap-1.5">
            {storageTokens.map(token => (
              <button
                key={token}
                type="button"
                onClick={() => setStorageTemplate(value => {
                  const tokenText = `{${token}}`;
                  if (token === "filename" && value.includes(tokenText)) return value;
                  const filenameSuffix = "/{filename}";
                  if (value.endsWith(filenameSuffix)) {
                    return `${value.slice(0, -filenameSuffix.length)}/${tokenText}${filenameSuffix}`;
                  }
                  return `${value}${value.endsWith("/") || !value ? "" : "/"}${tokenText}`;
                })}
                className="rounded-md border border-panel-strong px-2 py-1 font-mono text-[11px]"
              >
                {`{${token}}`}
              </button>
            ))}
          </div>
          <div className="rounded-md border border-dashed border-panel-strong p-3">
            <div className="text-[10px] uppercase tracking-wide text-muted">Example path</div>
            <div className="mt-1 break-all font-mono text-xs">{draftSample || storageSample || "Enter a template to preview its path"}</div>
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={storageApplyExisting}
              onChange={e => setStorageApplyExisting(e.target.checked)}
              className="mt-0.5 h-4 w-4"
              disabled={storageLoading || storageSaving}
            />
            <span>
              Reorganize existing managed files now
              <span className="block text-xs opacity-70">Mounted no-copy files are skipped. Existing URLs continue to use stable asset IDs.</span>
            </span>
          </label>
          <div className="flex items-center gap-3 flex-wrap">
            <button
              className="text-sm px-3 py-2 rounded-md bg-accent disabled:opacity-60"
              disabled={storageLoading || storageSaving || (!isDirty && !storageApplyExisting)}
              onClick={saveStorageSettings}
            >
              {storageSaving ? "Saving..." : "Save storage structure"}
            </button>
            {storageStatus && <span className="text-xs opacity-80">{storageStatus}</span>}
          </div>
        </div>

        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
          <div>
            <div className="text-lg font-semibold">Files added from outside MakersVault</div>
            <p className="text-sm opacity-70">
              Scan the storage folder and register files you copied in with rsync, cp or another tool.
              Nothing is moved or deleted: files are registered where they already sit, and folders are created from the directory tree.
              Files that have disappeared are counted only, never removed from the library.
            </p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <button
              className="text-sm px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
              disabled={libraryScanBusy || Boolean(libraryScan?.running)}
              onClick={runLibraryScan}
            >
              {libraryScan?.running ? "Scanning..." : "Rescan storage folder"}
            </button>
            {libraryScan && (
              <span className="text-xs opacity-80">
                {libraryScan.running
                  ? "Scan in progress"
                  : `Last scan: ${libraryScan.registered} new, ${libraryScan.known} known, ${libraryScan.missing} missing, ${libraryScan.failed} failed`}
              </span>
            )}
            {libraryScanError && <span className="text-xs text-red-400">{libraryScanError}</span>}
          </div>
          {Boolean(libraryScan?.errors?.length) && (
            <div className="rounded-md border border-dashed border-panel-strong p-3 font-mono text-[11px] break-all">
              {libraryScan?.errors.map((message, index) => <div key={index}>{message}</div>)}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (section === "previews") {
    const options: Array<{ id: PreviewMode; label: string; description: string }> = [
      {
        id: "automatic",
        label: "Automatic",
        description: "Load missing previews only as cards enter view, then save them for future visits.",
      },
      {
        id: "on-demand",
        label: "On demand",
        description: "Show saved previews immediately and generate missing ones only when requested.",
      },
      {
        id: "disabled",
        label: "Disabled",
        description: "Never generate card previews. Interactive viewing remains available by opening a model.",
      },
    ];
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Model Previews</h2>
            <p className="text-sm opacity-70">Control background preview work on this browser.</p>
          </div>
          <button className="text-sm px-3 py-2 rounded-md border border-panel-strong" onClick={() => setSection("root")}>Back</button>
        </div>
        <div className="grid gap-3">
          {options.map(option => (
            <label
              key={option.id}
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 ${
                settings.previews.mode === option.id ? "border-accent bg-accent-soft" : "border-panel bg-panel-soft"
              }`}
            >
              <input
                type="radio"
                name="preview-mode"
                value={option.id}
                checked={settings.previews.mode === option.id}
                onChange={() => updatePreviews(option.id)}
                className="mt-1 h-4 w-4"
              />
              <span>
                <span className="block font-medium">{option.label}</span>
                <span className="block text-sm text-muted">{option.description}</span>
              </span>
            </label>
          ))}
        </div>
        <p className="text-xs opacity-70">
          Embedded 3MF thumbnails and previously generated server thumbnails are always used when available.
        </p>
      </div>
    );
  }

  if (section === "imports") {
    const totalSelected = scanRawEntries.length;
    const supportedSelected = scanEntries.length;
    const newSelected = scanEntries.length ? filterNewEntries(scanEntries).length : 0;
    const mountDirty = mountEnabled !== mountInitial.enabled || mountCopyFiles !== mountInitial.copy;
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Imports</h2>
            <p className="text-sm opacity-70">Manage session cookies and import local folders.</p>
          </div>
          <button
            className="text-sm px-3 py-2 rounded-md border border-panel-strong"
            onClick={() => setSection("root")}
          >
            Back
          </button>
        </div>

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
            <span>Copy files into MakerVault storage (disable to use mounted files directly)</span>
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
              onChange={e => {
                const entries = entriesFromFileList(e.target.files || []);
                if (!entries.length) {
                  setScanRawEntries([]);
                  setScanRoot("");
                  setScanStatus(null);
                  setScanHandle(null);
                  setScanFolderId(null);
                  uploadedKeysRef.current = new Set();
                  return;
                }
                const root = findRootSegment(entries);
                setScanHandle(null);
                setScanFolderId(null);
                const stripRoot = Boolean(root);
                const prepared = updateScanSelection(entries, root, stripRoot, true);
                setScanStatus(null);
                void (async () => {
                  const parentFolderId = await ensureRootFolder(root);
                  await uploadScanEntries(prepared, undefined, parentFolderId);
                  onSelectFolder?.(parentFolderId ?? null);
                })();
                if (folderInputRef.current) folderInputRef.current.value = "";
              }}
              multiple
              className="hidden"
            />
            <button
              className="text-sm px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
              disabled={scanBusy}
              onClick={async () => {
                const picker = typeof window !== "undefined"
                  && (window as unknown as { showDirectoryPicker?: DirectoryPicker }).showDirectoryPicker;
                if (picker) {
                  try {
                    const handle = await picker();
                    const entries = await entriesFromDirectoryHandle(handle);
                    if (!entries.length) {
                      setScanRawEntries([]);
                      setScanRoot(handle.name || "");
                      setScanHandle(handle);
                      setScanFolderId(null);
                      uploadedKeysRef.current = new Set();
                      setScanStatus("No files found in that folder.");
                      return;
                    }
                    setScanHandle(handle);
                    setScanFolderId(null);
                    const rootLabel = handle.name || findRootSegment(entries);
                    const stripRoot = Boolean(rootLabel);
                    const prepared = updateScanSelection(entries, rootLabel, stripRoot, true);
                    setScanStatus(null);
                    void (async () => {
                      const parentFolderId = await ensureRootFolder(rootLabel);
                      await uploadScanEntries(prepared, undefined, parentFolderId);
                      onSelectFolder?.(parentFolderId ?? null);
                    })();
                    return;
                  } catch (err) {
                    if (err instanceof DOMException && err.name === "AbortError") {
                      return;
                    }
                    console.warn("Directory picker failed, falling back to file input", err);
                  }
                }
                if (folderInputRef.current) {
                  folderInputRef.current.setAttribute("webkitdirectory", "");
                  folderInputRef.current.setAttribute("directory", "");
                }
                folderInputRef.current?.click();
              }}
            >
              Choose folder
            </button>
            <button
              className="text-sm px-3 py-2 rounded-md bg-accent hover:bg-accent-strong disabled:opacity-60"
              disabled={scanBusy || supportedSelected === 0}
              onClick={async () => {
                if (scanHandle) {
                  const freshEntries = await entriesFromDirectoryHandle(scanHandle);
                  if (!freshEntries.length) {
                    setScanRawEntries([]);
                    setScanRoot(scanHandle.name || "");
                    setScanEntries([]);
                    setScanSkipped(0);
                    setScanStatus("No files found in that folder.");
                    uploadedKeysRef.current = new Set();
                    setScanFolderId(null);
                    return;
                  }
                  const rootLabel = scanHandle.name || findRootSegment(freshEntries) || scanRoot;
                  const stripRoot = Boolean(rootLabel);
                  const prepared = updateScanSelection(freshEntries, rootLabel, stripRoot, false);
                  const parentFolderId = await ensureRootFolder(rootLabel);
                  await uploadScanEntries(prepared, "No new files to upload.", parentFolderId);
                  onSelectFolder?.(parentFolderId ?? null);
                  return;
                }
                if (!scanEntries.length) {
                  setScanStatus("No supported files selected.");
                  return;
                }
                const parentFolderId = await ensureRootFolder(scanRoot);
                await uploadScanEntries(scanEntries, "No new files to upload.", parentFolderId);
                onSelectFolder?.(parentFolderId ?? null);
              }}
            >
              {scanBusy ? "Uploading..." : scanRawEntries.length ? "Rescan now" : "Scan now"}
            </button>
            <button
              className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
              disabled={scanBusy || totalSelected === 0}
              onClick={() => {
                setScanRawEntries([]);
                setScanRoot("");
                setScanStatus(null);
                setScanHandle(null);
                setScanFolderId(null);
                uploadedKeysRef.current = new Set();
              }}
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

        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
          <div>
            <div className="text-lg font-semibold">MakerWorld</div>
            <p className="text-sm opacity-70">Optional auth for importing MakerWorld models.</p>
          </div>
          <p className="text-xs opacity-70">
            Paste the Cookie header from a logged-in makerworld.com request to lift download limits.
            This value is stored only in your browser.
          </p>
          <div className="flex items-center justify-between gap-3">
            <label className="text-xs uppercase tracking-wide text-muted">
              Session cookie
            </label>
            {makerworldEditing ? (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
                onClick={() => {
                  updateMakerWorld({ cookie: makerworldDraft });
                  setMakerworldEditing(false);
                }}
              >
                Save
              </button>
            ) : (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong"
                onClick={() => setMakerworldEditing(true)}
              >
                Edit
              </button>
            )}
          </div>
          <textarea
            rows={4}
            value={makerworldDraft}
            onChange={e => setMakerworldDraft(e.target.value)}
            placeholder="example: mw_session=...; mw_token=...;"
            readOnly={!makerworldEditing}
            className={`px-3 py-2 rounded-md border border-panel-strong bg-panel-soft text-sm ${
              makerworldEditing ? "" : "opacity-70"
            }`}
          />
        </div>

        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
          <div>
            <div className="text-lg font-semibold">Thingiverse</div>
            <p className="text-sm opacity-70">Optional auth for importing Thingiverse models.</p>
          </div>
          <p className="text-xs opacity-70">
            Paste your Thingiverse Cookie header to pass Cloudflare checks when importing.
            This value is stored only in your browser.
          </p>
          <div className="flex items-center justify-between gap-3">
            <label className="text-xs uppercase tracking-wide text-muted">
              Session cookie
            </label>
            {thingiverseEditing ? (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
                onClick={() => {
                  updateThingiverse({ cookie: thingiverseDraft });
                  setThingiverseEditing(false);
                }}
              >
                Save
              </button>
            ) : (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong"
                onClick={() => setThingiverseEditing(true)}
              >
                Edit
              </button>
            )}
          </div>
          <textarea
            rows={4}
            value={thingiverseDraft}
            onChange={e => setThingiverseDraft(e.target.value)}
            placeholder="example: cf_clearance=...; PHPSESSID=...;"
            readOnly={!thingiverseEditing}
            className={`px-3 py-2 rounded-md border border-panel-strong bg-panel-soft text-sm ${
              thingiverseEditing ? "" : "opacity-70"
            }`}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => setSection("slicer")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Slicer</div>
          <div className="text-lg font-semibold">Open in Slicer</div>
          <div className="text-sm opacity-70">Pick a slicer for 3D model downloads.</div>
        </button>
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => setSection("engraving")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Engraving</div>
          <div className="text-lg font-semibold">Open in Engraving Software</div>
          <div className="text-sm opacity-70">Pick a laser app for vector and image files.</div>
        </button>
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => setSection("theme")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Theme</div>
          <div className="text-lg font-semibold">Appearance</div>
          <div className="text-sm opacity-70">Switch between light, dark, and neon colors.</div>
        </button>
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => setSection("network")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Reverse Proxy</div>
          <div className="text-lg font-semibold">Public URL</div>
          <div className="text-sm opacity-70">Set the domain for proxied access.</div>
        </button>
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => setSection("previews")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Performance</div>
          <div className="text-lg font-semibold">Model Previews</div>
          <div className="text-sm opacity-70">Choose automatic, on-demand, or disabled preview generation.</div>
        </button>
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => setSection("storage")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Files</div>
          <div className="text-lg font-semibold">Storage Structure</div>
          <div className="text-sm opacity-70">Organize files with folders, model names, creators, tags, and collections.</div>
        </button>
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => setSection("imports")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Imports</div>
          <div className="text-lg font-semibold">Imports & Folder Scan</div>
          <div className="text-sm opacity-70">Manage import cookies and scan local folders.</div>
        </button>
      </div>
    </div>
  );
}
