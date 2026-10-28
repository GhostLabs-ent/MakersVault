// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createRef, type ReactElement } from "react";

import type { Asset, Folder } from "../lib/api";
import {
  ESTIMATED_ROW_HEIGHT,
  GRID_GAP_PX,
  OVERSCAN_ROWS,
  colsForWidth,
  rowOffsets,
  rowsTotal,
} from "../lib/virtualGrid";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  addProjectAssets: vi.fn(),
  batchDeleteAssets: vi.fn(),
  batchMoveAssets: vi.fn(),
  batchSetTags: vi.fn(),
  createProject: vi.fn(),
  createFolder: vi.fn(),
  deleteAsset: vi.fn(),
  deleteAssetFile: vi.fn(),
  deletePreparedPrint: vi.fn(),
  downloadZip: vi.fn(),
  fileUrl: vi.fn((rel: string) => rel),
  getLibraryScanStatus: vi.fn(),
  listAssetFiles: vi.fn(async () => []),
  listAssets: vi.fn(),
  listFolders: vi.fn(async () => []),
  listProjects: vi.fn(async () => []),
  listTags: vi.fn(async () => []),
  setTags: vi.fn(),
  startLibraryScan: vi.fn(),
  updateAssetFolder: vi.fn(),
  updateAssetMeta: vi.fn(),
  uploadAsset: vi.fn(),
  uploadAssetFile: vi.fn(),
}));

vi.mock("./ModelViewer", () => ({
  default: () => null,
  ModelSnapshot: () => null,
}));

vi.mock("./LightBurnPreview", () => ({
  default: () => null,
}));

import AssetGrid from "./asset-grid/AssetGrid";
import Toaster from "./Toaster";
import { resetToasts } from "../lib/toast";
import {
  batchDeleteAssets,
  batchMoveAssets,
  batchSetTags,
  createFolder,
  deleteAsset,
  deleteAssetFile,
  deletePreparedPrint,
  fileUrl,
  getLibraryScanStatus,
  listAssetFiles,
  listAssets,
  listFolders,
  listTags,
  setTags,
  startLibraryScan,
  updateAssetMeta,
  uploadAsset,
} from "../lib/api";

const listAssetsMock = vi.mocked(listAssets);
const listTagsMock = vi.mocked(listTags);
const listFoldersMock = vi.mocked(listFolders);
const batchDeleteAssetsMock = vi.mocked(batchDeleteAssets);
const batchMoveAssetsMock = vi.mocked(batchMoveAssets);
const batchSetTagsMock = vi.mocked(batchSetTags);
const setTagsMock = vi.mocked(setTags);
const fileUrlMock = vi.mocked(fileUrl);
const deleteAssetMock = vi.mocked(deleteAsset);
const startLibraryScanMock = vi.mocked(startLibraryScan);
const getLibraryScanStatusMock = vi.mocked(getLibraryScanStatus);
const updateAssetMetaMock = vi.mocked(updateAssetMeta);
const uploadAssetMock = vi.mocked(uploadAsset);
const createFolderMock = vi.mocked(createFolder);
const deleteAssetFileMock = vi.mocked(deleteAssetFile);
const deletePreparedPrintMock = vi.mocked(deletePreparedPrint);
const listAssetFilesMock = vi.mocked(listAssetFiles);

/** Chip requests are asserted in the mode-aware filter tests; default them to none. */
beforeEach(() => {
  listTagsMock.mockReset();
  listTagsMock.mockResolvedValue([]);
});

/** The toast stack, scoped so `BulkActionBar`'s own `role="alert"` is never hit. */
function toaster() {
  return within(screen.getByTestId("toaster"));
}

function renderWithToaster(ui: ReactElement) {
  return render(
    <>
      {ui}
      <Toaster />
    </>
  );
}

/** Status payload of an idle library scan, as the API reports it. */
function idleScanStatus(): Awaited<ReturnType<typeof getLibraryScanStatus>> {
  return {
    running: false,
    started_at: null,
    finished_at: null,
    registered: 0,
    known: 0,
    ignored: 0,
    missing: 1,
    failed: 0,
    errors: [],
  };
}

/** Query arguments of the `index`th `listAssets` call, with paging made explicit. */
function callQuery(index: number) {
  const params = listAssetsMock.mock.calls[index]?.[0];
  if (!params || params.limit === undefined || params.offset === undefined) {
    throw new Error(`listAssets call ${index} was missing an explicit paging window`);
  }
  const { limit, offset } = params;
  return { ...params, limit, offset };
}

/** The per-card selectors only: the toolbar filter is a checkbox too. */
function cardCheckboxes(): HTMLInputElement[] {
  return screen.getAllByRole("checkbox", { name: "Select" }) as HTMLInputElement[];
}

const assets: Asset[] = [
  {
    id: "a1",
    name: "Calibration cube",
    filename: "calibration-cube.stl",
    mime: "model/stl",
    size: 1200,
    tags: ["pla"],
    url: "/api/assets/a1/file",
    thumb_url: "/api/assets/a1/thumb",
    supporting_file_count: 0,
  },
  {
    id: "b2",
    name: "Spool holder",
    filename: "spool-holder.stl",
    mime: "model/stl",
    size: 3400,
    tags: [],
    url: "/api/assets/b2/file",
    thumb_url: "/api/assets/b2/thumb",
    supporting_file_count: 1,
  },
  {
    id: "c3",
    name: "Engraved sign",
    filename: "engraved-sign.png",
    mime: "image/png",
    size: 900,
    tags: ["sign"],
    url: "/api/assets/c3/file",
    thumb_url: "/api/assets/c3/thumb",
    supporting_file_count: 0,
  },
];

/** Asset whose backing file is gone from storage but whose entry still exists. */
const missingAsset: Asset = {
  id: "m4",
  name: "Lost model",
  filename: "lost-model.stl",
  mime: "model/stl",
  size: 2200,
  tags: [],
  url: "/api/assets/m4/file",
  thumb_url: "/api/assets/m4/thumb",
  supporting_file_count: 0,
  missing_since: "2026-10-27T11:31:34+00:00",
};

/** Fixture asset for paged batches: no 3D extensions and a thumb, so no WebGL path. */
function makeAsset(batch: number, index: number): Asset {
  const id = `page${batch}-item${index}`;
  return {
    id,
    name: `Page ${batch} item ${index}`,
    filename: `${id}.png`,
    mime: "image/png",
    size: 1000 + index,
    tags: [],
    url: `/api/assets/${id}/file`,
    thumb_url: `/api/assets/${id}/thumb`,
    supporting_file_count: 0,
  };
}

function makeBatch(batch: number, size: number): Asset[] {
  return Array.from({ length: size }, (_, i) => makeAsset(batch, i + 1));
}

function sortSelect(): HTMLSelectElement {
  const found = screen
    .getAllByRole("combobox")
    .find(el =>
      Array.from((el as HTMLSelectElement).options).some(o => o.value === "folder"),
    );
  if (!found) throw new Error("sort control not rendered");
  return found as HTMLSelectElement;
}

/**
 * jsdom has no layout, so a `DOMRect`-shaped value has to be supplied by hand.
 * Only `top` (offset math) and `height` (scroll extent) are meaningful.
 */
function rectOf(top: number, height: number): DOMRect {
  return {
    top,
    bottom: top + height,
    height,
    left: 0,
    right: 0,
    width: 0,
    x: 0,
    y: top,
    toJSON: () => ({}),
  } as DOMRect;
}

type HarnessProps = {
  folderId?: string | null;
  foldersVersion?: number;
  assetsVersion?: number;
  onNavigateFolder?: (id: string | null) => void;
};

/**
 * Renders the grid inside a real scroll container and gives jsdom the two
 * numbers a browser would provide: a 768px-tall scroller (`clientHeight`) and
 * an emulated scroll position. `stubGridRect` supplies the grid wrapper's rect
 * so `offset` is derived purely from `scrollTop`.
 */
