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
import {
  applyFolderLocally,
  applyMetaLocally,
  applySingleOutcome,
  applyTagsLocally,
  unionTags,
} from "../../lib/bulkUi";
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
  /**
   * The live paging cursor and the view facets, so a single mutation can be
   * reconciled in place instead of refetching page 1. Optional only because
   * harnesses mount this hook without a grid behind it; `AssetGrid` always
   * passes all of them.
   */
  offset?: number;
  setOffset?: Dispatch<SetStateAction<number>>;
  setAllTags?: Dispatch<SetStateAction<string[]>>;
  folderId?: string | null;
  activeTags?: string[];
  activeCreator?: string | null;
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
  offset = 0,
  setOffset,
  setAllTags,
  folderId,
  activeTags = [],
  activeCreator,
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

  // File-level changes (supporting-file add/remove, prepared-print clear) can
  // never change which rows the active filters return, so they keep the plain
  // map replace and never touch the paging cursor.
  const replaceAsset = useStableCallback((updated: Asset) => {
    setItems(current => current.map(item => item.id === updated.id ? updated : item));
    setPreviewItem(current => current?.id === updated.id ? updated : current);
  });

  // One mutation's server row, replayed over the pre-mutation snapshot exactly
  // like a batch of one: the row is replaced or dropped, and the cursor rewinds
  // by the rows that left the result set (absolute, never relative, or it would
  // double-count across a page boundary).
  const reconcileAsset = useStableCallback((updated: Asset, before: Asset[], startOffset: number) => {
    const view = { folderId, activeTags, activeCreator };
    const { items: next, offsetDelta } = applySingleOutcome(before, updated, view);
    setItems(next);
    setOffset?.(Math.max(0, startOffset - offsetDelta));
    // Bulk parity: a reconcile never touches preview state beyond this id match.
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
    const before = items;
    const startOffset = offset;
    // A card outside the loaded window has nothing to paint, so it waits for
    // the server row instead of guessing at one.
    if (item) {
      const add = tags.filter(tag => !item.tags.includes(tag));
      const remove = item.tags.filter(tag => !tags.includes(tag));
      setItems(applyTagsLocally(before, [id], add, remove));
      setOffset?.(startOffset);
    }
    try {
      const updated = await setTags(id, tags);
      reconcileAsset(updated, before, startOffset);
      setAllTags?.(prev => unionTags(prev, [updated]));
    } catch (err) {
      // A 401 already called `onUnauthorized` and is not a rollback: the write
      // may still have landed, exactly like the bulk paths.
      if (handleApiError(err, "Tag update failed.")) return;
      setItems(before);
      setOffset?.(startOffset);
    }
  });

  const onSaveDetails = useStableCallback(async (id: string, payload: { notes: string; creator: string }) => {
    const before = items;
    const startOffset = offset;
    setItems(applyMetaLocally(before, [id], payload));
    setOffset?.(startOffset);
    try {
      const updated = await updateAssetMeta(id, payload);
      reconcileAsset(updated, before, startOffset);
    } catch (err) {
      if (handleApiError(err, err instanceof Error ? err.message : "Failed to save model details.")) return;
      setItems(before);
      setOffset?.(startOffset);
    }
  });

  const onRename = useStableCallback(async (id: string, name: string) => {
    // Response-only: the server row is the only truth for a name. No optimistic
    // paint, and a failure still rethrows so the card's inline field reverts.
    const before = items;
    const startOffset = offset;
    try {
      const updated = await updateAssetMeta(id, { name });
      reconcileAsset(updated, before, startOffset);
    } catch (err) {
      if (handleApiError(err, err instanceof Error ? err.message : "Rename failed. Please try again.")) return;
      throw err;
    }
  });

  const onMoveFolder = useStableCallback(async (id: string, folder_id: string | null) => {
    const before = items;
    const startOffset = offset;
    setMovingId(id);
    // The optimistic phase only repaints: the row leaves the window at
    // reconcile, so a move out of the viewed folder drops the card once the
    // server confirms and rewinds the cursor by one.
    setItems(applyFolderLocally(before, [id], folder_id));
    setOffset?.(startOffset);
    try {
      const updated = await updateAssetFolder(id, folder_id);
      // A move never introduces a tag, so there is nothing to union here.
      reconcileAsset(updated, before, startOffset);
    } catch (err) {
      if (handleApiError(err, err instanceof Error ? err.message : "Folder update failed. Please try again.")) return;
      setItems(before);
      setOffset?.(startOffset);
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
