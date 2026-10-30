// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// Every child of App is mocked: these tests only exercise App's session
// handling (reload refresh + login token storage), never the child UI.
vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  FORBIDDEN_MESSAGE: "Your role does not allow this action.",
  apiHealth: vi.fn(async () => ({ ok: true, auth_required: true })),
  fileUrl: vi.fn((rel: string) => rel),
  getApiBase: vi.fn(() => "http://localhost:8000"),
  getMe: vi.fn(async () => ({
    id: "u1",
    username: "admin",
    email: null,
    role: "admin",
    disabled: false,
    kind: "local",
  })),
  listProjects: vi.fn(async () => []),
  logout: vi.fn(async () => {}),
  refreshToken: vi.fn(),
}));

// The OIDC seam is mocked at the domain module, which is where App imports it:
// the `../lib/api` barrel above is a fixed object and must stay one.
vi.mock("../lib/api/auth", () => ({
  exchangeOidcCode: vi.fn(),
  ssoErrorCopy: () => null,
  OidcExchangeError: class OidcExchangeError extends Error {
    readonly status: number;

    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
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
vi.mock("./ModeSwitch", () => ({ default: () => null }));
vi.mock("./ProjectSidebar", () => ({ default: () => null }));
vi.mock("./ProjectView", () => ({ default: () => null }));
vi.mock("./asset-grid/AssetGrid", () => ({ default: () => null }));
vi.mock("./settings/Settings", () => ({ default: () => null }));
vi.mock("./AuditLog", () => ({ default: () => null }));
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
import { OidcExchangeError, exchangeOidcCode } from "../lib/api/auth";
import { readRefreshToken, readToken, storeRefreshToken, storeToken } from "../lib/auth";

const refreshTokenMock = vi.mocked(refreshToken);
const exchangeOidcCodeMock = vi.mocked(exchangeOidcCode);

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
  exchangeOidcCodeMock.mockReset();
  // Hash state leaks between tests: every test starts on a clean URL.
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
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

describe("App SSO handoff", () => {
  it("spends the handoff code once, clears the fragment and never shows the login form", async () => {
    exchangeOidcCodeMock.mockResolvedValue({
      token: "access-sso",
      expires_in: 900,
      refresh_token: "refresh-sso",
    });
    window.location.hash = "#sso_code=handoff-1";

    render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    );

    // The code is single-use server-side, so StrictMode's second effect run must
    // find the fragment already gone and leave the exchange alone.
    await waitFor(() => {
      expect(exchangeOidcCodeMock).toHaveBeenCalledTimes(1);
    });
    expect(exchangeOidcCodeMock).toHaveBeenCalledWith("handoff-1");
    expect(window.location.hash).toBe("");

    await waitFor(() => {
      expect(readToken()).toBe("access-sso");
    });
    expect(readRefreshToken()).toBe("refresh-sso");
    // The gate swaps in a placeholder, so the form never flashes before the
    // exchange lands and the app is signed in by the time it renders.
    expect(screen.queryByText("Sign in without refresh token")).toBeNull();
  });

  it("hands a 409 back to Login as the no_admin_bootstrap copy", async () => {
    // A deployment with no local administrator yet is a persistent condition:
    // telling the user to try again would be wrong advice, so the status picks
    // the copy rather than every failure collapsing into exchange_failed.
    exchangeOidcCodeMock.mockRejectedValue(
      new OidcExchangeError("An administrator must sign in locally first", 409)
    );
    window.location.hash = "#sso_code=handoff-2";

    render(<App />);

    await waitFor(() => {
      expect(window.location.hash).toBe("");
    });
    expect(exchangeOidcCodeMock).toHaveBeenCalledWith("handoff-2");
    // The exchange failed, so there is no token and the gate falls through to
    // the login form, which owns the frozen copy for the code App passes it.
    expect(readToken()).toBeNull();
  });
});
