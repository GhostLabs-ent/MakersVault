import React from "react";
import { getOidcStatus, login, oidcStartUrl, ssoErrorCopy } from "../lib/api";
import { ResolvedTheme } from "../lib/settings";

type Props = {
  onSuccess: (token: string, expires_in: number, refresh_token: string) => void;
  apiUp: boolean | null;
  theme: ResolvedTheme;
  /** A frozen `sso_error` value from the redirect fragment, or null. */
  ssoError?: string | null;
};

const logoForTheme = (theme: ResolvedTheme) => {
  switch (theme) {
    case "neon":
      return "/img/green_theme/Neon_Green_bgrm.png";
    case "purple":
      return "/img/purple_theme/Neon_Purple_logo_bgrm.png";
    case "blue":
      return "/img/blue_theme/Blue_Theme_logo_bgrm.png";
    case "dark":
      return "/img/whitelogo.png";
    default:
      return "/img/blacklogo.png";
  }
};

export default function Login({ onSuccess, apiUp, theme, ssoError }: Props) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // SSO is racked only once the API confirms it: a deployment without an IdP
  // must not offer a button that dead-ends at a 503.
  const [ssoEnabled, setSsoEnabled] = React.useState(false);
  // The SSO failure is a separate channel from the password `error`: a failed
  // handoff and a mistyped password can both be true at the same time.
  const ssoMessage = ssoErrorCopy(ssoError ?? null);

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      const status = await getOidcStatus();
      if (!cancelled) setSsoEnabled(status.enabled);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await login(username, password);
      onSuccess(res.token, res.expires_in, res.refresh_token ?? "");
    } catch (err) {
      console.error(err);
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Login failed");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-md rounded-xl border border-panel bg-panel-soft p-6 shadow-xl backdrop-blur">
      <div className="mb-6 text-center space-y-3">
        <div className="flex justify-center">
          <img
            src={logoForTheme(theme)}
            alt="Makers Vault"
            className="max-h-40 w-auto"
          />
        </div>
        <p className="text-sm text-muted">Sign in to continue</p>
      </div>
      {apiUp === false && (
        <div className="mb-4 rounded-md bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-100 px-3 py-2 text-sm">
          API appears offline. Ensure the API service is running.
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-md bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-100 px-3 py-2 text-sm">
          {error}
        </div>
      )}
      <form className="space-y-4" onSubmit={handleSubmit}>
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium">Username</label>
          <input
            value={username}
            onChange={e => setUsername(e.target.value)}
            className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
            autoComplete="username"
            required
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium">Password</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong"
            autoComplete="current-password"
            required
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full px-3 py-2 rounded-md bg-accent font-medium disabled:opacity-60"
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
        {ssoEnabled && (
          // Secondary, not `bg-accent`: the local password form stays the
          // primary path and the only one that works offline.
          <button
            type="button"
            onClick={() => window.location.assign(oidcStartUrl())}
            className="w-full px-3 py-2 rounded-md border border-panel-strong bg-panel-strong font-medium"
          >
            Sign in with SSO
          </button>
        )}
      </form>
      {/* Only the frozen copy table above can reach here; the API's own error
          detail is never rendered. */}
      {ssoMessage && (
        <div className="mt-4 rounded-md bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-100 px-3 py-2 text-sm">
          {ssoMessage}
        </div>
      )}
    </div>
  );
}