function renderHarness(initialProps: HarnessProps = {}) {
  const scrollerRef = createRef<HTMLDivElement>();
  const tree = (props: HarnessProps) => (
    <div ref={scrollerRef} data-testid="asset-scroller">
      <AssetGrid theme="dark" scrollElementRef={scrollerRef} {...props} />
    </div>
  );
  const utils = render(tree(initialProps));
  const scroller = scrollerRef.current;
  if (!scroller) throw new Error("scroll harness did not mount");
  Object.defineProperty(scroller, "clientHeight", { value: 768, configurable: true });
  vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(rectOf(0, 768));
  return {
    ...utils,
    scroller,
    rerenderGrid: (props: HarnessProps) => utils.rerender(tree(props)),
  };
}

/**
 * Makes the grid wrapper's rect track the scroller's `scrollTop`, which is
 * exactly what the browser reports for a real scroll (and what jsdom cannot
 * do by itself). Call after the first paint.
 */
function stubGridRect(scroller: HTMLDivElement): HTMLElement {
  const gridWrap = document.querySelector<HTMLElement>("[data-virtual-grid]");
  if (!gridWrap) throw new Error("virtual grid wrapper not rendered");
  vi.spyOn(gridWrap, "getBoundingClientRect").mockImplementation(() =>
    rectOf(-scroller.scrollTop, 0),
  );
  return gridWrap;
}

function scrollGrid(scroller: HTMLElement, top: number) {
  scroller.scrollTop = top;
  fireEvent.scroll(scroller);
}

function mountedRowIndexes(): number[] {
  return Array.from(document.querySelectorAll("[data-row-index]")).map(el =>
    Number(el.getAttribute("data-row-index")),
  );
}

function checkboxCount(): number {
  // Card selectors only: the toolbar's "Not in any project" filter is a checkbox too.
  return screen.queryAllByRole("checkbox", { name: "Select" }).length;
}

/** Observers still observing `target` (a `disconnect` empties the target list). */
function liveObserversFor(target: Element): FakeResizeObserver[] {
  return FakeResizeObserver.instances.filter(entry => entry.targets.includes(target));
}

/** Cards rendered inside the row wrapper at `rowIndex` (0 when unmounted). */
function rowCardCount(rowIndex: number): number {
  const row = document.querySelector(`[data-row-index="${rowIndex}"]`);
  if (!row) return 0;
  return row.querySelectorAll('input[type="checkbox"]').length;
}

/** Vendor-free, WebGL-free fixture: a png with a thumbnail. */
function makeSyntheticAsset(index: number, overrides: Partial<Asset> = {}): Asset {
  const id = `asset-${index}`;
  return {
    id,
    name: `Asset ${index}`,
    filename: `asset-${String(index).padStart(5, "0")}.png`,
    mime: "image/png",
    size: 10_000_000 - index,
    tags: [],
    url: `/api/assets/${id}/file`,
    thumb_url: `/api/assets/${id}/thumb`,
    supporting_file_count: 0,
    ...overrides,
  };
}

function makeSyntheticBatch(count: number, namePrefix = "Asset"): Asset[] {
  return Array.from({ length: count }, (_, i) => {
    const asset = makeSyntheticAsset(i + 1);
    const label = `${namePrefix} ${i + 1}`;
    return { ...asset, name: label };
  });
}

/**
 * Minimal stand-in for `ResizeObserver` (absent in jsdom). Tests drive it by
 * hand, mirroring the `FakeIntersectionObserver` in LightBurnPreview.test.tsx.
 */
class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  targets: Element[] = [];
  constructor(private readonly callback: ResizeObserverCallback) {
    FakeResizeObserver.instances.push(this);
  }
  observe(target: Element) {
    this.targets.push(target);
  }
  unobserve(target: Element) {
    this.targets = this.targets.filter(entry => entry !== target);
  }
  disconnect() {
    this.targets = [];
  }
  takeRecords(): ResizeObserverEntry[] {
    return [];
  }
  static trigger(target: Element, sizes: { height?: number; width?: number }) {
    const observer = FakeResizeObserver.instances.find(entry => entry.targets.includes(target));
    if (!observer) throw new Error("target is not observed");
    observer.callback(
      [
        {
          target,
          contentRect: { height: sizes.height ?? 0, width: sizes.width ?? 0 },
        } as ResizeObserverEntry,
      ],
      observer as unknown as ResizeObserver,
    );
  }
}

