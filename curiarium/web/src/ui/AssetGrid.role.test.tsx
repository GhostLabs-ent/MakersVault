// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createRef } from "react";

import type { Asset, AssetFile } from "../lib/api";
import {
  ESTIMATED_ROW_HEIGHT,
  GRID_GAP_PX,
  OVERSCAN_ROWS,
  colsForWidth,
} from "../lib/virtualGrid";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  addProjectAssets: vi.fn(),
  batchDeleteAssets: vi.fn(),
  batchMoveAssets: vi.fn(),
  batchSetMeta: vi.fn(),
  batchSetTags: vi.fn(),
  createProject: vi.fn(),
  createFolder: vi.fn(),
  deleteAsset: vi.fn(),
  deleteAssetFile: vi.fn(),
  deletePreparedPrint: vi.fn(),
  downloadZip: vi.fn(),
  fileUrl: vi.fn((rel: string) => rel),
  getLibraryScanStatus: vi.fn(),
  assetFilePreviewUrl: vi.fn((rel: string) => `${rel}?inline=1`),
  listAssetFileLimits: vi.fn(async () => ({
    count: 0,
    total_bytes: 0,
    max_count: 0,
    max_file_bytes: 0,
    max_total_bytes: 0,
  })),
  listAssetFiles: vi.fn(async () => []),
  renameAssetFile: vi.fn(),
  reorderAssetFiles: vi.fn(async (_assetId: string, fileIds: string[]) => fileIds),
  listAssets: vi.fn(),
  listFolders: vi.fn(async () => []),
  listProjects: vi.fn(async () => []),
  listCreators: vi.fn(async () => []),
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
  addProjectAssets,
  batchDeleteAssets,
  batchMoveAssets,
  batchSetMeta,
  batchSetTags,
  createFolder,
  deleteAsset,
  deleteAssetFile,
  deletePreparedPrint,
  listAssetFileLimits,
  listAssetFiles,
  listAssets,
  listCreators,
  listFolders,
  listTags,
  renameAssetFile,
  reorderAssetFiles,
  setTags,
  startLibraryScan,
  updateAssetFolder,
  updateAssetMeta,
  uploadAsset,
  uploadAssetFile,
} from "../lib/api";

const listAssetsMock = vi.mocked(listAssets);
const listFoldersMock = vi.mocked(listFolders);
const listTagsMock = vi.mocked(listTags);
const listCreatorsMock = vi.mocked(listCreators);
const listAssetFilesMock = vi.mocked(listAssetFiles);
const listAssetFileLimitsMock = vi.mocked(listAssetFileLimits);

/** Every endpoint that writes. No viewer interaction may reach one of them. */
const writeMocks = [
  setTags,
  updateAssetMeta,
  deleteAsset,
  uploadAsset,
  uploadAssetFile,
  renameAssetFile,
  reorderAssetFiles,
  deleteAssetFile,
  deletePreparedPrint,
  batchSetTags,
  batchMoveAssets,
  batchDeleteAssets,
  batchSetMeta,
  updateAssetFolder,
  startLibraryScan,
  createFolder,
  addProjectAssets,
].map(api => vi.mocked(api));

const NO_FILE_LIMITS = {
  count: 0,
  total_bytes: 0,
  max_count: 0,
  max_file_bytes: 0,
  max_total_bytes: 0,
};

const supportingFile: AssetFile = {
  id: "sf1",
  filename: "notes.pdf",
  mime: "application/pdf",
  size: 120,
  position: 0,
  url: "/api/assets/a1/files/sf1",
};

/** png-with-thumb fixtures only: no WebGL, no vendor preview path. */
const assets: Asset[] = [
  {
    id: "a1",
    name: "Calibration cube",
    filename: "calibration-cube.png",
    mime: "image/png",
    size: 1200,
    tags: ["pla"],
    url: "/api/assets/a1/file",
    thumb_url: "/api/assets/a1/thumb",
    supporting_file_count: 1,
    creator: "Ada",
    notes: "Strong print",
  },
  {
    id: "b2",
    name: "Prepared spool",
    filename: "prepared-spool.png",
    mime: "image/png",
    size: 3400,
    tags: [],
    url: "/api/assets/b2/file",
    thumb_url: "/api/assets/b2/thumb",
    supporting_file_count: 0,
    prepared_print: { printer: "X1C", removable: true },
  },
  {
    id: "m3",
    name: "Lost model",
    filename: "lost-model.png",
    mime: "image/png",
    size: 2200,
    tags: [],
    url: "/api/assets/m3/file",
    thumb_url: "/api/assets/m3/thumb",
    supporting_file_count: 0,
    missing_since: "2026-10-27T11:31:34+00:00",
  },
];

