// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps } from "react";

import type { Asset, Project } from "../lib/api";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  addProjectAssets: vi.fn(),
  deleteProject: vi.fn(),
  downloadAsset: vi.fn(),
  downloadZip: vi.fn(),
  fileUrl: vi.fn((rel: string) => rel),
  listAssets: vi.fn(),
  listProjectAssets: vi.fn(),
  removeProjectAssets: vi.fn(),
  renderFileUrl: vi.fn((src: string | undefined) => src),
  stableFileUrl: vi.fn((rel: string) => `/api${rel}`),
  updateProject: vi.fn(),
  uploadAsset: vi.fn(),
  uploadAssetFile: vi.fn(),
}));

vi.mock("../lib/download", () => ({
  saveResponseToDisk: vi.fn(),
}));

import ProjectLanding from "./ProjectLanding";
import {
  addProjectAssets,
  deleteProject,
  downloadAsset,
  downloadZip,
  listAssets,
  listProjectAssets,
  removeProjectAssets,
  updateProject,
  uploadAsset,
  uploadAssetFile,
} from "../lib/api";
import { saveResponseToDisk } from "../lib/download";
import { getToasts, resetToasts } from "../lib/toast";

const addProjectAssetsMock = vi.mocked(addProjectAssets);
const deleteProjectMock = vi.mocked(deleteProject);
const downloadAssetMock = vi.mocked(downloadAsset);
const downloadZipMock = vi.mocked(downloadZip);
const listAssetsMock = vi.mocked(listAssets);
const listProjectAssetsMock = vi.mocked(listProjectAssets);
const removeProjectAssetsMock = vi.mocked(removeProjectAssets);
const updateProjectMock = vi.mocked(updateProject);
const uploadAssetMock = vi.mocked(uploadAsset);
const uploadAssetFileMock = vi.mocked(uploadAssetFile);
const saveResponseToDiskMock = vi.mocked(saveResponseToDisk);

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "Hydra",
    description: "A **bold** multi-part print",
    creator: "Ada",
    source_url: null,
    licence: null,
    licence_url: null,
    origin: "local",
    cover_asset_id: null,
    cover_thumb_url: null,
    asset_count: 3,
    metadata_json: {},
    total_size: 5120,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

function makeAsset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: "a1",
    name: "Body",
    filename: "body.stl",
    mime: "model/stl",
    size: 2048,
    tags: [],
    url: "/assets/a1/file",
    thumb_url: null,
    supporting_file_count: 0,
    ...overrides,
  };
}

const members: Asset[] = [
  makeAsset({
    id: "a1",
    name: "Body",
    filename: "body.stl",
    mime: "model/stl",
    size: 2048,
    tags: ["pla"],
    url: "/assets/a1/file",
    thumb_url: "/assets/a1/thumb",
  }),
  makeAsset({
    id: "a2",
    name: "Photo one",
    filename: "photo-one.jpg",
    mime: "image/jpeg",
    size: 1024,
    tags: ["photo"],
    url: "/assets/a2/file",
    thumb_url: "/assets/a2/thumb",
  }),
  makeAsset({
    id: "a3",
    name: "Photo two",
    filename: "photo-two.png",
    mime: "image/png",
    size: 2048,
    tags: ["pla"],
    url: "/assets/a3/file",
    thumb_url: "/assets/a3/thumb",
  }),
];

type Props = ComponentProps<typeof ProjectLanding>;

function landingProps(overrides: Partial<Props> = {}): Props {
  return {
    canContribute: true,
    canDelete: true,
    project: makeProject(),
    assetsVersion: 0,
    onProjectUpdated: vi.fn(),
    onProjectDeleted: vi.fn(),
    onAssetsChanged: vi.fn(),
    theme: "dark",
    ...overrides,
  };
}

function renderLanding(overrides: Partial<Props> = {}) {
  return render(<ProjectLanding {...landingProps(overrides)} />);
}

/** The plain object jsdom hands a drag handler for a file drag. */
function fileDataTransfer(files: File[]): {
  types: string[];
  files: File[];
  items: unknown[];
} {
  return { types: ["Files"], files, items: [] };
}

/** Every API call a viewer must never reach, whatever is on screen. */
function expectNoWriteCalls(): void {
  expect(uploadAssetMock).not.toHaveBeenCalled();
  expect(uploadAssetFileMock).not.toHaveBeenCalled();
  expect(updateProjectMock).not.toHaveBeenCalled();
  expect(deleteProjectMock).not.toHaveBeenCalled();
  expect(removeProjectAssetsMock).not.toHaveBeenCalled();
  expect(addProjectAssetsMock).not.toHaveBeenCalled();
}

