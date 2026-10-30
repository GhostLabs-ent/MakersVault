import React from "react";
import { getMfaStatus, setMfaPolicy, type MfaStatus } from "../../lib/api/auth";
// The status and policy calls come from the domain module, not the `../../lib/api`
// barrel: `Settings.test.tsx` and `App.test.tsx` replace that barrel with a fixed
// object, and a new named import from it would throw. Same precedent `ui/App.tsx`
// documents for `OidcExchangeError`.
import { UnauthorizedError } from "../../lib/api/http";
import type { Section } from "./types";

type Props = {
  section: Section;
  onUnauthorized?: () => void;
  /** Admin-only: a viewer must never fire the admin-only policy write. */
  enabled: boolean;
};

const LOAD_ERROR = "Two-factor settings are unavailable right now.";
const POLICY_ERROR = "The two-factor policy could not be updated.";

export type MfaState = {
  status: MfaStatus | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  /** Set by a successful `/mfa/step-up`; the policy toggle needs it. */
  policyVerified: boolean;
  /** The admin threshold `Settings.tsx` already computed, surfaced for the toggle. */
  canManagePolicy: boolean;
  reload: () => Promise<MfaStatus | null>;
  markPolicyVerified: () => void;
  savePolicy: (requireAdmin: boolean) => Promise<boolean>;
};

/**
 * Loads the caller's second-factor status and owns the admin policy write.
 *
 * The load runs for every role - any account may enrol itself - while the write
 * is gated on `enabled`, the mirror of `useStorageSettings`'s shape. The status
 * payload already carries `require_admin`, so a viewer reads the policy without
 * a second, admin-only request.
 */
export function useMfa({ section, onUnauthorized, enabled }: Props): MfaState {
  const [status, setStatus] = React.useState<MfaStatus | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [policyVerified, setPolicyVerified] = React.useState(false);

  // Every mutation below can outlive the section, so results are dropped once
  // the component is gone rather than written into a dead tree.
  const aliveRef = React.useRef(true);
  React.useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const reload = React.useCallback(async (): Promise<MfaStatus | null> => {
    setLoading(true);
    try {
      const data = await getMfaStatus();
      if (!aliveRef.current) return null;
      setStatus(data);
      setError(null);
      return data;
    } catch (err) {
      if (!aliveRef.current) return null;
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return null;
      }
      setError(LOAD_ERROR);
      return null;
    } finally {
      if (aliveRef.current) setLoading(false);
    }
  }, [onUnauthorized]);

  React.useEffect(() => {
    if (section !== "mfa") return;
    void reload();
  }, [section, reload]);

  const markPolicyVerified = React.useCallback(() => {
    setPolicyVerified(true);
  }, []);

  const savePolicy = async (requireAdmin: boolean): Promise<boolean> => {
    if (!enabled) return false;
    setSaving(true);
    setError(null);
    try {
      const data = await setMfaPolicy(requireAdmin);
      if (!aliveRef.current) return false;
      setStatus(current => (current ? { ...current, require_admin: data.require_admin } : current));
      return true;
    } catch (err) {
      if (!aliveRef.current) return false;
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return false;
      }
      setError(err instanceof Error ? err.message : POLICY_ERROR);
      return false;
    } finally {
      if (aliveRef.current) setSaving(false);
    }
  };

  return {
    status,
    loading,
    saving,
    error,
    policyVerified,
    canManagePolicy: enabled,
    reload,
    markPolicyVerified,
    savePolicy,
  };
}
