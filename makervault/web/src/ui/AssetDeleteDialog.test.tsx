// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { Asset } from "../lib/api";
import AssetDeleteDialog from "./AssetDeleteDialog";

function makeAsset(overrides: Partial<Asset> & Pick<Asset, "id" | "filename">): Asset {
  return {
    name: overrides.filename,
    mime: "model/stl",
    size: 1024,
    tags: [],
    url: `/api/assets/${overrides.id}/file`,
    supporting_file_count: 0,
    ...overrides,
  };
}

const cube = makeAsset({
  id: "a1",
  filename: "calibration-cube.stl",
  name: "Calibration cube",
  size: 2048,
  supporting_file_count: 2,
});
const spool = makeAsset({ id: "b2", filename: "spool-holder.stl", size: 1024 });
const mounted = makeAsset({
  id: "c3",
  filename: "engraved-sign.png",
  mime: "image/png",
  size: 512,
  is_reference: true,
});

type Overrides = {
  onDelete?: (assets: Asset[]) => Promise<{ failed: { id: string; message: string }[] }>;
  onCancel?: () => void;
  onClosed?: () => void;
};

function renderDialog(assets: Asset[], overrides: Overrides = {}) {
  const onDelete = vi.fn(overrides.onDelete ?? (async () => ({ failed: [] })));
  const onCancel = vi.fn(overrides.onCancel ?? (() => {}));
  const onClosed = vi.fn(overrides.onClosed ?? (() => {}));
  render(
    <AssetDeleteDialog
      assets={assets}
      onDelete={onDelete}
      onCancel={onCancel}
      onClosed={onClosed}
    />,
  );
  return { onDelete, onCancel, onClosed };
}

function dialog() {
  return within(screen.getByRole("dialog", { name: /^(Delete|Forget)/ }));
}

function confirmInput(): HTMLInputElement {
  return dialog().getByLabelText("Type the file name to confirm") as HTMLInputElement;
}

function destructiveButton(name: string): HTMLButtonElement {
  return dialog().getByRole("button", { name }) as HTMLButtonElement;
}

