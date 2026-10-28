// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { Asset, Project } from "../lib/api";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  addProjectAssets: vi.fn(),
  batchDeleteAssets: vi.fn(),
  batchMoveAssets: vi.fn(),
  batchSetTags: vi.fn(),
  createProject: vi.fn(),
  deleteAsset: vi.fn(),
  deleteAssetFile: vi.fn(),
  deletePreparedPrint: vi.fn(),
  downloadZip: vi.fn(),
  fileUrl: vi.fn((rel: string) => rel),
  getLibraryScanStatus: vi.fn(),
  listAssetFiles: vi.fn(async () => []),
  listAssets: vi.fn(),
  listFolders: vi.fn(async () => []),
  listProjects: vi.fn(),
  listProjectAssets: vi.fn(),
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
import {
  addProjectAssets,
  listAssets,
  listProjects,
} from "../lib/api";
import { resetToasts } from "../lib/toast";

const addProjectAssetsMock = vi.mocked(addProjectAssets);
const listAssetsMock = vi.mocked(listAssets);
const listProjectsMock = vi.mocked(listProjects);

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "Hydra",
    description: null,
    creator: null,
    source_url: null,
    licence: null,
    licence_url: null,
    origin: "own",
    cover_asset_id: null,
    cover_thumb_url: null,
    asset_count: 0,
    metadata_json: {},
    total_size: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

/** Card-safe fixture: an image with a thumb, so no WebGL path is exercised. */
function makeAsset(index: number, folderId: string | null = null): Asset {
  const id = `asset-${index}`;
  return {
    id,
    name: `Model ${index}`,
    filename: `${id}.png`,
    mime: "image/png",
    size: 1000 + index,
    tags: [],
    url: `/api/assets/${id}/file`,
    thumb_url: `/api/assets/${id}/thumb`,
    folder_id: folderId,
    supporting_file_count: 0,
  };
}

const threeAssets: Asset[] = [makeAsset(1), makeAsset(2), makeAsset(3)];

const FOLDERS = ["fa", "fb", "fc"];

/** 100 assets spread over three folders: the bulk path is cross-folder. */
const hundredAssets: Asset[] = Array.from({ length: 100 }, (_, index) =>
  makeAsset(index + 1, FOLDERS[index % FOLDERS.length]),
);

function cardCheckboxes(): HTMLInputElement[] {
  // The files-mode toolbar also renders a checkbox, so name-scope to card selectors.
  return screen.getAllByRole("checkbox", { name: "Select" }) as HTMLInputElement[];
}

beforeEach(() => {
  vi.clearAllMocks();
  resetToasts();
  listProjectsMock.mockResolvedValue([makeProject()]);
  listAssetsMock.mockResolvedValue({ items: threeAssets, hasMore: false });
  addProjectAssetsMock.mockResolvedValue({ added: [], skipped: [], failed: [] });
});

afterEach(cleanup);

describe("AssetGrid add-to-project", () => {
  it("opens the picker for the whole multi-selection from a card button", async () => {
    const onProjectsChanged = vi.fn();
    render(<AssetGrid theme="dark" onProjectsChanged={onProjectsChanged} />);

    await screen.findByText("Model 1");
    const boxes = cardCheckboxes();
    expect(boxes.length).toBe(3);
    boxes.forEach(box => fireEvent.click(box));

    // Scope to one card: the bulk bar above it carries a button of the same
    // name, so a bare getAllByRole would not prove the card path.
    const card = document.querySelector('[data-asset-id="asset-2"]') as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Add to project…" }));

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    fireEvent.click(await within(dialog).findByRole("radio", { name: "Hydra" }));
    fireEvent.click(within(dialog).getByRole("button", { name: 'Add 3 files to "Hydra"' }));

    await waitFor(() => expect(addProjectAssetsMock).toHaveBeenCalledTimes(1));
    const [projectId, sentIds] = addProjectAssetsMock.mock.calls[0];
    expect(projectId).toBe("p1");
    expect(sentIds).toHaveLength(3);
    expect(new Set(sentIds)).toEqual(new Set(["asset-1", "asset-2", "asset-3"]));
    await waitFor(() => expect(onProjectsChanged).toHaveBeenCalledTimes(1));
  });

  it("adds a cross-folder 100-asset selection in exactly one request", async () => {
    listAssetsMock.mockResolvedValue({ items: hundredAssets, hasMore: false });
    render(<AssetGrid theme="dark" />);

    await screen.findByText("Model 1");

    // The bulk bar only renders once something is selected.
    fireEvent.click(cardCheckboxes()[0]);
    const bar = within(screen.getByTestId("bulk-action-bar"));
    fireEvent.click(bar.getByRole("button", { name: "Select all" }));
    expect(screen.getByText("100 selected")).toBeTruthy();

    fireEvent.click(bar.getByRole("button", { name: "Add to project…" }));
    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    fireEvent.click(await within(dialog).findByRole("radio", { name: "Hydra" }));
    fireEvent.click(within(dialog).getByRole("button", { name: 'Add 100 files to "Hydra"' }));

    await waitFor(() => expect(addProjectAssetsMock).toHaveBeenCalledTimes(1));
    const [projectId, sentIds] = addProjectAssetsMock.mock.calls[0];
    expect(projectId).toBe("p1");
    expect(sentIds).toHaveLength(100);
    expect(new Set(sentIds)).toEqual(new Set(hundredAssets.map(asset => asset.id)));
    // The fixture really is cross-folder, so this was not a single-folder path.
    expect(new Set(hundredAssets.map(asset => asset.folder_id)).size).toBeGreaterThan(1);
  });
});
