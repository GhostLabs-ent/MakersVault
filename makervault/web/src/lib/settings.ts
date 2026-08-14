export type SlicerOption = { id: string; label: string };

export const SLICER_OPTIONS: SlicerOption[] = [
  { id: "orca", label: "OrcaSlicer" },
  { id: "bambu", label: "Bambu Studio" },
  { id: "prusa", label: "PrusaSlicer" },
  { id: "superslicer", label: "SuperSlicer" },
  { id: "cura", label: "UltiMaker Cura" },
  { id: "ideamaker", label: "ideaMaker" },
  { id: "simplify3d", label: "Simplify3D" },
  { id: "kisslicer", label: "KISSlicer" },
  { id: "repetier", label: "Repetier-Host" },
  { id: "chitubox", label: "ChiTuBox" },
  { id: "lychee", label: "Lychee Slicer" },
  { id: "photon", label: "Anycubic Photon Workshop" },
  { id: "creality", label: "Creality Print" },
];

export type EngraverOption = { id: string; label: string };

export const ENGRAVER_OPTIONS: EngraverOption[] = [
  { id: "lightburn", label: "LightBurn" },
  { id: "ezcad", label: "EZCAD" },
];

export type ThemeId = "system" | "light" | "dark" | "neon" | "purple" | "blue";
export type ResolvedTheme = "light" | "dark" | "neon" | "purple" | "blue";
export type ThemeOption = { id: ThemeId; label: string; description: string };

export const THEME_OPTIONS: ThemeOption[] = [
  { id: "system", label: "System", description: "Match your device preference." },
  { id: "light", label: "Light", description: "Bright backgrounds, dark text." },
  { id: "dark", label: "Dark", description: "Dimmed panels for low light." },
  { id: "neon", label: "Neon Green", description: "Black UI with neon green accents." },
  { id: "purple", label: "Neon Purple", description: "Black UI with purple glow highlights." },
  { id: "blue", label: "Neon Blue", description: "Black UI with blue glow highlights." },
];

export type SlicerSettings = {
  enabled: boolean;
  selected: string;
};

export type EngravingSettings = {
  enabled: boolean;
  selected: string;
};

export type ThemeSettings = {
  selected: ThemeId;
};

export type MakerWorldSettings = {
  cookie: string;
};

export type ThingiverseSettings = {
  cookie: string;
};

export type NetworkSettings = {
  publicUrl: string;
};

export type PreviewMode = "automatic" | "on-demand" | "disabled";

export type PreviewSettings = {
  mode: PreviewMode;
};

export type AppSettings = {
  slicer: SlicerSettings;
  engraving: EngravingSettings;
  theme: ThemeSettings;
  makerworld: MakerWorldSettings;
  thingiverse: ThingiverseSettings;
  network: NetworkSettings;
  previews: PreviewSettings;
};

const STORAGE_KEY = "makersvault_settings";
const LEGACY_THEME_KEY = "makersvault_theme";

const DEFAULT_SETTINGS: AppSettings = {
  slicer: {
    enabled: false,
    selected: "orca",
  },
  engraving: {
    enabled: false,
    selected: "lightburn",
  },
  theme: {
    selected: "system",
  },
  makerworld: {
    cookie: "",
  },
  thingiverse: {
    cookie: "",
  },
  network: {
    publicUrl: "",
  },
  previews: {
    mode: "automatic",
  },
};

export function loadSettings(): AppSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) || {} : {};
    const slicer = parsed.slicer || {};
    const selected = typeof slicer.selected === "string" ? slicer.selected : DEFAULT_SETTINGS.slicer.selected;
    const enabled = typeof slicer.enabled === "boolean" ? slicer.enabled : DEFAULT_SETTINGS.slicer.enabled;
    const valid = SLICER_OPTIONS.some(opt => opt.id === selected);
    const engraving = parsed.engraving || {};
    const engravingSelected = typeof engraving.selected === "string"
      ? engraving.selected
      : DEFAULT_SETTINGS.engraving.selected;
    const engravingEnabled = typeof engraving.enabled === "boolean"
      ? engraving.enabled
      : DEFAULT_SETTINGS.engraving.enabled;
    const engravingValid = ENGRAVER_OPTIONS.some(opt => opt.id === engravingSelected);
    const theme = parsed.theme || {};
    let themeSelected = typeof theme.selected === "string" ? theme.selected : DEFAULT_SETTINGS.theme.selected;
    const themeValid = THEME_OPTIONS.some(opt => opt.id === themeSelected);
    const makerworld = parsed.makerworld || {};
    const cookie = typeof makerworld.cookie === "string" ? makerworld.cookie : DEFAULT_SETTINGS.makerworld.cookie;
    const thingiverse = parsed.thingiverse || {};
    const thingiverseCookie = typeof thingiverse.cookie === "string"
      ? thingiverse.cookie
      : DEFAULT_SETTINGS.thingiverse.cookie;
    const network = parsed.network || {};
    const publicUrl = typeof network.publicUrl === "string" ? network.publicUrl : DEFAULT_SETTINGS.network.publicUrl;
    const previews = parsed.previews || {};
    const previewMode = ["automatic", "on-demand", "disabled"].includes(previews.mode)
      ? previews.mode as PreviewMode
      : DEFAULT_SETTINGS.previews.mode;
    if (!themeValid) {
      const legacy = window.localStorage.getItem(LEGACY_THEME_KEY);
      if (legacy === "light" || legacy === "dark") {
        themeSelected = legacy;
      } else {
        themeSelected = DEFAULT_SETTINGS.theme.selected;
      }
    }
    return {
      slicer: {
        enabled,
        selected: valid ? selected : DEFAULT_SETTINGS.slicer.selected,
      },
      engraving: {
        enabled: engravingEnabled,
        selected: engravingValid ? engravingSelected : DEFAULT_SETTINGS.engraving.selected,
      },
      theme: {
        selected: themeSelected as ThemeId,
      },
      makerworld: {
        cookie,
      },
      thingiverse: {
        cookie: thingiverseCookie,
      },
      network: {
        publicUrl,
      },
      previews: {
        mode: previewMode,
      },
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: AppSettings) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // ignore storage errors
  }
}

export function slicerLabelFor(id?: string | null) {
  if (!id) return "Slicer";
  const match = SLICER_OPTIONS.find(opt => opt.id === id);
  return match ? match.label : "Slicer";
}

export function engraverLabelFor(id?: string | null) {
  if (!id) return "Engraving";
  const match = ENGRAVER_OPTIONS.find(opt => opt.id === id);
  return match ? match.label : "Engraving";
}

export function resolveTheme(selected: ThemeId): ResolvedTheme {
  if (selected === "system") {
    if (typeof window !== "undefined") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    return "light";
  }
  return selected;
}
