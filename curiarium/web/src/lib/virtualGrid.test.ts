import { describe, expect, it } from "vitest";

import {
  CARD_MIN_WIDTH_PX,
  ESTIMATED_ROW_HEIGHT,
  GRID_GAP_PX,
  OVERSCAN_ROWS,
  chunkRows,
  colsForWidth,
  computeVirtualWindow,
  rowHeightAt,
  rowOffsets,
  rowsTotal,
} from "./virtualGrid";

/** Tops/total for `rows` unmeasured rows. */
function estimatedRows(rows: number) {
  const heights = new Array<number>(rows).fill(0);
  return { tops: rowOffsets(heights), total: rowsTotal(heights) };
}

const ROW_STRIDE = ESTIMATED_ROW_HEIGHT + GRID_GAP_PX;

describe("colsForWidth", () => {
  it("matches the card min-width plus gap arithmetic", () => {
    expect(CARD_MIN_WIDTH_PX).toBe(260);
    expect(GRID_GAP_PX).toBe(16);

    expect(colsForWidth(1024)).toBe(3);
    expect(colsForWidth(1292)).toBe(4);
    expect(colsForWidth(276)).toBe(1);
  });

  it("steps at the exact column boundaries", () => {
    // N columns fit once width + gap >= N * (min width + gap).
    expect(colsForWidth(535)).toBe(1);
    expect(colsForWidth(536)).toBe(2);
    expect(colsForWidth(811)).toBe(2);
    expect(colsForWidth(812)).toBe(3);
  });

  it("never returns less than one column", () => {
    expect(colsForWidth(0)).toBe(1);
    expect(colsForWidth(-500)).toBe(1);
    expect(colsForWidth(Number.NaN)).toBe(1);
    expect(colsForWidth(Number.POSITIVE_INFINITY)).toBe(1);
  });
});

describe("chunkRows", () => {
  it("splits exact multiples into full rows", () => {
    const rows = chunkRows([1, 2, 3, 4, 5, 6], 3);
    expect(rows).toEqual([
      [1, 2, 3],
      [4, 5, 6],
    ]);
  });

  it("keeps the remainder in a short trailing row", () => {
    const rows = chunkRows([1, 2, 3, 4, 5, 6, 7], 3);
    expect(rows).toEqual([[1, 2, 3], [4, 5, 6], [7]]);
  });

  it("handles empty input and single-column layouts", () => {
    expect(chunkRows([], 3)).toEqual([]);
    expect(chunkRows([1, 2, 3], 1)).toEqual([[1], [2], [3]]);
  });

  it("falls back to one item per row for invalid columns", () => {
    expect(chunkRows([1, 2], 0)).toEqual([[1], [2]]);
    expect(chunkRows([1, 2, 3], -4)).toEqual([[1], [2], [3]]);
    expect(chunkRows([1, 2, 3], 2.7)).toEqual([[1, 2], [3]]);
  });
});

describe("rowOffsets / rowsTotal", () => {
  it("treats unmeasured and invalid heights as the estimate", () => {
    const heights = [360, 400, 0];
    expect(rowOffsets(heights)).toEqual([0, 376, 792]);
    expect(rowsTotal(heights)).toBe(360 + 400 + 360 + 2 * GRID_GAP_PX);
    expect(rowHeightAt(heights, 1)).toBe(400);
    expect(rowHeightAt(heights, 2)).toBe(ESTIMATED_ROW_HEIGHT);
    expect(rowHeightAt([Number.NaN], 0)).toBe(ESTIMATED_ROW_HEIGHT);
    expect(rowHeightAt([-10], 0)).toBe(ESTIMATED_ROW_HEIGHT);
  });

  it("is empty for zero rows", () => {
    expect(rowOffsets([])).toEqual([]);
    expect(rowsTotal([])).toBe(0);
    expect(rowOffsets([], 100, 0)).toEqual([]);
  });

  it("honours custom estimate and gap values", () => {
    expect(rowOffsets([100, 100], 50, 0)).toEqual([0, 100]);
    expect(rowsTotal([100, 100], 50, 0)).toBe(200);
    expect(rowOffsets([0, 0, 0], 50, 10)).toEqual([0, 60, 120]);
    expect(rowsTotal([0, 0, 0], 50, 10)).toBe(3 * 50 + 2 * 10);
  });
});

