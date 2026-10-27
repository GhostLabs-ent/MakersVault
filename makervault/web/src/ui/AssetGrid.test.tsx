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
  fileUrl: (rel: string) => rel,
  listAssetFiles: vi.fn(async () => []),
  listAssets: vi.fn(),
  listFolders: vi.fn(async () => []),
  listTags: vi.fn(async () => []),
  setTags: vi.fn(),
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
import { listAssets } from "../lib/api";

const listAssetsMock = vi.mocked(listAssets);

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
});