beforeEach(() => {
  vi.clearAllMocks();
  resetToasts();
  listProjectAssetsMock.mockResolvedValue({ items: members, hasMore: false });
  listAssetsMock.mockResolvedValue({ items: [], hasMore: false });
  downloadZipMock.mockResolvedValue(new Response("zip-bytes"));
  downloadAssetMock.mockResolvedValue(new Response("file-bytes"));
  deleteProjectMock.mockResolvedValue(undefined);
  updateProjectMock.mockImplementation(async (_id, patch) =>
    makeProject({ ...(patch as Partial<Project>) }),
  );
  removeProjectAssetsMock.mockResolvedValue({ removed: [], skipped: [], failed: [] });
  addProjectAssetsMock.mockResolvedValue({ added: [], skipped: [], failed: [] });
  uploadAssetMock.mockImplementation(async (uploadedFile: File) =>
    makeAsset({ id: "new1", name: "Widget", filename: uploadedFile.name, size: uploadedFile.size }),
  );
  uploadAssetFileMock.mockImplementation(async id => makeAsset({ id }));
});

afterEach(cleanup);

describe("ProjectLanding hero", () => {
  it("renders title, creator, licence chip, source badge and the stat row", async () => {
    renderLanding({
      project: makeProject({
        source_url: "https://www.printables.com/model/123-hydra",
        licence: "CC-BY-SA",
        licence_url: "https://creativecommons.org/licenses/by-sa/4.0/",
      }),
    });
    await screen.findByText("Body");

    expect(screen.getByRole("heading", { level: 1, name: "Hydra" })).toBeTruthy();
    expect(screen.getByText("By Ada")).toBeTruthy();

    const source = screen.getByRole("link", { name: "View original on Printables" });
    expect(source.getAttribute("href")).toBe("https://www.printables.com/model/123-hydra");
    expect(source.getAttribute("target")).toBe("_blank");
    expect(source.getAttribute("rel")).toContain("noopener");

    // Hero chip plus the details-panel row both link the licence.
    const licenceLinks = screen.getAllByRole("link", { name: "CC-BY-SA" });
    expect(licenceLinks.length).toBe(2);
    expect(licenceLinks[0].getAttribute("href")).toBe(
      "https://creativecommons.org/licenses/by-sa/4.0/",
    );

    expect(screen.getByText("3 files")).toBeTruthy();
    expect(screen.getByText("5.0 KB")).toBeTruthy();
    expect(screen.getAllByText(/2026/).length).toBeGreaterThan(0);
  });

  it("falls back to a generic source badge for unknown hosts", async () => {
    renderLanding({
      project: makeProject({ source_url: "https://cults3d.com/en/3d-model/hydra" }),
    });
    await screen.findByText("Body");
    expect(screen.getByRole("link", { name: "View original" })).toBeTruthy();
  });

  it("shows only image members in the gallery, cover first", async () => {
    renderLanding({ project: makeProject({ cover_asset_id: "a3" }) });
    await screen.findByText("Body");

    const gallery = screen.getByTestId("project-gallery");
    const imgs = within(gallery).getAllByRole("img");
    expect(imgs.map(img => img.getAttribute("alt"))).toEqual(["Photo two", "Photo one"]);
    expect(within(gallery).getByText("Cover")).toBeTruthy();
  });

  it("patches exactly cover_asset_id when choosing a new cover", async () => {
    const onProjectUpdated = vi.fn();
    renderLanding({ onProjectUpdated });
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Use Photo one as cover" }));

    await waitFor(() => expect(updateProjectMock).toHaveBeenCalledTimes(1));
    expect(updateProjectMock).toHaveBeenCalledWith("p1", { cover_asset_id: "a2" });
    await waitFor(() => expect(onProjectUpdated).toHaveBeenCalledTimes(1));
    expect(onProjectUpdated.mock.calls[0][0]).toMatchObject({ cover_asset_id: "a2" });
  });

  it("prefers cover_thumb_url for the hero cover", async () => {
    renderLanding({ project: makeProject({ cover_thumb_url: "/projects/p1/cover-thumb" }) });
    await screen.findByText("Body");

    const img = screen.getByRole("img", { name: "Hydra cover" });
    expect(img.getAttribute("src")).toBe("/projects/p1/cover-thumb");
  });

  it("falls back to the first image member's thumb for the hero cover", async () => {
    renderLanding();
    await screen.findByText("Body");

    const img = screen.getByRole("img", { name: "Hydra cover" });
    expect(img.getAttribute("src")).toBe("/assets/a2/thumb");
  });

  it("renders a placeholder when nothing can cover the project", async () => {
    listProjectAssetsMock.mockResolvedValue({
      items: [
        makeAsset({
          id: "a9",
          name: "Only model",
          filename: "only.stl",
          mime: "model/stl",
          thumb_url: null,
        }),
      ],
      hasMore: false,
    });
    renderLanding({ project: makeProject({ asset_count: 1 }) });
    await screen.findByText("Only model");

    expect(screen.getByRole("img", { name: "No cover image" })).toBeTruthy();
    expect(screen.queryByTestId("project-gallery")).toBeNull();
  });

  it("unions member tags, caps the chips at 8 and shows +N", async () => {
    const tagged = [
      makeAsset({
        id: "t1",
        name: "T1",
        filename: "t1.stl",
        tags: ["alpha", "bravo", "charlie", "delta", "echo"],
      }),
      makeAsset({
        id: "t2",
        name: "T2",
        filename: "t2.stl",
        tags: ["foxtrot", "golf", "hotel", "india", "juliet", "alpha"],
      }),
    ];
    listProjectAssetsMock.mockResolvedValue({ items: tagged, hasMore: false });
    renderLanding();
    await screen.findByText("T1");

    expect(screen.getByText("alpha")).toBeTruthy();
    expect(screen.getByText("hotel")).toBeTruthy();
    expect(screen.getByText("+2")).toBeTruthy();
    expect(screen.queryByText("india")).toBeNull();
    expect(screen.queryByText("juliet")).toBeNull();
  });
});

