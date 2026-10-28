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
  { id: "other", label: "Other / Manual" },
];

export type EngraverOption = { id: string; label: string };

export const ENGRAVER_OPTIONS: EngraverOption[] = [
  { id: "lightburn", label: "LightBurn" },
  { id: "ezcad", label: "EZCAD" },
  { id: "other", label: "Other / Manual" },
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

export type ImportSettings = {
  rememberCookies: boolean;
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
  imports: ImportSettings;
  network: NetworkSettings;
  previews: PreviewSettings;
};

const STORAGE_KEY = "makersvault_settings";
const LEGACY_THEME_KEY = "makersvault_theme";
const SESSION_COOKIES_KEY = "makersvault_session_cookies";

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
  imports: {
    rememberCookies: false,
  },
  network: {
    publicUrl: "",
  },
  previews: {
    mode: "automatic",
  },
};

type StoredCookies = {
  makerworld: string;
  thingiverse: string;
};

const EMPTY_COOKIES: StoredCookies = { makerworld: "", thingiverse: "" };

type SessionCookieSnapshot = {
  raw: string | null;
  cookies: StoredCookies;
};

/** Parses a raw session-cookie payload; unknown shapes degrade to empty cookies and never throw. */
function parseSessionCookies(raw: string): StoredCookies {
  try {
    const parsed = JSON.parse(raw) || {};
    return {
      makerworld: typeof parsed.makerworld === "string" ? parsed.makerworld : "",
      thingiverse: typeof parsed.thingiverse === "string" ? parsed.thingiverse : "",
    };
  } catch {
    return EMPTY_COOKIES;
  }
}

/**
 * Reads the session-scoped cookie snapshot.
 *
 * `sessionStorage` throws in some privacy modes, which is treated as an empty
 * store. The raw string is returned alongside the parsed cookies so the
 * settings cache can revalidate on it; an absent key is never parsed.
 */
function readSessionCookies(): SessionCookieSnapshot {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(SESSION_COOKIES_KEY);
  } catch {
    return { raw: null, cookies: EMPTY_COOKIES };
  }
  if (!raw) return { raw, cookies: EMPTY_COOKIES };
  return { raw, cookies: parseSessionCookies(raw) };
}

/** Writes the session-scoped cookie snapshot, dropping the key when both values are empty. */
function persistSessionCookies(cookies: StoredCookies): void {
  try {
    if (!cookies.makerworld && !cookies.thingiverse) {
      window.sessionStorage.removeItem(SESSION_COOKIES_KEY);
      return;
    }
    window.sessionStorage.setItem(SESSION_COOKIES_KEY, JSON.stringify(cookies));
  } catch {
    // Session storage unavailable; the cookie just stays in memory.
  }
}

/**
 * Picks the cookie value a load should hand back.
 *
 * A remembered cookie lives in the long-lived blob; otherwise the session copy
 * wins and the blob value is only the fallback, so a build that predates the
 * opt-in keeps its cookie in memory until the first save migrates it out.
 */
function resolveCookie(remembered: boolean, storedValue: string, sessionValue: string): string {
  if (remembered) return storedValue;
  return sessionValue || storedValue;
}

type SettingsCacheEntry = {
  raw: string | null;
  legacyTheme: string | null;
  sessionCookies: string | null;
  settings: AppSettings;
};

// Single-entry cache keyed by the two raw storage strings. `null` is a valid
// key (empty storage), so the uninitialized state is `null` for the entry
// itself rather than an entry with `raw: null`.
let settingsCache: SettingsCacheEntry | null = null;

/**
 * Parses and validates a raw settings payload.
 *
 * Pure: callers pass the raw storage values in, so this never reads
 * `localStorage` itself. `legacyTheme` is only consulted when the stored theme
 * is missing or invalid. `sessionCookies` supplies the session-scoped cookie
 * values. Malformed JSON yields `DEFAULT_SETTINGS`.
 */
