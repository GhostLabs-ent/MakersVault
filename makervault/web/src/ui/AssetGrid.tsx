import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckSquare2,
  ChevronRight,
  Download as DownloadIcon,
  FolderMinus,
  FolderInput,
  FolderOpen,
  Tags as TagsIcon,
  Trash2,
  X,
} from "lucide-react";
import {
  Asset,
  AssetFile,
  ArtifactRevision,
  Machine,
  MachineScope,
  PreparedPrint,
  Folder,
  RelationshipCleanupRequiredError,
  UnauthorizedError,
  deleteAsset,
  fileUrl,
  listAssets,
  listTags,
  listFolders,
  listMachines,
  setTags,
  updateAssetFolder,
  updateAssetMeta,
  downloadZip,
  deleteAssetFile,
  deletePreparedPrint,
  createHandoff,
  createGeneralHandoff,
  listAssetFiles,
  uploadAssetFile,
  artifactHistoryExportUrl,
  listArtifactRevisions,
  restoreArtifactRevision,
  removeProjectItem,
  uploadArtifactRevision,
} from "../lib/api";
import { buildGeneralHandoffProtocolUrl, buildHandoffProtocolUrl, HandoffContentRole } from "../lib/handoff";
import ModelViewer, { ModelSnapshot } from "./ModelViewer";
import LightBurnPreview from "./LightBurnPreview";
import TagBadge from "./TagBadge";
import TagInput from "./TagInput";
import { colorForTag } from "./tagColors";
import { EngravingSettings, PreviewSettings, ResolvedTheme, SlicerSettings, engraverLabelFor, slicerLabelFor } from "../lib/settings";
import { entriesFromDataTransfer, uploadEntriesToFolder } from "../lib/uploadTree";
import { buildUploadEntriesFromZip, isZipFile, readZipEntries } from "../lib/zipUtils";
import { useZipImportPrompt } from "./ZipImportModal";
import { buildFolderTrail, mutateTags, selectionAfterSuccess, type TagMutationMode } from "../lib/organization";
import { machineCategoryLabel, shouldLoadMachineContext } from "../lib/machineContext";
import MachineContextPanel from "./MachineContextPanel";

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
const FREECAD_EXTS = new Set(["step", "stp", "stl", "obj", "dxf"]);
const INKSCAPE_EXTS = new Set(["svg", "dxf", "pdf", "eps", "ai", "png"]);

function generalAdapterFor(filename: string): { id: "freecad" | "inkscape"; label: string } | null {
  const extension = extOf(filename);
  if (FREECAD_EXTS.has(extension)) return { id: "freecad", label: "FreeCAD" };
  if (INKSCAPE_EXTS.has(extension)) return { id: "inkscape", label: "Inkscape" };
  return null;
}

const ROWS_PER_BATCH = 5;
const CARD_MIN_WIDTH_PX = 260;
const GRID_GAP_PX = 16;
const LIBRARY_CHROME_WIDTH_PX = 340;

function rowsBatchSizeForWidth(width: number) {
  const cols = Math.max(1, Math.floor((width + GRID_GAP_PX) / (CARD_MIN_WIDTH_PX + GRID_GAP_PX)));
  return cols * ROWS_PER_BATCH;
}

type Props = {
  folderId?: string | null;
  projectId?: string | null;
  projectName?: string | null;
  projectUnassigned?: boolean;
  onMembershipChanged?: () => void;
  foldersVersion?: number;
  onSelectFolder: (id: string | null) => void;
  onUnauthorized?: () => void;
  slicerSettings?: SlicerSettings;
  engravingSettings?: EngravingSettings;
  previewSettings?: PreviewSettings;
  theme: ResolvedTheme;
};

type RefreshOpts = {
  tags?: string[];
  search?: string;
  machineId?: string;
  machineScope?: MachineScope;
};
type GroupBucket = { id: string; title: string; items: Asset[] };
type BulkPanel = "move" | "tags" | "delete" | null;
type BulkFailure = { id: string; name: string; reason: string };
type BulkStatus = {
  label: string;
  completed: number;
  total: number;
  failures: BulkFailure[];
  done: boolean;
};

