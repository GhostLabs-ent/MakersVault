// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { notifyError, notifyInfo, resetToasts } from "../lib/toast";
import Toaster from "./Toaster";

function toaster() {
  return within(screen.getByTestId("toaster"));
}

describe("Toaster", () => {
  beforeEach(resetToasts);
  afterEach(cleanup);

  it("renders nothing while the store is empty", () => {
    render(<Toaster />);
    expect(screen.queryByTestId("toaster")).toBeNull();
  });

  it("shows an error toast with details, a retry button and role=alert", () => {
    const retry = vi.fn();
    notifyError("Failed to upload 1 file", {
      details: ["b.stl (disk full)"],
      retry,
    });

    render(<Toaster />);

    expect(toaster().getByText("Failed to upload 1 file")).toBeTruthy();
    expect(toaster().getByText("b.stl (disk full)")).toBeTruthy();
    expect(toaster().getByRole("button", { name: /retry/i })).toBeTruthy();
    expect(
      toaster().getByRole("alert").textContent,
    ).toContain("Failed to upload 1 file");
  });

  it("runs the retry action exactly once when clicked", () => {
    const retry = vi.fn();
    notifyError("Failed to upload 1 file", { retry });

    render(<Toaster />);
    fireEvent.click(toaster().getByRole("button", { name: /retry/i }));

    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("removes the toast when dismissed", () => {
    notifyError("Failed to upload 1 file");

    render(<Toaster />);
    fireEvent.click(toaster().getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByTestId("toaster")).toBeNull();
    expect(screen.queryByText("Failed to upload 1 file")).toBeNull();
  });

  it("gives an info toast role=status instead of alert", () => {
    notifyInfo("Copied to clipboard");

    render(<Toaster />);

    expect(toaster().getByRole("status").textContent).toContain("Copied to clipboard");
    expect(toaster().queryByRole("alert")).toBeNull();
  });

  it("renders inside StrictMode with a pre-existing toast", () => {
    notifyInfo("Copied to clipboard");

    render(
      <React.StrictMode>
        <Toaster />
      </React.StrictMode>,
    );

    expect(toaster().getByText("Copied to clipboard")).toBeTruthy();
  });
});