describe("AssetGrid asset refresh", () => {
  beforeEach(() => {
    resetToasts();
    listAssetsMock.mockReset();
    listAssetsMock.mockResolvedValue({ items: assets, hasMore: false });
    fileUrlMock.mockClear();
  });

  afterEach(cleanup);

  it("keeps search, sort and selection and refetches exactly once when assets change", async () => {
    const { rerender } = render(<AssetGrid theme="dark" />);

    await waitFor(() => expect(listAssets).toHaveBeenCalledTimes(1));
    await screen.findByText("Calibration cube");
    expect(screen.getByText("Spool holder")).toBeTruthy();

    const firstCall = callQuery(0);
    expect(firstCall.offset).toBe(0);

    const searchInput = screen.getByPlaceholderText(
      "Search title, filename, notes...",
    ) as HTMLInputElement;
    fireEvent.change(searchInput, { target: { value: "cube" } });

    const selection = cardCheckboxes()[0];
    fireEvent.click(selection);
    expect(selection.checked).toBe(true);

    const sort = sortSelect();
    fireEvent.change(sort, { target: { value: "size" } });
    expect(sort.value).toBe("size");

    const callsBefore = listAssetsMock.mock.calls.length;

    rerender(<AssetGrid theme="dark" assetsVersion={1} />);

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1));
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
    expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1);

    const refreshCall = callQuery(callsBefore);
    expect(refreshCall.q).toBe("cube");
    expect(refreshCall.offset).toBe(0);
    expect(refreshCall.limit).toBe(Math.max(firstCall.limit, assets.length));

    const searchAfter = screen.getByPlaceholderText(
      "Search title, filename, notes...",
    ) as HTMLInputElement;
    expect(searchAfter).toBe(searchInput);
    expect(searchAfter.value).toBe("cube");

    const selectionAfter = cardCheckboxes().find(el => el === selection);
    expect(selectionAfter).toBe(selection);
    expect(selection.isConnected).toBe(true);
    expect(selection.checked).toBe(true);

    expect(sortSelect()).toBe(sort);
    expect(sortSelect().value).toBe("size");
  });

  it("refetches both loaded pages in one call when assets change after loading more", async () => {
    let pageSize = 0;
    let callCount = 0;
    let firstBatch: Asset[] = [];
    let secondBatch: Asset[] = [];

    listAssetsMock.mockImplementation(async params => {
      callCount += 1;
      const limit = params?.limit ?? 0;
      const offset = params?.offset ?? 0;
      if (callCount === 1) {
        // Page size is derived from the viewport, so take it from the request.
        pageSize = limit;
        firstBatch = makeBatch(1, pageSize);
        return { items: firstBatch, hasMore: true };
      }
      if (callCount === 2) {
        secondBatch = makeBatch(2, pageSize);
        return { items: secondBatch, hasMore: false };
      }
      const loaded = [...firstBatch, ...secondBatch];
      return { items: loaded.slice(offset, offset + limit), hasMore: false };
    });

    const { scroller, rerenderGrid } = renderHarness();

    await waitFor(() => expect(listAssets).toHaveBeenCalledTimes(1));
    await screen.findByText("Page 1 item 1");
    expect(pageSize).toBeGreaterThan(1);
    const firstCall = callQuery(0);
    expect(firstCall.offset).toBe(0);
    expect(firstCall.limit).toBe(pageSize);

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(2));
    const loadMoreCall = callQuery(1);
    expect(loadMoreCall.offset).toBe(pageSize);
    expect(loadMoreCall.limit).toBe(pageSize);

    const callsBefore = listAssetsMock.mock.calls.length;

    rerenderGrid({ assetsVersion: 1 });

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1));
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
    expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1);

    const refreshCall = callQuery(callsBefore);
    expect(refreshCall.offset).toBe(0);
    expect(refreshCall.limit).toBe(pageSize * 2);

    // The grid is virtualized, so "both pages survived" is proven by their
    // contents: page 1 is mounted at the top, and page 2 is reachable by
    // scrolling to the end of the (now two-page tall) content.
    expect(screen.getByText("Page 1 item 1")).toBeTruthy();
    expect(screen.queryByText(`Page 2 item ${pageSize}`)).toBeNull();
    expect(checkboxCount()).toBeLessThan(pageSize * 2);

    const cols = colsForWidth(window.innerWidth);
    const rows = Math.ceil((pageSize * 2) / cols);
    const contentHeight = rows * ESTIMATED_ROW_HEIGHT + (rows - 1) * GRID_GAP_PX;

    stubGridRect(scroller);
    scrollGrid(scroller, contentHeight);

    await screen.findByText(`Page 2 item ${pageSize}`);
    expect(screen.queryByText("Page 1 item 1")).toBeNull();
  });

  // `renderPreviewContent` runs on every card render and unconditionally calls
  // `fileUrl(asset.url)`, so a per-URL call count is a faithful render counter.
  describe("card render probe", () => {
    /** Flat grid order: cards are sorted by filename ascending. */
    const flatOrder = [...assets].sort((a, b) => a.filename.localeCompare(b.filename));

    function renderCounts(): Record<string, number> {
      const counts: Record<string, number> = {};
      for (const asset of assets) {
        counts[asset.id] = fileUrlMock.mock.calls.filter(([url]) => url === asset.url).length;
      }
      return counts;
    }

    async function renderFirstBatch(): Promise<HTMLInputElement> {
      render(<AssetGrid theme="dark" />);
      await waitFor(() => expect(listAssets).toHaveBeenCalledTimes(1));
      await screen.findByText("Calibration cube");
      await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
      return screen.getByPlaceholderText(
        "Search title, filename, notes...",
      ) as HTMLInputElement;
    }

    it("does not re-render existing cards while typing in the search box", async () => {
      const searchInput = await renderFirstBatch();
      const before = renderCounts();
      expect(before[flatOrder[0].id]).toBeGreaterThan(0);

      fireEvent.change(searchInput, { target: { value: "c" } });
      fireEvent.change(searchInput, { target: { value: "cu" } });

      expect(searchInput.value).toBe("cu");
      expect(renderCounts()).toEqual(before);
      // Typing alone never refetches, same as before.
      expect(listAssets).toHaveBeenCalledTimes(1);
    });

    it("re-renders only the card whose selection changed", async () => {
      await renderFirstBatch();
      const checkboxes = cardCheckboxes();
      expect(checkboxes.length).toBe(flatOrder.length);

      // The first click flips `hasSelection` false -> true, which may legally
      // re-render every card; take the baseline after it settles.
      fireEvent.click(checkboxes[0]);
      expect(checkboxes[0].checked).toBe(true);
      const baseline = renderCounts();

      fireEvent.click(checkboxes[1]);
      expect(checkboxes[1].checked).toBe(true);

      const after = renderCounts();
      expect(after[flatOrder[1].id]).toBe(baseline[flatOrder[1].id] + 1);
      expect(after[flatOrder[0].id]).toBe(baseline[flatOrder[0].id]);
      expect(after[flatOrder[2].id]).toBe(baseline[flatOrder[2].id]);
    });

    it("search still refetches with the typed query", async () => {
      const searchInput = await renderFirstBatch();

      fireEvent.change(searchInput, { target: { value: "cube" } });
      fireEvent.keyDown(searchInput, { key: "Enter" });

      await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(2));
      const enterCall = callQuery(1);
      expect(enterCall.q).toBe("cube");
      expect(enterCall.offset).toBe(0);

      fireEvent.change(searchInput, { target: { value: "spool" } });
      fireEvent.click(screen.getByRole("button", { name: "Search" }));

      await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(3));
      const buttonCall = callQuery(2);
      expect(buttonCall.q).toBe("spool");
      expect(buttonCall.offset).toBe(0);
    });
  });

  // `img.loading` / `img.decoding` are undefined in jsdom 26, so only the
  // serialized attributes can be asserted here.
  describe("thumbnail loading hints", () => {
    it("marks card thumbnails lazy and async", async () => {
      render(<AssetGrid theme="dark" />);
      await screen.findByText("Calibration cube");
      await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());

      for (const asset of assets) {
        const img = screen.getByAltText(asset.filename);
        expect(img.getAttribute("loading")).toBe("lazy");
        expect(img.getAttribute("decoding")).toBe("async");
      }
    });

    it("marks svg fallback images lazy and async", async () => {
      const svgAsset: Asset = {
        id: "s4",
        name: "Logo",
        filename: "logo.svg",
        mime: "image/svg+xml",
        size: 10,
        tags: [],
        url: "/api/assets/s4/file",
        thumb_url: null,
        supporting_file_count: 0,
      };
      listAssetsMock.mockResolvedValue({ items: [svgAsset], hasMore: false });

      render(<AssetGrid theme="dark" />);

      const img = await screen.findByAltText("logo.svg");
      expect(img.getAttribute("loading")).toBe("lazy");
      expect(img.getAttribute("decoding")).toBe("async");
    });

    it("keeps the modal preview image eager with async decoding", async () => {
      render(<AssetGrid theme="dark" />);
      await screen.findByText("Engraved sign");

      // The double-click handler lives on the card's preview wrapper, so it bubbles.
      fireEvent.doubleClick(screen.getByAltText("engraved-sign.png"));

      const modalImage = await waitFor(() => {
        const img = document.querySelector("img.object-contain");
        if (!img) throw new Error("modal preview image not rendered");
        return img;
      });
      expect(modalImage.getAttribute("loading")).toBeNull();
      expect(modalImage.getAttribute("decoding")).toBe("async");
    });
  });
});

describe("files-mode \"not in any project\" filter", () => {
  beforeEach(() => {
    resetToasts();
    listAssetsMock.mockReset();
    listAssetsMock.mockResolvedValue({ items: assets, hasMore: false });
    fileUrlMock.mockClear();
  });

  afterEach(cleanup);

  function notInProjectBox(): HTMLInputElement {
    return screen.getByRole("checkbox", { name: "Not in any project" }) as HTMLInputElement;
  }

  it("narrows the grid and the tag chips to unassigned assets when checked", async () => {
    render(<AssetGrid theme="dark" />);
    await screen.findByText("Calibration cube");
    const callsBefore = listAssetsMock.mock.calls.length;

    fireEvent.click(notInProjectBox());

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1));
    const refreshCall = callQuery(callsBefore);
    expect(refreshCall.not_in_project).toBe(true);
    // A filter change resets the paging window rather than keeping loaded pages.
    expect(refreshCall.offset).toBe(0);

    await waitFor(() =>
      expect(listTagsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ not_in_project: true }),
      ),
    );
  });

  it("drops the flag from both requests when unchecked again", async () => {
    render(<AssetGrid theme="dark" />);
    await screen.findByText("Calibration cube");

    fireEvent.click(notInProjectBox());
    await waitFor(() => expect(notInProjectBox().checked).toBe(true));

    const callsBefore = listAssetsMock.mock.calls.length;
    fireEvent.click(notInProjectBox());

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1));
    expect(callQuery(callsBefore).not_in_project).toBeFalsy();
    expect(listTagsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ not_in_project: false }),
    );
  });

  it("sends no unassigned filter on first load", async () => {
    render(<AssetGrid theme="dark" />);
    await screen.findByText("Calibration cube");

    expect(notInProjectBox().checked).toBe(false);
    expect(callQuery(0).not_in_project).toBeFalsy();
    expect(listTagsMock).toHaveBeenCalledTimes(1);
    expect(listTagsMock.mock.calls[0][0]).toEqual(
      expect.objectContaining({ not_in_project: false }),
    );
  });
});

