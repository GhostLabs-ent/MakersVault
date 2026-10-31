import { roleAtLeast, type Role } from "../../lib/auth";
import type { Section } from "./types";

type Props = {
  onOpen: (section: Section) => void;
  role?: Role | null;
  username?: string | null;
  kind?: string | null;
};

export default function SettingsRootMenu({ onOpen, role = null, username = null, kind = null }: Props) {
  const how = kind === "oidc" ? "single sign-on" : kind === "break-glass" ? "break-glass" : kind === "password" ? "password" : null;
  return (
    <div className="flex flex-col gap-3">
    {(username || role) && (
      <div className="rounded-lg border border-panel bg-panel-soft px-4 py-3 text-sm">
        <span className="opacity-70">Signed in as </span>
        <strong data-testid="settings-username">{username ?? "auth disabled"}</strong>
        {role && <span className="ml-2 rounded border border-panel-strong px-1 py-px text-[11px] uppercase tracking-wide" data-testid="settings-role">{role}</span>}
        {how && <span className="ml-2 text-xs opacity-70">via {how}</span>}
      </div>
    )}
    <div className="grid gap-3 sm:grid-cols-2">
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("slicer")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Slicer</div>
        <div className="text-lg font-semibold">Open in Slicer</div>
        <div className="text-sm opacity-70">Pick a slicer for 3D model downloads.</div>
      </button>
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("engraving")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Engraving</div>
        <div className="text-lg font-semibold">Open in Engraving Software</div>
        <div className="text-sm opacity-70">Pick a laser app for vector and image files.</div>
      </button>
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("theme")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Theme</div>
        <div className="text-lg font-semibold">Appearance</div>
        <div className="text-sm opacity-70">Switch between light, dark, and neon colors.</div>
      </button>
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("network")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Reverse Proxy</div>
        <div className="text-lg font-semibold">Public URL</div>
        <div className="text-sm opacity-70">Set the domain for proxied access.</div>
      </button>
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("previews")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Performance</div>
        <div className="text-lg font-semibold">Model Previews</div>
        <div className="text-sm opacity-70">Choose automatic, on-demand, or disabled preview generation.</div>
      </button>
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("sessions")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Security</div>
        <div className="text-lg font-semibold">Sessions</div>
        <div className="text-sm opacity-70">See the devices signed in to this account and sign them out.</div>
      </button>
      {/* No role gate: any account may put a second factor on its own sign-in.
          Only the deployment-wide policy inside the section is admin-only. */}
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("mfa")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Security</div>
        <div className="text-lg font-semibold">Two-factor authentication</div>
        <div className="text-sm opacity-70">Add an authenticator code on top of your password.</div>
      </button>
      {roleAtLeast(role, "admin") && (
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => onOpen("storage")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Files</div>
          <div className="text-lg font-semibold">Storage Structure</div>
          <div className="text-sm opacity-70">Organize files with folders, model names, creators, and tags. Use Projects to group files.</div>
        </button>
      )}
      {roleAtLeast(role, "admin") && (
        <button
          className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
          onClick={() => onOpen("users")}
        >
          <div className="text-xs uppercase tracking-wide text-muted">Security</div>
          <div className="text-lg font-semibold">Users</div>
          <div className="text-sm opacity-70">Create accounts, change their roles, disable them, and reset passwords.</div>
        </button>
      )}
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("imports")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Imports</div>
        <div className="text-lg font-semibold">Imports & Folder Scan</div>
        <div className="text-sm opacity-70">Manage import rate-limit workarounds and scan local folders.</div>
      </button>
      <p className="col-span-full text-xs text-muted" data-testid="app-version">
        Curiarium {__APP_VERSION__}
      </p>
    </div>
    </div>
  );
}
