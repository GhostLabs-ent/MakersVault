// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

// Only the network layer is mocked: the real `useUpload`/`ZipImportModal`
// prompt, the real target control and the real toast store run end to end.
vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  },
  createFolder: vi.fn(),
  importFromLink: vi.fn(),
  importToProject: vi.fn(),
  importZipFromLink: vi.fn(),
  inspectImportLink: vi.fn(),
  listImportZipEntries: vi.fn(),
  listProjects: vi.fn(),
  uploadAsset: vi.fn(),
}));

import type { Asset, ImportProjectResult, Project } from "../lib/api";
import {
  importFromLink,
  importToProject,
  inspectImportLink,
  listImportZipEntries,
  listProjects,
} from "../lib/api";
import { resetToasts } from "../lib/toast";
import Toaster from "./Toaster";
import UploadBar from "./UploadBar";

const importFromLinkMock = vi.mocked(importFromLink);
const importToProjectMock = vi.mocked(importToProject);
const inspectImportLinkMock = vi.mocked(inspectImportLink);
const listImportZipEntriesMock = vi.mocked(listImportZipEntries);
const listProjectsMock = vi.mocked(listProjects);

const LINK_URL = "https://www.printables.com/model/1-bundle";
const LINK_INPUT = "Paste model link (MakerWorld, Printables, Thingiverse...)";

function asset(name: string): Asset {
  return {
    id: `asset-${name}`,
    name,
    filename: name,
    mime: "model/stl",
    size: 1,
    tags: [],
    url: `/assets/${name}`,
    supporting_file_count: 0,
  };
}

