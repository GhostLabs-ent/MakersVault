// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// The MFA client is mocked at the domain module, which is where the section and
// its hook import it: the `../../lib/api` barrel is a fixed object elsewhere.
vi.mock("../../lib/api/auth", () => ({
  getMfaStatus: vi.fn(),
  mfaEnrol: vi.fn(),
  mfaConfirm: vi.fn(),
  mfaDisable: vi.fn(),
  mfaRegenerateRecoveryCodes: vi.fn(),
  mfaStepUp: vi.fn(),
  setMfaPolicy: vi.fn(),
}));

import {
  getMfaStatus,
  mfaConfirm,
  mfaDisable,
  mfaEnrol,
  mfaRegenerateRecoveryCodes,
  mfaStepUp,
  setMfaPolicy,
} from "../../lib/api/auth";
import MfaSection from "./MfaSection";

const getMfaStatusMock = vi.mocked(getMfaStatus);
const mfaEnrolMock = vi.mocked(mfaEnrol);
const mfaConfirmMock = vi.mocked(mfaConfirm);
const mfaDisableMock = vi.mocked(mfaDisable);
const mfaRegenerateMock = vi.mocked(mfaRegenerateRecoveryCodes);
const mfaStepUpMock = vi.mocked(mfaStepUp);
const setMfaPolicyMock = vi.mocked(setMfaPolicy);

const notEnrolled = {
  enrolled: false,
  enrolled_at: null,
  recovery_codes_remaining: 0,
  require_admin: false,
  can_enrol: true,
};

const enrolled = {
  enrolled: true,
  enrolled_at: "2024-05-01T10:00:00Z",
  recovery_codes_remaining: 10,
  require_admin: false,
  can_enrol: false,
};

const enrolment = {
  secret: "JBSWY3DPEHPK3PXP",
  otpauth_uri: "otpauth://totp/MakersVault:admin?secret=JBSWY3DPEHPK3PXP&issuer=MakersVault",
  digits: 6,
  period: 30,
  algorithm: "SHA1",
};

const freshCodes = Array.from({ length: 10 }, (_, index) => `AAAA${index}-BBBBB`);

function renderSection(role: "admin" | "editor" | "viewer" = "editor") {
  const onUnauthorized = vi.fn();
  render(<MfaSection role={role} onBack={vi.fn()} onUnauthorized={onUnauthorized} />);
  return { onUnauthorized };
}

function codesOnScreen(): string[] {
  const element = screen.getByTestId("mfa-recovery-codes");
  return (element.textContent ?? "").split("\n").filter(Boolean);
}

function typeInto(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => {
  getMfaStatusMock.mockReset();
  getMfaStatusMock.mockResolvedValue(notEnrolled);
  mfaEnrolMock.mockReset();
  mfaEnrolMock.mockResolvedValue(enrolment);
  mfaConfirmMock.mockReset();
  mfaConfirmMock.mockResolvedValue({ recovery_codes: freshCodes });
  mfaDisableMock.mockReset();
  mfaDisableMock.mockResolvedValue(undefined);
  mfaRegenerateMock.mockReset();
  mfaRegenerateMock.mockResolvedValue({ recovery_codes: freshCodes });
  mfaStepUpMock.mockReset();
  mfaStepUpMock.mockResolvedValue({ mfa_verified: true });
  setMfaPolicyMock.mockReset();
  setMfaPolicyMock.mockResolvedValue({ require_admin: true });
});

afterEach(() => {
  cleanup();
});

