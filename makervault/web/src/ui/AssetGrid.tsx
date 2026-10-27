import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Asset,
  AssetFile,
  PreparedPrint,
  Folder,
  UnauthorizedError,
  deleteAsset,
  fileUrl,
  listAssets,
  listTags,
  listFolders,
  setTags,
  updateAssetFolder,
  updateAssetMeta,
  downloadZip,
  deleteAssetFile,
  deletePreparedPrint,
  getLibraryScanStatus,
  listAssetFiles,
  startLibraryScan,
  uploadAssetFile,
} from "../lib/api";
import ModelViewer, { ModelSnapshot } from "./ModelViewer";
import LightBurnPreview from "./LightBurnPreview";
import TagBadge from "./TagBadge";
import TagInput from "./TagInput";
import { colorForTag } from "./tagColors";
import { refreshWindow } from "../lib/assetPaging";
import { useStableCallback } from "../lib/useStableCallback";
import { formatBytes } from "../lib/format";
import { EngravingSettings, PreviewSettings, ResolvedTheme, SlicerSettings, engraverLabelFor, slicerLabelFor } from "../lib/settings";
import { entriesFromDataTransfer, uploadEntriesToFolder } from "../lib/uploadTree";
import { buildUploadEntriesFromZip, isZipFile, readZipEntries } from "../lib/zipUtils";
import { useZipImportPrompt } from "./ZipImportModal";

function extOf(name: string) {
  const m = /\.([^.]+)$/.exec(name);
  return (m?.[1] || "").toLowerCase();
}

const MODEL_EXTS = new Set(["stl", "3mf", "step", "stp", "obj"]);
const LIGHTBURN_EXTS = new Set(["lbrn", "lbrn2"]);
const ENGRAVING_EXTS = new Set([
  "svg",
  "dxf",
  "ai",
  "eps",
  "pdf",
  "plt",
  "hpgl",
  "png",
  "jpg",
  "jpeg",
  "bmp",
  "gif",
  "tif",
  "tiff",
  "lbrn",
  "lbrn2",
  "ezd",
]);

const ROWS_PER_BATCH = 5;
const CARD_MIN_WIDTH_PX = 260;
const GRID_GAP_PX = 16;
/** Upper bound on how long a re-scan triggered from a card is polled. */
const RESCAN_TIMEOUT_MS = 10 * 60 * 1000;
const RESCAN_POLL_INTERVAL_MS = 1000;

