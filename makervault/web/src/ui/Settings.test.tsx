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
  getStorageSettings: vi.fn(),
  getTrash: vi.fn(async () => ({ entries: [], total_size: 0 })),
  purgeTrash: vi.fn(),
  startLibraryScan: vi.fn(),
  updateMountImportSettings: vi.fn(),
  updateStorageSettings: vi.fn(),
}));

import Settings from "./settings/Settings";
import { getStorageSettings, updateStorageSettings } from "../lib/api";
import type { AppSettings } from "../lib/settings";

const getStorageSettingsMock = vi.mocked(getStorageSettings);
const updateStorageSettingsMock = vi.mocked(updateStorageSettings);

const settings: AppSettings = {
  slicer: { enabled: false, selected: "orca" },
  engraving: { enabled: false, selected: "lightburn" },
  theme: { selected: "system" },
  makerworld: { cookie: "" },
  thingiverse: { cookie: "" },
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
  render(<Settings settings={settings} onChange={() => {}} />);

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
