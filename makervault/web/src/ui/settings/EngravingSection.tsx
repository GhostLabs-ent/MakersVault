import { ENGRAVER_OPTIONS, type AppSettings } from "../../lib/settings";
import SectionHeader from "./SectionHeader";

type Props = {
  settings: AppSettings;
  onChange: (next: AppSettings) => void;
  onBack: () => void;
};

export default function EngravingSection({ settings, onChange, onBack }: Props) {
  const updateEngraving = (patch: Partial<AppSettings["engraving"]>) => {
    onChange({
      ...settings,
      engraving: {
        ...settings.engraving,
        ...patch,
      },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader
        title="Engraving Software"
        subtitle="Control the Open in Engraving Software button for laser-ready files."
        onBack={onBack}
      />

      <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-4">
        <p className="text-xs opacity-70">
          Requires the Bridge helper to be installed on each client to register
          the makersvault-engrave:// protocol. Download the installer from{" "}
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
            checked={settings.engraving.enabled}
            onChange={e => updateEngraving({ enabled: e.target.checked })}
            className="w-4 h-4"
          />
          <span>Enable Open in Engraving Software</span>
        </label>

        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase tracking-wide text-muted">
            Preferred engraving software
          </label>
          <select
            value={settings.engraving.selected}
            onChange={e => updateEngraving({ selected: e.target.value })}
            disabled={!settings.engraving.enabled}
            className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
          >
            {ENGRAVER_OPTIONS.map(opt => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <p className="text-xs opacity-70">
          The Open in Engraving Software button launches the custom protocol with a signed download URL.
        </p>
      </div>
    </div>
  );
}
