import { type AppSettings, type PreviewMode } from "../../lib/settings";

type Props = {
  settings: AppSettings;
  onChange: (next: AppSettings) => void;
  onBack: () => void;
};

const options: Array<{ id: PreviewMode; label: string; description: string }> = [
  {
    id: "automatic",
    label: "Automatic",
    description: "Load missing previews only as cards enter view, then save them for future visits.",
  },
  {
    id: "on-demand",
    label: "On demand",
    description: "Show saved previews immediately and generate missing ones only when requested.",
  },
  {
    id: "disabled",
    label: "Disabled",
    description: "Never generate card previews. Interactive viewing remains available by opening a model.",
  },
];

export default function PreviewsSection({ settings, onChange, onBack }: Props) {
  const updatePreviews = (mode: PreviewMode) => {
    onChange({
      ...settings,
      previews: { mode },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Model Previews</h2>
          <p className="text-sm opacity-70">Control background preview work on this browser.</p>
        </div>
        <button className="text-sm px-3 py-2 rounded-md border border-panel-strong" onClick={onBack}>Back</button>
      </div>
      <div className="grid gap-3">
        {options.map(option => (
          <label
            key={option.id}
            className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 ${
              settings.previews.mode === option.id ? "border-accent bg-accent-soft" : "border-panel bg-panel-soft"
            }`}
          >
            <input
              type="radio"
              name="preview-mode"
              value={option.id}
              checked={settings.previews.mode === option.id}
              onChange={() => updatePreviews(option.id)}
              className="mt-1 h-4 w-4"
            />
            <span>
              <span className="block font-medium">{option.label}</span>
              <span className="block text-sm text-muted">{option.description}</span>
            </span>
          </label>
        ))}
      </div>
      <p className="text-xs opacity-70">
        Embedded 3MF thumbnails and previously generated server thumbnails are always used when available.
      </p>
    </div>
  );
}
