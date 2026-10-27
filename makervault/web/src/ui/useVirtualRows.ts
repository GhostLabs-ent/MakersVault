import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  ESTIMATED_ROW_HEIGHT,
  GRID_GAP_PX,
  OVERSCAN_ROWS,
  colsForWidth,
  computeVirtualWindow,
  rowOffsets,
  rowsTotal,
  type VirtualWindow,
} from "../lib/virtualGrid";

/**
 * Virtualization for the flat asset grid.
 *
 * Only the rows covering the viewport (plus {@link OVERSCAN_ROWS} on each side)
 * are rendered. Row heights are measured with a `ResizeObserver` when the
 * runtime has one (jsdom and other CSS-less environments do not), and fall back
 * to `ESTIMATED_ROW_HEIGHT` until a real measurement exists.
 *
 * The scroll container is either an explicit `scrollElementRef` (the app's
 * `<main>`), or the window when the ref is absent/null. The offset is derived
 * from element rects only — never from `scrollTop + rect delta` — because that
 * combination cannot be reproduced faithfully in jsdom.
 *
 * The window fallback is for callers/embedders that do not own a scroll
 * container (the app always passes the `<main>` ref); it has no scroll
 * compensation or resize re-anchoring.
 */

export type VirtualRowsOptions = {
  /** Scroll container. When absent (or null) the window is used. */
  scrollElementRef?: React.RefObject<HTMLElement | null>;
  /** Flat, already-sorted items; only `id` is used, for height-cache retention. */
  items: readonly { id: string }[];
  /** Cards per row before the container has been measured. */
  cols: number;
};

export type VirtualRowsResult = {
  /** Effective cards per row (from the measured container width when known). */
  cols: number;
  rowCount: number;
  startRow: number;
  endRow: number;
  /** Height of the spacer above the rendered rows (excluding the flex gap). */
  topSpacer: number;
  /** Height of the spacer below the rendered rows (excluding the flex gap). */
  bottomSpacer: number;
  /**
   * Callback ref for the flat grid wrapper. Attach it with `ref={...}`: the
   * wrapper is only mounted for the flat sorts, so its width observation has to
   * follow the element rather than run once on mount.
   */
  setGridWrapRef: (element: HTMLDivElement | null) => void;
  setRowRef: (rowIndex: number) => (element: HTMLElement | null) => void;
};

type RowRange = VirtualWindow;

const EMPTY_RANGE: RowRange = { startRow: 0, endRow: -1 };
const FALLBACK_VIEWPORT_HEIGHT = 768;
/** Sub-pixel measurements below this are layout noise, not a real change. */
const HEIGHT_EPSILON = 0.5;
/** Sparse, immutable row-height cache: `undefined`/`0` means unmeasured. */
const EMPTY_HEIGHTS: number[] = [];

function windowHeight(): number {
  if (typeof window === "undefined") return FALLBACK_VIEWPORT_HEIGHT;
  return window.innerHeight || FALLBACK_VIEWPORT_HEIGHT;
}

function viewportHeightFor(scrollElement: HTMLElement | null): number {
  if (scrollElement) {
    return scrollElement.clientHeight || windowHeight();
  }
  return windowHeight();
}

/**
 * Row index of the currently focused element, if it lives inside a rendered
 * row. Used to pin the row under the focus so keyboard navigation inside a
 * card never has the card unmounted mid-interaction.
 */
function focusedRowIndex(): number | null {
  if (typeof document === "undefined") return null;
  const active = document.activeElement;
  if (!active || active === document.body) return null;
  const row = typeof active.closest === "function"
    ? active.closest("[data-row-index]")
    : null;
  if (!row) return null;
  const index = Number(row.getAttribute("data-row-index"));
  return Number.isInteger(index) ? index : null;
}

/** Widen/trim the sparse cache to exactly one entry per rendered row. */
function heightsForRowCount(cache: readonly number[], rowCount: number): number[] {
  if (cache.length === rowCount) return cache as number[];
  const list = new Array<number>(rowCount);
  for (let index = 0; index < rowCount; index += 1) {
    list[index] = cache[index] ?? 0;
  }
  return list;
}

