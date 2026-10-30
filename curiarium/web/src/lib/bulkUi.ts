import type { Asset, BatchFailure, BatchMetaChange } from "./api";

/**
 * Pure reconciliation for bulk actions.
 *
 * A bulk endpoint answers per asset (`updated`/`deleted` plus `failed`). The
 * grid keeps a snapshot of the loaded window from before the action and
 * replays that answer over it: successes take the server row, failures roll
 * back to the snapshot, and the paging cursor rewinds by however many rows
 * left the server-side result set. Nothing here touches the DOM.
 */

export type ViewFilter = {
  folderId?: string | null;
  activeTags: string[];
  /** Exact creator facet, case-insensitive; unset/blank means "no filter". */
  activeCreator?: string | null;
};

/** Trim, drop empties and de-duplicate by exact string (no case folding). */
function normalized(list: string[]): string[] {
  const out: string[] = [];
  for (const raw of list) {
    const tag = raw.trim();
    if (!tag) continue;
    if (!out.includes(tag)) out.push(tag);
  }
  return out;
}

/** Server tag-merge rule, mirrored: exact-string match, order preserved. */
export function mergeTagsLocally(current: string[], add: string[], remove: string[]): string[] {
  const removed = new Set(normalized(remove));
  const kept = normalized(current).filter(tag => !removed.has(tag));
  for (const tag of normalized(add)) {
    if (!kept.includes(tag)) kept.push(tag);
  }
  return kept;
}

export function applyTagsLocally(
  items: Asset[],
  ids: string[],
  add: string[],
  remove: string[],
): Asset[] {
  const target = new Set(ids);
  return items.map(item =>
    target.has(item.id) ? { ...item, tags: mergeTagsLocally(item.tags, add, remove) } : item,
  );
}

export function applyFolderLocally(
  items: Asset[],
  ids: string[],
  folderId: string | null,
): Asset[] {
  const target = new Set(ids);
  return items.map(item =>
    target.has(item.id) ? { ...item, folder_id: folderId } : item,
  );
}

export function dropIds(items: Asset[], ids: string[]): Asset[] {
  const target = new Set(ids);
  return items.filter(item => !target.has(item.id));
}

/** Apply a creator/notes change to exactly the given ids; absent keys stay put. */
export function applyMetaLocally(
  items: Asset[],
  ids: string[],
  change: BatchMetaChange,
): Asset[] {
  const target = new Set(ids);
  return items.map(item => {
    if (!target.has(item.id)) return item;
    const next = { ...item };
    if (change.creator !== undefined) next.creator = change.creator;
    if (change.notes !== undefined) next.notes = change.notes;
    return next;
  });
}

export type BatchOutcome =
  | { kind: "delete"; deleted: string[]; failed: BatchFailure[]; view: ViewFilter }
  | { kind: "folder"; updated: Asset[]; failed: BatchFailure[]; view: ViewFilter }
  | { kind: "tags"; updated: Asset[]; failed: BatchFailure[]; view: ViewFilter }
  | { kind: "meta"; updated: Asset[]; failed: BatchFailure[]; view: ViewFilter };

/** Folder/creator views only filter when that facet is actually set. */
function matchesView(asset: Asset, view: ViewFilter): boolean {
  if (view.folderId && (asset.folder_id ?? null) !== view.folderId) return false;
  // Mirrors `apply_asset_filters`: an exact, trimmed, case-insensitive creator
  // match where a NULL creator can never match a non-blank filter.
  const creator = (view.activeCreator ?? "").trim().toLowerCase();
  if (creator && (asset.creator ?? "").toLowerCase() !== creator) return false;
  // The server's tag filter is AND: every active tag must be present.
  // Case-insensitive on purpose, not a preference: the server filters with
  // `tags_json LIKE '%"tag"%'` and SQLite LIKE folds ASCII case, so a row tagged
  // "PLA" stays in the result set for `pla`. Matching exactly here would drop
  // it locally, over-count `offsetDelta`, and make "Load more" re-fetch a row.
  return view.activeTags.every(tag =>
    asset.tags.some(assetTag => assetTag.toLowerCase() === tag.toLowerCase()),
  );
}

/**
 * Rebuild the loaded window from the pre-action snapshot and the server's
 * per-id answer: successes take the server row, failures roll back to the
 * snapshot, and rows that no longer match the active view filter leave.
 * `offsetDelta` is how many loaded rows left the server-side result set; the
 * paging cursor must rewind by exactly that or "Load more" silently skips rows.
 */
export function applyBatchOutcome(
  before: Asset[],
  outcome: BatchOutcome,
): { items: Asset[]; offsetDelta: number } {
  let items: Asset[];

  if (outcome.kind === "delete") {
    const deleted = new Set(outcome.deleted);
    items = before.filter(item => !deleted.has(item.id));
  } else {
    const updatedById = new Map(outcome.updated.map(item => [item.id, item]));
    items = [];
    for (const row of before) {
      const updated = updatedById.get(row.id);
      if (!updated) {
        // Absent from both `updated` and `failed`: stay conservative.
        items.push(row);
        continue;
      }
      if (matchesView(updated, outcome.view)) items.push(updated);
    }
  }

  const offsetDelta = Math.max(0, before.length - items.length);
  return { items, offsetDelta };
}

/**
 * One asset's server-answered mutation, reconciled exactly like a batch of one:
 * the server row replaces the snapshot row when it still matches the active
 * view, and leaves the loaded window when the change took it out of the
 * filtered result set. `offsetDelta` is 0 or 1 and is the absolute rewind the
 * paging cursor owes. An id that is not in the snapshot reconciles to a no-op.
 */
export function applySingleOutcome(
  before: Asset[],
  updated: Asset,
  view: ViewFilter,
): { items: Asset[]; offsetDelta: number } {
  const index = before.findIndex(item => item.id === updated.id);
  if (index < 0) return { items: before, offsetDelta: 0 };
  if (!matchesView(updated, view)) {
    return { items: before.filter(item => item.id !== updated.id), offsetDelta: 1 };
  }
  const items = [...before];
  items[index] = updated;
  return { items, offsetDelta: 0 };
}

/** Per-asset failure lines for the UI: filename when known, else the id. */
export function failureLines(
  failed: BatchFailure[],
  items: Asset[],
): { id: string; label: string; message: string }[] {
  const byId = new Map(items.map(item => [item.id, item]));
  return failed.map(failure => {
    const asset = byId.get(failure.id);
    return {
      id: failure.id,
      label: asset ? asset.filename || asset.name || failure.id : failure.id,
      message: failure.error,
    };
  });
}

/** Union of the current tag list and every tag on the given assets (never removes). */
export function unionTags(allTags: string[], assets: Asset[]): string[] {
  const out = [...allTags];
  for (const asset of assets) {
    for (const tag of asset.tags) {
      if (!out.includes(tag)) out.push(tag);
    }
  }
  return out;
}
