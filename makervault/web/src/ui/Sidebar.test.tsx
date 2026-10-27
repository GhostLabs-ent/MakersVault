// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { Folder } from "../lib/api";

// Network calls are the only thing Sidebar touches on mount, so mock the API
// module; uploadTree/zipUtils/ZipImportModal are pure UI helpers and render
// without a browser/WebGL dependency.
vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  createFolder: vi.fn(),
  deleteFolder: vi.fn(async () => ({ ok: true })),
  downloadFolderZip: vi.fn(),
  getFolderDeletePreview: vi.fn(),
  listFolders: vi.fn(),
  updateFolder: vi.fn(),
}));

import Sidebar from "./Sidebar";
import Toaster from "./Toaster";
import { deleteFolder, getFolderDeletePreview, listFolders } from "../lib/api";
import { resetToasts } from "../lib/toast";

const listFoldersMock = vi.mocked(listFolders);
const deleteFolderMock = vi.mocked(deleteFolder);
const previewMock = vi.mocked(getFolderDeletePreview);

const folders: Folder[] = [
  { id: "f1", name: "Keep", tags: [] },
  { id: "f2", name: "Victim", tags: [] },
];

/** Open the per-folder `<details>` menu and return its Delete button. */
function deleteButtonFor(folderName: string): HTMLElement {
  const summary = screen.getByLabelText(`Actions for ${folderName}`);
  fireEvent.click(summary);
  const details = summary.closest("details");
  if (!details) throw new Error(`No action menu for ${folderName}`);
  const label = within(details).getByText(/^Delete$/);
  const button = label.closest("button");
  if (!button) throw new Error(`Delete action for ${folderName} is not a button`);
  return button;
}

/** Click a folder's Delete action and wait for the confirmation dialog's preview. */
async function openDeleteDialog(folderName: string) {
  fireEvent.click(deleteButtonFor(folderName));
  const input = await screen.findByLabelText("Type the folder name to confirm");
  await screen.findByText(/tracked asset/);
  const button = screen.getByRole("button", { name: "Delete folder" }) as HTMLButtonElement;
  return { input, button };
}

