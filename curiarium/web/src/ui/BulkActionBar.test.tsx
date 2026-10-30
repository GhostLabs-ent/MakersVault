// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import type { BatchFailure } from "../lib/api";
import BulkActionBar, { BulkActionBarProps } from "./BulkActionBar";

function renderBar(overrides: Partial<BulkActionBarProps> = {}) {
  const props: BulkActionBarProps = {
    canWrite: true,
    count: 3,
    folderOptions: [
      { id: null, name: "Unassigned" },
      { id: "f1", name: "Folder one" },
      { id: "f2", name: "Folder two" },
    ],
    busy: null,
    failures: null,
    failureLabels: [],
    onMove: vi.fn(),
    onAddTags: vi.fn(),
    onRemoveTags: vi.fn(),
    onEditMeta: vi.fn(),
    onAddToProject: vi.fn(),
    onDownload: vi.fn(),
    onDelete: vi.fn(),
    onClear: vi.fn(),
    onSelectAll: vi.fn(),
    onDismissFailures: vi.fn(),
    ...overrides,
  };
  const utils = render(<BulkActionBar {...props} />);
  return { ...utils, props };
}

describe("BulkActionBar", () => {
  afterEach(cleanup);

  it("renders nothing without a selection", () => {
    const { container } = renderBar({ count: 0 });
    expect(container.querySelector('[data-testid="bulk-action-bar"]')).toBeNull();
  });

  it("shows the selected count and the scope of the actions", () => {
    renderBar({ count: 3 });
    expect(screen.getByText("3 selected")).toBeTruthy();
    expect(
      screen.getByText("These actions apply to exactly the 3 selected items."),
    ).toBeTruthy();
    expect(screen.getByTestId("bulk-action-bar")).toBeTruthy();
  });

  it("moves the selection to the chosen folder", () => {
    const { props } = renderBar();

    fireEvent.change(screen.getByRole("combobox", { name: "Target folder" }), {
      target: { value: "f2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Move" }));

    expect(props.onMove).toHaveBeenCalledTimes(1);
    expect(props.onMove).toHaveBeenCalledWith("f2");
  });

  it("hides the move control when folder controls are disabled", () => {
    renderBar({ showFolderControls: false });

    expect(screen.queryByRole("combobox", { name: "Target folder" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Move" })).toBeNull();
    // Everything else stays available.
    expect(screen.getByRole("button", { name: "Add tags" })).toBeTruthy();
  });

  it("moves the selection to unassigned by default", () => {
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "Move" }));

    expect(props.onMove).toHaveBeenCalledWith(null);
  });

  it("passes normalized comma-separated tags to add and remove", () => {
    const { props } = renderBar();
    const input = screen.getByRole("textbox", { name: "Tags" });

    fireEvent.change(input, { target: { value: "  pla , PLA, strong   plastic , ," } });
    fireEvent.click(screen.getByRole("button", { name: "Add tags" }));

    expect(props.onAddTags).toHaveBeenCalledTimes(1);
    expect(props.onAddTags).toHaveBeenCalledWith(["pla", "strong plastic"]);

    fireEvent.change(input, { target: { value: " old ,retired" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove tags" }));

    expect(props.onRemoveTags).toHaveBeenCalledTimes(1);
    expect(props.onRemoveTags).toHaveBeenCalledWith(["old", "retired"]);
  });

  it("downloads the selection as one zip", () => {
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "Download zip" }));

    expect(props.onDownload).toHaveBeenCalledTimes(1);
  });

  it("opens the project picker for the selection", () => {
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "Add to project…" }));

    expect(props.onAddToProject).toHaveBeenCalledTimes(1);
  });

  it("opens the bulk metadata editor from the action bar", () => {
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "Edit metadata…" }));

    expect(props.onEditMeta).toHaveBeenCalledTimes(1);
  });

  it("disables the metadata editor while another bulk action is busy", () => {
    renderBar({ busy: { label: "Deleting", count: 2 } });

    expect(
      (screen.getByRole("button", { name: "Edit metadata…" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("opens the confirm dialog with one click instead of confirming inline", () => {
    const { props } = renderBar();
    const bar = within(screen.getByTestId("bulk-action-bar"));

    fireEvent.click(bar.getByRole("button", { name: "Delete" }));

    // The bar has no second step of its own: the dialog it opens is the step.
    expect(props.onDelete).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Delete permanently" })).toBeNull();
    expect(screen.queryByText(/Permanently delete/)).toBeNull();
  });

  it("clears and selects all through the explicit controls", () => {
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(props.onSelectAll).toHaveBeenCalledTimes(1);
    expect(props.onClear).toHaveBeenCalledTimes(1);
  });

  it("shows the busy label and disables every action while busy", () => {
    renderBar({ busy: { label: "Deleting", count: 2 } });

    expect(screen.getByText(/Deleting 2 items/)).toBeTruthy();
    for (const name of ["Move", "Add tags", "Remove tags", "Edit metadata…", "Download zip", "Delete", "Select all", "Clear"]) {
      expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
    }
    expect((screen.getByRole("combobox", { name: "Target folder" }) as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole("textbox", { name: "Tags" }) as HTMLInputElement).disabled).toBe(true);
  });

  it("lists one failure line per asset without offering a retry", () => {
    const failures: BatchFailure[] = [
      { id: "b2", code: "conflict", status: 409, error: "Storage path already exists: X" },
      { id: "c3", code: "error", status: 500, error: "Disk full" },
    ];
    const { props } = renderBar({
      count: 2,
      failures,
      failureLabels: [
        { id: "b2", label: "spool-holder.stl", message: "Storage path already exists: X" },
        { id: "c3", label: "engraved-sign.png", message: "Disk full" },
      ],
    });

    const list = screen.getByTestId("bulk-failures");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].getAttribute("data-failed-id")).toBe("b2");
    expect(items[0].textContent).toBe("spool-holder.stl — Storage path already exists: X");
    expect(items[1].getAttribute("data-failed-id")).toBe("c3");
    expect(items[1].textContent).toBe("engraved-sign.png — Disk full");

    expect(
      screen.getByText("The successful items were applied; nothing was retried."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(props.onDismissFailures).toHaveBeenCalledTimes(1);
  });

  it("surfaces a whole-request error", () => {
    renderBar({ requestError: "Bulk delete failed." });
    expect(screen.getByRole("alert").textContent).toBe("Bulk delete failed.");
  });
});

describe("BulkActionBar role capability", () => {
  afterEach(cleanup);

  const WRITE_CONTROLS = [
    "Move",
    "Add tags",
    "Remove tags",
    "Edit metadata…",
    "Add to project…",
    "Delete",
  ];
  const READ_CONTROLS = ["Download zip", "Select all", "Clear"];

  it("offers every bulk write action to an editor", () => {
    renderBar({ canWrite: true });

    for (const name of WRITE_CONTROLS) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    expect(screen.getByRole("combobox", { name: "Target folder" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Tags" })).toBeTruthy();
    for (const name of READ_CONTROLS) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
  });

  it("keeps only the download, selection and clearing controls for a viewer", () => {
    renderBar({ canWrite: false });

    expect(screen.getByText("3 selected")).toBeTruthy();
    for (const name of READ_CONTROLS) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    for (const name of WRITE_CONTROLS) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByRole("combobox", { name: "Target folder" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Tags" })).toBeNull();
  });

  it("still reports what already happened, dismissible, to a viewer", () => {
    const { props } = renderBar({
      canWrite: false,
      requestError: "Bulk delete failed.",
      failures: [{ id: "b2", code: "conflict", status: 409, error: "Storage path exists" }],
      failureLabels: [{ id: "b2", label: "spool-holder.stl", message: "Storage path exists" }],
    });

    expect(screen.getByRole("alert").textContent).toBe("Bulk delete failed.");
    expect(screen.getByTestId("bulk-failures").textContent).toContain("spool-holder.stl");

    // Both reporting blocks share the one dismiss callback.
    for (const button of screen.getAllByRole("button", { name: "Dismiss" })) {
      fireEvent.click(button);
    }
    expect(props.onDismissFailures).toHaveBeenCalledTimes(2);
  });
});