describe("ProjectLanding actions", () => {
  it("downloads everything with exactly { project_id } and saves the zip", async () => {
    renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: /Download all as ZIP/ }));

    await waitFor(() => expect(downloadZipMock).toHaveBeenCalledTimes(1));
    expect(downloadZipMock).toHaveBeenCalledWith({ project_id: "p1" });
    expect(Object.keys(downloadZipMock.mock.calls[0][0])).toEqual(["project_id"]);
    await waitFor(() => expect(saveResponseToDiskMock).toHaveBeenCalledTimes(1));
    expect(saveResponseToDiskMock.mock.calls[0][1]).toBe("Hydra.zip");
  });

  it("disables download-all with an explanation when the project has no files", async () => {
    listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });
    renderLanding({ project: makeProject({ asset_count: 0 }) });
    await screen.findByText("This project has no files yet.");

    const button = screen.getByRole("button", {
      name: /Download all as ZIP/,
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("title")).toBeTruthy();
  });

  it("shows the primary-file slicer action only when the slicer is enabled", async () => {
    const first = renderLanding({ slicerSettings: { enabled: false, selected: "orca" } });
    await screen.findByText("Body");
    expect(screen.queryByRole("button", { name: "Open in OrcaSlicer" })).toBeNull();
    first.unmount();

    renderLanding({ slicerSettings: { enabled: true, selected: "orca" } });
    await screen.findByText("Body");
    expect(screen.getByRole("button", { name: "Open in OrcaSlicer" })).toBeTruthy();
  });

  it("deletes the project after an honest confirm dialog", async () => {
    const onProjectDeleted = vi.fn();
    renderLanding({ onProjectDeleted });
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete Hydra?" });
    expect(dialog.textContent).toMatch(/files themselves stay in your library/i);

    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteProjectMock).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(onProjectDeleted).toHaveBeenCalledWith("p1"));
  });
});