describe("computeVirtualWindow", () => {
  it("renders the visible rows plus overscan at the top", () => {
    const { tops, total } = estimatedRows(20);
    expect(
      computeVirtualWindow({ offset: 0, viewportHeight: 768, tops, total }),
    ).toEqual({ startRow: 0, endRow: 4 });
  });

  it("renders overscan on both sides in the middle", () => {
    const { tops, total } = estimatedRows(20);
    expect(
      computeVirtualWindow({ offset: 1400, viewportHeight: 768, tops, total }),
    ).toEqual({ startRow: 1, endRow: 7 });
  });

  it("clamps overscan at the bottom end", () => {
    const { tops, total } = estimatedRows(20);
    expect(
      computeVirtualWindow({
        offset: total - 1,
        viewportHeight: 768,
        tops,
        total,
      }),
    ).toEqual({ startRow: 17, endRow: 19 });
  });

  it("renders nothing for zero rows", () => {
    expect(
      computeVirtualWindow({ offset: 0, viewportHeight: 768, tops: [], total: 0 }),
    ).toEqual({ startRow: 0, endRow: -1 });
    expect(
      computeVirtualWindow({ offset: 0, viewportHeight: 768, tops: [0], total: 0 }),
    ).toEqual({ startRow: 0, endRow: -1 });
  });

  it("stays in range when the offset is past the content", () => {
    const { tops, total } = estimatedRows(3);
    const window = computeVirtualWindow({
      offset: 50_000,
      viewportHeight: 768,
      tops,
      total,
    });
    expect(window.startRow).toBeGreaterThanOrEqual(0);
    expect(window.endRow).toBe(tops.length - 1);
    expect(window.startRow).toBeLessThanOrEqual(window.endRow);
  });

  it("stays in range when the list shrank under a deep offset", () => {
    // Five rows remain but the browser still reports a 40k scroll offset; the
    // window must not disappear or go out of bounds.
    const { tops, total } = estimatedRows(5);
    const window = computeVirtualWindow({
      offset: tops[4] + 40_000,
      viewportHeight: 768,
      tops,
      total,
    });
    expect(window).toEqual({
      startRow: Math.max(0, tops.length - 1 - OVERSCAN_ROWS),
      endRow: tops.length - 1,
    });
  });

  it("never exceeds the row count with a large overscan", () => {
    const { tops, total } = estimatedRows(4);
    const window = computeVirtualWindow({
      offset: total - 1,
      viewportHeight: 768,
      tops,
      total,
      overscanRows: 50,
    });
    expect(window.startRow).toBe(0);
    expect(window.endRow).toBe(3);
  });

  it("still produces a valid window for degenerate viewports and offsets", () => {
    const { tops, total } = estimatedRows(6);
    const cases = [
      { offset: 0, viewportHeight: 0 },
      { offset: -100, viewportHeight: 768 },
      { offset: Number.NaN, viewportHeight: 768 },
      { offset: 0, viewportHeight: Number.NaN },
      { offset: 0, viewportHeight: 768, overscanRows: -3 },
    ];
    for (const partial of cases) {
      const window = computeVirtualWindow({ tops, total, ...partial });
      expect(window.startRow).toBeGreaterThanOrEqual(0);
      expect(window.endRow).toBeLessThanOrEqual(tops.length - 1);
      expect(window.startRow).toBeLessThanOrEqual(window.endRow);
    }
  });

  it("covers the whole viewport for a one-row list", () => {
    const { tops, total } = estimatedRows(1);
    expect(
      computeVirtualWindow({ offset: 0, viewportHeight: 768, tops, total }),
    ).toEqual({ startRow: 0, endRow: 0 });
  });

  it("uses the real row stride for row boundaries", () => {
    // An offset that lands exactly on a row boundary belongs to that row, not
    // to the row before it.
    const heights = new Array<number>(4).fill(ESTIMATED_ROW_HEIGHT);
    const tops = rowOffsets(heights);
    const total = rowsTotal(heights);
    expect(tops[1]).toBe(ROW_STRIDE);
    expect(
      computeVirtualWindow({
        offset: ROW_STRIDE,
        viewportHeight: 10,
        tops,
        total,
        overscanRows: 0,
      }),
    ).toEqual({ startRow: 1, endRow: 1 });
  });
});