describe("AssetDeleteDialog", () => {
  afterEach(cleanup);

  it("keeps the single-asset button disabled until the exact file name is typed", () => {
    const { onDelete } = renderDialog([cube]);

    expect(screen.getByRole("heading", { name: "Delete “calibration-cube.stl”?" })).toBeTruthy();
    expect(destructiveButton("Delete asset").disabled).toBe(true);

    fireEvent.change(confirmInput(), { target: { value: "calibration-cube" } });
    expect(destructiveButton("Delete asset").disabled).toBe(true);

    // A near-miss with stray whitespace is not the name the server compares against.
    fireEvent.change(confirmInput(), { target: { value: "calibration-cube.stl " } });
    expect(destructiveButton("Delete asset").disabled).toBe(true);

    fireEvent.change(confirmInput(), { target: { value: "calibration-cube.stl" } });
    expect(destructiveButton("Delete asset").disabled).toBe(false);

    fireEvent.click(destructiveButton("Delete asset"));
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith([cube]);
  });

  it("submits with Enter only once the name matches", () => {
    const { onDelete } = renderDialog([cube]);

    fireEvent.keyDown(confirmInput(), { key: "Enter" });
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.change(confirmInput(), { target: { value: cube.filename } });
    fireEvent.keyDown(confirmInput(), { key: "Enter" });
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("states where the files go, when bytes are freed and how restoring works", () => {
    renderDialog([cube]);

    expect(screen.getAllByText(/\.trash/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Empty trash/)).toBeTruthy();
    expect(screen.getByText(/Settings → Storage/)).toBeTruthy();
    expect(screen.getByText(/move the file back out of/)).toBeTruthy();
    expect(screen.getByText(/rescan the storage folder/)).toBeTruthy();
    expect(screen.getByText(/its metadata \(names,/)).toBeTruthy();
    // The trash story is never sold as instantaneous, permanent deletion.
    expect(screen.queryByText(/cannot be undone/i)).toBeNull();
  });

  it("counts the primary file plus its supporting files and their bytes", () => {
    renderDialog([cube]);

    expect(screen.getByText("3 files")).toBeTruthy();
    expect(screen.getByText("2.0 KB")).toBeTruthy();
  });

  it("confirms a selection with a step instead of N typed names", () => {
    const { onDelete } = renderDialog([cube, spool, mounted]);

    expect(screen.getByRole("heading", { name: "Delete 3 selected items?" })).toBeTruthy();
    expect(dialog().queryByLabelText("Type the file name to confirm")).toBeNull();
    expect(dialog().getByText(/confirming removes all 3 selected items/)).toBeTruthy();

    // Aggregate counts across the selection: 1 primary + 2 supporting files, plus
    // one single, and none for the mounted reference (it owns no bytes here).
    expect(dialog().getByText("4 files")).toBeTruthy();
    expect(dialog().getByText("3.0 KB")).toBeTruthy();
    expect(dialog().getByText(/1 of these are mounted references/)).toBeTruthy();

    fireEvent.click(destructiveButton("Delete 3 items"));

    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith([cube, spool, mounted]);
  });

  it("says a mounted reference only loses its record", () => {
    renderDialog([mounted]);

    expect(screen.getByText(/This asset is a mounted reference/)).toBeTruthy();
    expect(screen.getByText(/The file on disk is never touched/)).toBeTruthy();
    // Its bytes live outside the storage root, so it has none of ours to count.
    expect(screen.getByText("0 files")).toBeTruthy();
  });

  it("says a missing file has nothing to move to the trash", () => {
    renderDialog([makeAsset({ id: "m4", filename: "lost-model.stl", missing_since: "2026-10-27T11:31:34+00:00" })]);

    expect(screen.getByRole("heading", { name: "Forget “lost-model.stl”?" })).toBeTruthy();
    expect(screen.getByText(/already missing from storage/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Forget entry" })).toBeTruthy();
  });

  it("lists what failed, keeps itself open and never claims success", async () => {
    const { onDelete, onClosed } = renderDialog([cube, spool], {
      onDelete: async () => ({
        failed: [{ id: "b2", message: "Storage path already exists: X" }],
      }),
    });

    fireEvent.click(destructiveButton("Delete 2 items"));
    await dialog().findByTestId("asset-delete-failures");

    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onClosed).not.toHaveBeenCalled();
    expect(dialog().getByRole("alert").textContent).toContain(
      "1 of 2 could not be deleted",
    );
    const lines = within(dialog().getByTestId("asset-delete-failures")).getAllByRole("listitem");
    expect(lines).toHaveLength(1);
    expect(lines[0].getAttribute("data-failed-id")).toBe("b2");
    expect(lines[0].textContent).toBe("spool-holder.stl — Storage path already exists: X");
    // No second run is offered from the failure state.
    expect(dialog().queryByRole("button", { name: "Delete 2 items" })).toBeNull();

    fireEvent.click(dialog().getByRole("button", { name: "Close" }));
    expect(onClosed).toHaveBeenCalledTimes(1);
  });

  it("closes after a clean run", async () => {
    const { onClosed } = renderDialog([cube]);

    fireEvent.change(confirmInput(), { target: { value: cube.filename } });
    fireEvent.click(destructiveButton("Delete asset"));

    await waitFor(() => expect(onClosed).toHaveBeenCalledTimes(1));
  });

  it("shows a rejected request inline and stays open", async () => {
    const { onClosed } = renderDialog([spool, mounted], {
      onDelete: async () => {
        throw new Error("confirm_name must match the asset's file name");
      },
    });

    fireEvent.click(destructiveButton("Delete 2 items"));
    expect(await screen.findByText("confirm_name must match the asset's file name")).toBeTruthy();
    expect(onClosed).not.toHaveBeenCalled();
  });

  it("cancelling never calls the API", () => {
    const { onDelete, onCancel } = renderDialog([cube]);

    fireEvent.change(confirmInput(), { target: { value: cube.filename } });
    fireEvent.click(dialog().getByRole("button", { name: "Cancel" }));

    expect(onDelete).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
