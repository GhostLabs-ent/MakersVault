import React from "react";
import { UnauthorizedError } from "../../lib/api";
import type { Section } from "./types";

type LoadOptions<T> = {
  section: Section;
  active: boolean;
  load: () => Promise<T>;
  onLoaded: (data: T) => void;
  onUnauthorized?: () => void;
  onError: (err: unknown) => void;
};

/**
 * The load / error / loading boilerplate shared by the storage and mount-import
 * sections. The effect re-runs only when the section or the unauthorized handler
 * changes: the load and result callbacks are held in refs so an inline callback
 * cannot trigger a re-fetch.
 */
export function useSettingsSection<T>({
  section,
  active,
  load,
  onLoaded,
  onUnauthorized,
  onError,
}: LoadOptions<T>): { loading: boolean } {
  const [loading, setLoading] = React.useState(false);
  const loadRef = React.useRef(load);
  const onLoadedRef = React.useRef(onLoaded);
  const onErrorRef = React.useRef(onError);
  loadRef.current = load;
  onLoadedRef.current = onLoaded;
  onErrorRef.current = onError;

  React.useEffect(() => {
    if (!active) return;
    let alive = true;
    setLoading(true);
    void (async () => {
      try {
        const data = await loadRef.current();
        if (!alive) return;
        onLoadedRef.current(data);
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
        } else {
          onErrorRef.current(err);
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [section, active, onUnauthorized]);

  return { loading };
}

type SaveOptions = {
  onUnauthorized?: () => void;
  onError: (err: unknown) => void;
};

/** The save / error / saving boilerplate shared by the storage and mount-import saves. */
export function useSettingsSave({ onUnauthorized, onError }: SaveOptions): {
  saving: boolean;
  save: <T>(action: () => Promise<T>) => Promise<T | null>;
} {
  const [saving, setSaving] = React.useState(false);

  const save = async <T>(action: () => Promise<T>): Promise<T | null> => {
    setSaving(true);
    try {
      return await action();
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
      } else {
        onError(err);
      }
      return null;
    } finally {
      setSaving(false);
    }
  };

  return { saving, save };
}