export default function AssetGrid({
  folderId,
  projectId,
  projectName,
  projectUnassigned = false,
  onMembershipChanged,
  foldersVersion = 0,
  onSelectFolder,
  onUnauthorized,
  slicerSettings,
  engravingSettings,
  previewSettings,
  theme,
}: Props) {
  const [items, setItems] = useState<Asset[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [machineId, setMachineId] = useState("");
  const [machineScope, setMachineScope] = useState<MachineScope>("any");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [previewItem, setPreviewItem] = useState<Asset | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [movingId, setMovingId] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<"name" | "size" | "type" | "folder">("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDownloading, setBulkDownloading] = useState<string | null>(null);
  const [bulkPanel, setBulkPanel] = useState<BulkPanel>(null);
  const [bulkMoveTarget, setBulkMoveTarget] = useState<string>("");
  const [bulkTagMode, setBulkTagMode] = useState<TagMutationMode>("add");
  const [bulkTags, setBulkTags] = useState<string[]>([]);
  const [bulkStatus, setBulkStatus] = useState<BulkStatus | null>(null);
  const [pageSize] = useState<number>(() => {
    if (typeof window === "undefined") return ROWS_PER_BATCH;
    return rowsBatchSizeForWidth(Math.max(CARD_MIN_WIDTH_PX, window.innerWidth - LIBRARY_CHROME_WIDTH_PX));
  });
  const dragDepth = useRef(0);
  const [dragActive, setDragActive] = useState(false);
  const [dropUploading, setDropUploading] = useState(false);
  const slicerEnabled = Boolean(slicerSettings?.enabled);
  const slicerLabel = slicerLabelFor(slicerSettings?.selected);
  const engravingEnabled = Boolean(engravingSettings?.enabled);
  const engraverLabel = engraverLabelFor(engravingSettings?.selected);
  const zipPrompt = useZipImportPrompt();

  const handleApiError = (err: unknown, message?: string) => {
    if (err instanceof UnauthorizedError) {
      onUnauthorized?.();
      return true;
    }
    console.error(err);
    if (message) alert(message);
    return false;
  };

  const resetBulkUi = () => {
    setBulkPanel(null);
    setBulkStatus(null);
    setBulkTags([]);
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
    resetBulkUi();
  };

  const refreshScope = (opts: RefreshOpts = {}) => {
    clearSelection();
    void refresh(opts);
  };

  const replaceAsset = React.useCallback((updated: Asset) => {
    setItems(current => current.map(item => item.id === updated.id ? updated : item));
    setPreviewItem(current => current?.id === updated.id ? updated : current);
  }, []);

  const refresh = async (opts: RefreshOpts = {}) => {
    setLoading(true);
    setHasMore(false);
    setOffset(0);
    const search = opts.search ?? q;
    const tags = opts.tags ?? activeTags;
    const selectedMachineId = opts.machineId ?? machineId;
    const selectedMachineScope = opts.machineScope ?? machineScope;
    const targetFolderId = folderId || undefined;
    const [assetsResult, tagsResult] = await Promise.allSettled([
      listAssets({
        q: search,
        tags,
        folder_id: targetFolderId,
        project_id: projectId || undefined,
        project_unassigned: projectUnassigned,
        machine_id: selectedMachineId || undefined,
        machine_scope: selectedMachineId ? selectedMachineScope : undefined,
        limit: pageSize,
        offset: 0,
      }),
      listTags({
        q: search,
        folder_id: targetFolderId,
        project_id: projectId || undefined,
        project_unassigned: projectUnassigned,
        machine_id: selectedMachineId || undefined,
        machine_scope: selectedMachineId ? selectedMachineScope : undefined,
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
  };

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const data = await listAssets({
        q,
        tags: activeTags,
        folder_id: folderId || undefined,
        project_id: projectId || undefined,
        project_unassigned: projectUnassigned,
        machine_id: machineId || undefined,
        machine_scope: machineId ? machineScope : undefined,
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
  };

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
      const result = await uploadEntriesToFolder(normalEntries, folderId || null, onUnauthorized, projectId);
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
          const result = await uploadEntriesToFolder([entry], folderId || null, onUnauthorized, projectId);
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
          const result = await uploadEntriesToFolder(unzipEntries, folderId || null, onUnauthorized, projectId);
          applyResult(result);
        },
      });
    }
    if (uploaded) {
      await refresh();
      onMembershipChanged?.();
    }
    if (failed.length) {
      alert(`Failed to upload: ${failed.join(", ")}`);
    }
    setDropUploading(false);
  };

  useEffect(() => {
    clearSelection();
    void refresh();
  }, [folderId, projectId, projectUnassigned]);
  useEffect(() => {
    let cancelled = false;
    void listMachines({ include_archived: true, limit: 200 }).then(result => {
      if (!cancelled) setMachines(result.items);
    }).catch(error => {
      if (!cancelled) handleApiError(error);
    });
    return () => { cancelled = true; };
  }, []);
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
    if (projectId) return projectName || "this Project";
    if (projectUnassigned) return "Unassigned";
    if (!folderId) return "All Items";
    return folderById[folderId]?.name || "this folder";
  }, [folderId, folderById, projectId, projectName, projectUnassigned]);

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

  const folderTrail = useMemo(() => buildFolderTrail(folderId, folders), [folderId, folders]);

  const childFolders = useMemo(() => folders
    .filter(folder => (folder.parent_id || null) === (folderId || null))
    .sort((a, b) => a.name.localeCompare(b.name)), [folderId, folders]);

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
    setActiveTags(prev => {
      const next = prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t];
      setSelectedIds(new Set());
      resetBulkUi();
      void refresh({ tags: next });
      return next;
    });
  };

  const toggleSelected = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectLoaded = () => {
    setSelectedIds(new Set(items.map(item => item.id)));
    setBulkStatus(null);
  };

  const runBulkMutation = async (
    label: string,
    operation: (asset: Asset) => Promise<unknown>,
  ) => {
    const targets = Array.from(selectedIds).map(id => itemById[id]).filter(Boolean);
    if (!targets.length) return;
    const failures: BulkFailure[] = [];
    const succeeded: string[] = [];
    setBulkStatus({ label, completed: 0, total: targets.length, failures: [], done: false });
    for (let index = 0; index < targets.length; index += 1) {
      const asset = targets[index];
      try {
        await operation(asset);
        succeeded.push(asset.id);
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
          break;
        }
        console.error(err);
        failures.push({
          id: asset.id,
          name: asset.name || asset.filename,
          reason: err instanceof Error ? err.message : "Operation failed",
        });
      }
      setBulkStatus({
        label,
        completed: index + 1,
        total: targets.length,
        failures: [...failures],
        done: false,
      });
    }
    await refresh();
    setSelectedIds(current => selectionAfterSuccess(current, succeeded));
    setBulkStatus({
      label,
      completed: succeeded.length + failures.length,
      total: targets.length,
      failures,
      done: true,
    });
    setBulkPanel(null);
    setBulkTags([]);
  };

  const moveSelected = async () => {
    const destination = bulkMoveTarget || null;
    await runBulkMutation("Moving models", asset => {
      if ((asset.folder_id || null) === destination) return Promise.resolve();
      return updateAssetFolder(asset.id, destination);
    });
  };

  const updateSelectedTags = async () => {
    if (!bulkTags.length) return;
    await runBulkMutation(
      bulkTagMode === "add" ? "Adding tags" : "Removing tags",
      asset => {
        const nextTags = mutateTags(asset.tags, bulkTags, bulkTagMode);
        if (nextTags.length === asset.tags.length && nextTags.every((tag, index) => tag === asset.tags[index])) {
          return Promise.resolve();
        }
        return setTags(asset.id, nextTags);
      },
    );
  };

  const filenameFromDisposition = (res: Response, fallback: string) => {
    const dispo = res.headers.get("content-disposition") || "";
    const match = dispo.match(/filename="?([^\";]+)"?/i);
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

  const onSaveTags = async (id: string, tags: string[]) => {
    try {
      await setTags(id, tags);
      await refresh();
    } catch (err) {
      handleApiError(err, err instanceof Error ? err.message : "Tag update failed.");
    }
  };

  const onSaveDetails = async (id: string, payload: { notes: string; creator: string; collection: string }) => {
    try {
      await updateAssetMeta(id, payload);
      await refresh();
    } catch (err) {
      handleApiError(err, err instanceof Error ? err.message : "Failed to save model details.");
    }
  };

  const onRename = async (id: string, name: string) => {
    try {
      await updateAssetMeta(id, { name });
      await refresh();
    } catch (err) {
      handleApiError(err, err instanceof Error ? err.message : "Rename failed. Please try again.");
      throw err;
    }
  };

  const onMoveFolder = async (id: string, folder_id: string | null) => {
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
  };

  const downloadAsset = async (asset: Asset) => {
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
  };

  const openInSlicer = async (asset: Asset) => {
    if (!slicerEnabled) return;
    try {
      const handoff = await createHandoff(asset.id, "slicer");
      window.location.href = buildHandoffProtocolUrl(
        "slicer",
        handoff,
        slicerSettings?.selected || "orca",
      );
    } catch (err) {
      if (!handleApiError(err, "Unable to open this file in the slicer.")) {
        console.error(err);
      }
    }
  };

  const openInEngraving = async (asset: Asset) => {
    if (!engravingEnabled) return;
    try {
      const handoff = await createHandoff(asset.id, "engraver");
      window.location.href = buildHandoffProtocolUrl(
        "engraver",
        handoff,
        engravingSettings?.selected || "lightburn",
      );
    } catch (err) {
      if (!handleApiError(err, "Unable to open this file in the engraving software.")) {
        console.error(err);
      }
    }
  };

  const openWithAdapter = async (
    asset: Asset,
    filename: string,
    contentRole: HandoffContentRole,
    selection: { revision_id?: string; file_id?: string } = {},
  ) => {
    const adapter = generalAdapterFor(filename);
    if (!adapter) return;
    try {
      const handoff = await createGeneralHandoff(asset.id, adapter.id, contentRole, selection);
      window.location.href = buildGeneralHandoffProtocolUrl(handoff);
    } catch (err) {
      if (!handleApiError(err, `Unable to open this file in ${adapter.label}.`)) {
        console.error(err);
      }
    }
  };

  const downloadSelected = async () => {
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
  };

  const downloadByTag = async (tag: string) => {
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
  };

  const removeAsset = async (asset: Asset) => {
    const confirmLabel = `Move "${asset.name || asset.filename}" to Trash? You can restore it later.`;
    if (!confirm(confirmLabel)) {
      return;
    }
    setDeletingId(asset.id);
    try {
      await deleteAsset(asset.id);
      setSelectedIds(current => selectionAfterSuccess(current, [asset.id]));
      await refresh();
      setBulkStatus({ label: "Moved model to Trash", completed: 1, total: 1, failures: [], done: true });
    } catch (err) {
      handleApiError(err, err instanceof Error ? err.message : "Delete failed.");
    } finally {
      setDeletingId(null);
    }
  };

  const deleteSelected = () => {
    if (selectedIds.size !== 1) {
      setBulkPanel("delete");
      setBulkStatus(null);
      return;
    }
    const selected = itemById[Array.from(selectedIds)[0]];
    if (selected) void removeAsset(selected);
  };

  const trashSelected = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length || !window.confirm(`Move ${ids.length} selected models to Trash? You can restore them later.`)) return;
    setBulkStatus({ label: "Moving models to Trash", completed: 0, total: ids.length, failures: [], done: false });
    const failures: { id: string; name: string; reason: string }[] = [];
    let completed = 0;
    for (const id of ids) {
      const asset = itemById[id];
      try {
        await deleteAsset(id);
      } catch (err) {
        failures.push({ id, name: asset?.name || asset?.filename || id, reason: err instanceof Error ? err.message : "Trash failed" });
      }
      completed += 1;
      setBulkStatus({ label: "Moving models to Trash", completed, total: ids.length, failures: [...failures], done: false });
    }
    setSelectedIds(current => selectionAfterSuccess(current, ids.filter(id => !failures.some(failure => failure.id === id))));
    setBulkStatus({ label: "Moving models to Trash", completed, total: ids.length, failures, done: true });
    setBulkPanel(null);
    await refresh();
  };

  const removeSelectedFromProject = async () => {
    if (!projectId || !selectedIds.size) return;
    if (!window.confirm(
      `Remove ${selectedIds.size} selected Project item${selectedIds.size === 1 ? "" : "s"}? ` +
      "The artifacts, folders, versions, and files will remain in the library."
    )) return;
    await runBulkMutation(
      "Removing Project items",
      async asset => {
        try {
          await removeProjectItem(projectId, asset.id);
        } catch (error) {
          if (!(error instanceof RelationshipCleanupRequiredError)) throw error;
          const count = error.relationshipCount;
          if (!window.confirm(
            `${asset.name || asset.filename} has ${count} Project relationship${count === 1 ? "" : "s"}. ` +
            "Remove those relationships and the Project membership? The artifact and all files will remain in the library."
          )) throw new Error("Relationship cleanup was not confirmed");
          await removeProjectItem(projectId, asset.id, true);
        }
      },
    );
    onMembershipChanged?.();
  };

  const bulkBusy = Boolean(bulkStatus && !bulkStatus.done);

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
      <nav aria-label="Breadcrumb" className="flex min-h-9 items-center gap-1 overflow-x-auto text-sm text-muted">
        {(projectId || projectUnassigned) ? (
          <>
            <span className="shrink-0 rounded-md px-2 py-1">Projects</span>
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-subtle" aria-hidden="true" />
            <span className="shrink-0 rounded-md px-2 py-1 font-semibold text-foreground">
              {projectUnassigned ? "Unassigned" : projectName || "Project"}
            </span>
          </>
        ) : (
          <>
        <button
          type="button"
          className={`shrink-0 rounded-md px-2 py-1 hover:bg-panel-soft hover:text-foreground ${!folderId ? "font-semibold text-foreground" : ""}`}
          onClick={() => onSelectFolder(null)}
          aria-current={!folderId ? "page" : undefined}
        >
          All files
        </button>
        {folderTrail.map((folder, index) => (
          <React.Fragment key={folder.id}>
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-subtle" aria-hidden="true" />
            <button
              type="button"
              className={`shrink-0 rounded-md px-2 py-1 hover:bg-panel-soft hover:text-foreground ${index === folderTrail.length - 1 ? "font-semibold text-foreground" : ""}`}
              onClick={() => onSelectFolder(folder.id)}
              aria-current={index === folderTrail.length - 1 ? "page" : undefined}
            >
              {folder.name || "Untitled"}
            </button>
          </React.Fragment>
        ))}
          </>
        )}
      </nav>
      <div className="flex items-center gap-3 flex-wrap">
        <input
          value={q}
          onChange={e=>setQ(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") {
              const val = (e.currentTarget as HTMLInputElement).value;
              refreshScope({ search: val });
            }
          }}
          placeholder="Search title, filename, notes..."
          className="px-3 py-2 rounded-md border border-panel-strong bg-panel-soft w-80"
        />
        <button
          className="px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
          onClick={() => refreshScope({ search: q })}
          disabled={loading}
        >
          Search
        </button>
        <select
          aria-label="Filter by Machine"
          className="max-w-64 px-2 py-2 rounded-md border border-panel-strong bg-panel-soft text-sm"
          value={machineId}
          onChange={event => {
            const next = event.target.value;
            setMachineId(next);
            refreshScope({ machineId: next, machineScope });
          }}
        >
          <option value="">All Machines</option>
          {machines.map(machine => (
            <option key={machine.id} value={machine.id}>
              {machine.name} · {machineCategoryLabel(machine.category)}{machine.archived_at ? " (Archived)" : ""}
            </option>
          ))}
        </select>
        <select
          aria-label="Machine match"
          className="px-2 py-2 rounded-md border border-panel-strong bg-panel-soft text-sm disabled:opacity-60"
          value={machineScope}
          disabled={!machineId}
          onChange={event => {
            const next = event.target.value as MachineScope;
            setMachineScope(next);
            refreshScope({ machineId, machineScope: next });
          }}
        >
          <option value="any">Any relationship</option>
          <option value="associated">Associated</option>
          <option value="prepared">Prepared for</option>
        </select>
        {loading && <span className="text-sm opacity-70">Loading...</span>}
        <div className="flex items-center gap-2 text-sm">
          <span className="opacity-70">Sort loaded</span>
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
              onClick={() => { setActiveTags([]); refreshScope({ tags: [] }); }}
            >
              Reset
            </button>
          )}
        </div>
      )}

      {selectedIds.size > 0 && (
        <section
          role="toolbar"
          aria-label="Selected models"
          className="sticky top-0 z-20 rounded-xl border border-accent-soft bg-panel-strong p-3 shadow-lg"
        >
          <div className="flex flex-wrap items-center gap-2">
            <div className="mr-1 flex items-center gap-2 font-semibold">
              <CheckSquare2 className="h-4 w-4 text-accent" aria-hidden="true" />
              <span>{selectedIds.size} selected</span>
            </div>
            <button
              type="button"
              className="rounded-md border border-panel-strong px-2.5 py-1.5 text-xs font-medium disabled:opacity-50"
              onClick={selectLoaded}
              disabled={bulkBusy || selectedIds.size === items.length}
            >
              Select loaded ({items.length})
            </button>
            <button
              type="button"
              className="rounded-md border border-panel-strong px-2.5 py-1.5 text-xs font-medium disabled:opacity-50"
              onClick={clearSelection}
              disabled={bulkBusy}
            >
              Clear
            </button>
            <span className="mx-1 hidden h-6 w-px bg-[color:var(--mv-border)] sm:block" aria-hidden="true" />
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-panel-strong px-2.5 py-1.5 text-xs font-medium disabled:opacity-50"
              onClick={() => { setBulkPanel(bulkPanel === "move" ? null : "move"); setBulkStatus(null); }}
              disabled={bulkBusy}
            >
              <FolderInput className="h-3.5 w-3.5" aria-hidden="true" /> Move
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-panel-strong px-2.5 py-1.5 text-xs font-medium disabled:opacity-50"
              onClick={() => { setBulkPanel(bulkPanel === "tags" ? null : "tags"); setBulkStatus(null); }}
              disabled={bulkBusy}
            >
              <TagsIcon className="h-3.5 w-3.5" aria-hidden="true" /> Tags
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-panel-strong px-2.5 py-1.5 text-xs font-medium disabled:opacity-50"
              onClick={downloadSelected}
              disabled={bulkBusy || Boolean(bulkDownloading)}
            >
              <DownloadIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {bulkDownloading ? "Preparing…" : "Download"}
            </button>
            {projectId && (
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-md border border-panel-strong px-2.5 py-1.5 text-xs font-medium disabled:opacity-50"
                onClick={removeSelectedFromProject}
                disabled={bulkBusy}
              >
                <FolderMinus className="h-3.5 w-3.5" aria-hidden="true" /> Remove from Project
              </button>
            )}
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-red-300 px-2.5 py-1.5 text-xs font-medium text-red-700 disabled:opacity-50 dark:text-red-300"
              onClick={deleteSelected}
              disabled={bulkBusy || Boolean(deletingId)}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Delete…
            </button>
          </div>

          {bulkPanel === "move" && (
            <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-panel pt-3">
              <label className="flex min-w-[260px] flex-1 flex-col gap-1 text-xs font-medium">
                Destination for {selectedIds.size} selected model{selectedIds.size === 1 ? "" : "s"}
                <select
                  value={bulkMoveTarget}
                  onChange={event => setBulkMoveTarget(event.target.value)}
                  className="h-9 rounded-md border border-panel-strong bg-panel-soft px-2 text-sm"
                >
                  {folderOptions.map(option => (
                    <option key={option.id || "none"} value={option.id || ""}>{option.name}</option>
                  ))}
                </select>
              </label>
              <button type="button" className="h-9 rounded-md bg-accent px-3 text-sm font-medium" onClick={moveSelected}>
                Move selected
              </button>
              <button type="button" className="grid h-9 w-9 place-items-center rounded-md border border-panel-strong" onClick={() => setBulkPanel(null)} aria-label="Close move controls">
                <X className="h-4 w-4" />
              </button>
            </div>
          )}

          {bulkPanel === "tags" && (
            <div className="mt-3 flex flex-col gap-2 border-t border-panel pt-3">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={bulkTagMode}
                  onChange={event => setBulkTagMode(event.target.value as TagMutationMode)}
                  className="h-9 rounded-md border border-panel-strong bg-panel-soft px-2 text-sm"
                  aria-label="Bulk tag operation"
                >
                  <option value="add">Add tags</option>
                  <option value="remove">Remove tags</option>
                </select>
                <div className="min-w-[260px] flex-1">
                  <TagInput value={bulkTags} onChange={setBulkTags} placeholder="Type tags and press comma/Enter" />
                </div>
                <button
                  type="button"
                  className="h-9 rounded-md bg-accent px-3 text-sm font-medium disabled:opacity-50"
                  onClick={updateSelectedTags}
                  disabled={!bulkTags.length}
                >
                  Apply to {selectedIds.size}
                </button>
                <button type="button" className="grid h-9 w-9 place-items-center rounded-md border border-panel-strong" onClick={() => setBulkPanel(null)} aria-label="Close tag controls">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <p className="text-xs text-muted">Existing unrelated tags are preserved.</p>
            </div>
          )}

          {bulkPanel === "delete" && selectedIds.size > 1 && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-panel bg-panel-soft p-3 text-sm">
              <div>
                <div className="font-semibold">Move {selectedIds.size} models to Trash?</div>
                <p className="mt-1 text-xs text-muted">Every version and supporting file remains recoverable.</p>
              </div>
              <div className="flex gap-2">
                <button type="button" className="rounded-md bg-accent px-3 py-2 text-sm font-medium" onClick={trashSelected}>Move to Trash</button>
                <button type="button" className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={() => setBulkPanel(null)}>Cancel</button>
              </div>
            </div>
          )}

        </section>
      )}

      {bulkStatus && <BulkProgress status={bulkStatus} />}

      {!loading && items.length === 0 && (
        <div className="rounded-xl border border-dashed border-panel-strong bg-panel-soft px-6 py-10 text-center">
          <FolderOpen className="mx-auto h-8 w-8 text-subtle" aria-hidden="true" />
          <h2 className="mt-3 font-semibold">
            {q || activeTags.length || machineId
              ? projectId || projectUnassigned
                ? "No Project items match this view"
                : "No models match this view"
              : projectId
                ? "No Project items yet"
                : projectUnassigned
                  ? "No Unassigned artifacts"
                  : folderId
                    ? "No models directly in this folder"
                    : "Your vault is empty"}
          </h2>
          {!projectId && !projectUnassigned && folderId && !q && !activeTags.length && !machineId && childFolders.length > 0 ? (
            <div className="mt-3">
              <p className="text-sm text-muted">Continue into a subfolder:</p>
              <div className="mt-3 flex flex-wrap justify-center gap-2">
                {childFolders.map(folder => (
                  <button key={folder.id} type="button" className="rounded-md border border-panel-strong px-3 py-2 text-sm hover:bg-panel-strong" onClick={() => onSelectFolder(folder.id)}>
                    {folder.name}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted">
              {q || activeTags.length || machineId ? "Try changing the search, tag, or Machine filters." : "Upload files or drop a folder here to get started."}
            </p>
          )}
        </div>
      )}

      {items.length > 0 && (["folder", "type"].includes(sortKey) ? (
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
                            selected={selectedIds.has(it.id)}
                            onToggleSelected={() => toggleSelected(it.id)}
                            bulkDownloading={Boolean(bulkDownloading)}
                            slicerEnabled={slicerEnabled}
                            slicerLabel={slicerLabel}
                            onOpenInSlicer={openInSlicer}
                            engravingEnabled={engravingEnabled}
                            engraverLabel={engraverLabel}
                            onOpenInEngraving={openInEngraving}
                            onOpenWithAdapter={openWithAdapter}
                            theme={theme}
                            previewMode={previewSettings?.mode || "automatic"}
                            onAssetChanged={replaceAsset}
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
              selected={selectedIds.has(it.id)}
              onToggleSelected={() => toggleSelected(it.id)}
              bulkDownloading={Boolean(bulkDownloading)}
              slicerEnabled={slicerEnabled}
              slicerLabel={slicerLabel}
              onOpenInSlicer={openInSlicer}
              engravingEnabled={engravingEnabled}
              engraverLabel={engraverLabel}
              onOpenInEngraving={openInEngraving}
              onOpenWithAdapter={openWithAdapter}
              theme={theme}
              previewMode={previewSettings?.mode || "automatic"}
              onAssetChanged={replaceAsset}
            />
          ))}
        </div>
      ))}
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
        <AssetPreviewModal
          asset={previewItem}
          theme={theme}
          onAssetChanged={replaceAsset}
          onContextChanged={() => void refresh()}
          onUnauthorized={onUnauthorized}
          onClose={() => setPreviewItem(null)}
        />
      )}
      {zipPrompt.modal}
      </div>
    </div>
  );
}

