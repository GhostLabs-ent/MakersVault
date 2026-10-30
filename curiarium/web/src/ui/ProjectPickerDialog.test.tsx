// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";

import type { BatchFailure, Project } from "../lib/api";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  addProjectAssets: vi.fn(),
  createProject: vi.fn(),
  listProjects: vi.fn(),
}));

import ProjectPickerDialog from "./ProjectPickerDialog";
import { UnauthorizedError, addProjectAssets, createProject, listProjects } from "../lib/api";
import { getToasts, resetToasts } from "../lib/toast";

const addProjectAssetsMock = vi.mocked(addProjectAssets);
const createProjectMock = vi.mocked(createProject);
const listProjectsMock = vi.mocked(listProjects);

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "Hydra",
    description: null,
    creator: null,
    source_url: null,
    licence: null,
    licence_url: null,
    origin: "own",
    cover_asset_id: null,
    cover_thumb_url: null,
    asset_count: 3,
    metadata_json: {},
    total_size: 4096,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

const hydra = makeProject();
const orion = makeProject({ id: "p2", name: "Orion", asset_count: 1 });

const ids = ["a1", "a2", "a3"];

function failure(id: string, error: string): BatchFailure {
  return { id, code: "error", status: 400, error };
}

type HarnessProps = {
  assetIds: string[];
  onClose: () => void;
  onChanged: () => void;
  onUnauthorized: () => void;
};

/** Mounts the picker the way the grid does: `onClose` really unmounts it. */
function Harness({ assetIds, onClose, onChanged, onUnauthorized }: HarnessProps) {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return (
    <ProjectPickerDialog
      assetIds={assetIds}
      onClose={() => {
        setOpen(false);
        onClose();
      }}
      onChanged={onChanged}
      onUnauthorized={onUnauthorized}
    />
  );
}

function renderPicker(overrides: Partial<Omit<HarnessProps, "assetIds">> & { assetIds?: string[] } = {}) {
  const onClose = overrides.onClose ?? vi.fn();
  const onChanged = overrides.onChanged ?? vi.fn();
  const onUnauthorized = overrides.onUnauthorized ?? vi.fn();
  const utils = render(
    <Harness
      assetIds={overrides.assetIds ?? ids}
      onClose={onClose}
      onChanged={onChanged}
      onUnauthorized={onUnauthorized}
    />,
  );
  return { ...utils, onClose, onChanged, onUnauthorized };
}