describe("MfaSection enrolment", () => {
  it("walks password, QR, code and shows the ten recovery codes once", async () => {
    renderSection();

    fireEvent.click(await screen.findByText("Set up two-factor authentication"));
    typeInto("Confirm your password", "hunter2");
    fireEvent.click(screen.getByText("Continue"));

    await waitFor(() => expect(mfaEnrolMock).toHaveBeenCalledWith("hunter2"));
    // The secret is reachable by hand for an app that cannot scan.
    expect(screen.getByTestId("mfa-manual-secret").textContent).toBe(enrolment.secret);
    expect(screen.getByRole("img", { name: "Authenticator app setup QR code" })).toBeTruthy();

    getMfaStatusMock.mockResolvedValue(enrolled);
    typeInto("Enter the code the app shows", "123456");
    fireEvent.click(screen.getByText("Turn on two-factor"));

    await waitFor(() =>
      expect(mfaConfirmMock).toHaveBeenCalledWith(enrolment.secret, "123456", "hunter2"),
    );
    await screen.findByTestId("mfa-recovery-codes");
    expect(codesOnScreen()).toHaveLength(10);
    expect(codesOnScreen()[0]).toBe("AAAA0-BBBBB");

    // The codes leave the DOM only on an explicit acknowledgement.
    fireEvent.click(screen.getByText("I have saved these recovery codes"));
    await waitFor(() => expect(screen.queryByTestId("mfa-recovery-codes")).toBeNull());
    expect(await screen.findByText(/Enabled/)).toBeTruthy();
  });

  it("does not offer enrolment to an account without a local password", async () => {
    getMfaStatusMock.mockResolvedValue({ ...notEnrolled, can_enrol: false });

    renderSection();

    expect(await screen.findByText(/managed by\s+the identity provider/)).toBeTruthy();
    expect(screen.queryByText("Set up two-factor authentication")).toBeNull();
  });
});

describe("MfaSection enrolled state", () => {
  it("disables two-factor behind a password confirmation", async () => {
    getMfaStatusMock.mockResolvedValue(enrolled);
    renderSection();

    expect(await screen.findByText(/10 recovery codes remaining/)).toBeTruthy();

    fireEvent.click(screen.getByText("Disable two-factor"));
    getMfaStatusMock.mockResolvedValue(notEnrolled);
    typeInto("Confirm your password to turn two-factor off", "hunter2");
    fireEvent.click(screen.getByText("Turn off two-factor"));

    await waitFor(() => expect(mfaDisableMock).toHaveBeenCalledWith("hunter2"));
    expect(await screen.findByText("Set up two-factor authentication")).toBeTruthy();
  });

  it("regenerates the recovery codes behind a password confirmation", async () => {
    getMfaStatusMock.mockResolvedValue(enrolled);
    renderSection();

    fireEvent.click(await screen.findByText("Regenerate recovery codes"));
    typeInto("Confirm your password", "hunter2");
    fireEvent.click(screen.getByText("Generate new codes"));

    await waitFor(() => expect(mfaRegenerateMock).toHaveBeenCalledWith("hunter2"));
    await screen.findByTestId("mfa-recovery-codes");
    expect(codesOnScreen()).toHaveLength(10);
  });
});

describe("MfaSection admin policy", () => {
  it("hides the policy toggle from a non-admin", async () => {
    renderSection("viewer");

    expect(await screen.findByText("Set up two-factor authentication")).toBeTruthy();
    expect(
      screen.queryByRole("switch", { name: "Require two-factor for administrators" }),
    ).toBeNull();
  });

  it("keeps the toggle disabled until the session is stepped up", async () => {
    getMfaStatusMock.mockResolvedValue(enrolled);
    renderSection("admin");

    const toggle = await screen.findByRole("switch", {
      name: "Require two-factor for administrators",
    });
    expect((toggle as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Verify this session with a code/)).toBeTruthy();

    typeInto("Code to verify this session", "123456");
    fireEvent.click(screen.getByText("Verify this session"));

    await waitFor(() => expect(mfaStepUpMock).toHaveBeenCalledWith("123456"));
    await waitFor(() =>
      expect(
        (screen.getByRole("switch", {
          name: "Require two-factor for administrators",
        }) as HTMLButtonElement).disabled,
      ).toBe(false),
    );

    fireEvent.click(
      screen.getByRole("switch", { name: "Require two-factor for administrators" }),
    );

    await waitFor(() => expect(setMfaPolicyMock).toHaveBeenCalledWith(true));
  });
});