describe("ProjectLanding files", () => {
  it("lists exactly the mocked members with name, size and type", async () => {
    renderLanding();
    await screen.findByText("Body");

    const files = screen.getByRole("region", { name: "Files" });
    const rows = within(files).getAllByRole("listitem");
    expect(rows.length).toBe(3);
    expect(within(files).getByText("Body")).toBeTruthy();
    expect(within(files).getByText("Photo one")).toBeTruthy();
    expect(within(files).getByText("Photo two")).toBeTruthy();
    expect(within(files).getByText("2.0 KB · STL")).toBeTruthy();
    expect(within(files).getByText("1.0 KB · JPG")).toBeTruthy();
    expect(within(files).getByText("2.0 KB · PNG")).toBeTruthy();
  });

  it("appends the uploader to the member meta line and leaves it out when unset", async () => {
    listProjectAssetsMock.mockResolvedValue({
      items: [
        { ...members[0], created_by: "Ada", created_via: "upload" },
        { ...members[1], created_by: null, created_via: "upload" },
        { ...members[2], created_by: "Ada", created_via: "zip-import", supporting_file_count: 2 },
      ],
      hasMore: false,
    });
    renderLanding();
    await screen.findByText("Body");

    const files = screen.getByRole("region", { name: "Files" });
    expect(within(files).getByText("2.0 KB · STL · Added by Ada")).toBeTruthy();
    // No uploader means no dangling separator, byte-identical to the old line.
    expect(within(files).getByText("1.0 KB · JPG")).toBeTruthy();
    // The supporting-file suffix keeps its place: bytes · type · supporting · added by.
    expect(
      within(files).getByText("2.0 KB · PNG · 2 supporting files · Added by Ada"),
    ).toBeTruthy();
  });

  it("removes a file from the project after confirming, then refreshes", async () => {
    const onAssetsChanged = vi.fn();
    removeProjectAssetsMock.mockResolvedValue({ removed: ["a2"], skipped: [], failed: [] });
    renderLanding({ onAssetsChanged });
    await screen.findByText("Photo one");

    fireEvent.click(screen.getByRole("button", { name: "Remove Photo one from project" }));
    const dialog = screen.getByRole("dialog", { name: "Remove Photo one?" });
    expect(dialog.textContent).toMatch(/stays in your library/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(removeProjectAssetsMock).toHaveBeenCalledWith("p1", ["a2"]));
    await waitFor(() => expect(screen.queryByText("Photo one")).toBeNull());
    expect(onAssetsChanged).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Body")).toBeTruthy();
  });

  it("downloads a single file through downloadAsset", async () => {
    renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Download Body" }));

    await waitFor(() => expect(downloadAssetMock).toHaveBeenCalledTimes(1));
    expect(downloadAssetMock.mock.calls[0][0]).toMatchObject({ id: "a1" });
    await waitFor(() => expect(saveResponseToDiskMock).toHaveBeenCalledTimes(1));
    expect(saveResponseToDiskMock.mock.calls[0][1]).toBe("body.stl");
  });

  it("appends the next page and shows progress while more remain", async () => {
    listProjectAssetsMock
      .mockReset()
      .mockResolvedValueOnce({ items: members.slice(0, 2), hasMore: true, nextOffset: 2 })
      .mockResolvedValueOnce({ items: members.slice(2), hasMore: false });
    renderLanding();
    await screen.findByText("Photo one");

    expect(screen.queryByText("Photo two")).toBeNull();
    expect(screen.getByText("Showing 2 of 3")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByText("Photo two");

    expect(listProjectAssetsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ projectId: "p1", offset: 2 }),
    );
    expect(screen.queryByText(/Showing \d+ of \d+/)).toBeNull();
  });

  it("shows the empty state with an add-files button", async () => {
    listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });
    renderLanding({ project: makeProject({ asset_count: 0 }) });
    await screen.findByText("This project has no files yet.");

    const addButtons = screen.getAllByRole("button", { name: "Add files" });
    expect(addButtons.length).toBe(2); // actions row + empty state
    fireEvent.click(addButtons[addButtons.length - 1]);
    await screen.findByRole("dialog", { name: /Add files to Hydra/ });
  });

  it("uploads a supporting file and refreshes the list", async () => {
    renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Add supporting file to Body" }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(uploadAssetFileMock).toHaveBeenCalledWith("a1", file));
    await waitFor(() => expect(listProjectAssetsMock).toHaveBeenCalledTimes(2));
    expect(getToasts().some(toast => /notes\.txt/.test(toast.message))).toBe(true);
  });
});