describe("Sidebar folder deletion", () => {
  beforeEach(() => {
    resetToasts();
    listFoldersMock.mockReset();
    listFoldersMock.mockResolvedValue(folders);
    deleteFolderMock.mockClear();
    previewMock.mockReset();
    previewMock.mockResolvedValue({
      folders: 2,
      assets: 3,
      files: 4,
      bytes: 2048,
      in_trash: false,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("opens the confirmation dialog without deleting, and only enables the button at the exact folder name", async () => {
    const onSelect = vi.fn();
    const onFoldersChanged = vi.fn();
    const onAssetsChanged = vi.fn();

    render(
      <Sidebar
        selectedId="f1"
        onSelect={onSelect}
        onFoldersChanged={onFoldersChanged}
        onAssetsChanged={onAssetsChanged}
      />,
    );

    await screen.findByText("Victim");
    const { input, button } = await openDeleteDialog("Victim");

    expect(previewMock).toHaveBeenCalledWith("f2");
    expect(deleteFolderMock).not.toHaveBeenCalled();
    expect(button.disabled).toBe(true);

    fireEvent.change(input, { target: { value: "Victim2" } });
    expect(deleteFolderMock).not.toHaveBeenCalled();
    expect(button.disabled).toBe(true);

    fireEvent.change(input, { target: { value: "Victim" } });
    expect(button.disabled).toBe(false);

    fireEvent.click(button);

    await waitFor(() => expect(deleteFolderMock).toHaveBeenCalledWith("f2", "Victim"));
    await waitFor(() => expect(onAssetsChanged).toHaveBeenCalledTimes(1));
    expect(onSelect).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("selects the root instead of signalling an asset refetch when the selected folder is deleted", async () => {
    const onSelect = vi.fn();
    const onFoldersChanged = vi.fn();
    const onAssetsChanged = vi.fn();

    render(
      <Sidebar
        selectedId="f2"
        onSelect={onSelect}
        onFoldersChanged={onFoldersChanged}
        onAssetsChanged={onAssetsChanged}
      />,
    );

    await screen.findByText("Victim");
    const { input, button } = await openDeleteDialog("Victim");

    fireEvent.change(input, { target: { value: "Victim" } });
    fireEvent.click(button);

    await waitFor(() => expect(deleteFolderMock).toHaveBeenCalledWith("f2", "Victim"));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(null));
    expect(onAssetsChanged).not.toHaveBeenCalled();
    expect(onFoldersChanged).toHaveBeenCalled();
  });
});

const treeFolders: Folder[] = [
  { id: "f1", name: "Keep", tags: [] },
  { id: "f2", name: "Victim", tags: [] },
  { id: "f3", name: "Nested", tags: [], parent_id: "f1" },
  { id: "f4", name: "Empty", tags: [], parent_id: "f2" },
];

/** The tree row element for a folder id. */
function treeRow(id: string): HTMLElement {
  const row = document.querySelector<HTMLElement>(`[data-tree-row="${id}"]`);
  if (!row) throw new Error(`Tree row ${id} is not rendered`);
  return row;
}

function treeRows(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>("[data-tree-row]"));
}

function rowIdsWithTabStop(): string[] {
  return treeRows()
    .filter(row => row.tabIndex === 0)
    .map(row => row.dataset.treeRow ?? "");
}

/**
 * Render the sidebar with the shared hierarchy and wait until root folders have
 * auto-expanded (Keep → Nested visible), i.e. the tree is in its stable order:
 * Keep, Nested, Victim, Empty.
 */
async function renderTree(selectedId: string | null = null) {
  listFoldersMock.mockReset();
  listFoldersMock.mockResolvedValue(treeFolders);
  const onSelect = vi.fn();
  const view = render(<Sidebar selectedId={selectedId} onSelect={onSelect} />);
  await screen.findByText("Nested");
  return { onSelect, ...view };
}

describe("Sidebar keyboard tree", () => {
  afterEach(() => {
    cleanup();
  });

  it("gives exactly one visible row the tab stop, starting on the selected folder", async () => {
    await renderTree("f2");

    await waitFor(() => expect(rowIdsWithTabStop()).toEqual(["f2"]));
    expect(treeRows().map(row => row.dataset.treeRow)).toEqual(["f1", "f3", "f2", "f4"]);
    for (const row of treeRows()) {
      expect(row.tabIndex).toBe(row.dataset.treeRow === "f2" ? 0 : -1);
    }
  });

  it("falls back to the first row when nothing is selected", async () => {
    await renderTree(null);

    await waitFor(() => expect(rowIdsWithTabStop()).toEqual(["f1"]));
    expect(treeRow("f1").tabIndex).toBe(0);
    expect(treeRow("f3").tabIndex).toBe(-1);
    expect(treeRow("f2").tabIndex).toBe(-1);
    expect(treeRow("f4").tabIndex).toBe(-1);
  });

  it("moves focus and the tab stop with ArrowDown/ArrowUp, clamped at the ends", async () => {
    await renderTree(null);
    await waitFor(() => expect(rowIdsWithTabStop()).toEqual(["f1"]));

    treeRow("f1").focus();
    expect(document.activeElement).toBe(treeRow("f1"));

    fireEvent.keyDown(treeRow("f1"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(treeRow("f3"));
    expect(rowIdsWithTabStop()).toEqual(["f3"]);

    fireEvent.keyDown(treeRow("f3"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(treeRow("f2"));

    fireEvent.keyDown(treeRow("f2"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(treeRow("f4"));

    fireEvent.keyDown(treeRow("f4"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(treeRow("f4"));

    fireEvent.keyDown(treeRow("f4"), { key: "ArrowUp" });
    expect(document.activeElement).toBe(treeRow("f2"));

    fireEvent.keyDown(treeRow("f2"), { key: "ArrowUp" });
    fireEvent.keyDown(treeRow("f3"), { key: "ArrowUp" });
    expect(document.activeElement).toBe(treeRow("f1"));
    expect(rowIdsWithTabStop()).toEqual(["f1"]);

    fireEvent.keyDown(treeRow("f1"), { key: "ArrowUp" });
    expect(document.activeElement).toBe(treeRow("f1"));
  });

  it("expands with ArrowRight, then focuses the child; ArrowLeft collapses or returns to the parent", async () => {
    await renderTree(null);
    await waitFor(() => expect(treeRow("f3")).toBeTruthy());

    treeRow("f1").focus();
    // Roots auto-expand, so collapse Keep first and reopen it with the keyboard.
    fireEvent.keyDown(treeRow("f1"), { key: "ArrowLeft" });
    expect(treeRow("f1").getAttribute("aria-expanded")).toBe("false");
    expect(document.querySelector('[data-tree-row="f3"]')).toBeNull();

    fireEvent.keyDown(treeRow("f1"), { key: "ArrowRight" });
    expect(treeRow("f1").getAttribute("aria-expanded")).toBe("true");
    await waitFor(() => expect(document.querySelector('[data-tree-row="f3"]')).not.toBeNull());
    // Expanding alone leaves focus on the parent row.
    expect(document.activeElement).toBe(treeRow("f1"));

    fireEvent.keyDown(treeRow("f1"), { key: "ArrowRight" });
    expect(document.activeElement).toBe(treeRow("f3"));

    fireEvent.keyDown(treeRow("f3"), { key: "ArrowLeft" });
    expect(document.activeElement).toBe(treeRow("f1"));

    fireEvent.keyDown(treeRow("f1"), { key: "ArrowLeft" });
    expect(treeRow("f1").getAttribute("aria-expanded")).toBe("false");
    expect(document.querySelector('[data-tree-row="f3"]')).toBeNull();
  });

  it("selects the focused folder with Enter and Space", async () => {
    const { onSelect } = await renderTree(null);
    await waitFor(() => expect(treeRow("f2")).toBeTruthy());

    treeRow("f2").focus();
    fireEvent.keyDown(treeRow("f2"), { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith("f2");

    onSelect.mockClear();
    treeRow("f4").focus();
    const notPrevented = fireEvent.keyDown(treeRow("f4"), { key: " " });
    expect(notPrevented).toBe(false);
    expect(onSelect).toHaveBeenLastCalledWith("f4");
  });

  it("leaves Enter and Space to the folder action menu instead of selecting", async () => {
    const { onSelect } = await renderTree(null);
    await waitFor(() => expect(treeRow("f2")).toBeTruthy());

    // The row's action menu summary is a natively focusable control inside the
    // treeitem: Enter/Space must keep toggling the menu, not open the folder.
    const summary = screen.getByLabelText("Actions for Victim");
    summary.focus();

    const enterNotPrevented = fireEvent.keyDown(summary, { key: "Enter" });
    expect(enterNotPrevented).toBe(true);
    const spaceNotPrevented = fireEvent.keyDown(summary, { key: " " });
    expect(spaceNotPrevented).toBe(true);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("moves from the All files button into the first tree row with ArrowDown", async () => {
    await renderTree(null);
    const allFiles = screen.getByRole("button", { name: /All files/ });

    fireEvent.keyDown(allFiles, { key: "ArrowDown" });

    expect(document.activeElement).toBe(treeRow("f1"));
    expect(rowIdsWithTabStop()).toEqual(["f1"]);
  });

  it("exposes tree/treeitem roles, levels, selection and non-tabbable inner controls", async () => {
    await renderTree("f3");
    await waitFor(() => expect(rowIdsWithTabStop()).toEqual(["f3"]));

    expect(screen.getByRole("tree", { name: "Folders" })).toBeTruthy();
    expect(treeRow("f1").getAttribute("role")).toBe("treeitem");
    expect(treeRow("f1").getAttribute("aria-level")).toBe("1");
    expect(treeRow("f1").getAttribute("aria-expanded")).toBe("true");
    expect(treeRow("f2").getAttribute("aria-level")).toBe("1");
    expect(treeRow("f3").getAttribute("aria-level")).toBe("2");
    expect(treeRow("f3").getAttribute("aria-selected")).toBe("true");
    expect(treeRow("f3").getAttribute("aria-current")).toBe("page");
    expect(treeRow("f3").hasAttribute("aria-expanded")).toBe(false);
    expect(treeRow("f2").getAttribute("aria-current")).toBeNull();
    expect(treeRow("f2").getAttribute("aria-selected")).toBe("false");

    expect(within(treeRow("f1")).getByRole("button", { name: "Keep" }).tabIndex).toBe(-1);
    expect(within(treeRow("f1")).getByRole("button", { name: "Collapse" }).tabIndex).toBe(-1);
  });
});

describe("Sidebar error reporting", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    resetToasts();
    // `handleError` logs before it toasts; keep test output clean.
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    consoleError.mockRestore();
  });

  it("raises a toast instead of a native alert when folders fail to load", async () => {
    listFoldersMock.mockReset();
    listFoldersMock.mockRejectedValue(new Error("nope"));

    render(
      <>
        <Sidebar selectedId={null} onSelect={vi.fn()} />
        <Toaster />
      </>,
    );

    await waitFor(() => {
      const toaster = within(screen.getByTestId("toaster"));
      expect(toaster.getAllByRole("alert")).toHaveLength(1);
      expect(toaster.getByText("Unable to load folders.")).toBeTruthy();
    });
  });
});
