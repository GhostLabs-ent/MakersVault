// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { BatchMetaChange } from "../lib/api";
import BulkMetaDialog from "./BulkMetaDialog";

type RenderOptions = {
  busy?: boolean;
  requestError?: string | null;
};

function renderDialog(options: RenderOptions = {}) {
  const onSubmit = vi.fn<(change: BatchMetaChange) => void>();
  const onCancel = vi.fn();
  render(
    <BulkMetaDialog
      open
      count={3}
      busy={options.busy ?? false}
      requestError={options.requestError ?? null}
      onCancel={onCancel}
      onSubmit={onSubmit}
    />,
  );
  return { onSubmit, onCancel };
}

function saveButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^Saving\.\.\.$|^Save$/ }) as HTMLButtonElement;
}

afterEach(cleanup);

describe("BulkMetaDialog", () => {
  it("leaves unchanged fields out of the payload by default", () => {
    const { onSubmit } = renderDialog();

    expect(saveButton().disabled).toBe(true);

    fireEvent.change(screen.getByRole("textbox", { name: "Creator" }), {
      target: { value: "  Ada   Lovelace " },
    });
    fireEvent.click(saveButton());

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).toEqual({ creator: "Ada Lovelace" });
  });

  it("sends only the notes field when only notes changed", () => {
    const { onSubmit } = renderDialog();

    fireEvent.change(screen.getByRole("textbox", { name: "Notes" }), {
      target: { value: "  line one\n  line two\tend  " },
    });
    fireEvent.click(saveButton());

    expect(onSubmit).toHaveBeenCalledWith({ notes: "line one\n  line two\tend" });
  });

  it("sends explicit nulls for the checked clear controls", () => {
    const { onSubmit } = renderDialog();

    fireEvent.click(screen.getByRole("checkbox", { name: "Clear creator" }));
    fireEvent.click(saveButton());

    expect(onSubmit).toHaveBeenCalledWith({ creator: null });

    cleanup();
    const second = renderDialog();
    fireEvent.click(screen.getByRole("checkbox", { name: "Clear notes" }));
    fireEvent.click(saveButton());

    expect(second.onSubmit).toHaveBeenCalledWith({ notes: null });
  });

  it("disables the clear field and omits the other untouched field", () => {
    renderDialog();

    fireEvent.change(screen.getByRole("textbox", { name: "Creator" }), {
      target: { value: "typed but ignored" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Clear creator" }));

    expect((screen.getByRole("textbox", { name: "Creator" }) as HTMLInputElement).disabled).toBe(true);
  });

  it("shows an inline validation error and keeps Save disabled for an over-long notes value", () => {
    renderDialog();

    fireEvent.change(screen.getByRole("textbox", { name: "Notes" }), {
      target: { value: "x".repeat(4001) },
    });

    expect(screen.getByRole("alert").textContent).toContain("at most 4000 characters");
    expect(saveButton().disabled).toBe(true);
  });

  it("rejects control characters in creator without submitting", () => {
    const { onSubmit } = renderDialog();

    fireEvent.change(screen.getByRole("textbox", { name: "Creator" }), {
      target: { value: "bad\u0000creator" },
    });

    expect(screen.getByRole("alert").textContent).toContain("control characters");
    expect(saveButton().disabled).toBe(true);

    fireEvent.click(saveButton());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("renders a request-level error and disables every control while busy", () => {
    renderDialog({ busy: true, requestError: "Bulk metadata update failed." });

    expect(screen.getByText("Bulk metadata update failed.")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Creator" }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("textbox", { name: "Notes" }) as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
    expect(saveButton().disabled).toBe(true);
  });

  it("renders nothing when closed", () => {
    const { container } = render(
      <BulkMetaDialog
        open={false}
        count={2}
        busy={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