describe("ProjectLanding viewer role", () => {
  it("hides every write control and keeps the read surfaces", async () => {
    renderLanding({ canContribute: false, canDelete: false, project: makeProject({ cover_asset_id: "a3" }) });
    await screen.findByText("Body");

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add files" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Use .* as cover$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add a description" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Attach files" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Attach folder" })).toBeNull();
    expect(screen.queryAllByRole("button", { name: /^Add supporting file to / })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /^Remove .* from project$/ })).toHaveLength(0);

    // Reads stay: the ZIP export, the member downloads and the rendered page.
    expect(screen.getByRole("button", { name: /Download all as ZIP/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download Body" })).toBeTruthy();
    expect(screen.getByText("bold").tagName).toBe("STRONG");

    const details = screen.getByRole("region", { name: "Details" });
    expect(within(details).getByText("Own creation")).toBeTruthy();

    const files = screen.getByRole("region", { name: "Files" });
    expect(within(files).getByText("Body")).toBeTruthy();

    // The gallery keeps its images and the cover badge.
    const gallery = screen.getByTestId("project-gallery");
    expect(within(gallery).getAllByRole("img").length).toBe(2);
    expect(within(gallery).getByText("Cover")).toBeTruthy();
  });

  it("keeps the empty state readable without offering add or attach controls", async () => {
    listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });
    renderLanding({ canContribute: false, canDelete: false, project: makeProject({ asset_count: 0 }) });
    await screen.findByText("This project has no files yet.");

    expect(screen.queryByRole("button", { name: "Add files" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Attach files" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Attach folder" })).toBeNull();
  });

  it("shows the no-description placeholder without the edit affordance", async () => {
    renderLanding({ canContribute: false, canDelete: false, project: makeProject({ description: null }) });
    await screen.findByText("Body");

    expect(screen.getByText("No description yet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add a description" })).toBeNull();
  });

  it("drops the attach instruction from the gated-import note", async () => {
    renderLanding({
      canContribute: false,
      canDelete: false,
      project: makeProject({ origin: "imported", metadata_json: { _files: "user-supplied" } }),
    });
    await screen.findByText("Body");

    const details = screen.getByRole("region", { name: "Details" });
    const note = within(details).getByText(/Imported details only/);
    expect(note.textContent).toContain("gated behind an account or a purchase");
    expect(note.textContent).not.toContain("Attach files");
  });

  it("is not a drop target, so a dropped file attaches nothing", async () => {
    renderLanding({ canContribute: false, canDelete: false });
    await screen.findByText("Body");

    const section = screen.getByRole("heading", { name: "Files" }).closest("section");
    if (!section) throw new Error("missing Files section");
    const dataTransfer = fileDataTransfer([
      new File(["cube"], "dropped.stl", { type: "model/stl" }),
    ]);

    // `fireEvent` returns false when the handler cancelled the event; a viewer's
    // handlers must leave the browser's own drop handling alone.
    expect(fireEvent.dragEnter(section, { dataTransfer })).toBe(true);
    expect(screen.queryByText(/Drop files or a folder to attach/)).toBeNull();
    expect(fireEvent.drop(section, { dataTransfer })).toBe(true);
    await waitFor(() => expectNoWriteCalls());

    expect(screen.queryByText(/Drop files or a folder to attach/)).toBeNull();
  });

  it("reaches no write API by clicking any visible control", async () => {
    renderLanding({ canContribute: false, canDelete: false });
    await screen.findByText("Body");

    const controls = screen.getAllByRole("button");
    expect(controls.length).toBeGreaterThan(0);
    for (const control of controls) {
      fireEvent.click(control);
    }
    await waitFor(() => expectNoWriteCalls());

    // Nothing in reach of a click can open a write-shaped dialog either.
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("ProjectLanding editor role", () => {
  it("keeps every write control", async () => {
    renderLanding({ project: makeProject({ cover_asset_id: "a3" }) });
    await screen.findByText("Body");

    expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add files" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Use Photo one as cover" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Attach files" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Attach folder" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add supporting file to Body" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Body from project" })).toBeTruthy();
  });

  it("keeps the empty-state write controls", async () => {
    listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });
    renderLanding({ project: makeProject({ description: null, asset_count: 0 }) });
    await screen.findByText("This project has no files yet.");

    expect(screen.getByRole("button", { name: "Add a description" })).toBeTruthy();
    // The action row and the empty state both offer the library picker.
    expect(screen.getAllByRole("button", { name: "Add files" }).length).toBe(2);
    expect(screen.getByRole("button", { name: "Attach files" })).toBeTruthy();
  });

  it("closes the editor when the role is demoted mid-edit", async () => {
    const view = renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("textbox", { name: "Project name" })).toBeTruthy();

    view.rerender(<ProjectLanding {...landingProps({ canContribute: false, canDelete: false })} />);

    expect(screen.queryByRole("textbox", { name: "Project name" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Licence" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Hydra" })).toBeTruthy();
  });
});

describe("ProjectLanding description", () => {
  it("renders the markdown description", async () => {
    renderLanding();
    await screen.findByText("Body");

    const strong = screen.getByText("bold");
    expect(strong.tagName).toBe("STRONG");
  });

  it("offers an editable placeholder when there is no description", async () => {
    renderLanding({ project: makeProject({ description: null }) });
    await screen.findByText("Body");

    expect(screen.getByText("No description yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add a description" }));

    const textarea = screen.getByRole("textbox", { name: "Description" });
    expect(document.activeElement).toBe(textarea);
  });
});

