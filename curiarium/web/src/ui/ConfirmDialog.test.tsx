// @vitest-environment jsdom
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import ConfirmDialog from "./ConfirmDialog";

function renderDialog(overrides: Partial<ComponentProps<typeof ConfirmDialog>> = {}) {
  const props = {
    title: "Delete 3 assets?",
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  const utils = render(<ConfirmDialog {...props} />);
  return { ...utils, props };
}

describe("ConfirmDialog", () => {
  afterEach(cleanup);

  it("renders a modal dialog titled by its heading, plus the body", () => {
    renderDialog({ body: "This cannot be undone." });

    const dialog = screen.getByRole("dialog", { name: "Delete 3 assets?" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByText("This cannot be undone.")).toBeTruthy();
  });

  it("calls onConfirm from the confirm button and honours a custom label", () => {
    const { props } = renderDialog({ confirmLabel: "Delete" });

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(props.onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel from the cancel button", () => {
    const { props } = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when Escape is pressed", () => {
    const { props } = renderDialog();

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables both buttons and ignores Escape and confirm clicks while busy", () => {
    const { props } = renderDialog({ busy: true });

    const buttons = screen.getAllByRole("button") as HTMLButtonElement[];
    expect(buttons).toHaveLength(2);
    for (const button of buttons) expect(button.disabled).toBe(true);

    fireEvent.click(buttons[1]);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(props.onConfirm).not.toHaveBeenCalled();
    expect(props.onCancel).not.toHaveBeenCalled();
  });

  it("styles the confirm button red only when danger is set", () => {
    const { unmount } = renderDialog({ danger: true });
    expect(screen.getByRole("button", { name: "Confirm" }).className).toContain("bg-red-600");
    unmount();

    renderDialog();
    expect(screen.getByRole("button", { name: "Confirm" }).className).not.toContain("bg-red-600");
  });
});
