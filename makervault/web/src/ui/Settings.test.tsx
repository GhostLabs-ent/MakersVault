// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// Every network touchpoint of Settings (storage + the embedded TrashCard) is
// mocked, so the component renders without a backend.
vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  createFolder: vi.fn(),
  getMountImportSettings: vi.fn(),
  getLibraryScanStatus: vi.fn(),
  getStorageCapabilities: vi.fn(async () => ({ volumes: [] })),
  getStorageSettings: vi.fn(),
  getTrash: vi.fn(async () => ({ entries: [], total_size: 0 })),
  listSessions: vi.fn(async () => []),
  listUserSessions: vi.fn(),
  purgeTrash: vi.fn(),
  revokeSession: vi.fn(),
  revokeUserSession: vi.fn(),
  startLibraryScan: vi.fn(),
  updateMountImportSettings: vi.fn(),
  updateStorageSettings: vi.fn(),
}));

// The section is stubbed: its own flows are covered in MfaSection.test.tsx, so
// this file only proves Settings routes the card to it and passes the role.
vi.mock("./settings/MfaSection", async () => {
  const react = await import("react");
  return {
    default: ({ role }: { role?: string | null }) =>
      react.createElement("div", { "data-testid": "mfa-section" }, `role:${role ?? "none"}`),
  };
});

import Settings from "./settings/Settings";
import { getMountImportSettings, getStorageSettings, listSessions, updateStorageSettings } from "../lib/api";
import type { AppSettings } from "../lib/settings";

const getMountImportSettingsMock = vi.mocked(getMountImportSettings);
const getStorageSettingsMock = vi.mocked(getStorageSettings);
const listSessionsMock = vi.mocked(listSessions);
const updateStorageSettingsMock = vi.mocked(updateStorageSettings);

const settings: AppSettings = {
  slicer: { enabled: false, selected: "orca" },
  engraving: { enabled: false, selected: "lightburn" },
  theme: { selected: "system" },
  makerworld: { cookie: "" },
  thingiverse: { cookie: "" },
  imports: { rememberCookies: false },
  network: { publicUrl: "" },
  previews: { mode: "automatic" },
};

const storedStorage = {
  template: "{folder}/{model}/{filename}",
  default_template: "{folder}/{model}/{filename}",
  allowed_tokens: ["folder", "model", "filename"],
  sample_path: "Props/Cable clip/Cable clip.3mf",
  moved: 0,
  skipped: 0,
};

/** Render Settings and navigate from the root menu into the storage section. */
async function renderStorageSection() {
  render(<Settings settings={settings} onChange={() => {}} role="admin" />);

  fireEvent.click(await screen.findByRole("button", { name: /Storage Structure/ }));

  const input = await screen.findByDisplayValue("{folder}/{model}/{filename}");
  return input as HTMLInputElement;
}

describe("Settings storage structure", () => {
  beforeEach(() => {
    getStorageSettingsMock.mockReset();
    getStorageSettingsMock.mockResolvedValue(storedStorage);
    updateStorageSettingsMock.mockReset();
    updateStorageSettingsMock.mockResolvedValue(storedStorage);
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the editable path template", async () => {
    const input = await renderStorageSection();

    expect(input.tagName).toBe("INPUT");
    expect(input.disabled).toBe(false);
    expect(screen.getByText(/never moved/)).toBeTruthy();
  });

  it("offers no control to reorganize existing files", async () => {
    await renderStorageSection();

    expect(screen.queryByText(/reorganize existing|apply to existing/i)).toBeNull();
    expect(document.body.textContent || "").not.toMatch(/reorganize existing|apply to existing/i);
    expect(document.body.querySelector('input[type="checkbox"]')).toBeNull();
  });

  it("saves only the template and confirms existing files are untouched", async () => {
    const input = await renderStorageSection();

    fireEvent.change(input, { target: { value: "{folder}/{model}" } });
    fireEvent.click(screen.getByRole("button", { name: "Save storage structure" }));

    await waitFor(() => expect(updateStorageSettingsMock).toHaveBeenCalledTimes(1));
    const payload = updateStorageSettingsMock.mock.calls[0][0];
    expect(Object.keys(payload)).toEqual(["template"]);
    expect(payload).toEqual({ template: "{folder}/{model}" });

    await screen.findByText(/Storage structure saved\. New uploads and imports use this template; existing files are never moved\./);
  });
});

