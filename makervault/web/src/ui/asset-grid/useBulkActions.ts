import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  type Asset,
  type BatchFailure,
  UnauthorizedError,
  batchDeleteAssets,
  batchMoveAssets,
  batchSetTags,
  downloadZip,
} from "../../lib/api";
import {
  type BatchOutcome,
  applyBatchOutcome,
  applyFolderLocally,
  applyTagsLocally,
  dropIds,
  failureLines,
  unionTags,
} from "../../lib/bulkUi";
import { saveResponseToDisk } from "../../lib/download";
import { notifyInfo } from "../../lib/toast";
import { useStableCallback } from "../../lib/useStableCallback";

type BulkActionsOptions = {
  folderId?: string | null;
  activeTags: string[];
  items: Asset[];
  setItems: Dispatch<SetStateAction<Asset[]>>;
  offset: number;
  setOffset: Dispatch<SetStateAction<number>>;
  setAllTags: Dispatch<SetStateAction<string[]>>;
  handleApiError: (err: unknown, message?: string) => boolean;
  onUnauthorized?: () => void;
  onAddToProject: (ids: string[]) => void;
};

export type BulkActionsApi = {
  selectedIds: Set<string>;
  toggleSelected: (id: string) => void;
  clearSelection: () => void;
  selectAllLoaded: () => void;
  bulkBusy: { label: string; count: number } | null;
  bulkFailures: BatchFailure[] | null;
  bulkRequestError: string | null;
  bulkFailureLabels: { id: string; label: string; message: string }[];
  dismissBulkFailures: () => void;
  bulkDelete: () => Promise<void>;
  bulkMoveToFolder: (targetFolderId: string | null) => Promise<void>;
  bulkAddTags: (tags: string[]) => Promise<void>;
  bulkRemoveTags: (tags: string[]) => Promise<void>;
  bulkSetTags: (add: string[], remove: string[]) => Promise<void>;
  bulkAddToProject: () => void;
  bulkDownloading: string | null;
  downloadSelected: () => Promise<void>;
  downloadByTag: (tag: string) => Promise<void>;
};

/**
 * Selection plus the bulk operations that act on it. Mutations are applied
 * optimistically from a snapshot and rolled back as a unit, so the paging
 * cursor can never drift from what is on screen.
 */
