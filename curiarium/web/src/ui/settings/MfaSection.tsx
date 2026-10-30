import React from "react";
import { roleAtLeast, type Role } from "../../lib/auth";
import {
  mfaConfirm,
  mfaDisable,
  mfaEnrol,
  mfaRegenerateRecoveryCodes,
  mfaStepUp,
  type MfaEnrolment,
} from "../../lib/api/auth";
// Direct module, like `useMfa`: the `../../lib/api` barrel is replaced wholesale
// by a fixed object in `Settings.test.tsx`.
import { UnauthorizedError } from "../../lib/api/http";
import MfaQrCode from "./MfaQrCode";
import SectionHeader from "./SectionHeader";
import { useMfa } from "./useMfa";

type Props = {
  role?: Role | null;
  onBack: () => void;
  onUnauthorized?: () => void;
};

/**
 * Which panel the card is showing, as one union rather than a boolean per step.
 * The enrolment secret and the recovery codes live *on* the flow, so leaving a
 * step is a single assignment that drops them from state; unmounting drops the
 * whole thing.
 */
type Flow =
  | { kind: "idle" }
  | { kind: "enrol-password" }
  | { kind: "enrol-scan"; enrolment: MfaEnrolment }
  | { kind: "enrol-codes"; codes: string[] }
  | { kind: "regenerate-password" }
  | { kind: "regenerate-codes"; codes: string[] }
  | { kind: "disable-password" };

const FALLBACK_ERROR = "Something went wrong. Please try again.";

/** An ISO stamp from the API as local time; a missing one reads as "unknown". */
function formatEnrolledAt(value: string | null): string {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toLocaleString();
}

function Badge({ children }: { children: string }) {
  return (
    <span className="rounded-md border border-panel-strong px-2 py-0.5 text-[11px] text-muted">
      {children}
    </span>
  );
}

