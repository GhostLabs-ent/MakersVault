import React from "react";
import { getImportRun, getImportRuns, type ImportRunDetail } from "../../lib/api";

export type ImportRunsState = {
  run: ImportRunDetail | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};

const POLL_MS = 1500;

/**
 * Latest mounted-import run, with per-file errors. The list endpoint has no
 * detail payload, so a second call fetches the newest run by id.
 */
export function useImportRuns(): ImportRunsState {
  const [run, setRun] = React.useState<ImportRunDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const cancelled = React.useRef(false);

  const refresh = React.useCallback(async () => {
    try {
      const list = await getImportRuns(1, 0);
      const latest = list.runs[0];
      if (!latest) {
        if (cancelled.current) return;
        setRun(null);
        setError(null);
        return;
      }
      const detail = await getImportRun(latest.id);
      if (cancelled.current) return;
      setRun(detail);
      setError(null);
    } catch {
      // Run history is advisory; a failure must not break the settings page.
      if (!cancelled.current) setError("Import run history is unavailable.");
    } finally {
      if (!cancelled.current) setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    cancelled.current = false;
    void refresh();
    return () => {
      cancelled.current = true;
    };
  }, [refresh]);

  React.useEffect(() => {
    if (run?.status !== "running") return;
    const timer = window.setTimeout(refresh, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [run, refresh]);

  return { run, loading, error, refresh };
}