export function useBulkActions({
  folderId,
  activeTags,
  items,
  setItems,
  offset,
  setOffset,
  setAllTags,
  handleApiError,
  onUnauthorized,
  onAddToProject,
}: BulkActionsOptions): BulkActionsApi {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDownloading, setBulkDownloading] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState<{ label: string; count: number } | null>(null);
  const [bulkFailures, setBulkFailures] = useState<BatchFailure[] | null>(null);
  const [bulkRequestError, setBulkRequestError] = useState<string | null>(null);

  useEffect(() => {
    const present = new Set(items.map(i => i.id));
    setSelectedIds(prev => new Set([...prev].filter(id => present.has(id))));
  }, [items]);

  const bulkFailureLabels = useMemo(
    () => failureLines(bulkFailures ?? [], items),
    [bulkFailures, items],
  );

  const toggleSelected = useStableCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  });

  const clearSelection = useStableCallback(() => {
    setSelectedIds(new Set());
  });

  const selectAllLoaded = useStableCallback(() => {
    setSelectedIds(new Set(items.map(item => item.id)));
  });

  const dismissBulkFailures = useStableCallback(() => {
    setBulkFailures(null);
    setBulkRequestError(null);
  });

  // Snapshot-based: the loaded window and the paging cursor are recomputed from
  // what was on screen before the action, so rollback cannot drift. Failures
  // stay selected so their per-asset explanation remains visible.
  const finishBulk = (before: Asset[], startOffset: number, outcome: BatchOutcome) => {
    const { items: next, offsetDelta } = applyBatchOutcome(before, outcome);
    setItems(next);
    setOffset(Math.max(0, startOffset - offsetDelta));
    setBulkFailures(outcome.failed.length ? outcome.failed : null);
    if (outcome.kind !== "delete") setAllTags(prev => unionTags(prev, outcome.updated));
    const failedIds = outcome.failed
      .map(failure => failure.id)
      .filter(id => next.some(item => item.id === id));
    if (failedIds.length) {
      setSelectedIds(prev => new Set([...prev, ...failedIds]));
    }
  };

  // A whole-request failure (bad body, 400, network) rewinds to the snapshot and
  // reports through the bar instead of an alert.
  const rollbackBulk = (
    before: Asset[],
    startOffset: number,
    ids: string[],
    err: unknown,
    fallback: string,
  ) => {
    console.error(err);
    setItems(before);
    setOffset(startOffset);
    const present = new Set(before.map(item => item.id));
    setSelectedIds(new Set(ids.filter(id => present.has(id))));
    setBulkRequestError(err instanceof Error ? err.message : fallback);
  };

  const bulkDelete = useStableCallback(async () => {
    if (bulkBusy || selectedIds.size === 0) return;
    const before = items;
    const startOffset = offset;
    const ids = Array.from(selectedIds);
    const droppedCount = before.filter(item => selectedIds.has(item.id)).length;
    setBulkFailures(null);
    setBulkRequestError(null);
    setBulkBusy({ label: "Deleting", count: ids.length });
    setItems(dropIds(before, ids));
    setOffset(Math.max(0, startOffset - droppedCount));
    try {
      const result = await batchDeleteAssets(ids);
      finishBulk(before, startOffset, {
        kind: "delete",
        deleted: result.deleted,
        failed: result.failed,
        view: { folderId, activeTags },
      });
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        setBulkRequestError("You were signed out. The delete may still have been applied.");
      } else {
        rollbackBulk(before, startOffset, ids, err, "Bulk delete failed.");
      }
    } finally {
      setBulkBusy(null);
    }
  });

  const bulkMoveAssets = useStableCallback(async (targetFolderId: string | null) => {
    if (bulkBusy || selectedIds.size === 0) return;
    const before = items;
    const startOffset = offset;
    const ids = Array.from(selectedIds);
    setBulkFailures(null);
    setBulkRequestError(null);
    setBulkBusy({ label: "Moving", count: ids.length });
    setItems(applyFolderLocally(before, ids, targetFolderId));
    setOffset(startOffset);
    try {
      const result = await batchMoveAssets(ids, targetFolderId);
      finishBulk(before, startOffset, {
        kind: "folder",
        updated: result.updated,
        failed: result.failed,
        view: { folderId, activeTags },
      });
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        setBulkRequestError("You were signed out. The move may still have been applied.");
      } else {
        rollbackBulk(before, startOffset, ids, err, "Bulk move failed.");
      }
    } finally {
      setBulkBusy(null);
    }
  });

  const bulkSetTags = useStableCallback(async (add: string[], remove: string[]) => {
    if (bulkBusy || selectedIds.size === 0) return;
    const before = items;
    const startOffset = offset;
    const ids = Array.from(selectedIds);
    setBulkFailures(null);
    setBulkRequestError(null);
    setBulkBusy({ label: "Updating tags", count: ids.length });
    setItems(applyTagsLocally(before, ids, add, remove));
    setOffset(startOffset);
    try {
      const result = await batchSetTags(ids, { add, remove });
      finishBulk(before, startOffset, {
        kind: "tags",
        updated: result.updated,
        failed: result.failed,
        view: { folderId, activeTags },
      });
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        setBulkRequestError("You were signed out. The tag change may still have been applied.");
      } else {
        rollbackBulk(before, startOffset, ids, err, "Bulk tag update failed.");
      }
    } finally {
      setBulkBusy(null);
    }
  });

  const bulkMoveToFolder = useStableCallback(async (targetFolderId: string | null) => {
    await bulkMoveAssets(targetFolderId);
  });

  const bulkAddTags = useStableCallback(async (tags: string[]) => {
    await bulkSetTags(tags, []);
  });

  const bulkRemoveTags = useStableCallback(async (tags: string[]) => {
    await bulkSetTags([], tags);
  });

  // Deliberately a thin passthrough: the bar's contract stays uniform (one
  // callback per action) and the empty-selection guard stays here, next to the
  // selection it protects.
  const bulkAddToProject = useStableCallback(() => {
    if (bulkBusy || selectedIds.size === 0) return;
    onAddToProject(Array.from(selectedIds));
  });

  const downloadSelected = useStableCallback(async () => {
    if (!selectedIds.size) {
      notifyInfo("Select at least one item to download.");
      return;
    }
    try {
      setBulkDownloading("selected");
      const res = await downloadZip({ asset_ids: Array.from(selectedIds) });
      await saveResponseToDisk(res, "makersvault-selected.zip");
    } catch (err) {
      handleApiError(err, "Bulk download failed.");
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
      handleApiError(err, "Download by tag failed.");
    } finally {
      setBulkDownloading(null);
    }
  });

  return {
    selectedIds,
    toggleSelected,
    clearSelection,
    selectAllLoaded,
    bulkBusy,
    bulkFailures,
    bulkRequestError,
    bulkFailureLabels,
    dismissBulkFailures,
    bulkDelete,
    bulkMoveToFolder,
    bulkAddTags,
    bulkRemoveTags,
    bulkSetTags,
    bulkAddToProject,
    bulkDownloading,
    downloadSelected,
    downloadByTag,
  };
}
