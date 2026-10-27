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
  listFolders: vi.fn(),
  updateFolder: vi.fn(),
}));

import Sidebar from "./Sidebar";
import { deleteFolder, listFolders } from "../lib/api";

const listFoldersMock = vi.mocked(listFolders);
const deleteFolderMock = vi.mocked(deleteFolder);

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

describe("Sidebar folder deletion", () => {
  beforeEach(() => {
    listFoldersMock.mockReset();
    listFoldersMock.mockResolvedValue(folders);
    deleteFolderMock.mockClear();
    // jsdom has no window.confirm; the delete flow must be approved.
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("signals an asset refetch when a non-selected folder is deleted", async () => {
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
    fireEvent.click(deleteButtonFor("Victim"));

    await waitFor(() => expect(deleteFolderMock).toHaveBeenCalledWith("f2"));
    await waitFor(() => expect(onAssetsChanged).toHaveBeenCalledTimes(1));
    expect(onSelect).not.toHaveBeenCalled();
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
    fireEvent.click(deleteButtonFor("Victim"));

    await waitFor(() => expect(deleteFolderMock).toHaveBeenCalledWith("f2"));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(null));
    expect(onAssetsChanged).not.toHaveBeenCalled();
  });
});