function parseStoredSettings(
  raw: string | null,
  legacyTheme: string | null,
  sessionCookies: StoredCookies,
): AppSettings {
  try {
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
    const imports = parsed.imports || {};
    const rememberCookies = typeof imports.rememberCookies === "boolean"
      ? imports.rememberCookies
      : DEFAULT_SETTINGS.imports.rememberCookies;
    const makerworld = parsed.makerworld || {};
    const storedCookie = typeof makerworld.cookie === "string"
      ? makerworld.cookie
      : DEFAULT_SETTINGS.makerworld.cookie;
    const thingiverse = parsed.thingiverse || {};
    const storedThingiverseCookie = typeof thingiverse.cookie === "string"
      ? thingiverse.cookie
      : DEFAULT_SETTINGS.thingiverse.cookie;
    // A legacy blob holding cookies with no `imports` key resolves to the blob
    // fallback here; the App mount save then blanks the blob and writes the
    // session store, so migration needs no separate pass.
    const cookie = resolveCookie(rememberCookies, storedCookie, sessionCookies.makerworld);
    const thingiverseCookie = resolveCookie(
      rememberCookies,
      storedThingiverseCookie,
      sessionCookies.thingiverse,
    );
    const network = parsed.network || {};
    const publicUrl = typeof network.publicUrl === "string" ? network.publicUrl : DEFAULT_SETTINGS.network.publicUrl;
    const previews = parsed.previews || {};
    const previewMode = ["automatic", "on-demand", "disabled"].includes(previews.mode)
      ? previews.mode as PreviewMode
      : DEFAULT_SETTINGS.previews.mode;
    if (!themeValid) {
      if (legacyTheme === "light" || legacyTheme === "dark") {
        themeSelected = legacyTheme;
      } else {
        themeSelected = DEFAULT_SETTINGS.theme.selected;
      }
    }
    return freezeSettings({
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
      imports: {
        rememberCookies,
      },
      network: {
        publicUrl,
      },
      previews: {
        mode: previewMode,
      },
    });
  } catch {
    // DEFAULT_SETTINGS is shared and must stay mutable: freeze only freshly
    // built settings objects.
    return DEFAULT_SETTINGS;
  }
}

/** Freezes a freshly parsed settings object so the cached reference cannot be mutated in place. */
function freezeSettings(settings: AppSettings): AppSettings {
  Object.freeze(settings.slicer);
  Object.freeze(settings.engraving);
  Object.freeze(settings.theme);
  Object.freeze(settings.makerworld);
  Object.freeze(settings.thingiverse);
  Object.freeze(settings.imports);
  Object.freeze(settings.network);
  Object.freeze(settings.previews);
  return Object.freeze(settings);
}

/**
 * Returns the parsed application settings.
 *
 * The result is a cached, frozen, shared reference - do not mutate it; copy
 * before editing. The cache revalidates on every call by comparing both stored
 * strings plus the session cookie string, so a change from this tab, another
 * tab, devtools or a test stub is picked up by the very next call. A hit costs
 * three `getItem` calls and three string comparisons (no `JSON.parse`); a miss
 * re-parses once and caches, including malformed JSON, which is cached as the
 * default settings. Read-only: any migration of a legacy blob happens on the
 * next `saveSettings`, never here.
 */
export function loadSettings(): AppSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;

  let raw: string | null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Storage is unreadable, so nothing can be cached or trusted.
    return DEFAULT_SETTINGS;
  }

  // A failing legacy read must not discard otherwise valid main settings.
  let legacyTheme: string | null = null;
  try {
    legacyTheme = window.localStorage.getItem(LEGACY_THEME_KEY);
  } catch {
    legacyTheme = null;
  }

  const session = readSessionCookies();

  if (
    settingsCache
    && settingsCache.raw === raw
    && settingsCache.legacyTheme === legacyTheme
    && settingsCache.sessionCookies === session.raw
  ) {
    return settingsCache.settings;
  }

  const settings = parseStoredSettings(raw, legacyTheme, session.cookies);
  settingsCache = { raw, legacyTheme, sessionCookies: session.raw, settings };
  return settings;
}

/** Test-only: drops the cached snapshot so stubbed or cleared stores cannot serve stale settings. */
export function resetSettingsCache(): void {
  settingsCache = null;
}

export function saveSettings(settings: AppSettings): void {
  if (typeof window === "undefined") return;
  const { rememberCookies } = settings.imports;
  // The session store is the only at-rest copy unless the user opted in, and a
  // remembered cookie must not linger in a second store.
  const persisted: AppSettings = {
    ...settings,
    makerworld: { cookie: rememberCookies ? settings.makerworld.cookie : "" },
    thingiverse: { cookie: rememberCookies ? settings.thingiverse.cookie : "" },
  };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  } catch {
    // ignore storage errors
  }
  persistSessionCookies(
    rememberCookies
      ? EMPTY_COOKIES
      : { makerworld: settings.makerworld.cookie, thingiverse: settings.thingiverse.cookie },
  );
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
