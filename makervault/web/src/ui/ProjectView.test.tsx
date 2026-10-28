// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState, type ComponentProps } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import type { Project } from "../lib/api";

/** The props the landing page is contractually handed by `ProjectView`. */
type LandingProps = {
  project: Project;
  assetsVersion: number;
  onProjectUpdated: (project: Project) => void;
  onProjectDeleted: (id: string) => void;
  onAssetsChanged: () => void;
  onUnauthorized?: () => void;
};

vi.mock("../lib/api", () => ({
  fileUrl: (rel: string) => rel,
}));

// The landing page is its own component: stub it to a marker plus the props it
// received, so the tests can prove `ProjectView` forwarded every callback.
// `withDialog` lets a test nest a modal, the way a delete ConfirmDialog does in
// the real page.
const landingState = vi.hoisted(() => ({
  withDialog: false,
  received: null as LandingProps | null,
}));

vi.mock("./ProjectLanding", () => ({
  default: (props: LandingProps) => {
    landingState.received = props;
    return (
      <div data-testid="project-landing">
        landing:{props.project.id}
        {landingState.withDialog && (
          <div role="dialog" aria-label="Delete file?">
            <button type="button">Delete</button>
          </div>
        )}
      </div>
    );
  },
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
    metadata_json: {},
    total_size: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

const projects: Project[] = [
  makeProject({ id: "p1", name: "Hydra" }),
  makeProject({ id: "p2", name: "Solo", description: null, creator: null, asset_count: 1 }),
];

type Props = ComponentProps<typeof ProjectView>;

function viewProps(overrides: Partial<Props> = {}): Props {
  return {
    projects,
    selectedProjectId: null,
    onOpenProject: vi.fn(),
    onCloseProject: vi.fn(),
    onProjectUpdated: vi.fn(),
    onProjectDeleted: vi.fn(),
    onAssetsChanged: vi.fn(),
    assetsVersion: 0,
    theme: "dark",
    ...overrides,
  };
}

afterEach(() => {
  landingState.withDialog = false;
  landingState.received = null;
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
    expect(screen.getByText("A multi-part print")).toBeTruthy();
    expect(screen.getByText("3 files")).toBeTruthy();
    expect(screen.getByText("By Ada")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open project Solo" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open project Hydra" }));
    expect(onOpenProject).toHaveBeenCalledWith("p1");
  });

  it("shows each card's licence, including the explicit unknown state", () => {
    render(
      <ProjectView
        {...viewProps({
          projects: [
            makeProject({ id: "p1", name: "Hydra", licence: "CC-BY-SA" }),
            makeProject({ id: "p2", name: "Solo", creator: null }),
          ],
        })}
      />,
    );

    const licensed = screen.getByRole("button", { name: "Open project Hydra" });
    expect(within(licensed).getByText("CC-BY-SA")).toBeTruthy();
    expect(within(licensed).queryByText("Licence unknown")).toBeNull();

    const unlicensed = screen.getByRole("button", { name: "Open project Solo" });
    expect(within(unlicensed).getByText("Licence unknown")).toBeTruthy();
    expect(within(unlicensed).queryByText("CC-BY-SA")).toBeNull();
  });

  it("shows the source host on a card without nesting an anchor in the button", () => {
    render(
      <ProjectView
        {...viewProps({
          projects: [
            makeProject({
              id: "p1",
              name: "Hydra",
              source_url: "https://www.printables.com/model/123-hydra",
            }),
          ],
        })}
      />,
    );

    const card = screen.getByRole("button", { name: "Open project Hydra" });
    const chip = card.querySelector("[data-source-chip]");
    expect(chip?.textContent).toBe("Printables");
    expect(chip?.getAttribute("title")).toBe("https://www.printables.com/model/123-hydra");
    // The card must stay a single interactive element.
    expect(within(card).queryByRole("link")).toBeNull();
    expect(card.querySelector("a")).toBeNull();
  });

  it("renders the landing page for the open project", () => {
    render(
      <ProjectView {...viewProps({ selectedProjectId: "p1", assetsVersion: 7 })} />,
    );

    expect(screen.getByTestId("project-landing").textContent).toBe("landing:p1");
    expect(landingState.received?.project.id).toBe("p1");
    expect(landingState.received?.assetsVersion).toBe(7);
    expect(screen.queryByRole("heading", { name: "Projects" })).toBeNull();
  });

  it("forwards the landing page's callbacks to its own props", () => {
    const onProjectUpdated = vi.fn();
    const onProjectDeleted = vi.fn();
    const onAssetsChanged = vi.fn();
    const onUnauthorized = vi.fn();
    render(
      <ProjectView
        {...viewProps({
          selectedProjectId: "p1",
          onProjectUpdated,
          onProjectDeleted,
          onAssetsChanged,
          onUnauthorized,
        })}
      />,
    );

    const landing = landingState.received;
    if (!landing) throw new Error("landing page did not render");

    const renamed = makeProject({ name: "Hydra v2" });
    landing.onProjectUpdated(renamed);
    expect(onProjectUpdated).toHaveBeenCalledWith(renamed);

    landing.onProjectDeleted("p1");
    expect(onProjectDeleted).toHaveBeenCalledWith("p1");

    landing.onAssetsChanged();
    expect(onAssetsChanged).toHaveBeenCalledTimes(1);

    expect(landing.onUnauthorized).toBe(onUnauthorized);
  });

  it("closes via the Back button", () => {
    const onCloseProject = vi.fn();
    render(
      <ProjectView {...viewProps({ selectedProjectId: "p1", onCloseProject })} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Back to projects" }));
    expect(onCloseProject).toHaveBeenCalledTimes(1);
  });

  it("closes via Escape", () => {
    const onCloseProject = vi.fn();
    render(
      <ProjectView {...viewProps({ selectedProjectId: "p1", onCloseProject })} />,
    );

    fireEvent.keyDown(screen.getByRole("button", { name: "Back to projects" }), {
      key: "Escape",
    });
    expect(onCloseProject).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape while the project list is showing", () => {
    const onCloseProject = vi.fn();
    render(<ProjectView {...viewProps({ onCloseProject })} />);

    fireEvent.keyDown(screen.getByRole("heading", { name: "Projects" }), { key: "Escape" });
    expect(onCloseProject).not.toHaveBeenCalled();
  });

  it("ignores Escape while a dialog inside the project is open", () => {
    const onCloseProject = vi.fn();
    landingState.withDialog = true;
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
        {...viewProps({ projects: [projects[1]], selectedProjectId: "p1", onCloseProject })}
      />,
    );

    expect(onCloseProject).toHaveBeenCalledTimes(1);
  });
});
