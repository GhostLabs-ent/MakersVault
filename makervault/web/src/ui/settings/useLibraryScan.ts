import React from "react";
import { getLibraryScanStatus, startLibraryScan, type LibraryScanStatus } from "../../lib/api";

export type LibraryScanState = {
  scan: LibraryScanStatus | null;
  busy: boolean;
  error: string | null;
  run: () => Promise<void>;
};

export function useLibraryScan(): LibraryScanState {
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
