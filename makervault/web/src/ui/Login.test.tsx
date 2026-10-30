// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// The barrel is replaced so `getOidcStatus`/`login` can be driven from the test.
// `ssoErrorCopy` stays the real implementation: these tests assert the frozen
// copy table, which is the contract, not a detail worth re-stating here.
vi.mock("../lib/api", async () => {
  const oidc = await import("../lib/api/auth");
  return {
    getOidcStatus: vi.fn(async () => ({ enabled: false })),
    login: vi.fn(),
    oidcStartUrl: () => "http://api.test/auth/oidc/start",
    ssoErrorCopy: oidc.ssoErrorCopy,
  };
});

import Login from "./Login";
import { getOidcStatus, login } from "../lib/api";

const getOidcStatusMock = vi.mocked(getOidcStatus);
const loginMock = vi.mocked(login);

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

beforeEach(() => {
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