function renderGrid(canWrite: boolean) {
  const utils = render(
    <>
      <AssetGrid canWrite={canWrite} theme="dark" />
      <Toaster />
    </>,
  );
  return utils;
}

/** Cards are the only elements carrying the asset id. */
function cardFor(assetId: string): HTMLElement {
  const card = document.querySelector<HTMLElement>(`[data-asset-id="${assetId}"]`);
  if (!card) throw new Error(`card ${assetId} is not rendered`);
  return card;
}

function folderSelectIn(card: HTMLElement): HTMLSelectElement | null {
  return (
    Array.from(card.querySelectorAll("select")).find(select =>
      // The folder options come from `listFolders`, so "f1" identifies it.
      Array.from(select.options).some(option => option.value === "f1"),
    ) ?? null
  );
}

function downloadSelectIn(card: HTMLElement): HTMLSelectElement | null {
  return (
    Array.from(card.querySelectorAll("select")).find(select =>
      Array.from(select.options).some(option => option.textContent === "Download..."),
    ) ?? null
  );
}

/** The supporting-file list only loads once the card section is expanded. */
async function expandSupportingFiles(card: HTMLElement) {
  fireEvent.click(within(card).getByRole("button", { name: /Supporting files/ }));
  return within(card).findByText("notes.pdf");
}

/** Clicks every control a viewer can reach, skipping hidden inputs. */
function clickEveryVisibleControl(): void {
  const controls = Array.from(
    document.querySelectorAll<HTMLElement>("button, select, input, a"),
  );
  for (const control of controls) {
    if (control instanceof HTMLInputElement) {
      if (control.type === "file" || control.hidden) continue;
      fireEvent.click(control);
      continue;
    }
    if (control instanceof HTMLSelectElement) {
      const option = Array.from(control.options).find(
        entry => !entry.disabled && entry.value !== "",
      );
      if (option) fireEvent.change(control, { target: { value: option.value } });
      continue;
    }
    if (control instanceof HTMLAnchorElement) {
      // A download link is a read: assert the target instead of navigating.
      expect(control.getAttribute("href")).toBeTruthy();
      continue;
    }
    fireEvent.click(control);
  }
}

function fileDrag() {
  return { dataTransfer: { types: ["Files"], items: [], files: [], dropEffect: "copy" } };
}

/** jsdom has no layout, so a `DOMRect`-shaped value has to be supplied by hand. */
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

/** Real scroll container with the one measurement jsdom cannot provide. */
function renderVirtualHarness(canWrite: boolean): HTMLDivElement {
  const scrollerRef = createRef<HTMLDivElement>();
  render(
    <div ref={scrollerRef} data-testid="asset-scroller">
      <AssetGrid canWrite={canWrite} theme="dark" scrollElementRef={scrollerRef} />
    </div>,
  );
  const scroller = scrollerRef.current;
  if (!scroller) throw new Error("scroll harness did not mount");
  Object.defineProperty(scroller, "clientHeight", { value: 768, configurable: true });
  vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(rectOf(0, 768));
  return scroller;
}

function stubGridRect(scroller: HTMLDivElement): HTMLElement {
  const gridWrap = document.querySelector<HTMLElement>("[data-virtual-grid]");
  if (!gridWrap) throw new Error("virtual grid wrapper not rendered");
  vi.spyOn(gridWrap, "getBoundingClientRect").mockImplementation(() =>
    rectOf(-scroller.scrollTop, 0),
  );
  return gridWrap;
}

function mountedRowIndexes(): number[] {
  return Array.from(document.querySelectorAll("[data-row-index]")).map(el =>
    Number(el.getAttribute("data-row-index")),
  );
}

function cardCount(): number {
  return document.querySelectorAll("[data-asset-id]").length;
}

function makeSyntheticAsset(index: number): Asset {
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
  };
}

function makeSyntheticBatch(count: number): Asset[] {
  return Array.from({ length: count }, (_, index) => makeSyntheticAsset(index + 1));
}

