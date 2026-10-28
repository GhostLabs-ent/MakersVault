import type { Section } from "./types";

type Props = {
  onOpen: (section: Section) => void;
};

export default function SettingsRootMenu({ onOpen }: Props) {
  return (
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
        onClick={() => onOpen("storage")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Files</div>
        <div className="text-lg font-semibold">Storage Structure</div>
        <div className="text-sm opacity-70">Organize files with folders, model names, creators, and tags. Use Projects to group files.</div>
      </button>
      <button
        className="text-left rounded-lg border border-panel bg-panel-soft p-4 hover:shadow"
        onClick={() => onOpen("imports")}
      >
        <div className="text-xs uppercase tracking-wide text-muted">Imports</div>
        <div className="text-lg font-semibold">Imports & Folder Scan</div>
        <div className="text-sm opacity-70">Manage import rate-limit workarounds and scan local folders.</div>
      </button>
    </div>
  );
}