describe("virtualized flat grid", () => {
  beforeEach(() => {
    resetToasts();
    listAssetsMock.mockReset();
    listAssetsMock.mockResolvedValue({ items: [], hasMore: false });
    fileUrlMock.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    FakeResizeObserver.instances = [];
    cleanup();
  });

  it("bounds the DOM to the visible rows for a 2000-asset library", async () => {
    const total = 2000;
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(total), hasMore: false });

    const { scroller } = renderHarness();

    await waitFor(() => expect(listAssetsMock).toHaveBeenCalledTimes(1));
    await screen.findByText("Asset 1");
    stubGridRect(scroller);

    // Derive the expectation from the shipped constants instead of hardcoding:
    // a 768px viewport covers 3 rows of 360 + 16, and the window never renders
    // more than that plus overscan on the far side.
    const cols = colsForWidth(window.innerWidth);
    expect(cols).toBe(3);
    const stride = ESTIMATED_ROW_HEIGHT + GRID_GAP_PX;
    const visibleRows = Math.ceil(768 / stride);
    const expectedTopRows = Math.min(Math.ceil(total / cols), visibleRows + OVERSCAN_ROWS);

    expect(checkboxCount()).toBe(expectedTopRows * cols);
    expect(checkboxCount()).toBeLessThan(100);
    expect(mountedRowIndexes()).toEqual(
      Array.from({ length: expectedTopRows }, (_, i) => i),
    );

    // A row deep in the list is not in the DOM at all, yet the content below is
    // accounted for by the bottom spacer.
    expect(screen.queryByText("Asset 1000")).toBeNull();
    const bottomSpacer = document.querySelector<HTMLElement>('[data-virtual-spacer="bottom"]');
    expect(bottomSpacer).toBeTruthy();
    expect(Number.parseFloat(bottomSpacer?.style.height ?? "0")).toBeGreaterThan(0);

    const middleOffset = 125_000;
    scrollGrid(scroller, middleOffset);

    await waitFor(() => expect(screen.queryByText("Asset 1")).toBeNull());
    const firstVisibleRow = Math.floor(middleOffset / stride);
    expect(screen.getByText(`Asset ${firstVisibleRow * cols + 1}`)).toBeTruthy();
    expect(mountedRowIndexes()[0]).toBe(firstVisibleRow - OVERSCAN_ROWS);
    // Same bound in the middle: overscan on both sides, still nowhere near 2000.
    expect(checkboxCount()).toBe((visibleRows + OVERSCAN_ROWS * 2) * cols);
    expect(checkboxCount()).toBeLessThan(100);
  });

  it("keeps the scroll position across sort and search changes", async () => {
    const total = 60;
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(total), hasMore: false });

    const { scroller } = renderHarness();

    await screen.findByText("Asset 1");
    stubGridRect(scroller);

    const cols = colsForWidth(window.innerWidth);
    const stride = ESTIMATED_ROW_HEIGHT + GRID_GAP_PX;
    const visibleRows = Math.ceil(768 / stride);
    const bounded = (visibleRows + OVERSCAN_ROWS * 2) * cols;

    const offset = 1400;
    scrollGrid(scroller, offset);

    await waitFor(() => expect(screen.queryByText("Asset 1")).toBeNull());
    const firstVisibleRow = Math.floor(offset / stride);
    expect(firstVisibleRow).toBe(3);
    expect(screen.getByText(`Asset ${firstVisibleRow * cols + 1}`)).toBeTruthy();
    expect(checkboxCount()).toBe(bounded);

    // Sorting re-chunks the same items (sizes are the reverse of the names), so
    // the window must stay at the same offset and re-render from the new order.
    fireEvent.change(sortSelect(), { target: { value: "size" } });

    await waitFor(() => expect(screen.getByText("Asset 57")).toBeTruthy());
    expect(scroller.scrollTop).toBe(offset);
    expect(screen.queryByText("Asset 60")).toBeNull();
    expect(screen.queryByText("Asset 1")).toBeNull();
    expect(checkboxCount()).toBe(bounded);

    // A filtered result set of the same size must not snap the list back to the
    // top either.
    const filtered = makeSyntheticBatch(total, "Filtered").map((asset, index) => ({
      ...asset,
      id: `filtered-${index + 1}`,
      url: `/api/assets/filtered-${index + 1}/file`,
    }));
    listAssetsMock.mockResolvedValue({ items: filtered, hasMore: false });

    const searchInput = screen.getByPlaceholderText(
      "Search title, filename, notes...",
    ) as HTMLInputElement;
    fireEvent.change(searchInput, { target: { value: "needle" } });
    fireEvent.keyDown(searchInput, { key: "Enter" });

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(2));
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
    // The "size" sort is still active, so the window is unchanged: the same
    // mid-list position now holds the filtered set's 57th item.
    await waitFor(() => expect(screen.getByText("Filtered 57")).toBeTruthy());

    expect(scroller.scrollTop).toBe(offset);
    expect(screen.queryByText("Filtered 60")).toBeNull();
    expect(screen.queryByText("Asset 57")).toBeNull();
    expect(checkboxCount()).toBeLessThan(100);
  });

  it("keeps selection when a selected card scrolls out of the window", async () => {
    const total = 60;
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(total), hasMore: false });

    const { scroller } = renderHarness();

    await screen.findByText("Asset 1");
    stubGridRect(scroller);

    const topRow = document.querySelector('[data-row-index="0"]');
    if (!topRow) throw new Error("first row was not rendered");
    const topBoxes = Array.from(
      topRow.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    );
    expect(topBoxes.length).toBeGreaterThanOrEqual(2);

    fireEvent.click(topBoxes[0]);
    // The first click flips `hasSelection`, which legally re-renders every card.
    fireEvent.click(topRow.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1]);
    expect(topBoxes[0].checked).toBe(true);
    expect(topBoxes[1].checked).toBe(true);

    scrollGrid(scroller, 1400);
    await waitFor(() => expect(screen.queryByText("Asset 1")).toBeNull());
    expect(screen.queryAllByText("Asset 2")).toHaveLength(0);

    scrollGrid(scroller, 0);
    await waitFor(() => expect(screen.getByText("Asset 1")).toBeTruthy());

    const restoredRow = document.querySelector('[data-row-index="0"]');
    if (!restoredRow) throw new Error("first row was not rendered after scrolling back");
    const restoredBoxes = Array.from(
      restoredRow.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    );
    expect(restoredBoxes[0].checked).toBe(true);
    expect(restoredBoxes[1].checked).toBe(true);
    expect(restoredBoxes[2].checked).toBe(false);
  });

  it("keeps the focused row mounted while the window moves", async () => {
    const total = 60;
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(total), hasMore: false });

    const { scroller } = renderHarness();

    await screen.findByText("Asset 1");
    stubGridRect(scroller);

    const stride = ESTIMATED_ROW_HEIGHT + GRID_GAP_PX;
    scrollGrid(scroller, 1400);
    await waitFor(() => expect(screen.queryByText("Asset 1")).toBeNull());

    // Row 1 is rendered (overscan) but not visible; it is the first row that a
    // three-row scroll would leave behind.
    const bootRow = document.querySelector('[data-row-index="1"]');
    if (!bootRow) throw new Error("overscan row was not rendered");
    const focused = bootRow.querySelector<HTMLButtonElement>("button");
    if (!focused) throw new Error("row has no button");
    focused.focus();
    expect(document.activeElement).toBe(focused);

    scrollGrid(scroller, 1400 + stride * 3);
    await waitFor(() => expect(mountedRowIndexes()[0]).toBe(1));
    const pinnedRow = document.querySelector('[data-row-index="1"]');
    expect(pinnedRow?.contains(document.activeElement)).toBe(true);

    // A long jump drops the pin (the DOM must stay bounded by the viewport) and
    // the row - with the focus inside it - is unmounted as usual.
    scrollGrid(scroller, 6000);
    await waitFor(() => expect(mountedRowIndexes()[0]).toBe(13));
    expect(document.querySelector('[data-row-index="1"]')).toBeNull();
    expect(document.activeElement).not.toBe(focused);

    const cols = colsForWidth(window.innerWidth);
    expect(checkboxCount()).toBe(
      (Math.ceil(768 / stride) + OVERSCAN_ROWS * 2) * cols,
    );
  });

  it("measures rows, keeps the viewport anchored and keeps the spacers exact", async () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    const total = 60;
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(total), hasMore: false });

    const { scroller } = renderHarness();

    await screen.findByText("Asset 1");
    stubGridRect(scroller);

    const offset = 1400;
    scrollGrid(scroller, offset);
    await waitFor(() => expect(screen.queryByText("Asset 1")).toBeNull());

    const rowIndexes = mountedRowIndexes();
    const firstVisibleRow = Math.floor(offset / (ESTIMATED_ROW_HEIGHT + GRID_GAP_PX));
    expect(rowIndexes[0]).toBe(firstVisibleRow - OVERSCAN_ROWS);

    // Every mounted row reports itself taller than the estimate. Rows above the
    // first visible row must be compensated by scrollTop so the content does
    // not jump; the spacers are then recomputed from the mixed heights.
    const measuredHeight = 500;
    act(() => {
      for (const rowIndex of rowIndexes) {
        const element = document.querySelector(`[data-row-index="${rowIndex}"]`);
        if (!element) throw new Error(`row ${rowIndex} is not rendered`);
        FakeResizeObserver.trigger(element, { height: measuredHeight });
      }
    });

    const rowsAboveViewport = firstVisibleRow - rowIndexes[0];
    expect(scroller.scrollTop).toBe(offset + rowsAboveViewport * (measuredHeight - ESTIMATED_ROW_HEIGHT));

    const cols = colsForWidth(window.innerWidth);
    const heights = new Array<number>(Math.ceil(total / cols)).fill(0);
    for (const rowIndex of rowIndexes) heights[rowIndex] = measuredHeight;
    const tops = rowOffsets(heights);
    const expectedTotal = rowsTotal(heights);
    const renderedRange = mountedRowIndexes();
    const lastRow = renderedRange[renderedRange.length - 1];

    const topSpacer = document.querySelector<HTMLElement>('[data-virtual-spacer="top"]');
    const bottomSpacer = document.querySelector<HTMLElement>('[data-virtual-spacer="bottom"]');
    expect(Number.parseFloat(topSpacer?.style.height ?? "-1")).toBe(
      tops[renderedRange[0]] - GRID_GAP_PX,
    );
    expect(Number.parseFloat(bottomSpacer?.style.height ?? "-1")).toBe(
      expectedTotal - (tops[lastRow] + heights[lastRow] + GRID_GAP_PX),
    );
  });

  it("re-observes the grid wrapper width after a grouped sort remounts it", async () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    const total = 12;
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(total), hasMore: false });

    const { scroller } = renderHarness();

    await screen.findByText("Asset 1");
    stubGridRect(scroller);

    // A 1200px wrapper fits four columns: 12 assets chunk into three rows.
    const fourColsWidth = 1200;
    expect(colsForWidth(fourColsWidth)).toBe(4);
    const firstWrap = document.querySelector<HTMLElement>("[data-virtual-grid]");
    if (!firstWrap) throw new Error("virtual grid wrapper not rendered");
    const mountObservers = liveObserversFor(firstWrap);
    expect(mountObservers).toHaveLength(1);
    act(() => FakeResizeObserver.trigger(firstWrap, { width: fourColsWidth }));

    await waitFor(() => expect(rowCardCount(0)).toBe(4));
    expect(mountedRowIndexes()).toEqual([0, 1, 2]);

    // Grouped sorts never render `[data-virtual-grid]`, and the ref detaches...
    fireEvent.change(sortSelect(), { target: { value: "type" } });
    await waitFor(() => expect(document.querySelector("[data-virtual-grid]")).toBeNull());
    expect(liveObserversFor(firstWrap)).toHaveLength(0);

    // ...and switching back attaches the ref to the wrapper again (whether or
    // not React reuses the DOM node). That attachment must observe the width
    // afresh: a one-shot effect at mount would leave `cols` frozen at four.
    fireEvent.change(sortSelect(), { target: { value: "name" } });
    const remountedWrap = await waitFor(() => {
      const element = document.querySelector<HTMLElement>("[data-virtual-grid]");
      if (!element) throw new Error("virtual grid wrapper did not remount");
      return element;
    });
    const remountObservers = liveObserversFor(remountedWrap);
    expect(remountObservers).toHaveLength(1);
    expect(mountObservers).not.toContain(remountObservers[0]);

    const twoColsWidth = 600;
    expect(colsForWidth(twoColsWidth)).toBe(2);
    act(() => FakeResizeObserver.trigger(remountedWrap, { width: twoColsWidth }));

    await waitFor(() => expect(rowCardCount(0)).toBe(2));
    expect(rowCardCount(1)).toBe(2);
    expect(screen.getByText("Asset 3")).toBeTruthy();
    expect(screen.getByText("Asset 4")).toBeTruthy();
  });

  it("caps each grouped row and expands it on demand", async () => {
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(30), hasMore: false });

    render(<AssetGrid theme="dark" />);

    await screen.findByText("Asset 1");
    fireEvent.change(sortSelect(), { target: { value: "type" } });

    const showAll = await screen.findByRole("button", { name: "Show all 30" });
    // 30 png assets collapse into one type group, capped at GROUP_CARD_CAP.
    expect(checkboxCount()).toBe(24);
    expect(screen.queryByText("Asset 30")).toBeNull();

    fireEvent.click(showAll);
    expect(await screen.findByRole("button", { name: "Show fewer" })).toBeTruthy();
    expect(screen.getByText("Asset 30")).toBeTruthy();
    expect(checkboxCount()).toBe(30);

    fireEvent.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(await screen.findByRole("button", { name: "Show all 30" })).toBeTruthy();
    expect(checkboxCount()).toBe(24);
  });
});

