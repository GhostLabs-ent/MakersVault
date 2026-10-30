import { useCallback, useLayoutEffect, useRef } from "react";

/**
 * Returns a callback whose identity never changes, while the body it runs is
 * always the latest render's closure (so there are no stale closures).
 *
 * The returned function is intended for event handlers and effects only: it
 * must not be invoked during render, because the ref it delegates to is
 * synchronised in a layout effect (no dependency array, so it also stays
 * correct under React 18 StrictMode's development double-invoke).
 */
export function useStableCallback<T extends (...args: never[]) => unknown>(callback: T): T {
  const callbackRef = useRef(callback);

  useLayoutEffect(() => {
    callbackRef.current = callback;
  });

  const stableCallback = useCallback(
    (...args: Parameters<T>) => callbackRef.current(...args),
    [],
  );

  return stableCallback as T;
}
