/** Top-level browsing mode of the library. */
export type LibraryMode = "files" | "projects";

export const MODE_STORAGE_KEY = "curiarium_library_mode";

const MODES: readonly LibraryMode[] = ["files", "projects"];
const DEFAULT_MODE: LibraryMode = "files";

/** The persisted mode, or "files" when nothing valid is stored. */
export function loadMode(): LibraryMode {
  if (typeof window === "undefined") return DEFAULT_MODE;
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(MODE_STORAGE_KEY);
  } catch {
    // Unreadable storage cannot be trusted: fall back to the default.
    return DEFAULT_MODE;
  }
  // Only an exact match counts, so stale or hand-edited values cannot put the
  // UI into a mode it does not know how to render.
  return MODES.includes(raw as LibraryMode) ? (raw as LibraryMode) : DEFAULT_MODE;
}

/** Persists the mode; storage failures are ignored (the mode still applies for this session). */
export function saveMode(mode: LibraryMode): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MODE_STORAGE_KEY, mode);
  } catch {
    // ignore storage errors
  }
}
