export const MAX_ASSET_PAGE_LIMIT = 1000;

export type RefreshWindow = { limit: number; offset: number };

/**
 * Window used by the asset list refresh.
 *
 * A plain refresh reloads a single page from the top. A refresh that preserves
 * the already-loaded pages re-requests the same prefix (page 0 up to the number
 * of items already on screen) so the DOM never shrinks and scroll position is
 * not clamped. The API caps `limit` at MAX_ASSET_PAGE_LIMIT.
 */
export function refreshWindow(
  loadedCount: number,
  pageSize: number,
  keepLoadedPages = false,
): RefreshWindow {
  if (!keepLoadedPages) {
    return { limit: pageSize, offset: 0 };
  }
  return { limit: Math.min(MAX_ASSET_PAGE_LIMIT, Math.max(loadedCount, pageSize)), offset: 0 };
}
