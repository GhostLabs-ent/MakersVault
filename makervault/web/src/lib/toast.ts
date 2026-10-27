/**
 * Sticky, app-wide toast notifications held in a module singleton.
 *
 * A module singleton (like `settings.ts`) rather than a React context: toasts
 * are raised from plain async helpers deep in the UI, and there is no existing
 * context provider this app could hang one off. `useSyncExternalStore` in
 * `Toaster` turns the singleton into render state without prop drilling.
 *
 * A retry closure retains the `File`/`Blob` handles of the failed uploads until
 * its toast is dismissed. The 4-toast cap bounds how many of those closures can
 * be alive at once, and dropping the oldest entry releases its handles.
 */

export type ToastTone = "error" | "info";

export type ToastAction = {
  label: string;
  run: () => void | Promise<void>;
};

export type Toast = {
  id: number;
  tone: ToastTone;
  message: string;
  details?: string[];
  actions?: ToastAction[];
};

const MAX_TOASTS = 4;

// Only ever reassigned to a fresh array: `getToasts` doubles as the
// `useSyncExternalStore` snapshot and must be referentially stable between
// changes.
let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function notifyListeners(): void {
  for (const listener of [...listeners]) listener();
}

function pushToast(toast: Omit<Toast, "id">): number {
  const id = nextId++;
  const next = [...toasts, { ...toast, id }];
  toasts = next.length > MAX_TOASTS ? next.slice(next.length - MAX_TOASTS) : next;
  notifyListeners();
  return id;
}

export function notifyError(
  message: string,
  options?: { details?: string[]; retry?: () => void | Promise<void> },
): number {
  const actions: ToastAction[] = [];
  if (options?.retry) actions.push({ label: "Retry", run: options.retry });
  return pushToast({
    tone: "error",
    message,
    details: options?.details,
    actions: actions.length > 0 ? actions : undefined,
  });
}

export function notifyInfo(
  message: string,
  options?: { details?: string[] },
): number {
  return pushToast({ tone: "info", message, details: options?.details });
}

export function dismissToast(id: number): void {
  const next = toasts.filter(toast => toast.id !== id);
  if (next.length === toasts.length) return;
  toasts = next;
  notifyListeners();
}

/** Test-only: empties the store and restarts id numbering. */
export function resetToasts(): void {
  toasts = [];
  nextId = 1;
  notifyListeners();
}

export function subscribeToasts(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Returns the store array itself (not a copy) so `useSyncExternalStore` can cache it. */
export function getToasts(): Toast[] {
  return toasts;
}
