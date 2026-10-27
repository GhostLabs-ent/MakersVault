// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { Asset } from "../lib/api";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  deleteAsset: vi.fn(),
  deleteAssetFile: vi.fn(),
  deletePreparedPrint: vi.fn(),
  downloadZip: vi.fn(),
  fileUrl: vi.fn((rel: string) => rel),
  getLibraryScanStatus: vi.fn(),
  listAssetFiles: vi.fn(async () => []),
  listAssets: vi.fn(),
  listFolders: vi.fn(async () => []),
  listTags: vi.fn(async () => []),
  setTags: vi.fn(),
  startLibraryScan: vi.fn(),
  updateAssetFolder: vi.fn(),
  updateAssetMeta: vi.fn(),
  uploadAssetFile: vi.fn(),
}));

vi.mock("./ModelViewer", () => ({
  default: () => null,
  ModelSnapshot: () => null,
}));

vi.mock("./LightBurnPreview", () => ({
  default: () => null,
}));

import AssetGrid from "./AssetGrid";
import {
  deleteAsset,
  fileUrl,
  getLibraryScanStatus,
  listAssets,
  startLibraryScan,
} from "../lib/api";

const listAssetsMock = vi.mocked(listAssets);
const fileUrlMock = vi.mocked(fileUrl);
const deleteAssetMock = vi.mocked(deleteAsset);
const startLibraryScanMock = vi.mocked(startLibraryScan);
const getLibraryScanStatusMock = vi.mocked(getLibraryScanStatus);

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

describe("AssetGrid asset refresh", () => {
  beforeEach(() => {
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

    const selection = screen.getAllByRole("checkbox")[0] as HTMLInputElement;
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

    const selectionAfter = screen.getAllByRole("checkbox").find(el => el === selection);
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

    const { rerender } = render(<AssetGrid theme="dark" />);

    await waitFor(() => expect(listAssets).toHaveBeenCalledTimes(1));
    await screen.findByText("Page 1 item 1");
    expect(pageSize).toBeGreaterThan(1);
    const firstCall = callQuery(0);
    expect(firstCall.offset).toBe(0);
    expect(firstCall.limit).toBe(pageSize);

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(2));
    await screen.findByText("Page 2 item 1");
    await waitFor(() => expect(screen.getByText(`Page 1 item ${pageSize}`)).toBeTruthy());
    const loadMoreCall = callQuery(1);
    expect(loadMoreCall.offset).toBe(pageSize);
    expect(loadMoreCall.limit).toBe(pageSize);

    const callsBefore = listAssetsMock.mock.calls.length;

    rerender(<AssetGrid theme="dark" assetsVersion={1} />);

    await waitFor(() => expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1));
    await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
    expect(listAssetsMock.mock.calls.length).toBe(callsBefore + 1);

    const refreshCall = callQuery(callsBefore);
    expect(refreshCall.offset).toBe(0);
    expect(refreshCall.limit).toBe(pageSize * 2);

    expect(screen.getByText("Page 1 item 1")).toBeTruthy();
    expect(screen.getByText(`Page 1 item ${pageSize}`)).toBeTruthy();
    expect(screen.getByText(`Page 2 item ${pageSize}`)).toBeTruthy();
    expect(screen.getAllByText(/^Page [12] item \d+$/).length).toBe(pageSize * 2);
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
      const checkboxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
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

describe("AssetGrid missing assets", () => {
  beforeEach(() => {
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

  it("Forget entry deletes only that asset", async () => {
    vi.stubGlobal("confirm", vi.fn(() => true));

    render(<AssetGrid theme="dark" />);

    await screen.findByText(/File missing/i);
    fireEvent.click(screen.getByRole("button", { name: "Forget entry" }));

    await waitFor(() => expect(deleteAssetMock).toHaveBeenCalledWith(missingAsset.id));
    for (const other of assets) {
      expect(deleteAssetMock).not.toHaveBeenCalledWith(other.id);
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
