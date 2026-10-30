// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// The barrel is replaced so `getOidcStatus`/`login`/`mfaVerify` can be driven from
// the test. `ssoErrorCopy` and `isMfaChallenge` stay the real implementations:
// these tests assert the frozen copy table and the challenge narrowing, which
// are the contract, not details worth re-stating here.
vi.mock("../lib/api", async () => {
  const oidc = await import("../lib/api/auth");
  return {
    getOidcStatus: vi.fn(async () => ({ enabled: false })),
    login: vi.fn(),
    mfaVerify: vi.fn(),
    isMfaChallenge: oidc.isMfaChallenge,
    oidcStartUrl: () => "http://api.test/auth/oidc/start",
    ssoErrorCopy: oidc.ssoErrorCopy,
  };
});

import Login from "./Login";
import { getOidcStatus, login, mfaVerify } from "../lib/api";

const getOidcStatusMock = vi.mocked(getOidcStatus);
const loginMock = vi.mocked(login);
const mfaVerifyMock = vi.mocked(mfaVerify);

/** `window.location.assign` is a full page navigation: stub the whole location. */
const assignMock = vi.fn<(url: string) => void>();

function renderLogin(ssoError?: string | null) {
  const onSuccess = vi.fn();
  render(<Login onSuccess={onSuccess} apiUp={true} theme="light" ssoError={ssoError} />);
  return { onSuccess };
}

function field(selector: string): HTMLInputElement {
  const el = document.querySelector(selector);
  if (!(el instanceof HTMLInputElement)) throw new Error(`missing input ${selector}`);
  return el;
}

function submitCredentials(username: string, password: string): void {
  fireEvent.change(field("input[autocomplete='username']"), { target: { value: username } });
  fireEvent.change(field("input[type='password']"), { target: { value: password } });
  fireEvent.click(screen.getByText("Sign in"));
}

/** jsdom's localStorage can resolve to `undefined` under Node's global; install a real one. */
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
      return store.has(key) ? (store.get(key) as string) : null;
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

/** Every key/value the page could have persisted, joined for a substring check. */
function storageDump(): string {
  const storage = window.localStorage;
  if (!storage) return "";
  const entries: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index) ?? "";
    entries.push(`${key}=${storage.getItem(key) ?? ""}`);
  }
  return entries.join("|");
}

const challenge = { mfa_required: true as const, mfa_token: "challenge-1" };

/** Sign in with a password that the API answers with a second-factor challenge. */
async function reachSecondStep(): Promise<HTMLInputElement> {
  loginMock.mockResolvedValue(challenge);
  submitCredentials("admin", "hunter2");
  const input = await screen.findByLabelText("Authentication code");
  if (!(input instanceof HTMLInputElement)) throw new Error("missing the code input");
  return input;
}

