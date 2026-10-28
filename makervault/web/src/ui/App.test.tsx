// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// Every child of App is mocked: these tests only exercise App's session
// handling (reload refresh + login token storage), never the child UI.
vi.mock("../lib/api", () => ({
  apiHealth: vi.fn(async () => ({ ok: true, auth_required: true })),
  getApiBase: vi.fn(() => "http://localhost:8000"),
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

vi.mock("./Sidebar", () => ({ default: () => null }));
vi.mock("./AssetGrid", () => ({ default: () => null }));
vi.mock("./Settings", () => ({ default: () => null }));
vi.mock("./UploadBar", () => ({ default: () => null }));
vi.mock("./UploadQueuePanel", () => ({ default: () => null }));
vi.mock("./Login", async () => {
  const react = await import("react");
  return {
    default: ({ onSuccess }: { onSuccess: (token: string, ttl: number, refresh: string) => void }) =>
      react.createElement(
        "button",
        { type: "button", onClick: () => onSuccess("access-new", 900, "") },
        "Sign in without refresh token"
      ),
  };
});

import App from "./App";
import { refreshToken } from "../lib/api";
import { readRefreshToken, readToken, storeRefreshToken, storeToken } from "../lib/auth";

const refreshTokenMock = vi.mocked(refreshToken);

const TOKEN_KEY = "makersvault_auth_token";
const REFRESH_TOKEN_KEY = "makersvault_auth_refresh_token";

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
  refreshTokenMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("App session bootstrap", () => {
  it("spends the stored refresh token once even though StrictMode runs the effect twice", async () => {
    storeToken("access-1");
    storeRefreshToken("refresh-1");
    refreshTokenMock.mockResolvedValue({
      token: "access-2",
      expires_in: 900,
      refresh_token: "refresh-2",
    });

    render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    );

    await waitFor(() => {
      expect(readRefreshToken()).toBe("refresh-2");
    });

    expect(refreshTokenMock).toHaveBeenCalledTimes(1);
    expect(refreshTokenMock).toHaveBeenCalledWith("refresh-1");
    // Still signed in: the single-use token was not spent twice, so no 401.
    expect(readToken()).toBe("access-2");
    expect(screen.queryByText("Sign in without refresh token")).toBeNull();
  });

  it("drops a stored refresh token when login returns none", async () => {
    storeRefreshToken("refresh-from-previous-account");

    render(<App />);

    fireEvent.click(await screen.findByText("Sign in without refresh token"));

    await waitFor(() => {
      expect(readToken()).toBe("access-new");
    });
    expect(readRefreshToken()).toBeNull();
    expect(window.localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe("access-new");
  });
});
