// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import SettingsRootMenu from "./SettingsRootMenu";

afterEach(() => {
  cleanup();
});

describe("SettingsRootMenu", () => {
  it("shows the build version in the footer", () => {
    render(<SettingsRootMenu onOpen={vi.fn()} role="admin" />);

    // __APP_VERSION__ is the vite define fed from package.json, so the expected
    // text comes from the same literal the build uses, not a second copy.
    expect(screen.getByTestId("app-version").textContent).toBe(`Makers Vault ${__APP_VERSION__}`);
  });

  it("offers the storage section to an admin", () => {
    render(<SettingsRootMenu onOpen={vi.fn()} role="admin" />);

    expect(screen.getByRole("button", { name: /Storage Structure/ })).toBeTruthy();
  });

  it.each(["viewer", "editor"] as const)("hides the storage section from a %s", role => {
    render(<SettingsRootMenu onOpen={vi.fn()} role={role} />);

    expect(screen.queryByRole("button", { name: /Storage Structure/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Imports & Folder Scan/ })).toBeTruthy();
  });

  it("fails closed while the role is unknown", () => {
    render(<SettingsRootMenu onOpen={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /Storage Structure/ })).toBeNull();
  });
});
