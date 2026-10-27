// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import type { Folder } from "../lib/api";
import FolderBreadcrumbs, { FolderTiles } from "./FolderNav";

const folders: Folder[] = [
  { id: "parts", name: "Parts", tags: [] },
  { id: "clamps", name: "Clamps", tags: [], parent_id: "parts" },
  { id: "brackets", name: "Brackets", tags: [], parent_id: "parts" },
  { id: "corners", name: "Corners", tags: [], parent_id: "brackets" },
  { id: "elsewhere", name: "Elsewhere", tags: [] },
];

function breadcrumbsNav(): HTMLElement {
  const nav = document.querySelector<HTMLElement>("[data-folder-breadcrumbs]");
  if (!nav) throw new Error("breadcrumb nav not rendered");
  return nav;
}

function folderTiles(): HTMLElement {
  const section = document.querySelector<HTMLElement>("[data-folder-tiles]");
  if (!section) throw new Error("folder tiles not rendered");
  return section;
}

afterEach(cleanup);

describe("FolderBreadcrumbs", () => {
  it("renders nothing at the root", () => {
    const { container } = render(
      <FolderBreadcrumbs folders={folders} folderId={null} onNavigate={vi.fn()} />,
    );
    expect(container.querySelector("[data-folder-breadcrumbs]")).toBeNull();
  });

  it("lists every ancestor in root → current order with aria-current on the last", () => {
    render(<FolderBreadcrumbs folders={folders} folderId="corners" onNavigate={vi.fn()} />);

    const nav = within(breadcrumbsNav());
    expect(nav.getAllByRole("button").map(button => button.textContent)).toEqual([
      "All files",
      "Parts",
      "Brackets",
      "Corners",
    ]);
    expect(nav.getByRole("button", { name: "All files" }).getAttribute("aria-current")).toBeNull();
    expect(
      nav.getByRole("button", { name: "Brackets" }).getAttribute("aria-current"),
    ).toBeNull();
    expect(nav.getByRole("button", { name: "Corners" }).getAttribute("aria-current")).toBe(
      "page",
    );
  });

  it("titles each crumb with the full path up to it", () => {
    render(<FolderBreadcrumbs folders={folders} folderId="corners" onNavigate={vi.fn()} />);
    expect(
      document.querySelector<HTMLElement>('[data-folder-crumb="corners"]')?.title,
    ).toBe("Parts / Brackets / Corners");
  });

  it("navigates to a middle segment and to the root", () => {
    const onNavigate = vi.fn();
    render(<FolderBreadcrumbs folders={folders} folderId="corners" onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole("button", { name: "Brackets" }));
    expect(onNavigate).toHaveBeenLastCalledWith("brackets");

    fireEvent.click(screen.getByRole("button", { name: "All files" }));
    expect(onNavigate).toHaveBeenLastCalledWith(null);
  });
});

describe("FolderTiles", () => {
  it("renders nothing at the root or for a leaf folder", () => {
    const root = render(
      <FolderTiles folders={folders} folderId={null} onNavigate={vi.fn()} />,
    );
    expect(root.container.querySelector("[data-folder-tiles]")).toBeNull();
    root.unmount();

    const leaf = render(
      <FolderTiles folders={folders} folderId="clamps" onNavigate={vi.fn()} />,
    );
    expect(leaf.container.querySelector("[data-folder-tiles]")).toBeNull();
  });

  it("shows exactly the direct children of the open folder", () => {
    render(<FolderTiles folders={folders} folderId="parts" onNavigate={vi.fn()} />);

    const tiles = within(folderTiles());
    expect(tiles.getByRole("heading", { name: "Subfolders" })).toBeTruthy();
    expect(
      tiles.getAllByRole("button").map(button => button.getAttribute("data-folder-tile")),
    ).toEqual(["brackets", "clamps"]);
    expect(tiles.getByRole("button", { name: /Brackets/ })).toBeTruthy();
    // Only Brackets itself has a child in the fixture.
    expect(tiles.getByRole("button", { name: /1 subfolder/ })).toBeTruthy();
    expect(tiles.queryByRole("button", { name: /Corners/ })).toBeNull();
    expect(tiles.queryByRole("button", { name: /Elsewhere/ })).toBeNull();
  });

  it("navigates on click, Enter and Space", () => {
    const onNavigate = vi.fn();
    render(<FolderTiles folders={folders} folderId="parts" onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole("button", { name: /Brackets/ }));
    expect(onNavigate).toHaveBeenLastCalledWith("brackets");

    const clamps = screen.getByRole("button", { name: /Clamps/ });
    fireEvent.keyDown(clamps, { key: "Enter" });
    expect(onNavigate).toHaveBeenLastCalledWith("clamps");

    onNavigate.mockClear();
    fireEvent.keyDown(clamps, { key: " " });
    expect(onNavigate).toHaveBeenLastCalledWith("clamps");

    // Unrelated keys must not navigate.
    onNavigate.mockClear();
    fireEvent.keyDown(clamps, { key: "a" });
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
