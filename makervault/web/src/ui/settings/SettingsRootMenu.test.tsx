// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import SettingsRootMenu from "./SettingsRootMenu";

afterEach(() => {
  cleanup();
});

describe("SettingsRootMenu", () => {
  it("shows the build version in the footer", () => {
    render(<SettingsRootMenu onOpen={vi.fn()} />);

    // __APP_VERSION__ is the vite define fed from package.json, so the expected
    // text comes from the same literal the build uses, not a second copy.
    expect(screen.getByTestId("app-version").textContent).toBe(`Makers Vault ${__APP_VERSION__}`);
  });
});
