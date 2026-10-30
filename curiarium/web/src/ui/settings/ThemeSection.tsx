import { THEME_OPTIONS, type AppSettings, type ThemeId } from "../../lib/settings";
import SectionHeader from "./SectionHeader";

const THEME_SWATCHES: Record<ThemeId, string> = {
  system: "linear-gradient(135deg, #f8fafc 0%, #f8fafc 50%, #0b0f19 50%, #0b0f19 100%)",
  light: "linear-gradient(135deg, #ffffff, #e2e8f0)",
  dark: "linear-gradient(135deg, #0b0f19, #1f2937)",
  neon: "linear-gradient(135deg, #b6ff2b, #0a1508)",
  purple: "linear-gradient(135deg, #c77dff, #12091f)",
  blue: "linear-gradient(135deg, #74d4ff, #0a1324)",
};

type Props = {
  settings: AppSettings;
  onChange: (next: AppSettings) => void;
  onBack: () => void;
};

export default function ThemeSection({ settings, onChange, onBack }: Props) {
  const updateTheme = (selected: ThemeId) => {
    onChange({
      ...settings,
      theme: {
        selected,
      },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader
        title="Theme"
        subtitle="Choose how Curiarium looks and feels."
        onBack={onBack}
      />

      <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
        {THEME_OPTIONS.map(option => {
          const selected = settings.theme.selected === option.id;
          return (
            <label
              key={option.id}
              className={`flex items-start gap-3 rounded-md border p-3 cursor-pointer transition ${
                selected ? "border-accent bg-accent-soft" : "border-panel-strong bg-panel-strong"
              }`}
            >
              <input
                type="radio"
                name="theme"
                value={option.id}
                checked={selected}
                onChange={() => updateTheme(option.id)}
                className="mt-1"
              />
              <span
                aria-hidden="true"
                className={`mt-0.5 h-8 w-8 shrink-0 rounded-md border ${
                  selected ? "border-accent" : "border-panel-strong"
                }`}
                style={{ backgroundImage: THEME_SWATCHES[option.id] }}
              />
              <div>
                <div className="font-medium">{option.label}</div>
                <div className="text-sm text-muted">{option.description}</div>
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}
