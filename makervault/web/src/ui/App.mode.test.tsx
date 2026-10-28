// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// The children are mocked: these tests cover App's mode state, persistence and
// the lazy mount/hide contract, not the panes' own rendering.
vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  apiHealth: vi.fn(async () => ({ ok: true, auth_required: true })),
  fileUrl: vi.fn((rel: string) => rel),
  getApiBase: vi.fn(() => "http://localhost:8000"),
  listProjects: vi.fn(async () => []),
  logout: vi.fn(async () => {}),
  refreshToken: vi.fn(),
}));

vi.mock("../lib/settings", () => ({
  loadSettings: () => ({
    slicer: { enabled: false, selected: "orca" },
    engraving: { enabled: false, selected: "lightburn" },
    theme: { selected: "light" },
    makerworld: { cookie: "" },
    thingiverse: { cookie: "" },
    network: { publicUrl: "" },
    previews: { mode: "automatic" },
  }),
  saveSettings: () => {},
  resolveTheme: () => "light",
}));

vi.mock("./Sidebar", async () => {
  const react = await import("react");
  return {
    default: () =>
      react.createElement("aside", { "aria-label": "Files" }, "Files tree"),
  };
});

vi.mock("./ProjectSidebar", async () => {
  const react = await import("react");
  return {
    default: ({ onOpenSettings }: { onOpenSettings?: () => void }) =>
      react.createElement(
        "aside",
        { "aria-label": "Projects" },
        react.createElement("p", null, "Projects list"),
        react.createElement("button", { type: "button", onClick: onOpenSettings }, "Open settings"),
      ),
  };
});

vi.mock("./ProjectView", async () => {
  const react = await import("react");
  return { default: () => react.createElement("div", null, "Project view") };
});

vi.mock("./asset-grid/AssetGrid", () => ({ default: () => null }));
vi.mock("./settings/Settings", async () => {
  const react = await import("react");
  return {
    default: ({ onSelectFolder }: { onSelectFolder?: (id: string | null) => void }) =>
      react.createElement(
        "div",
        null,
        react.createElement("p", null, "Settings view"),
        // Stands in for "Scan now"/folder navigation, which hand a folder back
        // to App while the projects pane may be the active one.
        react.createElement(
          "button",
          { type: "button", onClick: () => onSelectFolder?.("folder-1") },
          "Scan now",
        ),
      ),
  };
});
vi.mock("./AuditLog", () => ({ default: () => null }));
vi.mock("./UploadBar", () => ({ default: () => null }));
vi.mock("./UploadQueuePanel", () => ({ default: () => null }));
vi.mock("./Login", () => ({ default: () => null }));

import App from "./App";
import { listProjects } from "../lib/api";
import { storeToken } from "../lib/auth";
import { MODE_STORAGE_KEY } from "../lib/mode";

const listProjectsMock = vi.mocked(listProjects);

/** jsdom may resolve `window.localStorage` to undefined; install a real one. */
function installMemoryStorage(): void {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length(): number {
      return store.size;
    },
    clear(): void {
      store.clear();
    },
    getItem(key: string): string | null {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      store.delete(key);
    },
    setItem(key: string, value: string): void {
      store.set(key, value);
    },
  };
  Object.defineProperty(window, "localStorage", { value: storage, configurable: true });
}

beforeEach(() => {
  installMemoryStorage();
  listProjectsMock.mockClear();
  storeToken("access-token");
});

afterEach(() => {
  cleanup();
});

describe("App library mode switch", () => {
  it("seeds the active pane from the persisted mode", async () => {
    window.localStorage.setItem(MODE_STORAGE_KEY, "projects");

    render(<App />);

    await waitFor(() => expect(listProjectsMock).toHaveBeenCalled());
    expect(screen.getByRole("complementary", { name: "Projects" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Files" })).toBeNull();
    // The files pane has never been visited, so it is not mounted at all.
    expect(screen.queryByText("Files tree")).toBeNull();
  });

  it("persists the chosen mode and never unmounts a visited pane", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("radio", { name: "Projects" }));

    expect(window.localStorage.getItem(MODE_STORAGE_KEY)).toBe("projects");
    expect(screen.getByRole("complementary", { name: "Projects" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Files" })).toBeNull();
    // Still mounted, just hidden: its selection/search state survives.
    expect(screen.getByText("Files tree")).toBeTruthy();
    await waitFor(() => expect(listProjectsMock).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("radio", { name: "Files" }));

    expect(window.localStorage.getItem(MODE_STORAGE_KEY)).toBe("files");
    expect(screen.getByRole("complementary", { name: "Files" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Projects" })).toBeNull();
    expect(screen.getByText("Projects list")).toBeTruthy();
  });

  it("keeps Settings reachable while projects mode is active", async () => {
    window.localStorage.setItem(MODE_STORAGE_KEY, "projects");

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));

    expect(screen.getByText("Settings view")).toBeTruthy();
  });

  it("returns to files mode when Settings selects a folder", async () => {
    window.localStorage.setItem(MODE_STORAGE_KEY, "projects");

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Open settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Scan now" }));

    expect(window.localStorage.getItem(MODE_STORAGE_KEY)).toBe("files");
    expect(screen.getByRole("complementary", { name: "Files" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Projects" })).toBeNull();
  });
});