describe("AssetGrid role capability", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    resetToasts();
    vi.clearAllMocks();
    // `handleApiError` reports through console.error; keep the test output clean.
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    listAssetsMock.mockResolvedValue({ items: assets, hasMore: false });
    listFoldersMock.mockResolvedValue([{ id: "f1", name: "Folder one", tags: [] }]);
    listTagsMock.mockResolvedValue([]);
    listCreatorsMock.mockResolvedValue([]);
    listAssetFilesMock.mockResolvedValue([supportingFile]);
    listAssetFileLimitsMock.mockResolvedValue({ ...NO_FILE_LIMITS, count: 1 });
  });

  afterEach(() => {
    cleanup();
    consoleError.mockRestore();
  });

  describe("viewer", () => {
    it("hides every per-card write control and keeps the read surfaces", async () => {
      renderGrid(false);
      await screen.findByText("Calibration cube");

      const card = cardFor("a1");
      for (const name of ["Edit tags", "Add to project…", "Delete", "Add files"]) {
        expect(within(card).queryByRole("button", { name })).toBeNull();
      }
      expect(folderSelectIn(card)).toBeNull();

      // Reads stay: the selection checkbox, the download menu and the counts.
      expect(within(card).getByRole("checkbox", { name: "Select" })).toBeTruthy();
      expect(downloadSelectIn(card)).toBeTruthy();
      expect(within(card).getByRole("button", { name: /Supporting files/ }).textContent).toContain(
        "1",
      );
      expect(within(card).getByText("By Ada")).toBeTruthy();
      expect(within(card).getByText("pla")).toBeTruthy();

      await expandSupportingFiles(card);
      // The file list itself is a read: preview and download stay, the
      // reorder/rename/remove controls do not.
      expect(within(card).getByRole("button", { name: "Preview notes.pdf" })).toBeTruthy();
      expect(within(card).getByRole("link", { name: "Download" })).toBeTruthy();
      for (const name of [/Move notes.pdf up/, /Move notes.pdf down/, "Rename", "Remove"]) {
        expect(within(card).queryByRole("button", { name })).toBeNull();
      }

      // The read-only creator/notes display survives; its editor trigger does not.
      fireEvent.click(within(card).getByRole("button", { name: "Expand" }));
      expect(within(card).getByText("Ada")).toBeTruthy();
      expect(within(card).getByText("Strong print")).toBeTruthy();
      expect(within(card).queryByRole("button", { name: "Edit details" })).toBeNull();
    });

    it("keeps the missing-file banner but not its repair controls", async () => {
      renderGrid(false);
      await screen.findByText("Lost model");

      const card = cardFor("m3");
      expect(within(card).getByText("File missing")).toBeTruthy();
      expect(within(card).queryByRole("button", { name: "Re-scan" })).toBeNull();
      expect(within(card).queryByRole("button", { name: "Forget entry" })).toBeNull();
    });

    it("keeps the prepared-print summary but drops its clear action", async () => {
      renderGrid(false);
      await screen.findByText("Prepared spool");

      const card = cardFor("b2");
      expect(within(card).getByText("Prepared for X1C")).toBeTruthy();
      expect(within(card).queryByRole("button", { name: "Clear" })).toBeNull();
    });

    it("leaves the card name as plain text when it is double-clicked", async () => {
      renderGrid(false);
      const name = await screen.findByText("Calibration cube");

      fireEvent.doubleClick(name);

      // No rename mode: the text stays, and no input appears in its place.
      expect(screen.getByText("Calibration cube")).toBeTruthy();
      expect(screen.queryByDisplayValue("Calibration cube")).toBeNull();
      expect(writeMocks.some(mock => mock.mock.calls.length > 0)).toBe(false);
    });

    it("shows the bulk bar without any of its write actions", async () => {
      renderGrid(false);
      await screen.findByText("Calibration cube");

      const boxes = screen.getAllByRole("checkbox", { name: "Select" });
      fireEvent.click(boxes[0]);
      fireEvent.click(boxes[1]);

      const bar = within(screen.getByTestId("bulk-action-bar"));
      expect(bar.getByText("2 selected")).toBeTruthy();
      for (const name of [
        "Move",
        "Add tags",
        "Remove tags",
        "Edit metadata…",
        "Add to project…",
        "Delete",
      ]) {
        expect(bar.queryByRole("button", { name })).toBeNull();
      }
      expect(bar.queryByRole("combobox", { name: "Target folder" })).toBeNull();
      expect(bar.queryByRole("textbox", { name: "Tags" })).toBeNull();

      for (const name of ["Download zip", "Select all", "Clear"]) {
        expect(bar.getByRole("button", { name })).toBeTruthy();
      }
    });
  });

  describe("editor", () => {
    it("offers every write control a viewer loses", async () => {
      renderGrid(true);
      await screen.findByText("Calibration cube");

      const card = cardFor("a1");
      for (const name of ["Edit tags", "Add to project…", "Delete", "Add files"]) {
        expect(within(card).getByRole("button", { name })).toBeTruthy();
      }
      expect(folderSelectIn(card)).toBeTruthy();

      await expandSupportingFiles(card);
      for (const name of [/Move notes.pdf up/, /Move notes.pdf down/, "Rename", "Remove"]) {
        expect(within(card).getByRole("button", { name })).toBeTruthy();
      }

      fireEvent.click(within(card).getByRole("button", { name: "Expand" }));
      expect(within(card).getByRole("button", { name: "Edit details" })).toBeTruthy();

      const missing = cardFor("m3");
      expect(within(missing).getByRole("button", { name: "Re-scan" })).toBeTruthy();
      expect(within(missing).getByRole("button", { name: "Forget entry" })).toBeTruthy();

      expect(within(cardFor("b2")).getByRole("button", { name: "Clear" })).toBeTruthy();
    });

    it("drops the open tag editor when the role is demoted mid-edit", async () => {
      const { rerender } = renderGrid(true);
      await screen.findByText("Calibration cube");

      fireEvent.click(within(cardFor("a1")).getByRole("button", { name: "Edit tags" }));
      // The tag editor is open: its Save button is the marker (the placeholder
      // is empty for an asset that already carries tags).
      expect(within(cardFor("a1")).getByRole("button", { name: "Save" })).toBeTruthy();

      rerender(
        <>
          <AssetGrid canWrite={false} theme="dark" />
          <Toaster />
        </>,
      );

      // The editor cannot outlive the capability that opened it.
      await waitFor(() =>
        expect(within(cardFor("a1")).queryByRole("button", { name: "Save" })).toBeNull(),
      );
      expect(screen.queryByRole("button", { name: "Edit tags" })).toBeNull();
    });
  });

  describe("no write is reachable", () => {
    it("calls no write endpoint for any click or file drop a viewer can make", async () => {
      const { container } = renderGrid(false);
      await screen.findByText("Calibration cube");
      const root = container.firstElementChild as HTMLElement;

      clickEveryVisibleControl();
      // Second pass: the first selection revealed the bulk bar.
      clickEveryVisibleControl();

      for (const name of ["Calibration cube", "Prepared spool", "Lost model"]) {
        fireEvent.doubleClick(screen.getByText(name));
      }

      fireEvent.dragEnter(root, fileDrag());
      fireEvent.dragOver(root, fileDrag());
      fireEvent.drop(root, fileDrag());

      await waitFor(() =>
        expect(screen.queryByText(/Drop files or folders to upload/)).toBeNull(),
      );
      expect(screen.queryByText(/Uploading to/)).toBeNull();
      // The read-only viewer gets no rename input either.
      expect(screen.queryByDisplayValue("Calibration cube")).toBeNull();

      for (const mock of writeMocks) {
        expect(mock).not.toHaveBeenCalled();
      }
    });

    it("shows the drop overlay to an editor, so the viewer assertion is not vacuous", async () => {
      const { container } = renderGrid(true);
      await screen.findByText("Calibration cube");

      fireEvent.dragEnter(container.firstElementChild as HTMLElement, fileDrag());

      expect(await screen.findByText(/Drop files or folders to upload/)).toBeTruthy();
    });
  });

  describe("virtualization", () => {
    it("renders a viewer's shorter cards inside exactly the editor's row window", async () => {
      const total = 2000;
      listAssetsMock.mockResolvedValue({ items: makeSyntheticBatch(total), hasMore: false });

      const editorScroller = renderVirtualHarness(true);
      await screen.findByText("Asset 1");
      stubGridRect(editorScroller);
      const editorRows = mountedRowIndexes();
      const editorCards = cardCount();
      cleanup();

      const viewerScroller = renderVirtualHarness(false);
      await screen.findByText("Asset 1");
      stubGridRect(viewerScroller);
      const viewerRows = mountedRowIndexes();
      const viewerCards = cardCount();

      // Expectations derived from the shipped constants, never hardcoded.
      const cols = colsForWidth(window.innerWidth);
      expect(cols).toBe(3);
      const stride = ESTIMATED_ROW_HEIGHT + GRID_GAP_PX;
      const visibleRows = Math.ceil(768 / stride);
      const expectedTopRows = Math.min(Math.ceil(total / cols), visibleRows + OVERSCAN_ROWS);
      const expectedWindow = Array.from({ length: expectedTopRows }, (_, index) => index);

      expect(viewerRows).toEqual(expectedWindow);
      // The gated action row must not move the window: a viewer mounts the same
      // rows, and therefore the same number of cards, as an editor.
      expect(viewerRows).toEqual(editorRows);
      expect(viewerCards).toBe(editorCards);
      expect(viewerCards).toBe(expectedTopRows * cols);
      expect(viewerCards).toBeLessThan(100);

      const bottomSpacer = document.querySelector<HTMLElement>('[data-virtual-spacer="bottom"]');
      expect(bottomSpacer).toBeTruthy();
      expect(Number.parseFloat(bottomSpacer?.style.height ?? "0")).toBeGreaterThan(0);
    });
  });
});
