// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import type { BatchFailure } from "../lib/api";
import BulkActionBar, { BulkActionBarProps } from "./BulkActionBar";

function renderBar(overrides: Partial<BulkActionBarProps> = {}) {
  const props: BulkActionBarProps = {
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

  it("requires a second click before deleting and lets Cancel abort", () => {
    const { props } = renderBar();
    const bar = within(screen.getByTestId("bulk-action-bar"));

    fireEvent.click(bar.getByRole("button", { name: "Delete" }));
    expect(props.onDelete).not.toHaveBeenCalled();
    expect(
      screen.getByText("Permanently delete 3 items? This cannot be undone."),
    ).toBeTruthy();

    fireEvent.click(bar.getByRole("button", { name: "Cancel" }));
    expect(props.onDelete).not.toHaveBeenCalled();
    expect(bar.getByRole("button", { name: "Delete" })).toBeTruthy();

    fireEvent.click(bar.getByRole("button", { name: "Delete" }));
    fireEvent.click(bar.getByRole("button", { name: "Delete permanently" }));

    expect(props.onDelete).toHaveBeenCalledTimes(1);
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
    for (const name of ["Move", "Add tags", "Remove tags", "Download zip", "Delete", "Select all", "Clear"]) {
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