export function useVirtualRows({
  scrollElementRef,
  items,
  cols: seedCols,
}: VirtualRowsOptions): VirtualRowsResult {
  const gridWrapRef = useRef<HTMLDivElement | null>(null);
  const widthObserverRef = useRef<ResizeObserver | null>(null);
  /** Last reported container width; guards against sub-pixel observer churn. */
  const measuredWidthRef = useRef(0);
  const [measuredWidth, setMeasuredWidth] = useState(0);
  const cols = measuredWidth > 0 ? colsForWidth(measuredWidth) : seedCols;
  const itemCount = items.length;
  const rowCount = cols > 0 ? Math.ceil(itemCount / cols) : 0;

  // Sparse row-height cache. Measurements are written from callback refs and
  // `ResizeObserver` callbacks, so the cached array is mirrored in a ref for
  // those imperative paths while state drives the re-render.
  const [cachedHeights, setCachedHeights] = useState<number[]>(EMPTY_HEIGHTS);
  const heightsRef = useRef<number[]>(cachedHeights);

  const heights = useMemo(
    () => heightsForRowCount(cachedHeights, rowCount),
    [cachedHeights, rowCount],
  );

  const tops = useMemo(() => rowOffsets(heights), [heights]);
  const total = useMemo(() => rowsTotal(heights), [heights]);

  // Latest geometry for the imperative (scroll/measurement) paths.
  const geometryRef = useRef({ tops, total, rowCount });
  geometryRef.current = { tops, total, rowCount };

  const [range, setRange] = useState<RowRange>(EMPTY_RANGE);
  const rangeRef = useRef<RowRange>(EMPTY_RANGE);
  /** First *visible* row (no overscan), used to decide scroll compensation. */
  const visibleStartRef = useRef(0);

  const applyRange = useCallback((next: RowRange) => {
    const previous = rangeRef.current;
    if (previous.startRow === next.startRow && previous.endRow === next.endRow) {
      return;
    }
    rangeRef.current = next;
    setRange(next);
  }, []);

  const computeNow = useCallback(() => {
    const gridWrap = gridWrapRef.current;
    const scrollElement = scrollElementRef?.current ?? null;
    const { tops: currentTops, total: currentTotal, rowCount: rows } = geometryRef.current;
    if (!gridWrap || rows === 0) {
      applyRange(EMPTY_RANGE);
      return;
    }

    const gridRect = gridWrap.getBoundingClientRect();
    const scrollerRect = scrollElement ? scrollElement.getBoundingClientRect() : null;
    // Element mode: how far the grid's top has scrolled above the container's
    // top. Window mode: how far it has scrolled above the viewport's top.
    const rawOffset = scrollerRect ? scrollerRect.top - gridRect.top : -gridRect.top;
    const offset = Number.isFinite(rawOffset) ? Math.max(0, rawOffset) : 0;
    const viewportHeight = viewportHeightFor(scrollElement);

    const visible = computeVirtualWindow({
      offset,
      viewportHeight,
      tops: currentTops,
      total: currentTotal,
      overscanRows: 0,
    });
    if (visible.endRow >= 0) {
      visibleStartRef.current = visible.startRow;
    }
    const next = computeVirtualWindow({
      offset,
      viewportHeight,
      tops: currentTops,
      total: currentTotal,
      overscanRows: OVERSCAN_ROWS,
    });
    const focusedRow = focusedRowIndex();
    if (focusedRow !== null && focusedRow >= 0 && focusedRow < rows) {
      // Keyboard/focus pinning: a row holding the focus must not be unmounted
      // mid-interaction. The pin is capped at roughly one window so that a long
      // scrollbar drag while a card control still holds focus cannot inflate the
      // DOM back to the full library.
      const visibleRows = visible.endRow >= visible.startRow
        ? visible.endRow - visible.startRow + 1
        : 1;
      const pinBudget = visibleRows + OVERSCAN_ROWS * 2;
      const distance = focusedRow < next.startRow
        ? next.startRow - focusedRow
        : Math.max(0, focusedRow - next.endRow);
      if (distance <= pinBudget) {
        next.startRow = Math.min(next.startRow, focusedRow);
        next.endRow = Math.max(next.endRow, focusedRow);
      }
    }
    applyRange(next);
  }, [applyRange, scrollElementRef]);

  const computeRef = useRef(computeNow);
  computeRef.current = computeNow;

  // ---- scroll / resize, rAF-throttled -------------------------------------

  const frameRef = useRef<{ kind: "raf" | "timeout"; id: number } | null>(null);

  const schedule = useCallback(() => {
    if (frameRef.current) return;
    if (typeof requestAnimationFrame === "function") {
      const id = requestAnimationFrame(() => {
        frameRef.current = null;
        computeRef.current();
      });
      frameRef.current = { kind: "raf", id };
    } else if (typeof window !== "undefined") {
      const id = window.setTimeout(() => {
        frameRef.current = null;
        computeRef.current();
      }, 0);
      frameRef.current = { kind: "timeout", id };
    }
  }, []);

  const cancelScheduled = useCallback(() => {
    const frame = frameRef.current;
    frameRef.current = null;
    if (!frame) return;
    if (frame.kind === "raf" && typeof cancelAnimationFrame === "function") {
      cancelAnimationFrame(frame.id);
    } else if (frame.kind === "timeout") {
      window.clearTimeout(frame.id);
    }
  }, []);

  useEffect(() => cancelScheduled, [cancelScheduled]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const scrollElement = scrollElementRef?.current ?? null;
    const scrollTarget: HTMLElement | Window = scrollElement ?? window;
    const onScroll = () => schedule();
    scrollTarget.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    // Re-run once here: the parent's ref may have been attached after this
    // hook's layout effects, which would have left `computeNow` on the window
    // fallback for the very first paint.
    computeRef.current();
    return () => {
      scrollTarget.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelScheduled();
    };
  }, [cancelScheduled, schedule, scrollElementRef]);

  // ---- row height measurement --------------------------------------------

  /** Height change of a row above the viewport top must not move the content. */
  const setRowHeight = useCallback(
    (rowIndex: number, height: number) => {
      if (!(height > 0) || !Number.isFinite(height)) return;
      const measured = Math.round(height * 100) / 100;
      const previous = heightsRef.current[rowIndex] ?? ESTIMATED_ROW_HEIGHT;
      if (Math.abs(previous - measured) < HEIGHT_EPSILON) return;
      const scrollElement = scrollElementRef?.current ?? null;
      if (scrollElement && rowIndex < visibleStartRef.current) {
        // Assignment only: `Element.scrollTo` does not exist in jsdom.
        scrollElement.scrollTop = Math.max(
          0,
          scrollElement.scrollTop + (measured - previous),
        );
      }
      const next = heightsRef.current.slice();
      next[rowIndex] = measured;
      heightsRef.current = next;
      setCachedHeights(next);
    },
    [scrollElementRef],
  );

  const setRowHeightRef = useRef(setRowHeight);
  setRowHeightRef.current = setRowHeight;

  const rowElementsRef = useRef(new Map<number, HTMLElement>());
  const rowIndexByElementRef = useRef(new WeakMap<Element, number>());
  const rowRefCacheRef = useRef(new Map<number, (element: HTMLElement | null) => void>());
  const rowObserverRef = useRef<ResizeObserver | null>(null);

  const setRowRef = useCallback((rowIndex: number) => {
    const cached = rowRefCacheRef.current.get(rowIndex);
    if (cached) return cached;
    const rowRef = (element: HTMLElement | null) => {
      const elements = rowElementsRef.current;
      const previous = elements.get(rowIndex);
      if (previous) {
        elements.delete(rowIndex);
        if (previous !== element) rowObserverRef.current?.unobserve(previous);
      }
      if (!element) return;
      elements.set(rowIndex, element);
      rowIndexByElementRef.current.set(element, rowIndex);
      rowObserverRef.current?.observe(element);
      // Measure on attach as well: the row is already laid out here, and jsdom
      // (no ResizeObserver) simply reports 0, which is ignored.
      setRowHeightRef.current(rowIndex, element.getBoundingClientRect().height);
    };
    rowRefCacheRef.current.set(rowIndex, rowRef);
    return rowRef;
  }, []);

  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(entries => {
      for (const entry of entries) {
        const rowIndex = rowIndexByElementRef.current.get(entry.target);
        if (rowIndex === undefined) continue;
        const element = entry.target as HTMLElement;
        const height = entry.contentRect?.height || element.getBoundingClientRect().height;
        setRowHeightRef.current(rowIndex, height);
      }
    });
    rowObserverRef.current = observer;
    for (const element of rowElementsRef.current.values()) {
      observer.observe(element);
    }
    return () => {
      observer.disconnect();
      rowObserverRef.current = null;
    };
  }, []);

  // ---- column count from the container width ------------------------------

  /**
   * Width observation tied to the wrapper's lifecycle: the flat branch of the
   * grid is replaced when the user switches to a grouped sort, so a one-shot
   * effect would leave `cols` frozen on the element observed at mount. Measuring
   * is skipped when the runtime has no `ResizeObserver` (jsdom).
   */
  const setGridWrapRef = useCallback((element: HTMLDivElement | null) => {
    gridWrapRef.current = element;
    widthObserverRef.current?.disconnect();
    widthObserverRef.current = null;
    if (element && typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(entries => {
        const width = entries[0]?.contentRect?.width ?? 0;
        if (!(width > 0) || Math.abs(width - measuredWidthRef.current) < 1) return;
        measuredWidthRef.current = width;
        setMeasuredWidth(width);
      });
      observer.observe(element);
      widthObserverRef.current = observer;
    }
    // The wrapper this ref just attached to is the one the offset math has to
    // use, so the window is recomputed for whatever element is current now.
    computeRef.current();
  }, []);

  useEffect(() => () => {
    widthObserverRef.current?.disconnect();
    widthObserverRef.current = null;
  }, []);

  // ---- recompute the window when the geometry changes --------------------

  useLayoutEffect(() => {
    computeNow();
  }, [computeNow, rowCount, cols, itemCount, heights]);

  // ---- height-cache retention and re-anchoring ---------------------------

  const identityRef = useRef<{ firstId: string | null; length: number }>({
    firstId: null,
    length: 0,
  });
  const colsRef = useRef(cols);

  useEffect(() => {
    const previousCols = colsRef.current;
    const colsChanged = previousCols !== cols;
    colsRef.current = cols;

    const firstId = itemCount > 0 ? items[0].id : null;
    const identity = identityRef.current;
    // Same first item and no shrink in length — an append (Load more, upload)
    // or an in-place edit/refresh that keeps the list shape (`replaceAsset`,
    // `keepLoadedPages`) — keeps the measured heights. A genuinely different
    // result set (sort, filter, folder switch) changes `firstId` and therefore
    // still invalidates them. Residual error self-corrects through the row
    // observers.
    const retained =
      !colsChanged &&
      firstId !== null &&
      firstId === identity.firstId &&
      itemCount >= identity.length;
    identityRef.current = { firstId, length: itemCount };
    if (!retained) {
      // Any other change invalidates every measurement.
      if (heightsRef.current.length > 0) {
        heightsRef.current = EMPTY_HEIGHTS;
        setCachedHeights(EMPTY_HEIGHTS);
      }
    }
    if (!colsChanged) return;

    // Re-chunking moves every row boundary: keep the first visible item under
    // the viewport top (estimate-based is exact enough; the observers fix it).
    const anchorItem = visibleStartRef.current * previousCols;
    const scrollElement = scrollElementRef?.current ?? null;
    if (!scrollElement || anchorItem <= 0 || cols <= 0) return;
    const nextRowCount = Math.ceil(itemCount / cols);
    if (nextRowCount <= 0) return;
    const anchorRow = Math.min(nextRowCount - 1, Math.floor(anchorItem / cols));
    const anchorTops = rowOffsets(new Array<number>(nextRowCount).fill(0));
    scrollElement.scrollTop = anchorTops[anchorRow] ?? 0;
  }, [cols, itemCount, items, scrollElementRef]);

  // ---- spacers ------------------------------------------------------------

  const hasRange = range.endRow >= range.startRow && rowCount > 0;
  let topSpacer = 0;
  let bottomSpacer = 0;
  if (hasRange) {
    // The wrapper is a flex column with `gap: GRID_GAP_PX`, so flex already
    // inserts one gap before and after the rendered rows: each spacer only
    // covers the remaining distance, which keeps the scroll height exact.
    if (range.startRow > 0) {
      topSpacer = Math.max(0, (tops[range.startRow] ?? 0) - GRID_GAP_PX);
    }
    if (range.endRow < rowCount - 1) {
      const rowBottom = (tops[range.endRow] ?? 0) + heights[range.endRow] + GRID_GAP_PX;
      bottomSpacer = Math.max(0, total - rowBottom);
    }
  }

  return {
    cols,
    rowCount,
    startRow: hasRange ? range.startRow : 0,
    endRow: hasRange ? range.endRow : -1,
    topSpacer,
    bottomSpacer,
    setGridWrapRef,
    setRowRef,
  };
}