describe("AssetGrid missing assets", () => {
  beforeEach(() => {
    resetToasts();
    listAssetsMock.mockReset();
    listAssetsMock.mockResolvedValue({ items: [missingAsset, ...assets], hasMore: false });
    deleteAssetMock.mockReset();
    startLibraryScanMock.mockReset();
    getLibraryScanStatusMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("shows a missing-file banner without hiding the asset", async () => {
    render(<AssetGrid theme="dark" />);

    await screen.findByText(/File missing/i);
    expect(screen.getByText(missingAsset.name)).toBeTruthy();
    expect(screen.getByText("Calibration cube")).toBeTruthy();
  });

  it("Forget entry opens the same delete dialog and requires the typed file name", async () => {
    render(<AssetGrid theme="dark" />);

    await screen.findByText(/File missing/i);
    fireEvent.click(screen.getByRole("button", { name: "Forget entry" }));

    const dialog = within(screen.getByRole("dialog", { name: /Forget/ }));
    expect(deleteAssetMock).not.toHaveBeenCalled();

    const forget = dialog.getByRole("button", { name: "Forget entry" }) as HTMLButtonElement;
    expect(forget.disabled).toBe(true);

    fireEvent.change(dialog.getByLabelText("Type the file name to confirm"), {
      target: { value: missingAsset.filename },
    });
    fireEvent.click(forget);

    await waitFor(() =>
      expect(deleteAssetMock).toHaveBeenCalledWith(missingAsset.id, missingAsset.filename),
    );
    for (const other of assets) {
      expect(deleteAssetMock).not.toHaveBeenCalledWith(other.id, other.filename);
    }
  });

  it("Re-scan starts a scan and refreshes when idle", async () => {
    startLibraryScanMock.mockResolvedValue(idleScanStatus());
    getLibraryScanStatusMock.mockResolvedValue(idleScanStatus());

    render(<AssetGrid theme="dark" />);

    await screen.findByText(/File missing/i);
    const callsBefore = listAssetsMock.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Re-scan" }));

    await waitFor(() => expect(startLibraryScanMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1));
  });
});

describe("AssetGrid bulk actions", () => {
  beforeEach(() => {
    resetToasts();
    listAssetsMock.mockReset();
    listAssetsMock.mockResolvedValue({ items: assets, hasMore: false });
    listFoldersMock.mockReset();
    listFoldersMock.mockResolvedValue([]);
    batchDeleteAssetsMock.mockReset();
    batchMoveAssetsMock.mockReset();
    batchSetTagsMock.mockReset();
    deleteAssetMock.mockReset();
    setTagsMock.mockReset();
    fileUrlMock.mockClear();
  });

  afterEach(cleanup);

  /** Clicks the first `count` card checkboxes (flat grid order: filename asc). */
  function selectCards(count: number): HTMLInputElement[] {
    const boxes = cardCheckboxes().slice(0, count);
    for (const box of boxes) fireEvent.click(box);
    return boxes;
  }

  function bulkBar() {
    return within(screen.getByTestId("bulk-action-bar"));
  }

  /** The grid's asset-delete dialog (the bar's Delete opens it). */
  function deleteDialog() {
    return within(screen.getByRole("dialog", { name: /Delete/ }));
  }

  async function waitForGrid() {
    await screen.findByText("Calibration cube");
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
  }

  it("bulk delete issues one request for the whole selection", async () => {
    batchDeleteAssetsMock.mockImplementation(async ids => ({ deleted: ids, failed: [] }));

    render(<AssetGrid theme="dark" />);
    await waitForGrid();
    const callsBefore = listAssetsMock.mock.calls.length;

    selectCards(3);
    fireEvent.click(bulkBar().getByRole("button", { name: "Delete" }));
    fireEvent.click(deleteDialog().getByRole("button", { name: "Delete 3 items" }));

    await waitFor(() => expect(batchDeleteAssetsMock).toHaveBeenCalledTimes(1));
    const [requested, confirmCount] = batchDeleteAssetsMock.mock.calls[0];
    expect(requested).toHaveLength(3);
    expect(requested).toEqual(expect.arrayContaining(["a1", "b2", "c3"]));
    expect(confirmCount).toBe(3);
    expect(deleteAssetMock).not.toHaveBeenCalled();

    await waitFor(() => expect(screen.queryByText("Calibration cube")).toBeNull());
    expect(screen.queryByText("Spool holder")).toBeNull();
    expect(screen.queryByText("Engraved sign")).toBeNull();
    // The O(1) proof: no refetch, and no per-asset calls.
    expect(listAssetsMock.mock.calls.length).toBe(callsBefore);
  });

  it("bulk delete keeps the failed asset selected and reports it in the dialog and the bar", async () => {
    batchDeleteAssetsMock.mockResolvedValue({
      deleted: ["a1"],
      failed: [
        { id: "b2", code: "conflict", status: 409, error: "Storage path already exists: X" },
      ],
    });

    render(<AssetGrid theme="dark" />);
    await waitForGrid();
    const callsBefore = listAssetsMock.mock.calls.length;

    selectCards(3);
    fireEvent.click(bulkBar().getByRole("button", { name: "Delete" }));
    fireEvent.click(deleteDialog().getByRole("button", { name: "Delete 3 items" }));

    await waitFor(() => expect(screen.queryByText("Calibration cube")).toBeNull());
    expect(screen.getByText("Spool holder")).toBeTruthy();

    // The dialog does not claim success: it stays open and names the failed row.
    const dialog = within(screen.getByRole("dialog", { name: /Delete/ }));
    const dialogFailures = await dialog.findByTestId("asset-delete-failures");
    const dialogLines = within(dialogFailures).getAllByRole("listitem");
    expect(dialogLines).toHaveLength(1);
    expect(dialogLines[0].getAttribute("data-failed-id")).toBe("b2");
    expect(dialogLines[0].textContent).toBe("spool-holder.stl — Storage path already exists: X");

    // Closing it leaves the same report in the bar, with the failed row selected.
    fireEvent.click(dialog.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(bulkBar().getByText("1 selected")).toBeTruthy();

    const failures = await screen.findByTestId("bulk-failures");
    const lines = within(failures).getAllByRole("listitem");
    expect(lines).toHaveLength(1);
    expect(lines[0].getAttribute("data-failed-id")).toBe("b2");
    expect(lines[0].textContent).toBe("spool-holder.stl — Storage path already exists: X");

    expect(listAssetsMock.mock.calls.length).toBe(callsBefore);
  });

  it("a rejected bulk delete restores the optimistic rows", async () => {
    batchDeleteAssetsMock.mockRejectedValue(new Error("Bulk delete failed: server exploded"));

    render(<AssetGrid theme="dark" />);
    await waitForGrid();
    const callsBefore = listAssetsMock.mock.calls.length;

    selectCards(3);
    fireEvent.click(bulkBar().getByRole("button", { name: "Delete" }));
    fireEvent.click(deleteDialog().getByRole("button", { name: "Delete 3 items" }));

    await waitFor(() => expect(batchDeleteAssetsMock).toHaveBeenCalledTimes(1));

    // The optimistic drop is undone: every row is back on screen.
    await waitFor(() => expect(screen.getByText("Calibration cube")).toBeTruthy());
    expect(screen.getByText("Spool holder")).toBeTruthy();
    expect(screen.getByText("Engraved sign")).toBeTruthy();

    // The whole-request failure is reported in the bar, not as a toast, and the
    // dialog stays open with it instead of closing as if the run had finished.
    await waitFor(() =>
      expect(bulkBar().getByRole("alert").textContent).toBe("Bulk delete failed: server exploded"),
    );
    await waitFor(() =>
      expect(deleteDialog().getByText("Bulk delete failed: server exploded")).toBeTruthy(),
    );

    // Rollback is local: no refetch, and no per-asset deletes.
    expect(listAssetsMock.mock.calls.length).toBe(callsBefore);
    expect(deleteAssetMock).not.toHaveBeenCalled();
  });

  it("a bulk delete rewinds the paging cursor", async () => {
    const loaded = makeSyntheticBatch(5);
    listAssetsMock.mockImplementation(async params => {
      if ((params?.offset ?? 0) === 0) return { items: loaded, hasMore: true };
      return { items: [], hasMore: false };
    });
    batchDeleteAssetsMock.mockImplementation(async ids => ({ deleted: ids, failed: [] }));

    render(<AssetGrid theme="dark" />);
    await screen.findByText("Asset 1");
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
    expect(callQuery(0).offset).toBe(0);

    selectCards(2);
    fireEvent.click(bulkBar().getByRole("button", { name: "Delete" }));
    fireEvent.click(deleteDialog().getByRole("button", { name: "Delete 2 items" }));
    await waitFor(() => expect(batchDeleteAssetsMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText("Asset 1")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(2));
    expect(callQuery(1).offset).toBe(3);
    expect(callQuery(1).limit).toBe(callQuery(0).limit);
  });

  it("bulk tag add is one request and updates rows in place", async () => {
    batchSetTagsMock.mockImplementation(async (ids, change) => ({
      updated: assets
        .filter(item => ids.includes(item.id))
        .map(item => ({ ...item, tags: [...item.tags, ...(change.add ?? [])] })),
      failed: [],
    }));

    render(<AssetGrid theme="dark" />);
    await waitForGrid();
    const callsBefore = listAssetsMock.mock.calls.length;

    selectCards(3);
    const bar = bulkBar();
    fireEvent.change(bar.getByRole("textbox", { name: "Tags" }), {
      target: { value: "bulk" },
    });
    fireEvent.click(bar.getByRole("button", { name: "Add tags" }));

    await waitFor(() => expect(batchSetTagsMock).toHaveBeenCalledTimes(1));
    const [ids, change] = batchSetTagsMock.mock.calls[0];
    expect(ids).toHaveLength(3);
    expect(ids).toEqual(expect.arrayContaining(["a1", "b2", "c3"]));
    expect(change).toEqual({ add: ["bulk"], remove: [] });
    expect(setTagsMock).not.toHaveBeenCalled();

    // One badge per card (the filter chip row also gains the new tag, so count
    // card badges only).
    await waitFor(() =>
      expect(screen.getAllByText("bulk").filter(el => el.tagName === "SPAN")).toHaveLength(3),
    );
    expect(listAssetsMock.mock.calls.length).toBe(callsBefore);
  });

  it("moving the selection out of the viewed folder hides the rows without a refetch", async () => {
    const folderAssets: Asset[] = [
      { ...assets[0], folder_id: "f1" },
      { ...assets[1], folder_id: "f1" },
    ];
    listAssetsMock.mockResolvedValue({ items: folderAssets, hasMore: false });
    listFoldersMock.mockResolvedValue([
      { id: "f1", name: "One", tags: [] },
      { id: "f2", name: "Two", tags: [] },
    ]);
    batchMoveAssetsMock.mockImplementation(async (ids, folderId) => ({
      updated: folderAssets
        .filter(item => ids.includes(item.id))
        .map(item => ({ ...item, folder_id: folderId })),
      failed: [],
    }));

    renderHarness({ folderId: "f1" });
    await screen.findByText("Calibration cube");
    await waitFor(() => expect(listFoldersMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
    const callsBefore = listAssetsMock.mock.calls.length;

    selectCards(2);
    const bar = bulkBar();
    await waitFor(() => expect(bar.getByRole("option", { name: "Two" })).toBeTruthy());
    fireEvent.change(bar.getByRole("combobox", { name: "Target folder" }), {
      target: { value: "f2" },
    });
    fireEvent.click(bar.getByRole("button", { name: "Move" }));

    await waitFor(() => expect(batchMoveAssetsMock).toHaveBeenCalledTimes(1));
    expect(batchMoveAssetsMock.mock.calls[0][1]).toBe("f2");
    expect(batchMoveAssetsMock.mock.calls[0][0]).toEqual(expect.arrayContaining(["a1", "b2"]));

    await waitFor(() => expect(screen.queryByText("Calibration cube")).toBeNull());
    expect(screen.queryByText("Spool holder")).toBeNull();
    expect(listAssetsMock.mock.calls.length).toBe(callsBefore);
  });
});

describe("AssetGrid shared dialogs and toasts", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    resetToasts();
    listAssetsMock.mockReset();
    listAssetsMock.mockResolvedValue({ items: assets, hasMore: false });
    listFoldersMock.mockReset();
    listFoldersMock.mockResolvedValue([]);
    batchDeleteAssetsMock.mockReset();
    deleteAssetMock.mockReset();
    deleteAssetFileMock.mockReset();
    deletePreparedPrintMock.mockReset();
    listAssetFilesMock.mockReset();
    listAssetFilesMock.mockResolvedValue([]);
    updateAssetMetaMock.mockReset();
    uploadAssetMock.mockReset();
    createFolderMock.mockReset();
    createFolderMock.mockImplementation(async (name: string) => ({ id: `folder-${name}` }));
    fileUrlMock.mockClear();
    // Failed requests are logged by design; keep the test output readable.
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
    cleanup();
  });

  async function waitForGrid() {
    await screen.findByText("Calibration cube");
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
  }

  /** The card's own Delete button, never the bulk bar's identically named one. */
  function cardDeleteButton(index = 0): HTMLElement {
    const bar = screen.queryByTestId("bulk-action-bar");
    const buttons = screen.getAllByRole("button", { name: "Delete" });
    const cardButtons = bar ? buttons.filter(button => !bar.contains(button)) : buttons;
    return cardButtons[index];
  }

  function makeDrop(files: File[]) {
    return { types: ["Files"], items: [], files, dropEffect: "copy" };
  }

  it("deleting a card opens the in-app dialog without calling deleteAsset", async () => {
    listAssetsMock.mockResolvedValue({ items: [assets[0]], hasMore: false });

    render(<AssetGrid theme="dark" />);
    await waitForGrid();

    fireEvent.click(cardDeleteButton());

    // The dialog says what actually happens and gates the button on the file name.
    screen.getByRole("dialog", { name: /Delete/ });
    expect(screen.getAllByText(/\.trash/).length).toBeGreaterThan(0);
    expect(deleteAssetMock).not.toHaveBeenCalled();
  });

  it("cancelling the delete dialog makes no request and closes it", async () => {
    listAssetsMock.mockResolvedValue({ items: [assets[0]], hasMore: false });

    render(<AssetGrid theme="dark" />);
    await waitForGrid();

    fireEvent.click(cardDeleteButton());
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(deleteAssetMock).not.toHaveBeenCalled();
  });

  it("confirming the delete dialog sends the typed file name and calls deleteAsset once", async () => {
    listAssetsMock.mockResolvedValue({ items: [assets[0]], hasMore: false });
    deleteAssetMock.mockResolvedValue({ ok: true, trash_path: ".trash/x", files: 1, bytes: 1200 });

    render(<AssetGrid theme="dark" />);
    await waitForGrid();

    fireEvent.click(cardDeleteButton());
    const dialog = within(screen.getByRole("dialog", { name: /Delete/ }));
    fireEvent.change(dialog.getByLabelText("Type the file name to confirm"), {
      target: { value: assets[0].filename },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Delete asset" }));

    await waitFor(() =>
      expect(deleteAssetMock).toHaveBeenCalledWith(assets[0].id, assets[0].filename),
    );
    expect(deleteAssetMock).toHaveBeenCalledTimes(1);
    expect(batchDeleteAssetsMock).not.toHaveBeenCalled();
    // A clean delete closes the dialog without a second confirmation.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a multi-select delete confirms once and uses the batch endpoint", async () => {
    batchDeleteAssetsMock.mockImplementation(async ids => ({ deleted: ids, failed: [] }));

    render(<AssetGrid theme="dark" />);
    await waitForGrid();

    const boxes = cardCheckboxes();
    fireEvent.click(boxes[0]);
    fireEvent.click(boxes[1]);

    fireEvent.click(cardDeleteButton());
    const dialog = within(screen.getByRole("dialog", { name: "Delete 2 selected items?" }));
    // Several assets are confirmed by the step, never by typing N names.
    expect(dialog.queryByLabelText("Type the file name to confirm")).toBeNull();
    expect(batchDeleteAssetsMock).not.toHaveBeenCalled();
    fireEvent.click(dialog.getByRole("button", { name: "Delete 2 items" }));

    await waitFor(() => expect(batchDeleteAssetsMock).toHaveBeenCalledTimes(1));
    const [ids, confirmCount] = batchDeleteAssetsMock.mock.calls[0];
    expect(ids).toHaveLength(2);
    expect(confirmCount).toBe(2);
    expect(deleteAssetMock).not.toHaveBeenCalled();
  });

  it("a failed rename emits exactly one toast and reverts the field", async () => {
    listAssetsMock.mockResolvedValue({ items: [assets[0]], hasMore: false });
    updateAssetMetaMock.mockRejectedValue(new Error("server says no"));

    renderWithToaster(<AssetGrid theme="dark" />);
    await waitForGrid();

    fireEvent.doubleClick(screen.getByText("Calibration cube"));
    const input = screen.getByDisplayValue("Calibration cube");
    fireEvent.change(input, { target: { value: "Renamed cube" } });
    fireEvent.blur(input);

    await waitFor(() => expect(screen.getByTestId("toaster")).toBeTruthy());
    const alerts = toaster().getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain("server says no");

    // The card reverts to the server-side name (the catch only resets the field).
    await waitFor(() => expect(screen.queryByDisplayValue("Renamed cube")).toBeNull());
    expect(screen.getByText("Calibration cube")).toBeTruthy();
  });

  it("a failed drop toasts the filename with a retry that re-uploads only that file", async () => {
    listAssetsMock.mockResolvedValue({ items: [], hasMore: false });
    uploadAssetMock.mockRejectedValue(new Error("disk full"));

    const { container } = renderWithToaster(<AssetGrid theme="dark" />);
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());

    const dropped = new File(["content"], "sample.stl", { type: "application/octet-stream" });
    fireEvent.drop(container.firstChild as Element, { dataTransfer: makeDrop([dropped]) });

    await waitFor(() => expect(uploadAssetMock).toHaveBeenCalledTimes(1));
    const toast = toaster();
    expect(toast.getByText(/Failed to upload 1 file/)).toBeTruthy();
    expect(toast.getByText(/sample\.stl/)).toBeTruthy();

    fireEvent.click(toast.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(uploadAssetMock).toHaveBeenCalledTimes(2));
    expect(uploadAssetMock.mock.calls[1][0].name).toBe("sample.stl");
  });

  it("cancelling the supporting-file remove dialog makes no request", async () => {
    listAssetsMock.mockResolvedValue({ items: [assets[1]], hasMore: false });
    listAssetFilesMock.mockResolvedValue([
      { id: "sf1", filename: "instructions.pdf", mime: "application/pdf", size: 10, url: "/x" },
    ]);

    render(<AssetGrid theme="dark" />);
    await screen.findByText("Spool holder");

    fireEvent.click(screen.getByRole("button", { name: /Supporting files/ }));
    await screen.findByText("instructions.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));

    const dialog = screen.getByRole("dialog", { name: "Remove instructions.pdf from this model?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(deleteAssetFileMock).not.toHaveBeenCalled();
  });

  it("cancelling the prepared-print clear dialog makes no request", async () => {
    listAssetsMock.mockResolvedValue({
      items: [
        {
          ...assets[0],
          prepared_print: {
            printer: "Prusa",
            material: "PLA",
            estimated_seconds: 3600,
            removable: true,
          },
        },
      ],
      hasMore: false,
    });

    render(<AssetGrid theme="dark" />);
    await screen.findByText("Calibration cube");

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    const dialog = screen.getByRole("dialog", {
      name: "Clear the attached prepared print from this model?",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(deletePreparedPrintMock).not.toHaveBeenCalled();
  });

  it("the details editor offers no Collection field and saves only notes and creator", async () => {
    listAssetsMock.mockResolvedValue({
      items: [
        {
          ...assets[0],
          notes: "Old notes",
          creator: "Old creator",
          collection: "Tabletop",
        },
      ],
      hasMore: false,
    });
    updateAssetMetaMock.mockResolvedValue(undefined);

    render(<AssetGrid theme="dark" />);
    await waitForGrid();

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit details" }));

    // The retired field is neither offered nor echoed back into the form.
    expect(screen.queryByPlaceholderText("Collection name")).toBeNull();
    expect(screen.queryByLabelText(/collection/i)).toBeNull();
    expect(screen.getByLabelText("Creator")).toBeTruthy();
    expect(screen.getByLabelText("Notes")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("Designer or source"), {
      target: { value: "New creator" },
    });
    fireEvent.change(screen.getByPlaceholderText("Add some details about this asset"), {
      target: { value: "New notes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateAssetMetaMock).toHaveBeenCalledTimes(1));
    const [id, payload] = updateAssetMetaMock.mock.calls[0];
    expect(id).toBe("a1");
    // The exact key set proves the client sends no `collection` at all, so a
    // stored legacy value can never be clobbered by an empty string.
    expect(Object.keys(payload as object).sort()).toEqual(["creator", "notes"]);
    expect(payload).toEqual({ notes: "New notes", creator: "New creator" });
  });
});

describe("folder cards", () => {
  const folderFixtures: Folder[] = [
    { id: "p", name: "Parts", tags: [] },
    { id: "c1", name: "Brackets", tags: [], parent_id: "p" },
    { id: "c2", name: "Clamps", tags: [], parent_id: "p" },
    { id: "x", name: "Elsewhere", tags: [] },
  ];

  beforeEach(() => {
    resetToasts();
    listAssetsMock.mockReset();
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(2), hasMore: false });
    listFoldersMock.mockReset();
    listFoldersMock.mockResolvedValue(folderFixtures);
    fileUrlMock.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    FakeResizeObserver.instances = [];
    cleanup();
  });

  it("shows the breadcrumb trail and the direct subfolders of the open folder", async () => {
    const onNavigateFolder = vi.fn();
    renderHarness({ folderId: "p", onNavigateFolder });

    const nav = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-folder-breadcrumbs]");
      if (!found) throw new Error("breadcrumbs not rendered");
      return found;
    });
    expect(within(nav).getByRole("button", { name: "All files" })).toBeTruthy();
    const current = within(nav).getByRole("button", { name: "Parts" });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(within(nav).getAllByRole("button").map(b => b.textContent)).toEqual([
      "All files",
      "Parts",
    ]);

    const tiles = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-folder-tiles]");
      if (!found) throw new Error("folder tiles not rendered");
      return found;
    });
    expect(
      Array.from(tiles.querySelectorAll("[data-folder-tile]")).map(el =>
        el.getAttribute("data-folder-tile"),
      ),
    ).toEqual(["c1", "c2"]);
    expect(within(tiles).getByRole("button", { name: /Brackets/ })).toBeTruthy();
    expect(within(tiles).getByRole("button", { name: /Clamps/ })).toBeTruthy();
    // Direct children only: a sibling root is not a subfolder of "Parts".
    expect(within(tiles).queryByRole("button", { name: /Elsewhere/ })).toBeNull();

    fireEvent.click(within(tiles).getByRole("button", { name: /Brackets/ }));
    expect(onNavigateFolder).toHaveBeenLastCalledWith("c1");

    fireEvent.keyDown(within(tiles).getByRole("button", { name: /Clamps/ }), { key: "Enter" });
    expect(onNavigateFolder).toHaveBeenLastCalledWith("c2");
  });

  it("keeps the virtualizer intact with subfolder tiles above the grid", async () => {
    const total = 60;
    listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(total), hasMore: false });

    const { scroller } = renderHarness({ folderId: "p", onNavigateFolder: vi.fn() });

    await screen.findByText("Asset 1");
    await waitFor(() =>
      expect(document.querySelector("[data-folder-tiles]")).toBeTruthy(),
    );
    const gridWrap = stubGridRect(scroller);

    // The tiles are their own block above the grid: never inside the wrapper
    // the virtualizer measures, or the offset math would be wrong.
    const tiles = document.querySelector("[data-folder-tiles]");
    expect(tiles).toBeTruthy();
    expect(gridWrap.contains(tiles)).toBe(false);

    const rows = mountedRowIndexes();
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0]).toBe(0);
    expect(rows).toEqual(Array.from({ length: rows.length }, (_, index) => index));
    expect(screen.getByText("Asset 1")).toBeTruthy();

    const bottomSpacer = document.querySelector<HTMLElement>('[data-virtual-spacer="bottom"]');
    expect(bottomSpacer).toBeTruthy();
    expect(Number.parseFloat(bottomSpacer?.style.height ?? "0")).toBeGreaterThan(0);
  });
});
