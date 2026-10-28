// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";

import type { Project } from "../lib/api";

/**
 * The real `ProjectView` + `ProjectLanding` pair, with `../lib/api` mocked the
 * way the landing page's own tests mock it. Neither component is stubbed: the
 * point is that a licence edit reaches the card grid through the same list
 * splice `App.handleProjectUpdated` performs.
 */
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

import ProjectView from "./ProjectView";
import { listAssets, listProjectAssets, updateProject } from "../lib/api";
import { resetToasts } from "../lib/toast";

const listAssetsMock = vi.mocked(listAssets);
const listProjectAssetsMock = vi.mocked(listProjectAssets);
const updateProjectMock = vi.mocked(updateProject);

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "Hydra",
    description: "A multi-part print",
    creator: "Ada",
    source_url: null,
    licence: null,
    licence_url: null,
    origin: "local",
    cover_asset_id: null,
    cover_thumb_url: null,
    asset_count: 3,
    metadata_json: {},
    total_size: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

/** `App`'s project list plus the splice `handleProjectUpdated` performs. */
function Harness({ initial }: { initial: Project[] }) {
  const [projects, setProjects] = useState(initial);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  return (
    <ProjectView
      projects={projects}
      selectedProjectId={selectedProjectId}
      onOpenProject={setSelectedProjectId}
      onCloseProject={() => setSelectedProjectId(null)}
      onProjectUpdated={project =>
        setProjects(list => list.map(item => (item.id === project.id ? project : item)))
      }
      onProjectDeleted={id => setProjects(list => list.filter(item => item.id !== id))}
      onAssetsChanged={() => undefined}
      assetsVersion={0}
      theme="dark"
    />
  );
}

function cardFor(name: string): HTMLElement {
  return screen.getByRole("button", { name: `Open project ${name}` });
}

const initial = [
  makeProject({ id: "p1", name: "Hydra" }),
  makeProject({ id: "p2", name: "Solo", creator: null, asset_count: 1 }),
];

beforeEach(() => {
  vi.clearAllMocks();
  resetToasts();
  listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });
  listAssetsMock.mockResolvedValue({ items: [], hasMore: false });
  updateProjectMock.mockImplementation(async (id, patch) => {
    const project = initial.find(item => item.id === id);
    if (!project) throw new Error(`unknown project ${id}`);
    return { ...project, ...(patch as Partial<Project>) };
  });
});

afterEach(cleanup);

describe("Project attribution propagation", () => {
  it("updates the edited card, and only that card, when a licence is saved", async () => {
    render(<Harness initial={initial} />);

    expect(within(cardFor("Hydra")).getByText("Licence unknown")).toBeTruthy();
    expect(within(cardFor("Solo")).getByText("Licence unknown")).toBeTruthy();

    fireEvent.click(cardFor("Hydra"));
    await screen.findByRole("heading", { level: 1, name: "Hydra" });

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Licence" }), {
      target: { value: "CC-BY-SA" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateProjectMock).toHaveBeenCalledWith("p1", {
      licence: "CC-BY-SA",
    }));

    // The open page reflects the saved row before we navigate back.
    const details = screen.getByRole("region", { name: "Details" });
    await waitFor(() =>
      expect(within(details).getByText("CC-BY-SA")).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Back to projects" }));

    const hydra = cardFor("Hydra");
    expect(within(hydra).getByText("CC-BY-SA")).toBeTruthy();
    expect(within(hydra).queryByText("Licence unknown")).toBeNull();
    // The untouched project keeps its honest unknown state.
    expect(within(cardFor("Solo")).getByText("Licence unknown")).toBeTruthy();
    expect(within(cardFor("Solo")).queryByText("CC-BY-SA")).toBeNull();
  });
});
