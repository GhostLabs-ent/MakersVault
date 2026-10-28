import { type AppSettings } from "../../lib/settings";
import SectionHeader from "./SectionHeader";

type Props = {
  settings: AppSettings;
  networkDraft: string;
  setNetworkDraft: (value: string) => void;
  updateNetwork: (patch: Partial<AppSettings["network"]>) => void;
  onBack: () => void;
};

export default function NetworkSection({
  settings,
  networkDraft,
  setNetworkDraft,
  updateNetwork,
  onBack,
}: Props) {
  const trimmedUrl = (networkDraft || "").trim().replace(/\/+$/, "");
  const apiPreview = trimmedUrl
    ? (trimmedUrl.endsWith("/api") ? trimmedUrl : `${trimmedUrl}/api`)
    : "Auto (same origin)";
  const isDirty = trimmedUrl !== (settings.network.publicUrl || "");

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader
        title="Reverse Proxy"
        subtitle="Point the app at your public domain."
        onBack={onBack}
      />

      <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
        <div>
          <div className="text-lg font-semibold">Public URL</div>
          <p className="text-sm opacity-70">
            Use this when MakerVault is available at a reverse proxy domain like
            https://makersvault.local. The API will be called at /api.
          </p>
        </div>
        <p className="text-xs opacity-70">
          This setting is stored in your browser, so each device can point to a different URL if needed.
        </p>
        <div className="text-xs opacity-70 flex flex-col gap-1">
          <span>1) Configure your reverse proxy:</span>
          <span>/ → web:5173</span>
          <span>/api/* → api:8000</span>
          <span>2) Save the public URL below, then open it in your browser.</span>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase tracking-wide text-muted">
            Reverse proxy URL
          </label>
          <input
            type="text"
            value={networkDraft}
            onChange={e => setNetworkDraft(e.target.value)}
            placeholder="https://makersvault.local"
            className="px-3 py-2 rounded-md border border-panel-strong bg-panel-soft text-sm"
          />
        </div>
        <div className="text-xs opacity-70">
          API base: {apiPreview}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
            disabled={!isDirty}
            onClick={() => {
              const next = trimmedUrl;
              updateNetwork({ publicUrl: next });
              setNetworkDraft(next);
            }}
          >
            Save
          </button>
          <button
            className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
            disabled={!settings.network.publicUrl}
            onClick={() => {
              updateNetwork({ publicUrl: "" });
              setNetworkDraft("");
            }}
          >
            Clear
          </button>
        </div>
      </div>
    </div>
  );
}