function formatMissingSince(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function rowsBatchSizeForWidth(width: number) {
  const cols = Math.max(1, Math.floor((width + GRID_GAP_PX) / (CARD_MIN_WIDTH_PX + GRID_GAP_PX)));
  return cols * ROWS_PER_BATCH;
}

type Props = {
  folderId?: string | null;
  foldersVersion?: number;
  assetsVersion?: number;
  onUnauthorized?: () => void;
  slicerSettings?: SlicerSettings;
  engravingSettings?: EngravingSettings;
  previewSettings?: PreviewSettings;
  theme: ResolvedTheme;
};

type RefreshOpts = { tags?: string[]; search?: string; keepLoadedPages?: boolean };
type GroupBucket = { id: string; title: string; items: Asset[] };

/**
 * Search box + button.
 *
 * Defined at module scope (and owning its own `value` state) so typing never
 * re-renders the grid or the cards, and so the input instance survives grid
 * re-renders (refetches) instead of being remounted.
 */
function AssetSearch({
  onQueryChange,
  onSearch,
  disabled,
}: {
  onQueryChange: (query: string) => void;
  onSearch: (query: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");
  return (
    <>
      <input
        value={value}
        onChange={e => {
          setValue(e.target.value);
          onQueryChange(e.target.value);
        }}
        onKeyDown={e => {
          if (e.key === "Enter") onSearch(value);
        }}
        placeholder="Search title, filename, notes..."
        className="px-3 py-2 rounded-md border border-panel-strong bg-panel-soft w-80"
      />
      <button
        className="px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
        onClick={() => onSearch(value)}
        disabled={disabled}
      >
        Search
      </button>
    </>
  );
}

export default function AssetGrid({
  folderId,
  foldersVersion = 0,
  assetsVersion = 0,
  onUnauthorized,
  slicerSettings,
  engravingSettings,
  previewSettings,
  theme,
}: Props) {
  const [items, setItems] = useState<Asset[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  // Latest typed query. Held in a ref (not state) so typing does not re-render
  // the grid; only submitting a search refetches.
  const queryRef = useRef("");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [previewItem, setPreviewItem] = useState<Asset | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const [movingId, setMovingId] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<"name" | "size" | "type" | "folder">("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDownloading, setBulkDownloading] = useState<string | null>(null);
  const [pageSize] = useState<number>(() => {
    if (typeof window === "undefined") return ROWS_PER_BATCH;
    return rowsBatchSizeForWidth(window.innerWidth);
  });
  const dragDepth = useRef(0);
  const [dragActive, setDragActive] = useState(false);
  const [dropUploading, setDropUploading] = useState(false);
  const slicerEnabled = Boolean(slicerSettings?.enabled);
  const slicerLabel = slicerLabelFor(slicerSettings?.selected);
  const engravingEnabled = Boolean(engravingSettings?.enabled);
  const engraverLabel = engraverLabelFor(engravingSettings?.selected);
  const zipPrompt = useZipImportPrompt();

  const handleApiError = useStableCallback((err: unknown, message?: string) => {
    if (err instanceof UnauthorizedError) {
      onUnauthorized?.();
      return true;
    }
    console.error(err);
    if (message) alert(message);
    return false;
  });

  const replaceAsset = useStableCallback((updated: Asset) => {
    setItems(current => current.map(item => item.id === updated.id ? updated : item));
    setPreviewItem(current => current?.id === updated.id ? updated : current);
  });

  const refresh = useStableCallback(async (opts: RefreshOpts = {}) => {
    setLoading(true);
    if (!opts.keepLoadedPages) {
      setHasMore(false);
      setOffset(0);
    }
    const search = opts.search ?? queryRef.current;
    const tags = opts.tags ?? activeTags;
    const targetFolderId = folderId || undefined;
    const paging = refreshWindow(offset, pageSize, opts.keepLoadedPages);
    const [assetsResult, tagsResult] = await Promise.allSettled([
      listAssets({
        q: search,
        tags,
        folder_id: targetFolderId,
        limit: paging.limit,
        offset: paging.offset,
      }),
      listTags({
        q: search,
        folder_id: targetFolderId,
      }),
    ]);

    if (assetsResult.status === "fulfilled") {
      setItems(assetsResult.value.items);
      setOffset(assetsResult.value.items.length);
      setHasMore(assetsResult.value.hasMore);
    } else {
      handleApiError(assetsResult.reason, "Failed to load assets. Please sign in again or refresh.");
    }

    if (tagsResult.status === "fulfilled") {
      setAllTags(tagsResult.value);
    } else {
      setAllTags([]);
      handleApiError(tagsResult.reason);
    }

    setLoading(false);
  });

  const loadMore = useStableCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const data = await listAssets({
        q: queryRef.current,
        tags: activeTags,
        folder_id: folderId || undefined,
        limit: pageSize,
        offset,
      });
      setItems(prev => [...prev, ...data.items]);
      setOffset(offset + data.items.length);
      setHasMore(data.hasMore);
    } catch (err) {
      handleApiError(err, "Failed to load more assets.");
    } finally {
      setLoadingMore(false);
    }
  });

  const isFileDrag = (e: React.DragEvent<HTMLDivElement>) => {
    const types = Array.from(e.dataTransfer?.types || []);
    return types.includes("Files");
  };

  const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current += 1;
    setDragActive(true);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current = 0;
    setDragActive(false);
    setDropUploading(true);
    const entries = await entriesFromDataTransfer(e.dataTransfer);
    if (!entries.length) {
      setDropUploading(false);
      return;
    }
    const normalEntries = entries.filter(entry => !isZipFile(entry.file.name));
    const zipEntries = entries.filter(entry => isZipFile(entry.file.name));
    let uploaded = 0;
    const failed: string[] = [];
    const applyResult = (result: { uploaded: number; failed: string[] }) => {
      uploaded += result.uploaded;
      failed.push(...result.failed);
    };
    if (normalEntries.length) {
      const result = await uploadEntriesToFolder(normalEntries, folderId || null, onUnauthorized);
      applyResult(result);
    }
    for (const entry of zipEntries) {
      let zipData: Record<string, Uint8Array> | null = null;
      const baseParts = entry.relativePath.split("/").filter(Boolean);
      baseParts.pop();
      const basePath = baseParts.join("/");
      await zipPrompt.prompt({
        label: entry.file.name,
        onImportAsZip: async () => {
          const result = await uploadEntriesToFolder([entry], folderId || null, onUnauthorized);
          applyResult(result);
        },
        loadEntries: async () => {
          const result = await readZipEntries(entry.file);
          zipData = result.data;
          return result.entries;
        },
        onImportSelected: async (selectedPaths: string[]) => {
          if (!zipData) {
            const result = await readZipEntries(entry.file);
            zipData = result.data;
          }
          const unzipEntries = buildUploadEntriesFromZip(zipData || {}, selectedPaths, basePath);
          const result = await uploadEntriesToFolder(unzipEntries, folderId || null, onUnauthorized);
          applyResult(result);
        },
      });
    }
    if (uploaded) {
      await refresh({ keepLoadedPages: true });
    }
    if (failed.length) {
      alert(`Failed to upload: ${failed.join(", ")}`);
    }
    setDropUploading(false);
  };

  useEffect(() => { refresh(); }, [folderId, refresh]);
  // `assetsVersion` bumps when another view (upload, folder scan) changed
  // assets. Refetch in place instead of remounting: the ref is seeded with the
  // current version so mounting performs no extra fetch, and comparing values
  // makes the effect idempotent under StrictMode's double mount.
  // The refetch is keyed on the version value; `refresh` is referentially
  // stable (useStableCallback), so listing it as a dependency cannot loop, and
  // the ref guard keeps the effect idempotent under StrictMode.
  // Invariant: no call site bumps `assetsVersion` and `folderId` in the same
  // commit; if one ever does, that is two refreshes.
  const seenAssetsVersion = useRef(assetsVersion);
  useEffect(() => {
    if (seenAssetsVersion.current === assetsVersion) return;
    seenAssetsVersion.current = assetsVersion;
    refresh({ keepLoadedPages: true });
  }, [assetsVersion, refresh]);
  useEffect(() => {
    (async () => {
      try {
        setFolders(await listFolders());
      } catch (err) {
        handleApiError(err, "Failed to load folders. Please refresh.");
      }
    })();
  }, [foldersVersion]);

  useEffect(() => {
    const present = new Set(items.map(i => i.id));
    setSelectedIds(prev => new Set([...prev].filter(id => present.has(id))));
  }, [items]);

  const itemById = useMemo(() => {
    const map: Record<string, Asset> = {};
    items.forEach(it => { map[it.id] = it; });
    return map;
  }, [items]);

  const folderById = useMemo(() => {
    const map: Record<string, Folder> = {};
    folders.forEach(f => { map[f.id] = f; });
    return map;
  }, [folders]);

  const dropTargetName = useMemo(() => {
    if (!folderId) return "All Items";
    return folderById[folderId]?.name || "this folder";
  }, [folderId, folderById]);

  const folderNames = useMemo(() => {
    const m: Record<string, string> = {};
    const pathFor = (f: Folder): string => {
      const parts = [f.name || "Untitled"];
      let current = f;
      const guard = new Set<string>([f.id]);
      while (current.parent_id) {
        const parent = folderById[current.parent_id];
        if (!parent || guard.has(parent.id)) break;
        parts.unshift(parent.name || "Untitled");
        guard.add(parent.id);
        current = parent;
      }
      return parts.join(" / ");
    };
    for (const f of folders) {
      m[f.id] = pathFor(f);
    }
    return m;
  }, [folders, folderById]);

  const folderOptions = useMemo(() => {
    return [
      { id: null as string | null, name: "Unassigned" },
      ...folders
        .map(f => ({ id: f.id, name: folderNames[f.id] || f.name || "Untitled" }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    ];
  }, [folders, folderNames]);

  const sortedItems = useMemo(() => {
    const copy = [...items];
    const dir = sortDir === "asc" ? 1 : -1;
    const nameForFolder = (a: Asset) => (a.folder_id ? folderNames[a.folder_id] || "" : "");
    copy.sort((a, b) => {
      if (sortKey === "size") {
        return (a.size - b.size) * dir;
      }
      if (sortKey === "type") {
        return extOf(a.filename).localeCompare(extOf(b.filename)) * dir;
      }
      if (sortKey === "folder") {
        return nameForFolder(a).localeCompare(nameForFolder(b)) * dir;
      }
      // default name
      return a.filename.localeCompare(b.filename) * dir;
    });
    return copy;
  }, [items, sortKey, sortDir, folderNames]);

  const folderGroups = useMemo<GroupBucket[]>(() => {
    if (sortKey !== "folder") return [];
    const grouping: Record<string, GroupBucket> = {};
    for (const item of items) {
      const key = item.folder_id || "__ungrouped";
      if (!grouping[key]) {
        grouping[key] = {
          id: `folder:${key}`,
          title: item.folder_id ? folderNames[item.folder_id] || "Untitled" : "Unassigned",
          items: [],
        };
      }
      grouping[key].items.push(item);
    }
    const dir = sortDir === "asc" ? 1 : -1;
    return Object.values(grouping)
      .sort((a, b) => a.title.localeCompare(b.title) * dir)
      .map(group => ({
        ...group,
        items: group.items.sort((a, b) => a.filename.localeCompare(b.filename)),
      }));
  }, [items, folderNames, sortKey, sortDir]);

  const typeGroups = useMemo<GroupBucket[]>(() => {
    if (sortKey !== "type") return [];
    const grouping: Record<string, GroupBucket> = {};
    for (const item of items) {
      const ext = extOf(item.filename) || "other";
      if (!grouping[ext]) {
        grouping[ext] = {
          id: `type:${ext}`,
          title: ext === "other" ? "Other" : ext.toUpperCase(),
          items: [],
        };
      }
      grouping[ext].items.push(item);
    }
    const dir = sortDir === "asc" ? 1 : -1;
    return Object.values(grouping)
      .sort((a, b) => a.title.localeCompare(b.title) * dir)
      .map(group => ({
        ...group,
        items: group.items.sort((a, b) => a.filename.localeCompare(b.filename)),
      }));
  }, [items, sortKey, sortDir]);

  const toggleGroup = (id: string) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleTag = (t: string) => {
    const next = activeTags.includes(t) ? activeTags.filter(x => x !== t) : [...activeTags, t];
    setActiveTags(next);
    refresh({ tags: next });
  };

  const toggleSelected = useStableCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  });

  const filenameFromDisposition = (res: Response, fallback: string) => {
    const dispo = res.headers.get("content-disposition") || "";
    const match = dispo.match(/filename="?([^";]+)"?/i);
    return (match && match[1]) || fallback || "download";
  };

  const saveResponseToDisk = async (res: Response, fallback: string) => {
    const filename = filenameFromDisposition(res, fallback);
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
  };

  const onSaveTags = useStableCallback(async (id: string, tags: string[]) => {
    const bulkEdit = selectedIds.has(id) && selectedIds.size > 1;
    const targets = bulkEdit ? Array.from(selectedIds) : [id];
    const failed: string[] = [];
    let aborted = false;
    for (const targetId of targets) {
      try {
        await setTags(targetId, tags);
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
          aborted = true;
          break;
        }
        console.error(err);
        failed.push(itemById[targetId]?.filename || targetId);
      }
    }
    if (!aborted) {
      await refresh({ keepLoadedPages: true });
    }
    if (failed.length) {
      alert(`Tag update failed for: ${failed.join(", ")}`);
    }
  });

  const onSaveDetails = useStableCallback(async (id: string, payload: { notes: string; creator: string; collection: string }) => {
    try {
      await updateAssetMeta(id, payload);
      await refresh();
    } catch (err) {
      handleApiError(err, err instanceof Error ? err.message : "Failed to save model details.");
    }
  });

  const onRename = useStableCallback(async (id: string, name: string) => {
    try {
      await updateAssetMeta(id, { name });
      await refresh();
    } catch (err) {
      handleApiError(err, err instanceof Error ? err.message : "Rename failed. Please try again.");
      throw err;
    }
  });

  const onMoveFolder = useStableCallback(async (id: string, folder_id: string | null) => {
    try {
      setMovingId(id);
      await updateAssetFolder(id, folder_id);
      await refresh();
    } catch (err) {
      if (!handleApiError(err)) {
        alert(err instanceof Error ? err.message : "Folder update failed. Please try again.");
      }
    } finally {
      setMovingId(null);
    }
  });

  const downloadAsset = useStableCallback(async (asset: Asset) => {
    try {
      setDownloadingId(asset.id);
      const res = await fetch(fileUrl(asset.url));
      if (res.status === 401) {
        onUnauthorized?.();
        throw new Error("Unauthorized");
      }
      if (!res.ok) throw new Error("Download failed");
      await saveResponseToDisk(res, asset.filename || "download");
    } catch (err) {
      if (!handleApiError(err)) {
        console.error(err);
        alert("Download failed. Please try again.");
      }
    } finally {
      setDownloadingId(null);
    }
  });

  const openInSlicer = useStableCallback((asset: Asset) => {
    if (!slicerEnabled) return;
    const url = fileUrl(asset.slicer_url || asset.url);
    const params = new URLSearchParams({
      url,
      slicer: slicerSettings?.selected || "orca",
      filename: asset.slicer_filename || asset.filename || "model",
    });
    const target = `makersvault-slicer://open?${params.toString()}`;
    window.location.href = target;
  });

  const openInEngraving = useStableCallback((asset: Asset) => {
    if (!engravingEnabled) return;
    const url = fileUrl(asset.url);
    const params = new URLSearchParams({
      url,
      engraver: engravingSettings?.selected || "lightburn",
      filename: asset.filename || "design",
    });
    const target = `makersvault-engrave://open?${params.toString()}`;
    window.location.href = target;
  });

  const downloadSelected = useStableCallback(async () => {
    if (!selectedIds.size) {
      alert("Select at least one item to download.");
      return;
    }
    try {
      setBulkDownloading("selected");
      const res = await downloadZip({ asset_ids: Array.from(selectedIds) });
      await saveResponseToDisk(res, "makersvault-selected.zip");
    } catch (err) {
      if (!handleApiError(err, "Bulk download failed.")) {
        console.error(err);
      }
    } finally {
      setBulkDownloading(null);
    }
  });

  const downloadByTag = useStableCallback(async (tag: string) => {
    if (!tag) return;
    try {
      setBulkDownloading(`tag:${tag}`);
      const res = await downloadZip({ tag });
      await saveResponseToDisk(res, `${tag}.zip`);
    } catch (err) {
      if (!handleApiError(err, "Download by tag failed.")) {
        console.error(err);
      }
    } finally {
      setBulkDownloading(null);
    }
  });

  const removeAsset = useStableCallback(async (asset: Asset) => {
    const targets = selectedIds.has(asset.id) && selectedIds.size > 1
      ? Array.from(selectedIds)
      : [asset.id];
    const confirmLabel = targets.length > 1
      ? `Delete ${targets.length} selected items? This cannot be undone.`
      : `Delete "${asset.title || asset.filename}"? This cannot be undone.`;
    if (!confirm(confirmLabel)) {
      return;
    }
    setDeletingId(asset.id);
    const failed: string[] = [];
    let aborted = false;
    for (const targetId of targets) {
      try {
        await deleteAsset(targetId);
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
          aborted = true;
          break;
        }
        console.error(err);
        failed.push(itemById[targetId]?.filename || targetId);
      }
    }
    if (!aborted) {
      await refresh();
    }
    if (failed.length) {
      alert(`Delete failed for: ${failed.join(", ")}`);
    }
    setDeletingId(null);
  });

  const forgetMissingAsset = useStableCallback(async (asset: Asset) => {
    const label = `Forget "${asset.title || asset.filename}"? The file is already gone; this removes the library entry, thumbnail and sidecars.`;
    if (!confirm(label)) return;
    setDeletingId(asset.id);
    try {
      await deleteAsset(asset.id);
      await refresh();
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      console.error(err);
      alert(`Forget failed for: ${asset.filename}`);
    } finally {
      setDeletingId(null);
    }
  });

  const rescanMissing = useStableCallback(async (_asset: Asset) => {
    if (rescanning) return;
    setRescanning(true);
    try {
      await startLibraryScan();
      const deadline = Date.now() + RESCAN_TIMEOUT_MS;
      let status = await getLibraryScanStatus();
      while (status.running && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, RESCAN_POLL_INTERVAL_MS));
        status = await getLibraryScanStatus();
      }
      await refresh();
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      alert(err instanceof Error ? err.message : "Re-scan failed.");
    } finally {
      setRescanning(false);
    }
  });

  const showDropOverlay = dragActive || dropUploading;
  const dropMessage = dropUploading
    ? `Uploading to ${dropTargetName}...`
    : `Drop files or folders to upload to ${dropTargetName}`;

  return (
    <div
      className="relative"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {showDropOverlay && (
        <div className="absolute inset-0 z-40 flex items-center justify-center rounded-lg border-2 border-dashed border-accent bg-panel-overlay pointer-events-none">
          <div className="px-4 py-3 rounded-md border border-panel-strong bg-panel-strong shadow-sm text-sm">
            {dropMessage}
          </div>
        </div>
      )}
      <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 flex-wrap">
        <AssetSearch
          onQueryChange={query => { queryRef.current = query; }}
          onSearch={query => { refresh({ search: query }); }}
          disabled={loading}
        />
        {loading && <span className="text-sm opacity-70">Loading...</span>}
        <div className="flex items-center gap-2 text-sm">
          <span className="opacity-70">Sort</span>
          <select
            className="px-2 py-1 rounded-md border border-panel-strong bg-panel-soft"
            value={sortKey}
            onChange={e => setSortKey(e.target.value as typeof sortKey)}
          >
            <option value="name">Name</option>
            <option value="size">Size</option>
            <option value="type">File type</option>
            <option value="folder">Folder</option>
          </select>
          <button
            type="button"
            onClick={() => setSortDir(prev => (prev === "asc" ? "desc" : "asc"))}
            className="px-2 py-1 rounded-md border border-panel-strong"
          >
            {sortDir === "asc" ? "Asc" : "Desc"}
          </button>
        </div>
      </div>

      {!!allTags.length && (
        <div className="flex flex-wrap gap-2">
          {allTags.map(t => {
            const colors = colorForTag(t);
            const active = activeTags.includes(t);
            return (
              <button
                key={t}
                className={`px-2 py-1 rounded-full text-sm border transition-colors ${
                  active ? "ring-2 ring-offset-1 ring-[color:var(--mv-accent)] ring-offset-[color:var(--mv-bg)]" : ""
                }`}
                style={{
                  backgroundColor: active ? colors.bg : "transparent",
                  color: colors.text,
                  borderColor: colors.border,
                }}
                onClick={()=>toggleTag(t)}
              >
                {t}
              </button>
            );
          })}
          {activeTags.length>0 && (
            <button
              className="px-2 py-1 rounded-full text-sm border border-panel-strong"
              onClick={() => { setActiveTags([]); refresh({ tags: [] }); }}
            >
              Reset
            </button>
          )}
        </div>
      )}

      {["folder", "type"].includes(sortKey) ? (
        <div className="space-y-4">
          {(sortKey === "folder" ? folderGroups : typeGroups).map(group => {
            const collapsed = collapsedGroups.has(group.id);
            return (
              <div
                key={group.id}
                className="rounded-lg border border-panel bg-panel-soft"
              >
                <button
                  className="w-full flex items-center justify-between px-4 py-3 text-left"
                  onClick={() => toggleGroup(group.id)}
                >
                  <div>
                    <div className="font-medium">{group.title}</div>
                    <div className="text-xs opacity-70">{group.items.length} item{group.items.length === 1 ? "" : "s"}</div>
                  </div>
                  <span className="text-sm opacity-70">{collapsed ? "Show" : "Hide"}</span>
                </button>
                {!collapsed && (
                  <div className="px-4 pb-4 overflow-x-auto">
                    <div className="flex gap-4 min-h-[280px]">
                      {group.items.map(it => (
                        <div key={it.id} className="min-w-[260px] max-w-[320px]">
                          <AssetCard
                            item={it}
                            onSaveTags={onSaveTags}
                            onSaveDetails={onSaveDetails}
                            onRename={onRename}
                            onPreview={setPreviewItem}
                            onDownloadSingle={downloadAsset}
                            downloading={downloadingId === it.id}
                            onDelete={removeAsset}
                            deleting={deletingId === it.id}
                            onMoveFolder={onMoveFolder}
                            folderOptions={folderOptions}
                            moving={movingId === it.id}
                            onDownloadByTag={downloadByTag}
                            onDownloadSelected={downloadSelected}
                            selected={selectedIds.has(it.id)}
                            onToggleSelected={toggleSelected}
                            hasSelection={selectedIds.size > 0}
                            bulkDownloading={Boolean(bulkDownloading)}
                            slicerEnabled={slicerEnabled}
                            slicerLabel={slicerLabel}
                            onOpenInSlicer={openInSlicer}
                            engravingEnabled={engravingEnabled}
                            engraverLabel={engraverLabel}
                            onOpenInEngraving={openInEngraving}
                            theme={theme}
                            previewMode={previewSettings?.mode || "automatic"}
                            onAssetChanged={replaceAsset}
                            onForgetMissing={forgetMissingAsset}
                            onRescanMissing={rescanMissing}
                            rescanning={rescanning}
                          />
                        </div>
                      ))}
                      {!group.items.length && (
                        <div className="px-2 py-4 text-sm opacity-60">No assets in this folder</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
          {sortedItems.map(it => (
            <AssetCard
              key={it.id}
              item={it}
              onSaveTags={onSaveTags}
              onSaveDetails={onSaveDetails}
              onRename={onRename}
              onPreview={setPreviewItem}
              onDownloadSingle={downloadAsset}
              downloading={downloadingId === it.id}
              onDelete={removeAsset}
              deleting={deletingId === it.id}
              onMoveFolder={onMoveFolder}
              folderOptions={folderOptions}
              moving={movingId === it.id}
              onDownloadByTag={downloadByTag}
              onDownloadSelected={downloadSelected}
              selected={selectedIds.has(it.id)}
              onToggleSelected={toggleSelected}
              hasSelection={selectedIds.size > 0}
              bulkDownloading={Boolean(bulkDownloading)}
              slicerEnabled={slicerEnabled}
              slicerLabel={slicerLabel}
              onOpenInSlicer={openInSlicer}
              engravingEnabled={engravingEnabled}
              engraverLabel={engraverLabel}
              onOpenInEngraving={openInEngraving}
              theme={theme}
              previewMode={previewSettings?.mode || "automatic"}
              onAssetChanged={replaceAsset}
              onForgetMissing={forgetMissingAsset}
              onRescanMissing={rescanMissing}
              rescanning={rescanning}
            />
          ))}
        </div>
      )}
      {hasMore && (
        <div className="flex justify-center pt-2">
          <button
            className="px-4 py-2 rounded-md border border-panel-strong text-sm disabled:opacity-60"
            onClick={loadMore}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading..." : "Load more"}
          </button>
        </div>
      )}
      {previewItem && (
        <AssetPreviewModal asset={previewItem} theme={theme} onClose={() => setPreviewItem(null)} />
      )}
      {zipPrompt.modal}
      </div>
    </div>
  );
}

type AssetCardProps = {
  item: Asset;
  onSaveTags: (id: string, tags: string[]) => void;
  onSaveDetails: (id: string, payload: { notes: string; creator: string; collection: string }) => void;
  onRename: (id: string, filename: string) => void;
  onPreview: (asset: Asset | null) => void;
  onDownloadSingle: (asset: Asset) => void;
  onDownloadByTag: (tag: string) => void;
  onDownloadSelected: () => void;
  downloading: boolean;
  onDelete: (asset: Asset) => void;
  deleting: boolean;
  onMoveFolder: (id: string, folder_id: string | null) => void;
  folderOptions: { id: string | null; name: string }[];
  moving: boolean;
  selected: boolean;
  onToggleSelected: (id: string) => void;
  hasSelection: boolean;
  bulkDownloading: boolean;
  slicerEnabled: boolean;
  slicerLabel: string;
  onOpenInSlicer: (asset: Asset) => void;
  engravingEnabled: boolean;
  engraverLabel: string;
  onOpenInEngraving: (asset: Asset) => void;
  theme: ResolvedTheme;
  previewMode: PreviewSettings["mode"];
  onAssetChanged: (asset: Asset) => void;
  onForgetMissing: (asset: Asset) => void;
  onRescanMissing: (asset: Asset) => void;
  rescanning: boolean;
};

const AssetCard = React.memo(function AssetCard({
  item,
  onSaveTags,
  onSaveDetails,
  onRename,
  onPreview,
  onDownloadSingle,
  onDownloadByTag,
  onDownloadSelected,
  downloading,
  onDelete,
  deleting,
  onMoveFolder,
  folderOptions,
  moving,
  selected,
  onToggleSelected,
  hasSelection,
  bulkDownloading,
  slicerEnabled,
  slicerLabel,
  onOpenInSlicer,
  engravingEnabled,
  engraverLabel,
  onOpenInEngraving,
  theme,
  previewMode,
  onAssetChanged,
  onForgetMissing,
  onRescanMissing,
  rescanning,
}: AssetCardProps) {
  const [editingTags, setEditingTags] = useState(false);
  const [tagList, setTagList] = useState<string[]>(item.tags);
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesValue, setNotesValue] = useState(item.notes || "");
  const [creatorValue, setCreatorValue] = useState(item.creator || "");
  const [collectionValue, setCollectionValue] = useState(item.collection || "");
  const [notesCollapsed, setNotesCollapsed] = useState(true);
  const [renaming, setRenaming] = useState(false);
  const [nameValue, setNameValue] = useState(item.name);
  const nameInputRef = React.useRef<HTMLInputElement | null>(null);
  const [downloadChoice, setDownloadChoice] = useState("");
  const [filesExpanded, setFilesExpanded] = useState(false);
  const [supportingFiles, setSupportingFiles] = useState<AssetFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesUploading, setFilesUploading] = useState(false);
  const [preparedClearing, setPreparedClearing] = useState(false);
  const relatedInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!editingTags) {
      setTagList(item.tags);
    }
  }, [item.tags, editingTags]);

  useEffect(() => {
    if (!editingNotes) {
      setNotesValue(item.notes || "");
      setCreatorValue(item.creator || "");
      setCollectionValue(item.collection || "");
    }
  }, [item.notes, item.creator, item.collection, editingNotes]);

  useEffect(() => {
    if (!renaming) {
      setNameValue(item.name);
    } else {
      setTimeout(() => nameInputRef.current?.select(), 0);
    }
  }, [item.name, renaming]);

  const loadSupportingFiles = async () => {
    setFilesLoading(true);
    try {
      setSupportingFiles(await listAssetFiles(item.id));
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Failed to load supporting files");
    } finally {
      setFilesLoading(false);
    }
  };

  useEffect(() => {
    if (filesExpanded) void loadSupportingFiles();
  }, [filesExpanded, item.id]);

  const addRelatedFiles = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    setFilesUploading(true);
    try {
      let updated = item;
      for (const file of files) {
        updated = await uploadAssetFile(item.id, file);
        onAssetChanged(updated);
      }
      setSupportingFiles(await listAssetFiles(item.id));
      setFilesExpanded(true);
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Failed to add files");
    } finally {
      setFilesUploading(false);
    }
  };

  const removeRelatedFile = async (file: AssetFile) => {
    if (!window.confirm(`Remove ${file.filename} from this model?`)) return;
    try {
      const updated = await deleteAssetFile(item.id, file.id);
      onAssetChanged(updated);
      setSupportingFiles(current => current.filter(entry => entry.id !== file.id));
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Failed to remove file");
    }
  };

  const clearPreparedPrint = async () => {
    if (!window.confirm("Clear the attached prepared print from this model?")) return;
    setPreparedClearing(true);
    try {
      onAssetChanged(await deletePreparedPrint(item.id));
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Failed to clear prepared print");
    } finally {
      setPreparedClearing(false);
    }
  };

  const startEditing = () => {
    setTagList(item.tags);
    setEditingTags(true);
  };

  const cancelEditing = () => {
    setEditingTags(false);
    setTagList(item.tags);
  };

  const save = async () => {
    await onSaveTags(item.id, tagList);
    setEditingTags(false);
  };

  const saveNotes = async () => {
    await onSaveDetails(item.id, {
      notes: notesValue,
      creator: creatorValue,
      collection: collectionValue,
    });
    setEditingNotes(false);
  };

  const cancelNotes = () => {
    setEditingNotes(false);
    setNotesValue(item.notes || "");
    setCreatorValue(item.creator || "");
    setCollectionValue(item.collection || "");
  };

  const noteText = (item.notes || "").trim();

  const commitRename = async () => {
    const next = nameValue.trim();
    if (!next) {
      setNameValue(item.name);
      setRenaming(false);
      return;
    }
    if (next === item.name) {
      setRenaming(false);
      return;
    }
    try {
      await onRename(item.id, next);
    } catch (err) {
      console.error(err);
      alert("Rename failed");
      setNameValue(item.name);
    } finally {
      setRenaming(false);
    }
  };

  const cancelRename = () => {
    setNameValue(item.name);
    setRenaming(false);
  };

  const handleRenameKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitRename();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelRename();
    }
  };

  const handleFolderChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const next = e.target.value || null;
    const current = item.folder_id || null;
    if (next === current) return;
    onMoveFolder(item.id, next);
  };

  const handleDownloadChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    if (!val) return;
    setDownloadChoice("");
    if (val === "single") {
      onDownloadSingle(item);
    } else if (val === "selected") {
      onDownloadSelected();
    } else if (val.startsWith("tag:")) {
      onDownloadByTag(val.slice(4));
    }
  };

  const canOpenInSlicer = slicerEnabled && (Boolean(item.prepared_print) || MODEL_EXTS.has(extOf(item.filename)));
  const canOpenInEngraving = engravingEnabled && ENGRAVING_EXTS.has(extOf(item.filename));

  return (
    <div className="rounded-lg border border-panel overflow-hidden bg-panel-soft">
      <div
        className="h-40 relative cursor-pointer"
        onDoubleClick={() => onPreview(item)}
        title="Double-click to open large preview"
        onClick={e => e.stopPropagation()}
      >
        {renderPreviewContent(item, "card", theme, previewMode)}
      </div>
      {item.missing_since && (
        <div
          role="status"
          className="m-3 mb-0 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/40 px-3 py-2 text-sm"
        >
          <div className="font-semibold text-red-700 dark:text-red-300">File missing</div>
          <div className="text-xs opacity-80">
            Not found in storage since {formatMissingSince(item.missing_since)}.
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              className="text-sm px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
              onClick={() => onRescanMissing(item)}
              disabled={rescanning}
            >
              {rescanning ? "Scanning..." : "Re-scan"}
            </button>
            <button
              className="text-sm px-2 py-1 rounded-md border border-red-300 text-red-700 dark:text-red-300 disabled:opacity-60"
              onClick={() => onForgetMissing(item)}
              disabled={deleting}
            >
              {deleting ? "Forgetting..." : "Forget entry"}
            </button>
          </div>
        </div>
      )}
      <div className="p-3 flex flex-col gap-2">
        {item.prepared_print && (
          <PreparedPrintSummary
            prepared={item.prepared_print}
            onClear={item.prepared_print.removable ? clearPreparedPrint : undefined}
            clearing={preparedClearing}
          />
        )}
        <div className="flex items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelected(item.id)}
              className="w-4 h-4"
            />
            <span>Select</span>
          </label>
          <div className="flex items-center gap-2">
            <select
              value={downloadChoice}
              onChange={handleDownloadChange}
              disabled={downloading || bulkDownloading}
              className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
            >
              <option value="">Download...</option>
              <option value="single">Download file</option>
              <option value="selected" disabled={!hasSelection}>Download all selected</option>
              {item.tags.map(t => (
                <option key={`tag-${t}`} value={`tag:${t}`}>Download tag: {t}</option>
              ))}
            </select>
            {(downloading || bulkDownloading) && (
              <span className="text-xs opacity-70">{downloading ? "Downloading..." : "Preparing..."}</span>
            )}
          </div>
        </div>
        {(canOpenInSlicer || canOpenInEngraving) && (
          <div className="flex flex-wrap gap-2 justify-end">
            {canOpenInSlicer && (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
                onClick={() => onOpenInSlicer(item)}
                disabled={downloading || bulkDownloading}
              >
                Open in {slicerLabel}
              </button>
            )}
            {canOpenInEngraving && (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
                onClick={() => onOpenInEngraving(item)}
                disabled={downloading || bulkDownloading}
              >
                Open in {engraverLabel}
              </button>
            )}
          </div>
        )}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold uppercase text-muted">
            {moving ? "Updating..." : "Folder"}
          </label>
          <select
            value={item.folder_id || ""}
            onChange={handleFolderChange}
            disabled={moving}
            className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
          >
            {folderOptions.map(opt => (
              <option key={opt.id || "none"} value={opt.id || ""}>
                {opt.name}
              </option>
            ))}
          </select>
        </div>
        <div
          className="text-sm font-medium truncate cursor-text"
          title={`${item.name} · ${item.filename}`}
          onDoubleClick={e => { e.stopPropagation(); setRenaming(true); }}
          onClick={e => renaming && e.stopPropagation()}
        >
          {renaming ? (
            <input
              ref={nameInputRef}
              value={nameValue}
              onChange={e => setNameValue(e.target.value)}
              onBlur={commitRename}
              onKeyDown={handleRenameKey}
              onClick={e => e.stopPropagation()}
              className="px-2 py-1 w-full rounded-md border border-panel-strong bg-panel-soft text-sm"
              autoFocus
            />
          ) : (
            item.name
          )}
        </div>
        <div className="text-[11px] truncate text-subtle" title={item.filename}>{item.filename}</div>
        {(item.creator || item.collection) && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
            {item.creator && <span>By {item.creator}</span>}
            {item.collection && <span>Collection: {item.collection}</span>}
          </div>
        )}
        <div className="flex flex-wrap gap-1">
          {item.tags.length ? (
            item.tags.map(t => <TagBadge key={t} tag={t} />)
          ) : (
            <span className="text-xs opacity-60">No tags</span>
          )}
        </div>
        <div className="rounded-md border border-panel-strong bg-panel-strong/40 text-sm">
          <div className="flex items-center justify-between gap-2 p-2">
            <button
              type="button"
              className="flex min-w-0 items-center gap-2 text-left"
              onClick={() => setFilesExpanded(value => !value)}
            >
              <span className="font-medium">Supporting files</span>
              <span className="rounded-full bg-panel px-2 py-0.5 text-[11px] text-muted">
                {item.supporting_file_count || 0}
              </span>
            </button>
            <>
              <input
                ref={relatedInputRef}
                type="file"
                multiple
                className="hidden"
                accept=".pdf,.txt,.md,.doc,.docx,.rtf,.csv,.html,.zip,.gcode,.gco,.bgcode,.3mf"
                onChange={addRelatedFiles}
              />
              <button
                type="button"
                className="rounded-md border border-panel-strong px-2 py-1 text-xs disabled:opacity-60"
                disabled={filesUploading}
                onClick={() => relatedInputRef.current?.click()}
                title="Add documentation or a prepared print"
              >
                {filesUploading ? "Adding..." : "Add files"}
              </button>
            </>
          </div>
          {filesExpanded && (
            <div className="border-t border-panel px-2 py-2">
              {filesLoading ? (
                <div className="text-xs text-muted">Loading files...</div>
              ) : supportingFiles.length ? (
                <div className="space-y-1">
                  {supportingFiles.map(file => (
                    <div key={file.id} className="flex items-center justify-between gap-2 rounded px-1 py-1 hover:bg-panel-soft">
                      <a
                        className="min-w-0 truncate text-xs underline-offset-2 hover:underline"
                        href={fileUrl(file.url)}
                        download={file.filename}
                        title={file.filename}
                      >
                        {file.filename}
                      </a>
                      <button
                        type="button"
                        className="text-[11px] text-red-700 dark:text-red-300"
                        onClick={() => removeRelatedFile(file)}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted">Add assembly instructions, notes, other documentation, or a prepared print.</div>
              )}
            </div>
          )}
        </div>
        <div className="border border-dashed border-panel-strong rounded-md p-2 text-sm flex flex-col gap-2">
          <div className="flex items-center justify-between text-xs uppercase tracking-wide text-muted">
            <span>Model details</span>
            <button
              className="text-[11px] px-2 py-0.5 rounded-md border border-panel-strong"
              onClick={() => setNotesCollapsed(v => !v)}
            >
              {notesCollapsed ? "Expand" : "Collapse"}
            </button>
          </div>
          {!notesCollapsed && (
            <>
              {editingNotes ? (
                <>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-muted">Creator</span>
                    <input
                      value={creatorValue}
                      onChange={e => setCreatorValue(e.target.value)}
                      className="w-full rounded-md border border-panel-strong bg-panel-soft px-2 py-1.5"
                      placeholder="Designer or source"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-muted">Collection</span>
                    <input
                      value={collectionValue}
                      onChange={e => setCollectionValue(e.target.value)}
                      className="w-full rounded-md border border-panel-strong bg-panel-soft px-2 py-1.5"
                      placeholder="Collection name"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-muted">Notes</span>
                  <textarea
                    value={notesValue}
                    onChange={e => setNotesValue(e.target.value)}
                    className="w-full min-h-[80px] rounded-md border border-panel-strong bg-panel-soft p-2"
                    placeholder="Add some details about this asset"
                  />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button className="text-sm px-3 py-1 rounded-md bg-accent" onClick={saveNotes}>Save</button>
                    <button className="text-sm px-3 py-1 rounded-md border border-panel-strong" onClick={cancelNotes}>Cancel</button>
                  </div>
                </>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div><span className="block text-[10px] uppercase text-muted">Creator</span>{item.creator || "Not set"}</div>
                    <div><span className="block text-[10px] uppercase text-muted">Collection</span>{item.collection || "Not set"}</div>
                  </div>
                  <div className={`text-sm whitespace-pre-wrap ${noteText ? "text-foreground" : "opacity-60"}`}>
                    {noteText || "Add notes"}
                  </div>
                  <button
                    className="self-start text-xs px-2 py-1 rounded-md border border-panel-strong"
                    onClick={() => setEditingNotes(true)}
                  >
                    Edit details
                  </button>
                </>
              )}
            </>
          )}
          {notesCollapsed && (
            <div className={`text-sm ${noteText ? "text-foreground" : "opacity-60"}`}>
              {noteText
                ? `${noteText.slice(0, 60)}${noteText.length > 60 ? "..." : ""}`
                : [item.creator, item.collection].filter(Boolean).join(" · ") || "No details"}
            </div>
          )}
        </div>

        {editingTags ? (
          <div className="flex flex-col gap-2">
            <TagInput
              value={tagList}
              onChange={setTagList}
              placeholder="Type and press comma/Enter"
            />
            <div className="flex flex-wrap gap-2">
              <button className="text-sm px-3 py-1 rounded-md bg-accent" onClick={save}>Save</button>
              <button className="text-sm px-3 py-1 rounded-md border border-panel-strong" onClick={cancelEditing}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 flex-wrap">
            <button className="text-sm px-2 py-1 rounded-md border border-panel-strong" onClick={startEditing}>Edit tags</button>
            <button
              className="text-sm px-2 py-1 rounded-md border border-red-300 text-red-700 dark:text-red-300 disabled:opacity-60"
              onClick={() => onDelete(item)}
              disabled={deleting}
            >
              {deleting ? "Deleting..." : "Delete"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
});

function formatPreparedDuration(totalSeconds?: number | null) {
  if (!totalSeconds || totalSeconds < 1) return null;
  const roundedMinutes = Math.max(1, Math.round(totalSeconds / 60));
  const days = Math.floor(roundedMinutes / 1440);
  const hours = Math.floor((roundedMinutes % 1440) / 60);
  const minutes = roundedMinutes % 60;
  return [
    days ? `${days}d` : "",
    hours ? `${hours}h` : "",
    minutes ? `${minutes}m` : "",
  ].filter(Boolean).join(" ");
}

function PreparedPrintSummary({
  prepared,
  onClear,
  clearing = false,
}: {
  prepared: PreparedPrint;
  onClear?: () => void;
  clearing?: boolean;
}) {
  const details = [
    prepared.material,
    prepared.nozzle_mm ? `${prepared.nozzle_mm} mm` : null,
    formatPreparedDuration(prepared.estimated_seconds),
  ].filter(Boolean);
  return (
    <div className="flex items-start justify-between gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-2 text-xs text-emerald-950 dark:text-emerald-100">
      <span>
        <span className="font-semibold">
          {prepared.printer ? `Prepared for ${prepared.printer}` : "Prepared print available"}
        </span>
        {details.length > 0 && <span> · {details.join(" · ")}</span>}
      </span>
      {onClear && (
        <button type="button" className="shrink-0 underline-offset-2 hover:underline disabled:opacity-60" onClick={onClear} disabled={clearing}>
          {clearing ? "Clearing..." : "Clear"}
        </button>
      )}
    </div>
  );
}

type PreviewVariant = "card" | "modal";

function renderPreviewContent(
  asset: Asset,
  variant: PreviewVariant,
  theme: ResolvedTheme,
  previewMode: PreviewSettings["mode"] = "automatic"
) {
  const ext = extOf(asset.filename);
  const assetUrl = fileUrl(asset.url);
  const thumbUrl = asset.thumb_url ? fileUrl(asset.thumb_url) : null;
  const imgClass =
    variant === "card"
      ? "w-full h-full object-cover"
      : "w-full h-full object-contain bg-panel-strong";
  const is3d = MODEL_EXTS.has(ext);
  const isLightBurn = LIGHTBURN_EXTS.has(ext);

  if (variant === "card") {
    if (thumbUrl) {
      return <img src={thumbUrl} alt={asset.filename} loading="lazy" decoding="async" className={imgClass} />;
    }
    if (ext === "svg") {
      return <img src={assetUrl} alt={asset.filename} loading="lazy" decoding="async" className={imgClass} />;
    }
    if (is3d) {
      if (previewMode === "disabled") {
        return <div className="flex h-full w-full items-center justify-center text-xs text-muted">Preview generation disabled</div>;
      }
      return <ModelSnapshot url={assetUrl} ext={ext} assetId={asset.id} theme={theme} mode={previewMode} />;
    }
    if (isLightBurn) {
      return (
        <LightBurnPreview
          url={assetUrl}
          assetId={asset.id}
          filename={asset.filename}
          imgClass={imgClass}
        />
      );
    }
    return (
      <div className="flex items-center justify-center w-full h-full text-sm opacity-60">
        No preview
      </div>
    );
  }

  if (is3d) {
    return <ModelViewer key={`${variant}-${asset.id}`} url={assetUrl} ext={ext} assetId={asset.id} theme={theme} />;
  }
  if (thumbUrl || ext === "svg") {
    const src = thumbUrl || assetUrl;
    return <img src={src} alt={asset.filename} decoding="async" className={imgClass} />;
  }
  if (isLightBurn) {
    return (
      <LightBurnPreview
        url={assetUrl}
        assetId={asset.id}
        filename={asset.filename}
        imgClass={imgClass}
      />
    );
  }
  return (
    <div className="flex items-center justify-center w-full h-full text-sm opacity-60">
      Preview unavailable
    </div>
  );
}

function AssetPreviewModal({ asset, theme, onClose }: { asset: Asset; theme: ResolvedTheme; onClose: () => void }) {
  const stop = (e: React.MouseEvent) => e.stopPropagation();
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="bg-panel-strong rounded-lg shadow-2xl max-w-5xl w-full max-h-full overflow-hidden flex flex-col"
        onClick={stop}
      >
        <div className="flex items-center justify-between border-b border-panel px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold">{asset.name}</h2>
            <p className="text-sm opacity-70">
              {asset.filename} · {formatBytes(asset.size)}
            </p>
            {(asset.creator || asset.collection) && (
              <p className="text-xs text-muted">
                {[asset.creator ? `By ${asset.creator}` : "", asset.collection ? `Collection: ${asset.collection}` : ""].filter(Boolean).join(" · ")}
              </p>
            )}
            {asset.prepared_print && (
              <div className="mt-2"><PreparedPrintSummary prepared={asset.prepared_print} /></div>
            )}
          </div>
          <button
            className="px-3 py-1 rounded-md border border-panel-strong text-sm"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <div className="p-4 space-y-4 overflow-auto">
          <div className="w-full h-[70vh] min-h-[400px]">
            <div className="w-full h-full rounded-lg bg-panel-soft flex items-center justify-center overflow-hidden">
              {renderPreviewContent(asset, "modal", theme)}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {asset.tags.length ? (
              asset.tags.map(tag => <TagBadge key={tag} tag={tag} />)
            ) : (
              <span className="text-xs opacity-60">No tags</span>
            )}
          </div>
          {asset.notes && (
            <div className="text-sm border border-dashed border-panel-strong rounded-md p-3 whitespace-pre-wrap">
              {asset.notes}
            </div>
          )}
          <div className="flex gap-3">
            <a
              className="px-3 py-2 rounded-md bg-accent text-sm"
              href={fileUrl(asset.url)}
              download={asset.filename}
            >
              Download
            </a>
            <button
              className="px-3 py-2 rounded-md border border-panel-strong text-sm"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