describe("ProjectLanding details", () => {
  it("renders the print-settings table for known and unknown metadata keys", async () => {
    renderLanding({
      project: makeProject({
        metadata_json: {
          filament: "PLA",
          layer_height: 0.2,
          infill: "15%",
          supports: true,
          perimeters: 3,
          nozzle_diameter: 0.4,
          temps: [200, 60],
        },
      }),
    });
    await screen.findByText("Body");

    const details = screen.getByRole("region", { name: "Details" });
    expect(within(details).getByText("Print settings")).toBeTruthy();
    expect(within(details).getByText("Filament")).toBeTruthy();
    expect(within(details).getByText("PLA")).toBeTruthy();
    expect(within(details).getByText("Layer height (mm)")).toBeTruthy();
    expect(within(details).getByText("0.2")).toBeTruthy();
    expect(within(details).getByText("Infill")).toBeTruthy();
    expect(within(details).getByText("Yes")).toBeTruthy();
    expect(within(details).getByText("Perimeters")).toBeTruthy();
    // Unknown keys are not dropped: generic label + stringified values.
    expect(within(details).getByText("nozzle diameter")).toBeTruthy();
    expect(within(details).getByText("0.4")).toBeTruthy();
    expect(within(details).getByText("[200,60]")).toBeTruthy();
  });

  it("omits the print-settings table when metadata_json is empty", async () => {
    renderLanding();
    await screen.findByText("Body");

    expect(screen.queryByText("Print settings")).toBeNull();
  });

  it("describes an in-app project as an own creation without source rows", async () => {
    renderLanding();
    await screen.findByText("Body");

    const details = screen.getByRole("region", { name: "Details" });
    expect(within(details).getByText("Own creation")).toBeTruthy();
    expect(within(details).queryByText("Source")).toBeNull();
    // The licence row is always there; a missing licence is stated explicitly
    // instead of the row disappearing.
    expect(within(details).getByText("Licence")).toBeTruthy();
    expect(within(details).getByText("Licence unknown")).toBeTruthy();
  });

  it("marks a missing licence in the hero and the details panel", async () => {
    renderLanding();
    await screen.findByText("Body");

    const unknowns = Array.from(document.querySelectorAll("[data-licence-unknown]"));
    expect(unknowns.map(element => element.textContent)).toEqual([
      "Licence unknown",
      "Licence unknown",
    ]);
    // Neither is dressed up as a real licence term.
    expect(document.querySelectorAll("[data-licence-chip]").length).toBe(0);
  });

  it("treats a whitespace-only licence as missing", async () => {
    renderLanding({ project: makeProject({ licence: "   " }) });
    await screen.findByText("Body");

    const details = screen.getByRole("region", { name: "Details" });
    expect(within(details).getByText("Licence unknown")).toBeTruthy();
    expect(screen.queryAllByText("Licence unknown").length).toBe(2);
    expect(document.querySelectorAll("[data-licence-chip]").length).toBe(0);
  });

  it("marks a recorded licence as a chip linked to its licence URL", async () => {
    renderLanding({
      project: makeProject({
        licence: "CC-BY-SA",
        licence_url: "https://creativecommons.org/licenses/by-sa/4.0/",
      }),
    });
    await screen.findByText("Body");

    // Hero chip plus the details-panel row.
    const chips = Array.from(document.querySelectorAll("[data-licence-chip]"));
    expect(chips.map(element => element.textContent)).toEqual(["CC-BY-SA", "CC-BY-SA"]);
    expect(document.querySelectorAll("[data-licence-unknown]").length).toBe(0);
    for (const chip of chips) {
      expect(chip.getAttribute("href")).toBe(
        "https://creativecommons.org/licenses/by-sa/4.0/",
      );
    }
  });

  it("describes an imported project with source, licence and creator", async () => {
    renderLanding({
      project: makeProject({
        origin: "imported",
        creator: "print_fan_99",
        source_url: "https://www.thingiverse.com/thing:456",
        licence: "CC0",
        licence_url: null,
      }),
    });
    await screen.findByText("Body");

    const details = screen.getByRole("region", { name: "Details" });
    expect(within(details).getByText("Imported")).toBeTruthy();
    expect(within(details).getByText("CC0")).toBeTruthy();
    const source = within(details).getByRole("link", {
      name: "https://www.thingiverse.com/thing:456",
    });
    expect(source.getAttribute("target")).toBe("_blank");

    expect(screen.getByRole("link", { name: "View original on Thingiverse" })).toBeTruthy();
    expect(screen.getByText("By print_fan_99")).toBeTruthy();
  });

  it("says a gated import brought details only, keeping the marker out of print settings", async () => {
    renderLanding({
      project: makeProject({
        origin: "imported",
        metadata_json: { filament: "PLA", _files: "user-supplied" },
      }),
    });
    await screen.findByText("Body");

    const details = screen.getByRole("region", { name: "Details" });
    const note = within(details).getByText(/Imported details only/);
    expect(note.textContent).toContain("gated behind an account or a purchase");
    // Points at the affordance that actually attaches the user's own files.
    expect(note.textContent).toContain("Attach files");

    // Real settings still render...
    expect(within(details).getByText("Filament")).toBeTruthy();
    expect(within(details).getByText("PLA")).toBeTruthy();
    // ...but the reserved import marker is bookkeeping, not a print setting.
    expect(within(details).queryByRole("rowheader", { name: "files" })).toBeNull();
    expect(within(details).queryByText("user-supplied")).toBeNull();
  });

  it("shows no imported-details note for a project whose files came with it", async () => {
    renderLanding({ project: makeProject({ metadata_json: { filament: "PLA" } }) });
    await screen.findByText("Body");

    expect(screen.queryByText(/Imported details only/)).toBeNull();
  });
});