describe("Settings imports", () => {
  beforeEach(() => {
    getMountImportSettingsMock.mockReset();
    getMountImportSettingsMock.mockResolvedValue({ enabled: false, copy_files: true, path: null });
  });

  afterEach(() => {
    cleanup();
  });

  /** Render Settings and open the Imports section for the given role. */
  async function renderImports(role: "admin" | "editor" | "viewer") {
    render(<Settings settings={settings} onChange={() => {}} role={role} />);
    fireEvent.click(await screen.findByRole("button", { name: /Imports & Folder Scan/ }));
    await screen.findByText(/Remember import cookies on this device/);
  }

  it("scopes the cookie copy to rate limits and reports the remember opt-in", async () => {
    const onChange = vi.fn();
    render(<Settings settings={settings} onChange={onChange} role="admin" />);

    fireEvent.click(await screen.findByRole("button", { name: /Imports & Folder Scan/ }));

    // Both cards state that the cookie is never used for paid content.
    expect((await screen.findAllByText(/Never used for paid content/)).length).toBe(2);

    fireEvent.click(screen.getByLabelText(/Remember import cookies on this device/));

    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1];
    const next = lastCall?.[0] as AppSettings;
    expect(next.imports.rememberCookies).toBe(true);
  });

  it("a viewer sees the read-only import runs and cookie cards, not the folder scan", async () => {
    await renderImports("viewer");

    expect(screen.getByText("Mount import runs")).toBeTruthy();
    expect(screen.getByText(/Remember import cookies on this device/)).toBeTruthy();
    expect(screen.queryByText("Local folder scan")).toBeNull();
  });

  it("an editor sees both the folder scan card and the read-only cards", async () => {
    await renderImports("editor");

    expect(screen.getByText("Mount import runs")).toBeTruthy();
    expect(screen.getByText("Local folder scan")).toBeTruthy();
    expect(screen.getByText(/Remember import cookies on this device/)).toBeTruthy();
  });
});

describe("Settings role gating", () => {
  beforeEach(() => {
    getStorageSettingsMock.mockReset();
    getMountImportSettingsMock.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("hides the admin-only storage section from a viewer", async () => {
    render(<Settings settings={settings} onChange={() => {}} role="viewer" />);

    await screen.findByRole("button", { name: /Imports & Folder Scan/ });
    expect(screen.queryByRole("button", { name: /Storage Structure/ })).toBeNull();
  });

  it("omits the mount-import card and never fetches admin settings for a viewer", async () => {
    render(<Settings settings={settings} onChange={() => {}} role="viewer" />);

    fireEvent.click(await screen.findByRole("button", { name: /Imports & Folder Scan/ }));

    await screen.findByText(/Remember import cookies on this device/);
    expect(screen.queryByText("Mount import (server)")).toBeNull();
    expect(getMountImportSettingsMock).not.toHaveBeenCalled();
    expect(getStorageSettingsMock).not.toHaveBeenCalled();
  });

  it("replaces the storage section with a notice when a non-admin opens it", async () => {
    const { rerender } = render(
      <Settings settings={settings} onChange={() => {}} role="admin" />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Storage Structure/ }));
    await screen.findByDisplayValue("{folder}/{model}/{filename}");

    rerender(<Settings settings={settings} onChange={() => {}} role="viewer" />);

    expect(await screen.findByText("Administrator access required.")).toBeTruthy();
    expect(screen.queryByDisplayValue("{folder}/{model}/{filename}")).toBeNull();
  });
});

describe("Settings sessions", () => {
  beforeEach(() => {
    listSessionsMock.mockReset();
    listSessionsMock.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("opens the sessions section for a viewer and loads the device list once", async () => {
    render(<Settings settings={settings} onChange={() => {}} role="viewer" />);

    fireEvent.click(await screen.findByRole("button", { name: /Sessions/ }));

    expect(await screen.findByText("Devices signed in to this account.")).toBeTruthy();
    expect(listSessionsMock).toHaveBeenCalledTimes(1);
  });
});

describe("Settings two-factor", () => {
  afterEach(() => {
    cleanup();
  });

  it("opens the two-factor section and hands it the role", async () => {
    render(<Settings settings={settings} onChange={() => {}} role="editor" />);

    // The card is not admin-gated: any account may enrol itself.
    fireEvent.click(await screen.findByRole("button", { name: /Two-factor authentication/ }));

    expect((await screen.findByTestId("mfa-section")).textContent).toBe("role:editor");
  });
});