export default function MfaSection({ role = null, onBack, onUnauthorized }: Props) {
  const isAdmin = roleAtLeast(role, "admin");
  const mfa = useMfa({ section: "mfa", enabled: isAdmin, onUnauthorized });
  const [flow, setFlow] = React.useState<Flow>({ kind: "idle" });
  // Held for as long as a step needs it: `/mfa/confirm` re-checks the password
  // the enrolment started with, so the same entry carries across one step. It
  // is cleared whenever the flow resets.
  const [password, setPassword] = React.useState("");
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const status = mfa.status;

  /** One busy/error wrapper for every mutation, so a 401 signs out everywhere. */
  const run = async (action: () => Promise<void>): Promise<void> => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      setError(err instanceof Error ? err.message : FALLBACK_ERROR);
    } finally {
      setBusy(false);
    }
  };

  const resetFlow = () => {
    setFlow({ kind: "idle" });
    setPassword("");
    setCode("");
    setError(null);
  };

  const submitEnrolment = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const enrolment = await mfaEnrol(password);
      setFlow({ kind: "enrol-scan", enrolment });
    });
  };

  const submitConfirmation = (e: React.FormEvent) => {
    e.preventDefault();
    if (flow.kind !== "enrol-scan") return;
    const secret = flow.enrolment.secret;
    void run(async () => {
      const result = await mfaConfirm(secret, code.trim(), password);
      // The secret is dropped with the step: it is worth nothing once the API
      // has proved a code from it, and there is no reason to keep it in memory.
      setFlow({ kind: "enrol-codes", codes: result.recovery_codes });
      setPassword("");
      setCode("");
      await mfa.reload();
    });
  };

  const submitRegeneration = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const result = await mfaRegenerateRecoveryCodes(password);
      setFlow({ kind: "regenerate-codes", codes: result.recovery_codes });
      setPassword("");
      await mfa.reload();
    });
  };

  const submitDisable = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await mfaDisable(password);
      setFlow({ kind: "idle" });
      setPassword("");
      setNotice("Two-factor authentication is off for this account.");
      await mfa.reload();
    });
  };

  const submitStepUp = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await mfaStepUp(code.trim());
      setCode("");
      mfa.markPolicyVerified();
      setNotice("This session is now two-factor verified.");
    });
  };

  const submitPolicy = (next: boolean) => {
    void run(async () => {
      const saved = await mfa.savePolicy(next);
      if (saved) setNotice(next ? "Administrators must now use two-factor." : "The administrator policy is off.");
    });
  };

  /** Codes leave the DOM only on this explicit acknowledgement. */
  const acknowledgeCodes = () => {
    setFlow({ kind: "idle" });
    setNotice("Recovery codes saved. They will not be shown again.");
  };

  const recoveryCodesPanel = (codes: string[]) => (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div>
        <div className="font-medium">Save your recovery codes</div>
        <p className="text-sm text-muted">
          Each code signs you in once if you lose your authenticator app. This is the only
          time they are shown.
        </p>
      </div>
      <code
        data-testid="mfa-recovery-codes"
        className="block whitespace-pre-line break-all rounded-md border border-panel-strong bg-panel-strong px-3 py-2 text-sm"
      >
        {codes.join("\n")}
      </code>
      <button
        type="button"
        onClick={acknowledgeCodes}
        className="self-start text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
      >
        I have saved these recovery codes
      </button>
    </div>
  );

  const canTogglePolicy = Boolean(status?.enrolled) && mfa.policyVerified && !mfa.saving && !busy;

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader
        title="Two-factor authentication"
        subtitle="A second factor on top of your password."
        onBack={onBack}
      />

      {mfa.loading && <p className="text-sm opacity-70">Loading two-factor status…</p>}
      {mfa.error && <p className="text-xs text-red-400">{mfa.error}</p>}
      {error && <p className="text-xs text-red-400">{error}</p>}
      {notice && <p className="text-xs opacity-70">{notice}</p>}

      {/* Rendered outside the enrolled/not-enrolled split: confirming enrolment
          flips that status, and the codes must survive the flip. */}
      {flow.kind === "enrol-codes" && recoveryCodesPanel(flow.codes)}
      {flow.kind === "regenerate-codes" && recoveryCodesPanel(flow.codes)}

      {status && !status.enrolled && (
        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-medium">Authenticator app</div>
              <p className="text-sm text-muted">
                Ask for a 6-digit code from an authenticator app after your password.
              </p>
            </div>
            <Badge>Off</Badge>
          </div>

          {/* An SSO account has no local password to confirm, so offering the
              flow would only produce a 409 at the first step. */}
          {!status.can_enrol && (
            <p className="text-sm text-muted">
              This account signs in with single sign-on, so the second factor is managed by
              the identity provider.
            </p>
          )}

          {status.can_enrol && flow.kind === "idle" && (
            <button
              type="button"
              onClick={() => setFlow({ kind: "enrol-password" })}
              className="self-start text-sm px-3 py-2 rounded-md bg-accent font-medium"
            >
              Set up two-factor authentication
            </button>
          )}

          {status.can_enrol && flow.kind === "enrol-password" && (
            <form className="flex flex-col gap-2" onSubmit={submitEnrolment}>
              <label className="text-sm font-medium" htmlFor="mfa-enrol-password">
                Confirm your password
              </label>
              <input
                id="mfa-enrol-password"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
                autoComplete="current-password"
                required
              />
              <p className="text-xs opacity-70">
                Your password is re-checked before a second factor is attached to this
                account.
              </p>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={busy}
                  className="text-sm px-3 py-2 rounded-md bg-accent font-medium disabled:opacity-60"
                >
                  Continue
                </button>
                <button
                  type="button"
                  onClick={resetFlow}
                  disabled={busy}
                  className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong disabled:opacity-60"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {status.can_enrol && flow.kind === "enrol-scan" && (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-start gap-4">
                <MfaQrCode
                  value={flow.enrolment.otpauth_uri}
                  label="Authenticator app setup QR code"
                />
                <div className="flex min-w-[14rem] flex-1 flex-col gap-1">
                  <span className="text-sm font-medium">Or enter this setup key by hand</span>
                  <code
                    data-testid="mfa-manual-secret"
                    className="break-all rounded-md border border-panel-strong bg-panel-strong px-3 py-2 text-sm"
                  >
                    {flow.enrolment.secret}
                  </code>
                  <span className="text-xs opacity-70">
                    {flow.enrolment.digits} digits, every {flow.enrolment.period} seconds,{" "}
                    {flow.enrolment.algorithm}.
                  </span>
                </div>
              </div>
              <form className="flex flex-col gap-2" onSubmit={submitConfirmation}>
                <label className="text-sm font-medium" htmlFor="mfa-confirm-code">
                  Enter the code the app shows
                </label>
                <input
                  id="mfa-confirm-code"
                  value={code}
                  onChange={e => setCode(e.target.value)}
                  className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
                  autoComplete="one-time-code"
                  inputMode="numeric"
                  autoFocus
                  required
                />
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={busy}
                    className="text-sm px-3 py-2 rounded-md bg-accent font-medium disabled:opacity-60"
                  >
                    {busy ? "Verifying…" : "Turn on two-factor"}
                  </button>
                  <button
                    type="button"
                    onClick={resetFlow}
                    disabled={busy}
                    className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong disabled:opacity-60"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      )}

      {status && status.enrolled && (
        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-medium">Authenticator app</div>
              <p className="text-sm text-muted">
                Enabled {formatEnrolledAt(status.enrolled_at)}. Every new sign-in asks for a
                code.
              </p>
            </div>
            <Badge>On</Badge>
          </div>
          <p className="text-sm text-muted">
            {status.recovery_codes_remaining} recovery{" "}
            {status.recovery_codes_remaining === 1 ? "code" : "codes"} remaining.
          </p>

          {flow.kind === "idle" && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setFlow({ kind: "regenerate-password" })}
                className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
              >
                Regenerate recovery codes
              </button>
              <button
                type="button"
                onClick={() => setFlow({ kind: "disable-password" })}
                className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
              >
                Disable two-factor
              </button>
            </div>
          )}

          {flow.kind === "regenerate-password" && (
            <form className="flex flex-col gap-2" onSubmit={submitRegeneration}>
              <label className="text-sm font-medium" htmlFor="mfa-regenerate-password">
                Confirm your password
              </label>
              <input
                id="mfa-regenerate-password"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
                autoComplete="current-password"
                required
              />
              <p className="text-xs opacity-70">
                Every unused code stops working as soon as the new set is shown.
              </p>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={busy}
                  className="text-sm px-3 py-2 rounded-md bg-accent font-medium disabled:opacity-60"
                >
                  {busy ? "Generating…" : "Generate new codes"}
                </button>
                <button
                  type="button"
                  onClick={resetFlow}
                  disabled={busy}
                  className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong disabled:opacity-60"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {flow.kind === "disable-password" && (
            <form className="flex flex-col gap-2" onSubmit={submitDisable}>
              <label className="text-sm font-medium" htmlFor="mfa-disable-password">
                Confirm your password to turn two-factor off
              </label>
              <input
                id="mfa-disable-password"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
                autoComplete="current-password"
                required
              />
              <p className="text-xs opacity-70">
                Your recovery codes stop working immediately.
              </p>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={busy}
                  className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong disabled:opacity-60"
                >
                  {busy ? "Disabling…" : "Turn off two-factor"}
                </button>
                <button
                  type="button"
                  onClick={resetFlow}
                  disabled={busy}
                  className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong disabled:opacity-60"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Admin-only, and never rendered for a viewer: enabling it without
          stepping up is a 409, so the control is disabled until verified. */}
      {status && mfa.canManagePolicy && (
        <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-medium">Require two-factor for administrators</div>
              <p className="text-sm text-muted">
                Administrators must present a second factor on every new sign-in.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={status.require_admin}
              aria-label="Require two-factor for administrators"
              disabled={!canTogglePolicy}
              onClick={() => submitPolicy(!status.require_admin)}
              className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong disabled:opacity-60"
            >
              {status.require_admin ? "On" : "Off"}
            </button>
          </div>

          {!status.enrolled && (
            <p className="text-xs opacity-70">
              Enrol a second factor before turning this policy on.
            </p>
          )}

          {status.enrolled && !mfa.policyVerified && (
            <form className="flex flex-col gap-2" onSubmit={submitStepUp}>
              <p className="text-xs opacity-70">
                Verify this session with a code before changing the policy.
              </p>
              <div className="flex flex-wrap gap-2">
                <input
                  aria-label="Code to verify this session"
                  value={code}
                  onChange={e => setCode(e.target.value)}
                  className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
                  autoComplete="one-time-code"
                  required
                />
                <button
                  type="submit"
                  disabled={busy}
                  className="text-sm px-3 py-2 rounded-md border border-panel-strong bg-panel-strong disabled:opacity-60"
                >
                  Verify this session
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