describe("ProjectLanding inline editing", () => {
  it("saves only the changed fields and reports the update", async () => {
    const onProjectUpdated = vi.fn();
    renderLanding({ onProjectUpdated });
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Licence" }), {
      target: { value: "CC-BY" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateProjectMock).toHaveBeenCalledTimes(1));
    expect(updateProjectMock).toHaveBeenCalledWith("p1", { licence: "CC-BY" });
    await waitFor(() => expect(onProjectUpdated).toHaveBeenCalledTimes(1));
    expect(getToasts().some(toast => toast.message === "Project updated.")).toBe(true);
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Licence" })).toBeNull(),
    );
  });

  it("asks before discarding changes on cancel", async () => {
    renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Project name" }), {
      target: { value: "Hydra X" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    const dialog = screen.getByRole("dialog", { name: "Discard changes?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Discard" }));

    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Project name" })).toBeNull(),
    );
    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1, name: "Hydra" })).toBeTruthy();
  });

  it("keeps the project open when Escape is pressed while editing", async () => {
    const seenOnDocument: boolean[] = [];
    document.addEventListener("keydown", event => seenOnDocument.push(event.defaultPrevented));
    renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const nameInput = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(nameInput, { target: { value: "Hydra Y" } });
    fireEvent.keyDown(nameInput, { key: "Escape" });

    // ProjectView closes on Escape unless the event was already handled.
    expect(seenOnDocument).toContain(true);
    // Dirty edits are guarded, not silently dropped.
    expect(screen.getByRole("dialog", { name: "Discard changes?" })).toBeTruthy();
  });

  it("blocks saving an empty project name", async () => {
    renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Project name" }), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/name/i);
  });
});

describe("ProjectLanding add-files dialog", () => {
  const libraryAssets: Asset[] = [
    makeAsset({ id: "lib1", name: "Lib one", filename: "lib-one.stl", url: "/assets/lib1/file" }),
    makeAsset({ id: "lib2", name: "Lib two", filename: "lib-two.stl", url: "/assets/lib2/file" }),
    makeAsset({ id: "a1", name: "Body", filename: "body.stl", url: "/assets/a1/file" }),
  ];

  it("adds the selected assets, toasts the summary and bumps assetsVersion", async () => {
    const onAssetsChanged = vi.fn();
    listAssetsMock.mockResolvedValue({ items: libraryAssets, hasMore: false });
    addProjectAssetsMock.mockResolvedValue({ added: ["lib1", "lib2"], skipped: [], failed: [] });
    renderLanding({ onAssetsChanged });
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Add files" }));
    const dialog = await screen.findByRole("dialog", { name: /Add files to Hydra/ });
    expect(dialog.getAttribute("aria-modal")).toBe("true");

    await within(dialog).findByRole("checkbox", { name: "Select Lib one" });
    const memberRow = within(dialog).getByRole("checkbox", {
      name: "Body (already in project)",
    }) as HTMLInputElement;
    expect(memberRow.disabled).toBe(true);
    expect(within(dialog).getByText("In project")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Select Lib one" }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Select Lib two" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Add 2 files" }));

    await waitFor(() =>
      expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["lib1", "lib2"]),
    );
    await waitFor(() => expect(onAssetsChanged).toHaveBeenCalledTimes(1));
    expect(getToasts().some(toast => /2 added/.test(toast.message))).toBe(true);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /Add files to Hydra/ })).toBeNull(),
    );
  });

  it("closes on Escape without adding anything", async () => {
    listAssetsMock.mockResolvedValue({ items: libraryAssets, hasMore: false });
    renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Add files" }));
    const dialog = await screen.findByRole("dialog", { name: /Add files to Hydra/ });
    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /Add files to Hydra/ })).toBeNull(),
    );
    expect(addProjectAssetsMock).not.toHaveBeenCalled();
  });
});

