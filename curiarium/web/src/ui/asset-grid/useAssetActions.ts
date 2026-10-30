import {
  type Dispatch,
  type SetStateAction,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  type Asset,
  UnauthorizedError,
  downloadAsset,
  fileUrl,
  getLibraryScanStatus,
  setTags,
  startLibraryScan,
  updateAssetFolder,
  updateAssetMeta,
} from "../../lib/api";
import { saveResponseToDisk } from "../../lib/download";
import { primeGrants } from "../../lib/fileGrants";
import type {
  EngravingSettings,
  SlicerSettings,
} from "../../lib/settings";
import { notifyError } from "../../lib/toast";
import { useStableCallback } from "../../lib/useStableCallback";
import type { ConfirmRequest } from "../ConfirmDialog";
import {
  RESCAN_POLL_INTERVAL_MS,
  RESCAN_TIMEOUT_MS,
  type RefreshOpts,
} from "./assetGridMeta";

type AssetActionsOptions = {
  items: Asset[];
  setItems: Dispatch<SetStateAction<Asset[]>>;
  setPreviewItem: Dispatch<SetStateAction<Asset | null>>;
  refresh: (opts?: RefreshOpts) => Promise<void>;
  handleApiError: (err: unknown, message?: string) => boolean;
  onUnauthorized?: () => void;
  slicerSettings?: SlicerSettings;
  engravingSettings?: EngravingSettings;
  selectedIds: Set<string>;
  bulkSetTags: (add: string[], remove: string[]) => Promise<void>;
  /** Opens the grid's delete dialog for exactly these targets. */
  onRequestDelete: (assets: Asset[]) => void;
  onAddToProject: (ids: string[]) => void;
};

export type AssetActionsApi = {
  downloadingId: string | null;
  movingId: string | null;
  rescanning: boolean;
  replaceAsset: (updated: Asset) => void;
  onSaveTags: (id: string, tags: string[]) => Promise<void>;
  onSaveDetails: (
    id: string,
    payload: { notes: string; creator: string },
  ) => Promise<void>;
  onRename: (id: string, name: string) => Promise<void>;
  onMoveFolder: (id: string, folder_id: string | null) => Promise<void>;
  downloadSingle: (asset: Asset) => Promise<void>;
  openInSlicer: (asset: Asset) => void;
  openInEngraving: (asset: Asset) => void;
  removeAsset: (asset: Asset) => void;
  addToProject: (asset: Asset) => void;
  forgetMissingAsset: (asset: Asset) => void;
  rescanMissing: (asset: Asset) => Promise<void>;
  pendingConfirm: ConfirmRequest | null;
  confirmBusy: boolean;
  setPendingConfirm: Dispatch<SetStateAction<ConfirmRequest | null>>;
  requestConfirm: (request: ConfirmRequest) => void;
  runPendingConfirm: () => Promise<void>;
};

/**
 * Per-asset actions (download, rename, move, delete, re-scan) and the single
 * parent-owned confirmation queue every card asks for a dialog through. Deletes
 * are only *requested* here: the grid's dialog owns the confirmation and the
 * request (Mf-cea1).
 */