function project(id: string, name: string): Project {
  return {
    id,
    name,
    description: null,
    creator: "Ada",
    source_url: LINK_URL,
    licence: "CC-BY",
    licence_url: null,
    origin: "imported",
    cover_asset_id: null,
    cover_thumb_url: null,
    asset_count: 1,
    metadata_json: {},
    total_size: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}

function projectResult(overrides: Partial<ImportProjectResult> = {}): ImportProjectResult {
  return {
    project: project("p9", "Hydra"),
    created: true,
    assets: [asset("model.stl")],
    added: ["model.stl"],
    skipped: [],
    failed: [],
    gated: false,
    message: "Imported Hydra.",
    ...overrides,
  };
}

function toaster() {
  return within(screen.getByTestId("toaster"));
}

function renderUploadBar() {
  const onUploaded = vi.fn();
  const onProjectImported = vi.fn();
  render(
    <>
      <UploadBar onUploaded={onUploaded} onProjectImported={onProjectImported} />
      <Toaster />
    </>,
  );
  return { onUploaded, onProjectImported };
}

function typeLink(url: string) {
  fireEvent.change(screen.getByPlaceholderText(LINK_INPUT), { target: { value: url } });
}

function mockPlainLink() {
  inspectImportLinkMock.mockResolvedValue({
    filename: "model.stl",
    mime: "model/stl",
    is_zip: false,
  });
}

function mockZipLink() {
  inspectImportLinkMock.mockResolvedValue({
    filename: "bundle.zip",
    mime: "application/zip",
    is_zip: true,
  });
  listImportZipEntriesMock.mockResolvedValue({
    filename: "bundle.zip",
    entries: [
      { path: "ok.stl", size: 1 },
      { path: "x.stl", size: 1 },
    ],
  });
}

/** Type a link, inspect it as a zip, then choose "Import and unzip" + "Import selected". */
async function importSelectedFromZip() {
  typeLink(LINK_URL);
  fireEvent.click(screen.getByRole("button", { name: "Import link" }));
  fireEvent.click(await screen.findByRole("button", { name: "Import and unzip" }));
  fireEvent.click(await screen.findByRole("button", { name: "Import selected" }));
}

function chooseNewProject() {
  fireEvent.click(screen.getByRole("radio", { name: "New project from the page" }));
}

async function chooseExistingProject() {
  fireEvent.click(screen.getByRole("radio", { name: "Existing project" }));
  await waitFor(() => expect(listProjectsMock).toHaveBeenCalled());
  await screen.findByRole("combobox", { name: "Project" });
}

describe("UploadBar project imports", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    resetToasts();
    vi.resetAllMocks();
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    consoleError.mockRestore();
  });

  it("keeps importing a loose asset when no project is chosen", async () => {
    mockPlainLink();
    importFromLinkMock.mockResolvedValue({ id: "asset-model" });
    const { onUploaded, onProjectImported } = renderUploadBar();

    typeLink(LINK_URL);
    fireEvent.click(screen.getByRole("button", { name: "Import link" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    expect(importFromLinkMock).toHaveBeenCalledTimes(1);
    expect(importToProjectMock).not.toHaveBeenCalled();
    expect(onProjectImported).not.toHaveBeenCalled();
  });

  it("imports into a project named from the page when 'New project' is chosen", async () => {
    mockPlainLink();
    importToProjectMock.mockResolvedValue(projectResult());
    const { onUploaded, onProjectImported } = renderUploadBar();

    chooseNewProject();
    typeLink(LINK_URL);
    fireEvent.click(screen.getByRole("button", { name: "Import link" }));

    await waitFor(() => expect(onProjectImported).toHaveBeenCalledWith("p9"));
    const payload = importToProjectMock.mock.calls[0][0];
    expect(payload.url).toBe(LINK_URL);
    // The server names a new project from the page, so no name/id is invented here.
    expect(payload).not.toHaveProperty("project_id");
    expect(payload).not.toHaveProperty("project_name");
    expect(importFromLinkMock).not.toHaveBeenCalled();
    expect(onUploaded).toHaveBeenCalledTimes(1);
    expect((screen.getByPlaceholderText(LINK_INPUT) as HTMLInputElement).value).toBe("");
  });

  it("addresses an existing project by id", async () => {
    mockPlainLink();
    listProjectsMock.mockResolvedValue([project("p1", "Hydra"), project("p2", "Kraken")]);
    importToProjectMock.mockResolvedValue(projectResult());
    const { onProjectImported } = renderUploadBar();

    await chooseExistingProject();
    fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
      target: { value: "p2" },
    });
    typeLink(LINK_URL);
    fireEvent.click(screen.getByRole("button", { name: "Import link" }));

    await waitFor(() => expect(onProjectImported).toHaveBeenCalledWith("p9"));
    const payload = importToProjectMock.mock.calls[0][0];
    expect(payload.project_id).toBe("p2");
    expect(payload).not.toHaveProperty("project_name");
    expect(importFromLinkMock).not.toHaveBeenCalled();
  });

  it("tells the user why a gated model brought no files, without claiming any", async () => {
    mockPlainLink();
    const message =
      "The files for this model are behind an account or a purchase, so none were downloaded.";
    importToProjectMock.mockResolvedValue(
      projectResult({ assets: [], added: [], gated: true, message }),
    );
    const { onProjectImported } = renderUploadBar();

    chooseNewProject();
    typeLink(LINK_URL);
    fireEvent.click(screen.getByRole("button", { name: "Import link" }));

    await waitFor(() => expect(onProjectImported).toHaveBeenCalledWith("p9"));
    // The server's sentence is shown verbatim, as an info toast: nothing failed.
    expect(toaster().getByRole("status").textContent).toContain(message);
    expect(toaster().queryByRole("alert")).toBeNull();
    expect(importToProjectMock).toHaveBeenCalledTimes(1);
  });

  it("sends the selected zip entries to the project and retries only the failed ones", async () => {
    mockZipLink();
    listProjectsMock.mockResolvedValue([project("p1", "Hydra")]);
    importToProjectMock
      .mockResolvedValueOnce(
        projectResult({ assets: [asset("ok.stl")], added: ["ok.stl"], failed: ["x.stl"] }),
      )
      .mockResolvedValueOnce(projectResult({ assets: [asset("x.stl")], added: ["x.stl"] }));
    const { onUploaded, onProjectImported } = renderUploadBar();

    await chooseExistingProject();
    await importSelectedFromZip();

    await waitFor(() => expect(toaster().getAllByRole("alert")).toHaveLength(1));
    expect(importToProjectMock.mock.calls[0][0].entries).toEqual(["ok.stl", "x.stl"]);
    expect(importToProjectMock.mock.calls[0][0].project_id).toBe("p1");
    expect(onProjectImported).toHaveBeenCalledWith("p9");
    expect(importFromLinkMock).not.toHaveBeenCalled();

    const alert = toaster().getByRole("alert");
    expect(alert.textContent).toContain("Failed to import 1 file");
    expect(within(alert).getByText("x.stl")).toBeTruthy();

    fireEvent.click(within(alert).getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(importToProjectMock).toHaveBeenCalledTimes(2));
    expect(importToProjectMock.mock.calls[1][0].entries).toEqual(["x.stl"]);
    expect(importToProjectMock.mock.calls[1][0].project_id).toBe("p1");
    expect(importToProjectMock.mock.calls[1][0].url).toBe(LINK_URL);
    // The retry refreshes the project and lands the user on it again.
    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(2));
    expect(onProjectImported).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.queryByTestId("toaster")).toBeNull());
  });

  it("imports a whole zip as one asset when 'Import as zip' is chosen", async () => {
    mockZipLink();
    importToProjectMock.mockResolvedValue(projectResult());
    const { onProjectImported } = renderUploadBar();

    chooseNewProject();
    typeLink(LINK_URL);
    fireEvent.click(screen.getByRole("button", { name: "Import link" }));
    fireEvent.click(await screen.findByRole("button", { name: "Import as zip" }));

    await waitFor(() => expect(onProjectImported).toHaveBeenCalledWith("p9"));
    expect(importToProjectMock).toHaveBeenCalledTimes(1);
    expect(importToProjectMock.mock.calls[0][0]).not.toHaveProperty("entries");
    expect(importFromLinkMock).not.toHaveBeenCalled();
  });
});
