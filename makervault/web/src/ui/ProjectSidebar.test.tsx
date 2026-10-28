// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { Project } from "../lib/api";

vi.mock("../lib/api", () => ({
  fileUrl: (rel: string) => rel,
}));

import ProjectSidebar from "./ProjectSidebar";

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
  makeProject({ id: "p1", name: "Hydra", asset_count: 3 }),
  makeProject({ id: "p2", name: "Solo", description: null, creator: null, asset_count: 1 }),
];

function rowFor(name: string) {
  const row = screen.getByText(name).closest("[data-project-row]");
  if (!row) throw new Error(`No project row for ${name}`);
  return row as HTMLElement;
}

afterEach(cleanup);

describe("ProjectSidebar", () => {
  it("renders each project with its file count", () => {
    render(<ProjectSidebar projects={projects} selectedId={null} onSelect={vi.fn()} />);

    expect(screen.getByText("Hydra")).toBeTruthy();
    expect(screen.getByText("A multi-part print")).toBeTruthy();
    expect(screen.getByText("3 files")).toBeTruthy();
    expect(screen.getByText("1 file")).toBeTruthy();
    expect(screen.getByRole("complementary", { name: "Projects" })).toBeTruthy();
  });

  it("marks only the open project as the current page", () => {
    render(<ProjectSidebar projects={projects} selectedId="p2" onSelect={vi.fn()} />);

    expect(rowFor("Hydra").getAttribute("aria-current")).toBeNull();
    expect(rowFor("Solo").getAttribute("aria-current")).toBe("page");
  });

  it("shows a loading line before the list arrives", () => {
    render(<ProjectSidebar projects={null} selectedId={null} onSelect={vi.fn()} />);
    expect(screen.getByText("Loading projects…")).toBeTruthy();
  });

  it("shows honest empty copy when there are no projects", () => {
    render(<ProjectSidebar projects={[]} selectedId={null} onSelect={vi.fn()} />);

    expect(screen.getByText("No projects yet")).toBeTruthy();
    expect(screen.getByText("Projects group files from any folder.")).toBeTruthy();
  });

  it("keeps Settings and Audit reachable through the shared footer", () => {
    const onOpenSettings = vi.fn();
    const onOpenAudit = vi.fn();
    render(
      <ProjectSidebar
        projects={projects}
        selectedId={null}
        onSelect={vi.fn()}
        onOpenSettings={onOpenSettings}
        onOpenAudit={onOpenAudit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Audit log" }));

    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    expect(onOpenAudit).toHaveBeenCalledTimes(1);
  });

  it("moves focus with the arrow keys without opening anything", () => {
    const onSelect = vi.fn();
    render(<ProjectSidebar projects={projects} selectedId={null} onSelect={onSelect} />);

    const first = rowFor("Hydra");
    const second = rowFor("Solo");
    first.focus();
    expect(document.activeElement).toBe(first);

    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(document.activeElement).toBe(second);

    fireEvent.keyDown(second, { key: "ArrowDown" });
    expect(document.activeElement).toBe(second);

    fireEvent.keyDown(second, { key: "Home" });
    expect(document.activeElement).toBe(first);

    fireEvent.keyDown(first, { key: "End" });
    expect(document.activeElement).toBe(second);

    expect(onSelect).not.toHaveBeenCalled();
    expect(first.getAttribute("aria-current")).toBeNull();
  });

  it("opens a project on Enter/Space", () => {
    const onSelect = vi.fn();
    render(<ProjectSidebar projects={projects} selectedId={null} onSelect={onSelect} />);

    fireEvent.keyDown(rowFor("Hydra"), { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith("p1");

    fireEvent.keyDown(rowFor("Solo"), { key: " " });
    expect(onSelect).toHaveBeenLastCalledWith("p2");
  });

  it("opens a project on click", () => {
    const onSelect = vi.fn();
    render(<ProjectSidebar projects={projects} selectedId={null} onSelect={onSelect} />);

    fireEvent.click(rowFor("Solo"));
    expect(onSelect).toHaveBeenCalledWith("p2");
  });
});
