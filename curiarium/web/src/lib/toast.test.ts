import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  dismissToast,
  getToasts,
  notifyError,
  notifyInfo,
  resetToasts,
  subscribeToasts,
} from "./toast";

describe("toast store", () => {
  beforeEach((): void => resetToasts());

  it("notifyError pushes an error toast with details and a retry action", () => {
    const retry = vi.fn();
    const id = notifyError("Failed to upload 1 file", {
      details: ["b.stl (disk full)"],
      retry,
    });

    expect(typeof id).toBe("number");
    const [toast] = getToasts();
    expect(getToasts()).toHaveLength(1);
    expect(toast.id).toBe(id);
    expect(toast.tone).toBe("error");
    expect(toast.message).toBe("Failed to upload 1 file");
    expect(toast.details).toEqual(["b.stl (disk full)"]);
    expect(toast.actions).toHaveLength(1);
    expect(toast.actions?.[0].label).toBe("Retry");
    expect(toast.actions?.[0].run).toBe(retry);
  });

  it("notifyInfo pushes an info toast without actions", () => {
    notifyInfo("Copied to clipboard", { details: ["12 assets"] });

    const [toast] = getToasts();
    expect(getToasts()).toHaveLength(1);
    expect(toast.tone).toBe("info");
    expect(toast.message).toBe("Copied to clipboard");
    expect(toast.details).toEqual(["12 assets"]);
    expect(toast.actions).toBeUndefined();
  });

  it("dismissToast removes exactly the requested toast", () => {
    const first = notifyError("first");
    const second = notifyInfo("second");
    const third = notifyError("third");

    dismissToast(second);
    expect(getToasts().map(toast => toast.id)).toEqual([first, third]);

    dismissToast(first);
    const remaining = getToasts();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].id).toBe(third);
    expect(remaining[0].message).toBe("third");
  });

  it("keeps only the four newest toasts", () => {
    for (let index = 0; index < 5; index += 1) notifyInfo(`toast ${index + 1}`);

    expect(getToasts()).toHaveLength(4);
    expect(getToasts().map(toast => toast.id)).toEqual([2, 3, 4, 5]);
    expect(getToasts().map(toast => toast.message)).toEqual([
      "toast 2",
      "toast 3",
      "toast 4",
      "toast 5",
    ]);
  });

  it("notifies subscribers on push and dismiss until they unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToasts(listener);

    const id = notifyInfo("hello");
    expect(listener).toHaveBeenCalledTimes(1);

    dismissToast(id);
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    notifyInfo("ignored");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("resetToasts empties the store and restarts id numbering", () => {
    notifyInfo("one");
    notifyInfo("two");
    expect(getToasts()).toHaveLength(2);

    resetToasts();
    expect(getToasts()).toHaveLength(0);

    const id = notifyInfo("fresh");
    expect(id).toBe(1);
  });

  it("returns a referentially stable snapshot between changes", () => {
    notifyInfo("stable");
    expect(getToasts()).toBe(getToasts());

    const first = getToasts();
    notifyInfo("mutated");
    expect(getToasts()).not.toBe(first);
  });
});