export function useAssetActions({
  items,
  setItems,
  setPreviewItem,
  refresh,
  handleApiError,
  onUnauthorized,
  slicerSettings,
  engravingSettings,
  selectedIds,
  bulkSetTags,
  onRequestDelete,
  onAddToProject,
}: AssetActionsOptions): AssetActionsApi {
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const [movingId, setMovingId] = useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const confirmRunningRef = useRef(false);
  const slicerEnabled = Boolean(slicerSettings?.enabled);
  const engravingEnabled = Boolean(engravingSettings?.enabled);

  const itemById = useMemo(() => {
    const map: Record<string, Asset> = {};
    items.forEach(it => { map[it.id] = it; });
    return map;
  }, [items]);

  const replaceAsset = useStableCallback((updated: Asset) => {
    setItems(current => current.map(item => item.id === updated.id ? updated : item));
    setPreviewItem(current => current?.id === updated.id ? updated : current);
  });

  // One parent-owned dialog serves the card-local confirmations (supporting-file
  // removals, prepared-print clears). Asset deletes go through their own dialog,
  // because those need a typed/stepped confirmation the grid owns. Stable so
  // memoised cards can request one without re-rendering.
  const requestConfirm = useStableCallback((request: ConfirmRequest) => {
    setPendingConfirm(request);
  });

  const runPendingConfirm = useStableCallback(async () => {
    if (!pendingConfirm || confirmRunningRef.current) return;
    confirmRunningRef.current = true;
    setConfirmBusy(true);
    try {
      await pendingConfirm.run();
    } finally {
      confirmRunningRef.current = false;
      setConfirmBusy(false);
      setPendingConfirm(null);
    }
  });

  const onSaveTags = useStableCallback(async (id: string, tags: string[]) => {
    const item = itemById[id];
    // Editing the tags of a selected card while several cards are selected is a
    // bulk edit: one request for the whole selection, not one per card.
    if (item && selectedIds.has(id) && selectedIds.size > 1) {
      const add = tags.filter(tag => !item.tags.includes(tag));
      const remove = item.tags.filter(tag => !tags.includes(tag));
      if (!add.length && !remove.length) return;
      await bulkSetTags(add, remove);
      return;
    }
    try {
      await setTags(id, tags);
      await refresh({ keepLoadedPages: true });
    } catch (err) {
      handleApiError(err, "Tag update failed.");
    }
  });

  const onSaveDetails = useStableCallback(async (id: string, payload: { notes: string; creator: string }) => {
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
      handleApiError(err, err instanceof Error ? err.message : "Folder update failed. Please try again.");
    } finally {
      setMovingId(null);
    }
  });

  const downloadSingle = useStableCallback(async (asset: Asset) => {
    try {
      setDownloadingId(asset.id);
      await saveResponseToDisk(await downloadAsset(asset), asset.filename || "download");
    } catch (err) {
      handleApiError(err, "Download failed. Please try again.");
    } finally {
      setDownloadingId(null);
    }
  });

  const openInSlicer = useStableCallback(async (asset: Asset) => {
    if (!slicerEnabled) return;
    const rel = asset.slicer_url || asset.url;
    // The OS handler fetches this URL without our headers, so it gets a signed,
    // file-scoped, 60-second grant instead of the session JWT. A failed mint
    // leaves the plain URL, exactly as a grant-less browser render would.
    await primeGrants([rel]);
    const url = fileUrl(rel);
    const params = new URLSearchParams({
      url,
      slicer: slicerSettings?.selected || "orca",
      filename: asset.slicer_filename || asset.filename || "model",
    });
    const target = `curiarium-slicer://open?${params.toString()}`;
    window.location.href = target;
  });

  const openInEngraving = useStableCallback(async (asset: Asset) => {
    if (!engravingEnabled) return;
    await primeGrants([asset.url]);
    const url = fileUrl(asset.url);
    const params = new URLSearchParams({
      url,
      engraver: engravingSettings?.selected || "lightburn",
      filename: asset.filename || "design",
    });
    const target = `curiarium-engrave://open?${params.toString()}`;
    window.location.href = target;
  });

  // Deletes never run from here any more: the grid's delete dialog owns the
  // typed/stepped confirmation and the request. This only hands it the target
  // set — a card inside a multi-selection acts on the whole selection.
  const removeAsset = useStableCallback((asset: Asset) => {
    const targets = selectedIds.has(asset.id) && selectedIds.size > 1
      ? items.filter(item => selectedIds.has(item.id))
      : [asset];
    onRequestDelete(targets);
  });

  // The card's "Add to project" is a selection-scoped affordance exactly like
  // delete: a card inside a multi-selection acts on the whole selection.
  // Stable so memoised cards keep their props identity.
  const addToProject = useStableCallback((asset: Asset) => {
    const ids = selectedIds.has(asset.id) && selectedIds.size > 1
      ? Array.from(selectedIds)
      : [asset.id];
    onAddToProject(ids);
  });

  // "Forget entry" is the missing-file card's delete: the same dialog, because
  // the server demands the same `confirm_name` for it. It is never scoped to the
  // selection — the card which lost its file is the only row in question.
  const forgetMissingAsset = useStableCallback((asset: Asset) => {
    onRequestDelete([asset]);
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
      notifyError(err instanceof Error && err.message ? err.message : "Re-scan failed.");
    } finally {
      setRescanning(false);
    }
  });

  return {
    downloadingId,
    movingId,
    rescanning,
    replaceAsset,
    onSaveTags,
    onSaveDetails,
    onRename,
    onMoveFolder,
    downloadSingle,
    openInSlicer,
    openInEngraving,
    removeAsset,
    addToProject,
    forgetMissingAsset,
    rescanMissing,
    pendingConfirm,
    confirmBusy,
    setPendingConfirm,
    requestConfirm,
    runPendingConfirm,
  };
}
