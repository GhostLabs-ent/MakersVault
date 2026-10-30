/**
 * Pure geometry for the virtualized asset grid.
 *
 * The grid is chunked into fixed rows of `cols` cards. Row heights are not
 * assumed to be uniform (missing banner, prepared-print block, expanded
 * supporting files, wrapped tags and the notes editor all change a card's
 * height), so callers measure them and feed the measurements back here as a
 * sparse `heights` array: `0`/`undefined` means "not measured yet" and the
 * estimate is used instead.
 *
 * Everything in this module is pure so the geometry can be unit-tested
 * without a DOM.
 */

/** Minimum width of one card, mirrored by the grid's `grid-template-columns`. */
export const CARD_MIN_WIDTH_PX = 260;
/** Gap between cards and between rows, mirrored by Tailwind's `gap-4`. */
export const GRID_GAP_PX = 16;
/** Height assumed for a row until it has actually been measured. */
export const ESTIMATED_ROW_HEIGHT = 360;
/** Extra rows rendered above and below the viewport (and the column count). */
export const OVERSCAN_ROWS = 2;

function isPositive(value: number | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/** Number of cards per row for a container of `width` CSS pixels. */
export function colsForWidth(width: number): number {
  const safeWidth = Number.isFinite(width) ? Math.max(0, width) : 0;
  return Math.max(
    1,
    Math.floor((safeWidth + GRID_GAP_PX) / (CARD_MIN_WIDTH_PX + GRID_GAP_PX)),
  );
}

/** Split a flat item list into rows of at most `cols` items (at least 1). */
export function chunkRows<T>(items: readonly T[], cols: number): T[][] {
  const perRow = Number.isFinite(cols) && cols >= 1 ? Math.floor(cols) : 1;
  const rows: T[][] = [];
  for (let start = 0; start < items.length; start += perRow) {
    rows.push(items.slice(start, start + perRow));
  }
  return rows;
}

/** Height used for a row: its measurement, or the estimate while unmeasured. */
export function rowHeightAt(
  heights: readonly number[],
  index: number,
  estimate = ESTIMATED_ROW_HEIGHT,
): number {
  const measured = heights[index];
  return isPositive(measured) ? measured : estimate;
}

/**
 * Top offset of every row, including the gap that precedes it. `tops[0]` is
 * always 0 and adjacent rows are `height + gap` apart.
 */
export function rowOffsets(
  heights: readonly number[],
  estimate = ESTIMATED_ROW_HEIGHT,
  gap = GRID_GAP_PX,
): number[] {
  const tops = new Array<number>(heights.length);
  let cursor = 0;
  for (let index = 0; index < heights.length; index += 1) {
    tops[index] = cursor;
    cursor += rowHeightAt(heights, index, estimate) + gap;
  }
  return tops;
}

/** Full scroll height of the rows, including the gaps between them. */
export function rowsTotal(
  heights: readonly number[],
  estimate = ESTIMATED_ROW_HEIGHT,
  gap = GRID_GAP_PX,
): number {
  if (!heights.length) return 0;
  let total = 0;
  for (let index = 0; index < heights.length; index += 1) {
    total += rowHeightAt(heights, index, estimate);
  }
  return total + gap * (heights.length - 1);
}

export type VirtualWindow = { startRow: number; endRow: number };

export type VirtualWindowInput = {
  /** Scroll offset of the grid's top above the viewport's top, in pixels. */
  offset: number;
  viewportHeight: number;
  /** Per-row top offsets from {@link rowOffsets}. */
  tops: readonly number[];
  /** Total height from {@link rowsTotal}. */
  total: number;
  overscanRows?: number;
};

/** Last row whose top is at or above `y` (binary search over `tops`). */
function lastRowAtOrAbove(tops: readonly number[], y: number): number {
  let low = 0;
  let high = tops.length - 1;
  let found = 0;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (tops[middle] <= y) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return found;
}

/**
 * Rows to render for a viewport. Always in range: `startRow >= 0`,
 * `endRow <= rowCount - 1`, and `endRow < startRow` only when there is nothing
 * to render. An offset past the end of the content (the list shrank under a
 * deep scroll position) yields the last rows rather than an out-of-range
 * window.
 */
export function computeVirtualWindow({
  offset,
  viewportHeight,
  tops,
  total,
  overscanRows = OVERSCAN_ROWS,
}: VirtualWindowInput): VirtualWindow {
  const rowCount = tops.length;
  if (rowCount === 0 || !(total > 0)) {
    return { startRow: 0, endRow: -1 };
  }

  const maxOffset = Math.max(0, total - 1);
  const safeOffset = Number.isFinite(offset)
    ? Math.min(Math.max(0, offset), maxOffset)
    : 0;
  const safeViewportHeight = Number.isFinite(viewportHeight)
    ? Math.max(0, viewportHeight)
    : 0;
  const viewportBottom = safeOffset + Math.max(safeViewportHeight, 1);
  const overscan = Number.isFinite(overscanRows) ? Math.max(0, Math.floor(overscanRows)) : 0;

  const firstVisible = lastRowAtOrAbove(tops, safeOffset);
  const lastVisible = lastRowAtOrAbove(tops, viewportBottom - 1);
  const startRow = Math.max(0, firstVisible - overscan);
  const endRow = Math.min(rowCount - 1, lastVisible + overscan);

  return { startRow, endRow: Math.max(startRow, endRow) };
}
