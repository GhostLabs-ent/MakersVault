import { SLICER_OPTIONS, type AppSettings } from "../../lib/settings";
import SectionHeader from "./SectionHeader";

type Props = {
  settings: AppSettings;
  onChange: (next: AppSettings) => void;
  onBack: () => void;
};

export default function SlicerSection({ settings, onChange, onBack }: Props) {
  const updateSlicer = (patch: Partial<AppSettings["slicer"]>) => {
    onChange({
      ...settings,
      slicer: {
        ...settings.slicer,
        ...patch,
      },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader
        title="Slicer"
        subtitle="Control the Open in Slicer button for 3D files."
        onBack={onBack}
      />

      <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-4">
        <p className="text-xs opacity-70">
          Requires the Slicer Bridge helper to be installed on each client to register
          the makersvault-slicer:// protocol. Download the installer from{" "}
          <a
            className="underline"
            href="https://github.com/VincentCinque/MakersVault/releases/latest"
            target="_blank"
            rel="noreferrer"
          >
            MakerVault releases
          </a>
          . On Linux, mark the download as executable if prompted.
        </p>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings.slicer.enabled}
            onChange={e => updateSlicer({ enabled: e.target.checked })}
            className="w-4 h-4"
          />
          <span>Enable Open in Slicer</span>
        </label>

        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase tracking-wide text-muted">
            Preferred slicer
          </label>
          <select
            value={settings.slicer.selected}
            onChange={e => updateSlicer({ selected: e.target.value })}
            disabled={!settings.slicer.enabled}
            className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
          >
            {SLICER_OPTIONS.map(opt => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <p className="text-xs opacity-70">
          The Open in Slicer button launches the custom protocol with a signed download URL.
        </p>
      </div>
    </div>
  );
}
