import React from "react";
import { getLibraryScanStatus, startLibraryScan, type LibraryScanStatus } from "../../lib/api";

export type LibraryScanState = {
  scan: LibraryScanStatus | null;
  busy: boolean;
  error: string | null;
  run: () => Promise<void>;
};

export type LibraryScanCallbacks = {
  /** A scan registers assets and creates folders from the directory tree, so both
   *  the grid and the sidebar must reload when it finishes. Without this the tree
   *  stayed stale until a manual refresh (found in live testing, 2026-10-31). */
  onAssetsChanged?: () => void;
  onFoldersChanged?: () => void;
};

export function useLibraryScan({ onAssetsChanged, onFoldersChanged }: LibraryScanCallbacks = {}): LibraryScanState {
  const [libraryScan, setLibraryScan] = React.useState<LibraryScanStatus | null>(null);
  const [libraryScanBusy, setLibraryScanBusy] = React.useState(false);
  const [libraryScanError, setLibraryScanError] = React.useState<string | null>(null);

  const refreshLibraryScan = React.useCallback(async () => {
    try {
      setLibraryScan(await getLibraryScanStatus());
    } catch {
      // scan status is advisory; a failure must not break the settings page
    }
  }, []);

  React.useEffect(() => {
    if (!libraryScan?.running) return;
    const timer = window.setTimeout(refreshLibraryScan, 1500);
    return () => window.clearTimeout(timer);
  }, [libraryScan, refreshLibraryScan]);

  // Fire once per completed scan, on the running -> finished transition. A scan
  // can also finish between polls, so `finished_at` is the signal, not `running`.
  const finishedMarker = libraryScan && !libraryScan.running ? libraryScan.finished_at : null;
  const announced = React.useRef<number | null>(null);
  React.useEffect(() => {
    if (finishedMarker == null || announced.current === finishedMarker) return;
    announced.current = finishedMarker;
    onFoldersChanged?.();
    onAssetsChanged?.();
  }, [finishedMarker, onFoldersChanged, onAssetsChanged]);

  const runLibraryScan = async () => {
    setLibraryScanBusy(true);
    setLibraryScanError(null);
    try {
      setLibraryScan(await startLibraryScan());
    } catch (err) {
      setLibraryScanError(err instanceof Error ? err.message : "Failed to start scan");
    } finally {
      setLibraryScanBusy(false);
    }
  };

  return {
    scan: libraryScan,
    busy: libraryScanBusy,
    error: libraryScanError,
    run: runLibraryScan,
  };
}
