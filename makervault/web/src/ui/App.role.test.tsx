// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  FORBIDDEN_MESSAGE: "Your role does not allow this action.",
  apiHealth: vi.fn(async () => ({ ok: true, auth_required: true })),
  fileUrl: vi.fn((rel: string) => rel),
  getApiBase: vi.fn(() => "http://localhost:8000"),
  getMe: vi.fn(),
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
    imports: { rememberCookies: false },
    network: { publicUrl: "" },
    previews: { mode: "automatic" },
  }),
  saveSettings: () => {},
  resolveTheme: () => "light",
}));

vi.mock("./Sidebar", () => ({ default: () => null }));
// The switch is the only way to visit a second pane, so keep it interactive.
vi.mock("./ModeSwitch", async () => {
  const react = await import("react");
  return {
    default: ({ onChange }: { onChange: (mode: "files" | "projects") => void }) =>
      react.createElement(
        "div",
        null,
        react.createElement("button", { type: "button", onClick: () => onChange("files") }, "Switch to files"),
        react.createElement("button", { type: "button", onClick: () => onChange("projects") }, "Switch to projects"),
      ),
  };
});

// The projects pane carries the real footer, so the role reaches the nav the
// same way it does in the app; the extra button stands in for a direct visit
// to a hidden view (a demotion while it is open, or a future call site).
vi.mock("./ProjectSidebar", async () => {
  const react = await import("react");
  const { default: SidebarFooter } = await import("./SidebarFooter");
  return {
    default: ({
      role,
      onOpenSettings,
      onOpenAudit,
    }: {
      role?: "admin" | "editor" | "viewer" | null;
      onOpenSettings?: () => void;
      onOpenAudit?: () => void;
    }) =>
      react.createElement(
        "aside",
        { "aria-label": "Projects" },
        react.createElement("button", { type: "button", onClick: onOpenAudit }, "Open audit"),
        react.createElement(SidebarFooter, { role, onOpenSettings, onOpenAudit }),
      ),
  };
});

// Both write-bearing panes render the `canWrite` they received, so the role
// gating is asserted from the DOM instead of from a prop spy.
vi.mock("./ProjectView", async () => {
  const react = await import("react");
  return {
    default: ({ canWrite }: { canWrite: boolean }) =>
      react.createElement("div", { "data-testid": "project-view", "data-can-write": String(canWrite) }),
  };
});
vi.mock("./asset-grid/AssetGrid", async () => {
  const react = await import("react");
  return {
    default: ({ canWrite }: { canWrite: boolean }) =>
      react.createElement("div", { "data-testid": "asset-grid", "data-can-write": String(canWrite) }),
  };
});
vi.mock("./settings/Settings", () => ({ default: () => null }));
vi.mock("./AuditLog", async () => {
  const react = await import("react");
  return { default: () => react.createElement("div", null, "Audit view") };
});
// The real UploadBar hides itself when it receives `canWrite: false`, so the
// mock does the same: the marker is present only when App threaded a write
// capability down. (UploadQueuePanel is gated by App itself.)
vi.mock("./UploadBar", async () => {
  const react = await import("react");
  return {
    default: ({ canWrite }: { canWrite: boolean }) =>
      canWrite ? react.createElement("div", null, "Upload bar") : null,
  };
});
vi.mock("./UploadQueuePanel", async () => {
  const react = await import("react");
  return { default: () => react.createElement("div", null, "Upload queue") };
});
vi.mock("./Login", () => ({ default: () => null }));

import App from "./App";
import { getMe, type Me } from "../lib/api";
import { storeToken } from "../lib/auth";
import { MODE_STORAGE_KEY } from "../lib/mode";

const getMeMock = vi.mocked(getMe);

function me(role: string): Me {
  return {
    id: "u1",
    username: role,
    email: null,
    role,
    disabled: false,
    kind: "local",
  };
}

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
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
}

beforeEach(() => {
  installMemoryStorage();
  storeToken("access-token");
  window.localStorage.setItem(MODE_STORAGE_KEY, "projects");
  getMeMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("App role-gated navigation", () => {
  it("hides the audit entry from a viewer", async () => {
    getMeMock.mockResolvedValue(me("viewer"));

    render(<App />);

    await waitFor(() => expect(getMeMock).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Audit log" })).toBeNull();
    expect(screen.getByRole("button", { name: "Settings" })).toBeTruthy();
  });

  it("shows the audit entry to an admin and opens the page", async () => {
    getMeMock.mockResolvedValue(me("admin"));

    render(<App />);

    const audit = await screen.findByRole("button", { name: "Audit log" });
    fireEvent.click(audit);

    await screen.findByText("Audit view");
    expect(screen.queryByText("Administrator access required.")).toBeNull();
  });

  it("shows a clean not-permitted state for a direct visit by a viewer", async () => {
    getMeMock.mockResolvedValue(me("viewer"));

    render(<App />);

    await waitFor(() => expect(getMeMock).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Open audit" }));

    await screen.findByText("Administrator access required.");
    expect(screen.queryByText("Audit view")).toBeNull();
  });
});

describe("App write gating by role", () => {
  /** Visit the files pane too, so both panes are mounted and can be asserted. */
  async function visitBothPanes() {
    const { unmount } = render(<App />);
    await waitFor(() => expect(getMeMock).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole("button", { name: "Switch to files" }));
    await screen.findByTestId("asset-grid");
    await screen.findByTestId("project-view");
    return unmount;
  }

  it("gives a viewer no upload bar, no upload queue panel and no write capability", async () => {
    getMeMock.mockResolvedValue(me("viewer"));

    await visitBothPanes();

    expect(screen.queryByText("Upload bar")).toBeNull();
    expect(screen.queryByText("Upload queue")).toBeNull();
    expect(screen.getByTestId("asset-grid").dataset.canWrite).toBe("false");
    expect(screen.getByTestId("project-view").dataset.canWrite).toBe("false");
  });

  it("gives an editor the upload bar, the upload queue panel and write capability", async () => {
    getMeMock.mockResolvedValue(me("editor"));

    await visitBothPanes();

    expect(screen.getByText("Upload bar")).toBeTruthy();
    expect(screen.getByText("Upload queue")).toBeTruthy();
    expect(screen.getByTestId("asset-grid").dataset.canWrite).toBe("true");
    expect(screen.getByTestId("project-view").dataset.canWrite).toBe("true");
  });
});
