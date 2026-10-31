// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import SettingsRootMenu from "./SettingsRootMenu";

afterEach(() => {
  cleanup();
});

describe("SettingsRootMenu", () => {
  it("shows the build version in the footer", () => {
    render(<SettingsRootMenu onOpen={vi.fn()} role="admin" />);

    // __APP_VERSION__ is the vite define fed from package.json, so the expected
    // text comes from the same literal the build uses, not a second copy.
    expect(screen.getByTestId("app-version").textContent).toBe(`Curiarium ${__APP_VERSION__}`);
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

  it("offers the users section to an admin", () => {
    render(<SettingsRootMenu onOpen={vi.fn()} role="admin" />);

    expect(screen.getByRole("button", { name: /Users/ })).toBeTruthy();
  });

  it.each(["viewer", "editor"] as const)("hides the users section from a %s", role => {
    render(<SettingsRootMenu onOpen={vi.fn()} role={role} />);

    expect(screen.queryByRole("button", { name: /Users/ })).toBeNull();
  });

  it("hides the users section while the role is unknown", () => {
    render(<SettingsRootMenu onOpen={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /Users/ })).toBeNull();
  });

  it("opens the users section", () => {
    const onOpen = vi.fn();
    render(<SettingsRootMenu onOpen={onOpen} role="admin" />);

    fireEvent.click(screen.getByRole("button", { name: /Users/ }));

    expect(onOpen).toHaveBeenCalledWith("users");
  });

  // Revoking your own devices is a read-level action, so no role gate here.
  it.each(["viewer", "editor", "admin"] as const)(
    "offers the sessions section to a %s",
    role => {
      render(<SettingsRootMenu onOpen={vi.fn()} role={role} />);

      expect(screen.getByRole("button", { name: /Sessions/ })).toBeTruthy();
    },
  );

  it("opens the sessions section", () => {
    const onOpen = vi.fn();
    render(<SettingsRootMenu onOpen={onOpen} role="viewer" />);

    fireEvent.click(screen.getByRole("button", { name: /Sessions/ }));

    expect(onOpen).toHaveBeenCalledWith("sessions");
  });

  // A second factor on your own sign-in is not an admin privilege: only the
  // deployment-wide policy inside the section is.
  it.each(["viewer", "editor", "admin"] as const)(
    "offers the two-factor section to a %s",
    role => {
      render(<SettingsRootMenu onOpen={vi.fn()} role={role} />);

      expect(screen.getByRole("button", { name: /Two-factor authentication/ })).toBeTruthy();
    },
  );

  it("opens the two-factor section", () => {
    const onOpen = vi.fn();
    render(<SettingsRootMenu onOpen={onOpen} role="viewer" />);

    fireEvent.click(screen.getByRole("button", { name: /Two-factor authentication/ }));

    expect(onOpen).toHaveBeenCalledWith("mfa");
  });
});
