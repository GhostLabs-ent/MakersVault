// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState, type ComponentProps } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { Project } from "../lib/api";

vi.mock("../lib/api", () => ({
  fileUrl: (rel: string) => rel,
}));

// Lets a single test nest a modal inside the grid, the way a delete
// ConfirmDialog does in the real AssetGrid.
const gridState = vi.hoisted(() => ({ withDialog: false }));

vi.mock("./AssetGrid", () => ({
  default: ({ projectId }: { projectId?: string | null }) => (
    <div data-testid="asset-grid">
      grid:{projectId}
      {gridState.withDialog && (
        <div role="dialog" aria-label="Delete file?">
          <button type="button">Delete</button>
        </div>
      )}
    </div>
  ),
}));

import ProjectView from "./ProjectView";

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
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

const projects: Project[] = [
  makeProject({ id: "p1", name: "Hydra" }),
  makeProject({ id: "p2", name: "Solo", creator: null, asset_count: 1 }),
];

type Props = ComponentProps<typeof ProjectView>;

function viewProps(overrides: Partial<Props> = {}): Props {
  return {
    projects,
    selectedProjectId: null,
    onOpenProject: vi.fn(),
    onCloseProject: vi.fn(),
    assetsVersion: 0,
    theme: "dark",
    ...overrides,
  };
}

afterEach(() => {
  gridState.withDialog = false;
  cleanup();
});

describe("ProjectView", () => {
  it("shows a loading line while the project list is null", () => {
    render(<ProjectView {...viewProps({ projects: null })} />);
    expect(screen.getByText("Loading projects…")).toBeTruthy();
  });

  it("shows neutral empty copy when there are no projects", () => {
    render(<ProjectView {...viewProps({ projects: [] })} />);

    expect(screen.getByRole("heading", { name: "Projects" })).toBeTruthy();
    expect(screen.getByText("No projects yet.")).toBeTruthy();
    expect(
      screen.getByText("Projects are collections of files from any folder."),
    ).toBeTruthy();
  });

  it("renders project cards and opens one on click", () => {
    const onOpenProject = vi.fn();
    render(<ProjectView {...viewProps({ onOpenProject })} />);

    expect(screen.getByText("Hydra")).toBeTruthy();
    expect(screen.getByText("3 files")).toBeTruthy();
    expect(screen.getByText("By Ada")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open project Hydra" }));
    expect(onOpenProject).toHaveBeenCalledWith("p1");
  });

  it("renders the open project's header and scopes the grid to it", () => {
    render(<ProjectView {...viewProps({ selectedProjectId: "p1" })} />);

    expect(screen.getByRole("heading", { name: "Hydra" })).toBeTruthy();
    expect(screen.getByText("A multi-part print")).toBeTruthy();
    expect(screen.getByTestId("asset-grid").textContent).toBe("grid:p1");
  });

  it("closes via the Back button and via Escape", () => {
    const onCloseProject = vi.fn();
    render(
      <ProjectView {...viewProps({ selectedProjectId: "p1", onCloseProject })} />,
    );

    const back = screen.getByRole("button", { name: "Back to projects" });
    fireEvent.click(back);
    expect(onCloseProject).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(back, { key: "Escape" });
    expect(onCloseProject).toHaveBeenCalledTimes(2);
  });

  it("ignores Escape while the project list is showing", () => {
    const onCloseProject = vi.fn();
    render(<ProjectView {...viewProps({ onCloseProject })} />);

    fireEvent.keyDown(screen.getByRole("heading", { name: "Projects" }), { key: "Escape" });
    expect(onCloseProject).not.toHaveBeenCalled();
  });

  it("ignores Escape while a dialog inside the project is open", () => {
    const onCloseProject = vi.fn();
    gridState.withDialog = true;
    render(
      <ProjectView {...viewProps({ selectedProjectId: "p1", onCloseProject })} />,
    );

    fireEvent.keyDown(screen.getByRole("button", { name: "Delete" }), { key: "Escape" });

    expect(onCloseProject).not.toHaveBeenCalled();
  });

  it("ignores Escape a child already handled", () => {
    const onCloseProject = vi.fn();
    render(
      <ProjectView {...viewProps({ selectedProjectId: "p1", onCloseProject })} />,
    );

    const back = screen.getByRole("button", { name: "Back to projects" });
    // A nested handler that consumed Escape prevents the default, which is how
    // a child (e.g. a closing popover) signals it owned the key.
    const handler = (event: KeyboardEvent) => event.preventDefault();
    back.addEventListener("keydown", handler);
    fireEvent.keyDown(back, { key: "Escape" });

    expect(onCloseProject).not.toHaveBeenCalled();
  });

  it("moves focus to Back on open and back to the originating card on close", () => {
    const { rerender } = render(<ProjectView {...viewProps()} />);
    const card = screen.getByRole("button", { name: "Open project Hydra" });
    card.focus();
    expect(document.activeElement).toBe(card);

    rerender(<ProjectView {...viewProps({ selectedProjectId: "p1" })} />);
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Back to projects" }),
    );

    rerender(<ProjectView {...viewProps({ selectedProjectId: null })} />);
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Open project Hydra" }),
    );
  });

  it("Escape also returns focus to the originating card", () => {
    function Harness() {
      const [selected, setSelected] = useState<string | null>("p1");
      return (
        <ProjectView
          {...viewProps({
            selectedProjectId: selected,
            onCloseProject: () => setSelected(null),
          })}
        />
      );
    }

    render(<Harness />);
    const back = screen.getByRole("button", { name: "Back to projects" });
    expect(document.activeElement).toBe(back);

    fireEvent.keyDown(back, { key: "Escape" });

    expect(
      screen.getByRole("button", { name: "Open project Hydra" }),
    ).toBe(document.activeElement);
  });

  it("closes a project that vanished from the refreshed list", () => {
    const onCloseProject = vi.fn();
    render(
      <ProjectView
        {...viewProps({ projects: [], selectedProjectId: "gone", onCloseProject })}
      />,
    );

    expect(onCloseProject).toHaveBeenCalledTimes(1);
  });
});
