import React from "react";
import { getStorageCapabilities, type StorageCapabilities } from "../../lib/api";

export type StorageCapabilitiesState = {
  capabilities: StorageCapabilities | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};

/**
 * Snapshot capability of the configured storage volumes. Detection happens
 * server-side from the mounted filesystem; this hook only reports it.
 */
export function useStorageCapabilities(): StorageCapabilitiesState {
  const [capabilities, setCapabilities] = React.useState<StorageCapabilities | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const cancelled = React.useRef(false);

  const refresh = React.useCallback(async () => {
    try {
      const next = await getStorageCapabilities();
      if (cancelled.current) return;
      setCapabilities(next);
      setError(null);
    } catch {
      // Detection is advisory; a failure must not break the settings page.
      if (!cancelled.current) setError("Snapshot capability is unavailable.");
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

  return { capabilities, loading, error, refresh };
}
