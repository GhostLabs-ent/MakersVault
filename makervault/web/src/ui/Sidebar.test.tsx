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
import { deleteFolder, getFolderDeletePreview, listFolders } from "../lib/api";

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