function BulkProgress({ status }: { status: BulkStatus }) {
  return (
    <div className={`rounded-lg border p-3 text-sm ${status.failures.length ? "border-amber-400 bg-amber-50 text-amber-950 dark:bg-amber-950/30 dark:text-amber-100" : "border-panel bg-panel-soft"}`} aria-live="polite">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{status.label}</span>
        <span>{status.completed} / {status.total}</span>
      </div>
      {!status.done && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-panel">
          <div className="h-full bg-accent transition-[width]" style={{ width: `${(status.completed / status.total) * 100}%` }} />
        </div>
      )}
      {status.done && !status.failures.length && <p className="mt-1 text-xs text-muted">Completed successfully.</p>}
      {!!status.failures.length && (
        <div className="mt-2">
          <p className="font-medium">{status.failures.length} failed and remain selected:</p>
          <ul className="mt-1 space-y-1 text-xs">
            {status.failures.map(failure => <li key={failure.id}><strong>{failure.name}:</strong> {failure.reason}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

const AssetCard = React.memo(function AssetCard({
  item,
  onSaveTags,
  onSaveDetails,
  onRename,
  onPreview,
  onDownloadSingle,
  onDownloadByTag,
  downloading,
  onDelete,
  deleting,
  onMoveFolder,
  folderOptions,
  moving,
  selected,
  onToggleSelected,
  bulkDownloading,
  slicerEnabled,
  slicerLabel,
  onOpenInSlicer,
  engravingEnabled,
  engraverLabel,
  onOpenInEngraving,
  onOpenWithAdapter,
  theme,
  previewMode,
  onAssetChanged,
}: {
  item: Asset;
  onSaveTags: (id: string, tags: string[]) => void;
  onSaveDetails: (id: string, payload: { notes: string; creator: string; collection: string }) => void;
  onRename: (id: string, filename: string) => void;
  onPreview: (asset: Asset | null) => void;
  onDownloadSingle: (asset: Asset) => void;
  onDownloadByTag: (tag: string) => void;
  downloading: boolean;
  onDelete: (asset: Asset) => void;
  deleting: boolean;
  onMoveFolder: (id: string, folder_id: string | null) => void;
  folderOptions: { id: string | null; name: string }[];
  moving: boolean;
  selected: boolean;
  onToggleSelected: () => void;
  bulkDownloading: boolean;
  slicerEnabled: boolean;
  slicerLabel: string;
  onOpenInSlicer: (asset: Asset) => void;
  engravingEnabled: boolean;
  engraverLabel: string;
  onOpenInEngraving: (asset: Asset) => void;
  onOpenWithAdapter: (
    asset: Asset,
    filename: string,
    contentRole: HandoffContentRole,
    selection?: { revision_id?: string; file_id?: string },
  ) => void;
  theme: ResolvedTheme;
  previewMode: PreviewSettings["mode"];
  onAssetChanged: (asset: Asset) => void;
}) {
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
  const [scopeFilesToVersion, setScopeFilesToVersion] = useState(false);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [revisions, setRevisions] = useState<ArtifactRevision[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [revisionUploading, setRevisionUploading] = useState(false);
  const [restoringRevisionId, setRestoringRevisionId] = useState<string | null>(null);
  const [revisionNote, setRevisionNote] = useState("");
  const relatedInputRef = useRef<HTMLInputElement | null>(null);
  const revisionInputRef = useRef<HTMLInputElement | null>(null);

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

  const loadRevisions = async () => {
    setHistoryLoading(true);
    try {
      setRevisions(await listArtifactRevisions(item.id));
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Failed to load version history");
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (historyExpanded) void loadRevisions();
  }, [historyExpanded, item.id]);

  const addRelatedFiles = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    setFilesUploading(true);
    try {
      let updated = item;
      for (const file of files) {
        updated = await uploadAssetFile(
          item.id,
          file,
          scopeFilesToVersion ? item.current_revision_id : null,
        );
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

  const addRevision = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setRevisionUploading(true);
    try {
      const result = await uploadArtifactRevision(
        item.id,
        file,
        revisionNote,
        item.current_revision_id,
      );
      onAssetChanged(result.asset);
      setRevisionNote("");
      setRevisions(await listArtifactRevisions(item.id));
      setHistoryExpanded(true);
      if (!result.created) alert("That file is identical to the current version; no new version was added.");
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Failed to add version");
    } finally {
      setRevisionUploading(false);
    }
  };

  const restoreVersion = async (revision: ArtifactRevision) => {
    if (!window.confirm(`Restore version ${revision.revision_number} as a new current version?`)) return;
    setRestoringRevisionId(revision.id);
    try {
      const result = await restoreArtifactRevision(item.id, revision.id);
      onAssetChanged(result.asset);
      setRevisions(await listArtifactRevisions(item.id));
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Failed to restore version");
    } finally {
      setRestoringRevisionId(null);
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
    } else if (val.startsWith("tag:")) {
      onDownloadByTag(val.slice(4));
    }
  };

  const canOpenInSlicer = slicerEnabled && (Boolean(item.prepared_print) || MODEL_EXTS.has(extOf(item.filename)));
  const canOpenInEngraving = engravingEnabled && ENGRAVING_EXTS.has(extOf(item.filename));
  const generalAdapter = generalAdapterFor(item.filename);

  return (
    <div className="rounded-lg border border-panel overflow-hidden bg-panel-soft">
      <div
        className="h-40 relative cursor-pointer"
        data-asset-id={item.id}
        onDoubleClick={() => onPreview(item)}
        title="Double-click to open large preview"
        onClick={e => e.stopPropagation()}
      >
        {renderPreviewContent(item, "card", theme, previewMode, onAssetChanged)}
      </div>
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
              onChange={onToggleSelected}
              aria-label={`Select ${item.name || item.filename}`}
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
              {item.tags.map(t => (
                <option key={`tag-${t}`} value={`tag:${t}`}>Download tag: {t}</option>
              ))}
            </select>
            {(downloading || bulkDownloading) && (
              <span className="text-xs opacity-70">{downloading ? "Downloading..." : "Preparing..."}</span>
            )}
          </div>
        </div>
        {(canOpenInSlicer || canOpenInEngraving || generalAdapter) && (
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
            {generalAdapter && (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
                onClick={() => onOpenWithAdapter(item, item.filename, "primary")}
                disabled={downloading || bulkDownloading}
              >
                Open with {generalAdapter.label}
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
              <label className="mb-2 flex items-start gap-2 text-xs text-muted">
                <input
                  type="checkbox"
                  checked={scopeFilesToVersion}
                  onChange={event => setScopeFilesToVersion(event.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  Attach documentation to the current version only
                  <span className="block text-[11px] text-subtle">Leave off for files that apply to the whole model.</span>
                </span>
              </label>
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
                      <div className="flex shrink-0 items-center gap-2">
                        {generalAdapterFor(file.filename) && (
                          <button
                            type="button"
                            className="text-[11px] text-blue-700 dark:text-blue-300"
                            onClick={() => onOpenWithAdapter(
                              item,
                              file.filename,
                              "supporting",
                              { file_id: file.id },
                            )}
                          >
                            Open with {generalAdapterFor(file.filename)?.label}
                          </button>
                        )}
                        <button
                          type="button"
                          className="text-[11px] text-red-700 dark:text-red-300"
                          onClick={() => removeRelatedFile(file)}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted">Add assembly instructions, notes, other documentation, or a prepared print.</div>
              )}
            </div>
          )}
        </div>
        <div className="rounded-md border border-panel-strong bg-panel-strong/40 text-sm">
          <div className="flex items-center justify-between gap-2 p-2">
            <button
              type="button"
              className="flex min-w-0 items-center gap-2 text-left"
              onClick={() => setHistoryExpanded(value => !value)}
            >
              <ChevronRight className={`h-4 w-4 transition-transform ${historyExpanded ? "rotate-90" : ""}`} />
              <span className="font-medium">Version history</span>
              {revisions.length > 0 && (
                <span className="rounded-full bg-panel px-2 py-0.5 text-[11px] text-muted">{revisions.length}</span>
              )}
            </button>
            <a
              className="rounded-md border border-panel-strong px-2 py-1 text-xs"
              href={artifactHistoryExportUrl(item.id)}
              download
              title="Download every version and attachment with a manifest"
            >
              Export
            </a>
          </div>
          {historyExpanded && (
            <div className="space-y-2 border-t border-panel px-2 py-2">
              <div className="flex gap-2">
                <input
                  value={revisionNote}
                  onChange={event => setRevisionNote(event.target.value)}
                  className="min-w-0 flex-1 rounded-md border border-panel-strong bg-panel-soft px-2 py-1 text-xs"
                  maxLength={500}
                  placeholder="What changed? (optional)"
                />
                <input
                  ref={revisionInputRef}
                  type="file"
                  className="hidden"
                  onChange={addRevision}
                />
                <button
                  type="button"
                  className="rounded-md border border-panel-strong px-2 py-1 text-xs disabled:opacity-60"
                  disabled={revisionUploading}
                  onClick={() => revisionInputRef.current?.click()}
                >
                  {revisionUploading ? "Adding..." : "Add version"}
                </button>
              </div>
              {historyLoading ? (
                <div className="text-xs text-muted">Loading versions...</div>
              ) : revisions.length ? (
                <div className="space-y-1">
                  {revisions.map(revision => (
                    <div key={revision.id} className="rounded border border-panel px-2 py-2 text-xs">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-medium">Version {revision.revision_number}</span>
                            {revision.is_current && (
                              <span className="rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] text-blue-800 dark:bg-blue-950 dark:text-blue-200">Current</span>
                            )}
                            {revision.content_state !== "ready" && (
                              <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-900 dark:bg-amber-950 dark:text-amber-200">{revision.content_state}</span>
                            )}
                          </div>
                          <div className="truncate text-subtle" title={revision.filename}>{revision.filename}</div>
                          {revision.change_note && <div className="mt-1 text-muted">{revision.change_note}</div>}
                          <div className="mt-1 text-[10px] text-subtle">{new Date(revision.created_at).toLocaleString()}</div>
                          {revision.prepared_print && <div className="mt-1 text-[10px] text-muted">Prepared print included</div>}
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          {revision.content_state === "ready" && (
                            <a className="underline-offset-2 hover:underline" href={fileUrl(revision.url)} download={revision.filename}>Download</a>
                          )}
                          {revision.content_state === "ready" && generalAdapterFor(revision.filename) && (
                            <button
                              type="button"
                              className="text-blue-700 dark:text-blue-300"
                              onClick={() => onOpenWithAdapter(
                                item,
                                revision.filename,
                                "revision_primary",
                                { revision_id: revision.id },
                              )}
                            >
                              Open with {generalAdapterFor(revision.filename)?.label}
                            </button>
                          )}
                          {!revision.is_current && revision.content_state === "ready" && (
                            <button
                              type="button"
                              className="text-blue-700 disabled:opacity-60 dark:text-blue-300"
                              disabled={restoringRevisionId !== null}
                              onClick={() => restoreVersion(revision)}
                            >
                              {restoringRevisionId === revision.id ? "Restoring..." : "Restore"}
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted">No version history is available yet.</div>
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
}, (previous, next) => (
  previous.item === next.item
  && previous.downloading === next.downloading
  && previous.deleting === next.deleting
  && previous.folderOptions === next.folderOptions
  && previous.moving === next.moving
  && previous.selected === next.selected
  && previous.bulkDownloading === next.bulkDownloading
  && previous.slicerEnabled === next.slicerEnabled
  && previous.slicerLabel === next.slicerLabel
  && previous.engravingEnabled === next.engravingEnabled
  && previous.engraverLabel === next.engraverLabel
  && previous.theme === next.theme
  && previous.previewMode === next.previewMode
));

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
  previewMode: PreviewSettings["mode"] = "automatic",
  onAssetChanged?: (asset: Asset) => void,
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
      return <img src={thumbUrl} alt={asset.filename} className={imgClass} />;
    }
    if (ext === "svg") {
      return <img src={assetUrl} alt={asset.filename} className={imgClass} />;
    }
    if (is3d) {
      if (previewMode === "disabled") {
        return <div className="flex h-full w-full items-center justify-center text-xs text-muted">Preview generation disabled</div>;
      }
      return (
        <ModelSnapshot
          url={assetUrl}
          ext={ext}
          assetId={asset.id}
          theme={theme}
          mode={previewMode}
          previewStatus={asset.preview_status || "pending"}
          previewReason={asset.preview_reason}
          onAssetChanged={onAssetChanged}
        />
      );
    }
    if (isLightBurn) {
      if (previewMode === "disabled") {
        return <div className="flex h-full w-full items-center justify-center text-xs text-muted">Preview generation disabled</div>;
      }
      return (
        <LightBurnPreview
          url={assetUrl}
          assetId={asset.id}
          byteSize={asset.size}
          filename={asset.filename}
          imgClass={imgClass}
          mode={previewMode}
          previewStatus={asset.preview_status}
          previewReason={asset.preview_reason}
          onAssetChanged={onAssetChanged}
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
    return (
      <ModelViewer
        key={`${variant}-${asset.id}`}
        url={assetUrl}
        ext={ext}
        assetId={asset.id}
        assetSize={asset.size}
        requireConfirmation={asset.preview_status === "skipped_policy"}
        theme={theme}
      />
    );
  }
  if (thumbUrl || ext === "svg") {
    const src = thumbUrl || assetUrl;
    return <img src={src} alt={asset.filename} className={imgClass} />;
  }
  if (isLightBurn) {
    return (
      <LightBurnPreview
        url={assetUrl}
        assetId={asset.id}
        byteSize={asset.size}
        filename={asset.filename}
        imgClass={imgClass}
        previewStatus={asset.preview_status}
        previewReason={asset.preview_reason}
        onAssetChanged={onAssetChanged}
      />
    );
  }
  return (
    <div className="flex items-center justify-center w-full h-full text-sm opacity-60">
      Preview unavailable
    </div>
  );
}

function AssetPreviewModal({
  asset,
  theme,
  onAssetChanged,
  onContextChanged,
  onUnauthorized,
  onClose,
}: {
  asset: Asset;
  theme: ResolvedTheme;
  onAssetChanged?: (asset: Asset) => void;
  onContextChanged?: () => void;
  onUnauthorized?: () => void;
  onClose: () => void;
}) {
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
              {asset.filename} · {formatFileSize(asset.size)}
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
          {shouldLoadMachineContext(true) && (
            <MachineContextPanel
              asset={asset}
              onAssetChanged={onAssetChanged}
              onContextChanged={onContextChanged}
              onUnauthorized={onUnauthorized}
            />
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

function formatFileSize(bytes: number) {
  if (!bytes && bytes !== 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx++;
  }
  return `${size.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}