/** A promise the test settles by hand, for the "request in flight" cases. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  resetToasts();
  listProjectsMock.mockResolvedValue([hydra, orion]);
  addProjectAssetsMock.mockResolvedValue({ added: ids, skipped: [], failed: [] });
});

afterEach(cleanup);

describe("ProjectPickerDialog", () => {
  it("lists the projects and keeps the add button disabled until one is chosen", async () => {
    const { onClose } = renderPicker();

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    await within(dialog).findByRole("radio", { name: "Hydra" });

    expect(within(dialog).getByText("3 files")).toBeTruthy();
    expect(within(dialog).getByText("1 file")).toBeTruthy();

    const disabledButton = within(dialog).getByRole("button", { name: "Add 3 files" }) as HTMLButtonElement;
    expect(disabledButton.disabled).toBe(true);
    fireEvent.click(disabledButton);
    expect(addProjectAssetsMock).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("radio", { name: "Orion" }));
    const enabledButton = within(dialog).getByRole("button", {
      name: 'Add 3 files to "Orion"',
    }) as HTMLButtonElement;
    expect(enabledButton.disabled).toBe(false);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("sends the whole 100-id selection in exactly one request", async () => {
    const many = Array.from({ length: 100 }, (_, index) => `asset-${index + 1}`);
    addProjectAssetsMock.mockResolvedValue({ added: many, skipped: [], failed: [] });
    const onClose = vi.fn();
    renderPicker({ assetIds: many, onClose });

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    fireEvent.click(await within(dialog).findByRole("radio", { name: "Hydra" }));
    fireEvent.click(within(dialog).getByRole("button", { name: 'Add 100 files to "Hydra"' }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(addProjectAssetsMock).toHaveBeenCalledTimes(1);
    expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", many);
  });

  it("creates a project inline and adds the selection to it", async () => {
    const created = makeProject({ id: "p9", name: "Fresh", asset_count: 0 });
    createProjectMock.mockResolvedValue(created);
    const onChanged = vi.fn();
    const onClose = vi.fn();
    renderPicker({ onChanged, onClose });

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    await within(dialog).findByRole("radio", { name: "Hydra" });

    fireEvent.change(within(dialog).getByRole("textbox", { name: "New project name" }), {
      target: { value: "  Fresh  " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create and add" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(createProjectMock).toHaveBeenCalledTimes(1);
    expect(createProjectMock).toHaveBeenCalledWith({ name: "Fresh" });
    expect(addProjectAssetsMock).toHaveBeenCalledTimes(1);
    expect(addProjectAssetsMock).toHaveBeenCalledWith("p9", ids);
    // Creating the project is itself a change App has to pick up.
    expect(onChanged).toHaveBeenCalled();
    expect(getToasts().some(toast => toast.message === 'Add to "Fresh": 3 added.')).toBe(true);
    expect(screen.queryByRole("dialog", { name: "Add to project" })).toBeNull();
  });

  it("summarises added, skipped and failed members in one toast", async () => {
    addProjectAssetsMock.mockResolvedValue({
      added: ["a1", "a2", "a3"],
      skipped: ["b1", "b2"],
      failed: [failure("c1", "not found")],
    });
    renderPicker();

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    fireEvent.click(await within(dialog).findByRole("radio", { name: "Hydra" }));
    fireEvent.click(within(dialog).getByRole("button", { name: 'Add 3 files to "Hydra"' }));

    await waitFor(() =>
      expect(
        getToasts().some(
          toast =>
            toast.message === 'Add to "Hydra": 3 added, 2 already in project, 1 failed.',
        ),
      ).toBe(true),
    );
    const toast = getToasts().find(entry => entry.message.startsWith('Add to "Hydra"'));
    expect(toast?.tone).toBe("info");
    expect(toast?.details).toEqual(["c1: not found"]);
  });

  it("uses an error tone when nothing was added and something failed", async () => {
    addProjectAssetsMock.mockResolvedValue({
      added: [],
      skipped: [],
      failed: [failure("a1", "asset not found")],
    });
    renderPicker();

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    fireEvent.click(await within(dialog).findByRole("radio", { name: "Hydra" }));
    fireEvent.click(within(dialog).getByRole("button", { name: 'Add 3 files to "Hydra"' }));

    await waitFor(() =>
      expect(getToasts().some(toast => toast.tone === "error")).toBe(true),
    );
    expect(
      getToasts().some(toast => toast.message === 'Add to "Hydra": 0 added, 1 failed.'),
    ).toBe(true);
  });

  it("closes on Escape when idle", async () => {
    const onClose = vi.fn();
    renderPicker({ onClose });

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    await within(dialog).findByRole("radio", { name: "Hydra" });
    fireEvent.keyDown(dialog, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape while the add request is in flight", async () => {
    const pending = deferred<{
      added: string[];
      skipped: string[];
      failed: BatchFailure[];
    }>();
    addProjectAssetsMock.mockReturnValue(pending.promise);
    const onClose = vi.fn();
    renderPicker({ onClose });

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    fireEvent.click(await within(dialog).findByRole("radio", { name: "Hydra" }));
    fireEvent.click(within(dialog).getByRole("button", { name: 'Add 3 files to "Hydra"' }));

    await within(dialog).findByRole("button", { name: "Adding…" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      pending.resolve({ added: ids, skipped: [], failed: [] });
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("reports a 401 from listProjects as unauthorized", async () => {
    listProjectsMock.mockRejectedValue(new UnauthorizedError());
    const onUnauthorized = vi.fn();
    renderPicker({ onUnauthorized });

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("dialog", { name: "Add to project" })).toBeTruthy();
  });

  it("keeps the created project and the dialog open when the add fails", async () => {
    const created = makeProject({ id: "p9", name: "Fresh", asset_count: 0 });
    createProjectMock.mockResolvedValue(created);
    addProjectAssetsMock.mockRejectedValue(
      new Error("Editor or administrator access required"),
    );
    const onChanged = vi.fn();
    const onClose = vi.fn();
    renderPicker({ onChanged, onClose });

    const dialog = await screen.findByRole("dialog", { name: "Add to project" });
    await within(dialog).findByRole("radio", { name: "Hydra" });

    fireEvent.change(within(dialog).getByRole("textbox", { name: "New project name" }), {
      target: { value: "Fresh" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create and add" }));

    await waitFor(() => expect(addProjectAssetsMock).toHaveBeenCalledTimes(1));
    expect(onClose).not.toHaveBeenCalled();
    expect(onChanged).toHaveBeenCalledTimes(1);

    const fresh = (await within(dialog).findByRole("radio", { name: "Fresh" })) as HTMLInputElement;
    expect(fresh.checked).toBe(true);
    expect(
      getToasts().some(
        toast =>
          toast.tone === "error" &&
          toast.message === "Editor or administrator access required",
      ),
    ).toBe(true);
  });
});