describe("ProjectLanding unsaved changes", () => {
  it("guards a dirty description behind the discard confirmation", async () => {
    renderLanding();
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const description = screen.getByRole("textbox", { name: "Description" });
    fireEvent.change(description, { target: { value: "A revised description" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    const dialog = screen.getByRole("dialog", { name: "Discard changes?" });
    expect(dialog.textContent).toMatch(/unsaved changes/i);
    // The editor survives until the discard is confirmed.
    expect(screen.getByRole("textbox", { name: "Description" })).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Discard" }));

    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Description" })).toBeNull(),
    );
    // The original rendered description is back and nothing was saved.
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText(/multi-part print/)).toBeTruthy();
    expect(updateProjectMock).not.toHaveBeenCalled();
  });

  it("clears the dirty flag after saving so a fresh cancel does not prompt", async () => {
    const onProjectUpdated = vi.fn();
    const view = renderLanding({ onProjectUpdated });
    await screen.findByText("Body");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "Saved description" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateProjectMock).toHaveBeenCalledTimes(1));
    expect(updateProjectMock).toHaveBeenCalledWith("p1", { description: "Saved description" });
    await waitFor(() => expect(onProjectUpdated).toHaveBeenCalledTimes(1));

    // The parent splices the saved row back in, as App does.
    const updated = onProjectUpdated.mock.calls[0][0] as Project;
    view.rerender(<ProjectLanding {...landingProps({ onProjectUpdated, project: updated })} />);

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Description" })).toBeNull();
    expect(updateProjectMock).toHaveBeenCalledTimes(1);
  });
});

describe("ProjectLanding attach-own-files", () => {
  it("renders the attach controls and a folder input that carries webkitdirectory", async () => {
    renderLanding();
    await screen.findByText("Body");

    expect(screen.getByRole("button", { name: "Attach files" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Attach folder" })).toBeTruthy();
    const folderInput = screen.getByTestId("attach-folder-input");
    expect(folderInput.hasAttribute("webkitdirectory")).toBe(true);
  });

  it("uploads a picked file to the root storage and adds its id to the project", async () => {
    const onAssetsChanged = vi.fn();
    addProjectAssetsMock.mockImplementation(async (_projectId, assetIds) => ({
      added: [...assetIds],
      skipped: [],
      failed: [],
    }));
    renderLanding({ onAssetsChanged });
    await screen.findByText("Body");

    const picked = new File(["cube"], "widget.stl", { type: "model/stl" });
    fireEvent.change(screen.getByTestId("attach-files-input"), { target: { files: [picked] } });

    await waitFor(() => expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["new1"]));
    expect(uploadAssetMock).toHaveBeenCalledTimes(1);
    expect((uploadAssetMock.mock.calls[0][0] as File).name).toBe("widget.stl");
    // No `folder_id`: attaching keeps the file in normal managed storage.
    expect(uploadAssetMock.mock.calls[0][1]).toEqual({});
    await waitFor(() => expect(onAssetsChanged).toHaveBeenCalledTimes(1));
    expect(getToasts().some(toast => /Attached 1 file to "Hydra"/.test(toast.message))).toBe(true);
  });

  it("attaches a file dropped anywhere on the Files section", async () => {
    addProjectAssetsMock.mockImplementation(async (_projectId, assetIds) => ({
      added: [...assetIds],
      skipped: [],
      failed: [],
    }));
    renderLanding();
    await screen.findByText("Body");

    const section = screen.getByRole("heading", { name: "Files" }).closest("section");
    if (!section) throw new Error("missing Files section");
    const dataTransfer = {
      types: ["Files"],
      files: [new File(["cube"], "dropped.stl", { type: "model/stl" })],
      items: [],
    };

    fireEvent.dragEnter(section, { dataTransfer });
    expect(screen.getByText(/Drop files or a folder to attach/)).toBeTruthy();

    fireEvent.drop(section, { dataTransfer });

    await waitFor(() => expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["new1"]));
    expect((uploadAssetMock.mock.calls[0][0] as File).name).toBe("dropped.stl");
  });

  it("still offers the attach controls when the project has no files", async () => {
    listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });
    renderLanding({ project: makeProject({ asset_count: 0 }) });

    await screen.findByText("This project has no files yet.");
    // The hero action and the empty state both offer the library picker.
    expect(screen.getAllByRole("button", { name: "Add files" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Attach files" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Attach folder" })).toBeTruthy();
  });
});

describe("ProjectLanding attach escape guard", () => {
  it("keeps the project open while the attach zip prompt is open", async () => {
    const seenOnDocument: boolean[] = [];
    document.addEventListener("keydown", event => seenOnDocument.push(event.defaultPrevented));
    renderLanding();
    await screen.findByText("Body");

    fireEvent.change(screen.getByTestId("attach-files-input"), {
      target: { files: [new File(["zip-bytes"], "pack.zip")] },
    });
    const choice = await screen.findByRole("button", { name: "Import and unzip" });

    // The shared zip prompt has no Escape handler, so ProjectLanding has to keep
    // the project from closing under it.
    fireEvent.keyDown(choice, { key: "Escape" });

    expect(seenOnDocument).toContain(true);
    expect(screen.getByRole("heading", { level: 1, name: "Hydra" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import and unzip" })).toBeTruthy();
  });
});