beforeEach(() => {
  installMemoryStorage();
  getOidcStatusMock.mockReset();
  getOidcStatusMock.mockResolvedValue({ enabled: false });
  loginMock.mockReset();
  assignMock.mockReset();
  vi.stubGlobal("location", {
    assign: assignMock,
    href: "http://localhost:3000/",
    hash: "",
    search: "",
    pathname: "/",
    protocol: "http:",
    origin: "http://localhost:3000",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Login SSO entry point", () => {
  it("hides the SSO button when the API reports OIDC is off", async () => {
    renderLogin();

    expect(await screen.findByText("Sign in")).toBeTruthy();
    await waitFor(() => expect(getOidcStatusMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Sign in with SSO")).toBeNull();
  });

  it("navigates to the API start URL when the SSO button is used", async () => {
    getOidcStatusMock.mockResolvedValue({ enabled: true });
    renderLogin();

    fireEvent.click(await screen.findByText("Sign in with SSO"));

    expect(assignMock).toHaveBeenCalledTimes(1);
    expect(assignMock).toHaveBeenCalledWith("http://api.test/auth/oidc/start");
    // The redirect is a side effect, not a local sign-in.
    expect(loginMock).not.toHaveBeenCalled();
  });
});

describe("Login SSO error copy", () => {
  it("renders the frozen copy for a rejected handoff", async () => {
    renderLogin("group_not_allowed");

    expect(
      await screen.findByText("Your account is not in a group allowed to sign in."),
    ).toBeTruthy();
  });

  it("renders each frozen copy for a sample of the enum", async () => {
    const cases: Array<[string, string]> = [
      ["state_expired", "This sign-in link has expired. Please try again."],
      ["provider_unavailable", "The identity provider is unavailable. Try again shortly."],
      ["token_invalid", "The identity provider's response could not be verified."],
      [
        "no_admin_bootstrap",
        "An administrator must sign in locally once before SSO can create accounts.",
      ],
    ];

    for (const [code, copy] of cases) {
      const { unmount } = render(
        <Login onSuccess={vi.fn()} apiUp={true} theme="light" ssoError={code} />,
      );
      expect(await screen.findByText(copy)).toBeTruthy();
      unmount();
    }
  });

  it("falls back to the generic line for an unknown code", async () => {
    renderLogin("idp_said_something_awful");

    expect(
      await screen.findByText("Sign-in could not be completed. Please try again."),
    ).toBeTruthy();
  });

  it("shows no SSO banner when there is no SSO error", async () => {
    renderLogin(null);

    expect(await screen.findByText("Sign in")).toBeTruthy();
    expect(screen.queryByText("Sign-in could not be completed. Please try again.")).toBeNull();
  });
});

describe("Login local password form", () => {
  it("still submits and hands the token pair to onSuccess", async () => {
    loginMock.mockResolvedValue({ token: "access-1", expires_in: 900, refresh_token: "refresh-1" });
    const { onSuccess } = renderLogin();

    submitCredentials("admin", "hunter2");

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith("access-1", 900, "refresh-1"));
    expect(loginMock).toHaveBeenCalledWith("admin", "hunter2");
  });

  it("keeps the password error independent of an SSO error", async () => {
    loginMock.mockRejectedValue(new Error("Invalid username or password"));
    renderLogin("state_replayed");

    submitCredentials("admin", "wrong");

    expect(await screen.findByText("Invalid username or password")).toBeTruthy();
    expect(
      screen.getByText("This sign-in link has already been used. Please try again."),
    ).toBeTruthy();
  });
});

describe("Login second factor", () => {
  beforeEach(() => {
    mfaVerifyMock.mockReset();
  });

  it("swaps the password form for a one-time-code step", async () => {
    const { onSuccess } = renderLogin();

    const input = await reachSecondStep();

    expect(onSuccess).not.toHaveBeenCalled();
    expect(input.getAttribute("autocomplete")).toBe("one-time-code");
    expect(input.getAttribute("inputmode")).toBe("numeric");
    // The password form is gone, so the SSO button with it: the challenge is
    // the only outstanding step and it cannot be handed to an IdP.
    expect(screen.queryByText("Sign in with SSO")).toBeNull();
    expect(screen.queryByText("Sign in")).toBeNull();
  });

  it("keeps the challenge in component state only, never in storage or the URL", async () => {
    renderLogin();

    await reachSecondStep();

    // The second step is up, and nothing was written anywhere it could outlive
    // the tab: a challenge in localStorage or the URL survives a reload and a
    // shared link, which is exactly the exposure a challenge must not have.
    expect(window.localStorage.length).toBe(0);
    expect(storageDump()).not.toContain("challenge-1");
    expect(window.location.href).not.toContain("challenge-1");
  });

  it("uppercases a recovery code and hands the stored tokens to onSuccess", async () => {
    mfaVerifyMock.mockResolvedValue({ token: "access-2", expires_in: 900, refresh_token: "refresh-2" });
    const { onSuccess } = renderLogin();

    const input = await reachSecondStep();
    fireEvent.change(input, { target: { value: "abcde-12345" } });
    fireEvent.click(screen.getByText("Verify"));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith("access-2", 900, "refresh-2"));
    expect(mfaVerifyMock).toHaveBeenCalledWith("challenge-1", "ABCDE-12345");
    // The password is never re-sent with the code.
    expect(loginMock).toHaveBeenCalledTimes(1);
  });

  it("shows the rejection and keeps the step open for another code", async () => {
    mfaVerifyMock.mockRejectedValue(new Error("Invalid or expired code."));
    const { onSuccess } = renderLogin();

    const input = await reachSecondStep();
    fireEvent.change(input, { target: { value: "000000" } });
    fireEvent.click(screen.getByText("Verify"));

    expect(await screen.findByText("Invalid or expired code.")).toBeTruthy();
    expect(screen.getByLabelText("Authentication code")).toBeTruthy();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("drops the challenge when the user goes back to the password form", async () => {
    const { onSuccess } = renderLogin();

    await reachSecondStep();
    fireEvent.click(screen.getByText("Back"));

    // A fresh sign-in starts over rather than replaying the spent challenge.
    loginMock.mockResolvedValue({ token: "access-3", expires_in: 900, refresh_token: "refresh-3" });
    submitCredentials("admin", "hunter2");

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith("access-3", 900, "refresh-3"));
    expect(mfaVerifyMock).not.toHaveBeenCalled();
  });
});
