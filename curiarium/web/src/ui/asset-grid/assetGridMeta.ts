import {
  Asset,
  ListAssetsResult,
  listAssets,
  listProjectAssets,
} from "../../lib/api";
import { colsForWidth } from "../../lib/virtualGrid";

/** Sort modes offered by the toolbar; the grouped sorts render section buckets. */
export type SortKey = "name" | "size" | "creator" | "type" | "folder";
export type SortDir = "asc" | "desc";

/** Keys the server orders the whole listing by; `type`/`folder` stay client-side. */
export const SERVER_SORT_KEYS: readonly SortKey[] = ["name", "size", "creator"];

export function serverSortKey(key: SortKey): "name" | "size" | "creator" | null {
  return SERVER_SORT_KEYS.includes(key) ? (key as "name" | "size" | "creator") : null;
}

export type RefreshOpts = {
  tags?: string[];
  search?: string;
  keepLoadedPages?: boolean;
  notInProject?: boolean;
  creator?: string | null;
  sortKey?: SortKey;
  sortDir?: SortDir;
};
export type GroupBucket = { id: string; title: string; items: Asset[] };
export type PreviewVariant = "card" | "modal";

export function extOf(name: string) {
  const m = /\.([^.]+)$/.exec(name);
  return (m?.[1] || "").toLowerCase();
}

export const MODEL_EXTS = new Set(["stl", "3mf", "step", "stp", "obj"]);
export const LIGHTBURN_EXTS = new Set(["lbrn", "lbrn2"]);
export const ENGRAVING_EXTS = new Set([
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

export const ROWS_PER_BATCH = 5;
/** Cards rendered per group before the "Show all" affordance is offered. */
export const GROUP_CARD_CAP = 24;
/** Upper bound on how long a re-scan triggered from a card is polled. */
export const RESCAN_TIMEOUT_MS = 10 * 60 * 1000;
export const RESCAN_POLL_INTERVAL_MS = 1000;

export function formatMissingSince(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/**
 * First-load page size: a handful of card rows. Uses the same `colsForWidth`
 * as the virtualization so the page size and the rendered row width can never
 * disagree.
 */
export function rowsBatchSizeForWidth(width: number) {
  return colsForWidth(width) * ROWS_PER_BATCH;
}

/** Placeholder so the folder nav props stay non-optional inside the grid. */
export function noop(): void {}

/**
 * The one place that decides between the folder-scoped and project-scoped asset
 * listing. A project has no folder axis, so `folderId` is ignored there.
 * `notInProject` is files-only: a project listing is already scoped by membership.
 */
export function fetchAssetPage(opts: {
  projectId?: string | null;
  q?: string;
  tags?: string[];
  folderId?: string;
  notInProject?: boolean;
  creator?: string;
  sort?: "name" | "size" | "creator";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}): Promise<ListAssetsResult> {
  if (opts.projectId) {
    return listProjectAssets({
      projectId: opts.projectId,
      q: opts.q,
      tags: opts.tags,
      creator: opts.creator,
      sort: opts.sort,
      order: opts.order,
      limit: opts.limit,
      offset: opts.offset,
    });
  }
  return listAssets({
    q: opts.q,
    tags: opts.tags,
    folder_id: opts.folderId,
    not_in_project: opts.notInProject,
    creator: opts.creator,
    sort: opts.sort,
    order: opts.order,
    limit: opts.limit,
    offset: opts.offset,
  });
}
