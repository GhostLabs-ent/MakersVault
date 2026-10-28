// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { Asset } from "../lib/api";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  addProjectAssets: vi.fn(),
  batchDeleteAssets: vi.fn(),
  batchMoveAssets: vi.fn(),
  batchSetMeta: vi.fn(),
  batchSetTags: vi.fn(),
  createProject: vi.fn(),
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
  listProjectAssets: vi.fn(),
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
import { listAssets, listFolders, listProjectAssets, listTags } from "../lib/api";

const listAssetsMock = vi.mocked(listAssets);
const listProjectAssetsMock = vi.mocked(listProjectAssets);
const listFoldersMock = vi.mocked(listFolders);
const listTagsMock = vi.mocked(listTags);

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
    supporting_file_count: 0,
  },
];

function projectGrid(projectId: string | null = "p1") {
  return render(<AssetGrid theme="dark" projectId={projectId} projectName="Hydra" />);
}

beforeEach(() => {
  listAssetsMock.mockReset();
  listProjectAssetsMock.mockReset();
  listFoldersMock.mockReset();
  listTagsMock.mockReset();

  listAssetsMock.mockResolvedValue({ items: [], hasMore: false });
  listProjectAssetsMock.mockResolvedValue({ items: assets, hasMore: false });
  listFoldersMock.mockResolvedValue([]);
  listTagsMock.mockResolvedValue([]);
});

afterEach(cleanup);

describe("AssetGrid in project mode", () => {
  it("lists project assets through listProjectAssets and never touches folders", async () => {
    projectGrid();

    await screen.findByText("Calibration cube");

    expect(listProjectAssetsMock).toHaveBeenCalledTimes(1);
    expect(listProjectAssetsMock.mock.calls[0][0]).toMatchObject({
      projectId: "p1",
      q: "",
      tags: [],
    });
    expect(listAssetsMock).not.toHaveBeenCalled();
    expect(listFoldersMock).not.toHaveBeenCalled();
    // Tag chips follow the open project now (Mf-o4vi), so they carry its id.
    expect(listTagsMock).toHaveBeenCalledWith({
      q: "",
      project_id: "p1",
      folder_id: undefined,
      not_in_project: undefined,
    });
  });

  it("hides every folder affordance", async () => {
    const { container } = projectGrid();
    await screen.findByText("Calibration cube");

    expect(container.querySelector("[data-folder-breadcrumbs]")).toBeNull();
    expect(container.querySelector("[data-folder-tiles]")).toBeNull();
    expect(screen.queryByRole("option", { name: "Folder" })).toBeNull();

    const sortSelect = screen
      .getAllByRole("combobox")
      .find(element =>
        Array.from((element as HTMLSelectElement).options).some(option => option.value === "size"),
      ) as HTMLSelectElement;
    expect(Array.from(sortSelect.options).map(option => option.value)).not.toContain("folder");
  });

  it("ignores file drags instead of offering an upload", async () => {
    const { container } = projectGrid();
    await screen.findByText("Calibration cube");

    const root = container.firstElementChild as Element;
    fireEvent.dragEnter(root, {
      dataTransfer: { types: ["Files"], items: [], files: [], dropEffect: "copy" },
    });

    expect(screen.queryByText(/Drop files or folders to upload/)).toBeNull();
  });

  it("hides the files-mode unassigned filter entirely", async () => {
    projectGrid();
    await screen.findByText("Calibration cube");

    // Membership already scopes a project listing, so the checkbox is files-only.
    expect(screen.queryByRole("checkbox", { name: "Not in any project" })).toBeNull();
    for (const [params] of listProjectAssetsMock.mock.calls) {
      expect(params).not.toHaveProperty("not_in_project");
    }
    expect(listAssetsMock).not.toHaveBeenCalled();
  });

  it("passes the submitted query to listProjectAssets", async () => {
    projectGrid();
    await screen.findByText("Calibration cube");

    fireEvent.change(screen.getByPlaceholderText("Search title, filename, notes..."), {
      target: { value: "cube" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(listProjectAssetsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ projectId: "p1", q: "cube" }),
      ),
    );
  });

  it("renders the empty-project message instead of files-mode empty copy", async () => {
    listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });

    projectGrid();

    expect(await screen.findByText("This project has no files yet.")).toBeTruthy();
  });

  it("does not claim an empty project while a search filter is active", async () => {
    listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });

    projectGrid();

    // A submitted query that matched nothing is an empty result, not an empty
    // project, so the empty-project copy must stay off.
    expect(await screen.findByText("This project has no files yet.")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Search title, filename, notes..."), {
      target: { value: "nothing-matches" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(screen.queryByText("This project has no files yet.")).toBeNull());
  });

  it("keeps using listAssets when no project is set", async () => {
    listAssetsMock.mockResolvedValue({ items: assets, hasMore: false });

    render(<AssetGrid theme="dark" />);

    await screen.findByText("Calibration cube");

    expect(listAssetsMock).toHaveBeenCalledTimes(1);
    expect(listProjectAssetsMock).not.toHaveBeenCalled();
    expect(listFoldersMock).toHaveBeenCalled();
  });
});
