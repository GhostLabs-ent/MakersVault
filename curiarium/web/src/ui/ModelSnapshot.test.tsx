// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import { PREVIEW_MAX_ATTEMPTS, PREVIEW_RETRY_MS, PREVIEW_SETTLE_MS, PreviewQueue } from "../lib/previewQueue";
import { ModelSnapshot } from "./ModelViewer";

type SnapshotJobSpy = (
  url: string,
  ext: string,
  width: number,
  height: number,
  theme: string,
  signal: AbortSignal,
) => Promise<string>;

type ObserverRecord = {
  callback: IntersectionObserverCallback;
  targets: Element[];
};

const observers: ObserverRecord[] = [];

class FakeIntersectionObserver {
  private readonly record: ObserverRecord;

  constructor(callback: IntersectionObserverCallback) {
    this.record = { callback, targets: [] };
    observers.push(this.record);
  }

  observe(target: Element) {
    this.record.targets.push(target);
  }

  unobserve() {}

  disconnect() {}

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

function fireIntersections() {
  act(() => {
    for (const record of observers) {
      record.callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    }
  });
}

function renderCards(tag: string, queue: PreviewQueue, job: SnapshotJobSpy, count: number) {
  return (
    <div>
      {Array.from({ length: count }, (_, index) => (
        <ModelSnapshot
          key={index}
          url={`/api/assets/${tag}-${index}/file`}
          ext="stl"
          theme="light"
          queue={queue}
          job={job}
        />
      ))}
    </div>
  );
}

async function settleDwell() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(PREVIEW_SETTLE_MS);
  });
}

/** Advances time in retry-sized chunks so retries scheduled mid-run also fire. */
async function settleRetries(chunks: number) {
  for (let i = 0; i < chunks; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PREVIEW_RETRY_MS);
    });
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(res => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  observers.length = 0;
  vi.useFakeTimers();
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("ModelSnapshot preview budget", () => {
  it("never enqueues the 197 cards that scrolled away before the dwell elapsed", async () => {
    const queue = new PreviewQueue();
    const jobSpy = vi.fn(async () => "data:image/png;base64,AA==");
    const view = render(renderCards("mass", queue, jobSpy, 200));

    fireIntersections();

    // Unmount everything except three cards before their settle timers fire.
    view.rerender(renderCards("mass", queue, jobSpy, 3));
    await settleDwell();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(jobSpy).toHaveBeenCalledTimes(3);
    expect(queue.getStats().started).toBe(3);
    expect(queue.getStats().aborted).toBe(0);
    expect(jobSpy.mock.calls.length).toBeLessThan(200);
  });

  it("drops a queued job when its card unmounts without errors or state writes", async () => {
    const queue = new PreviewQueue();
    const first = deferred<string>();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const jobSpy = vi.fn((url: string) =>
      url.includes("-0/") ? first.promise : Promise.resolve("data:image/png;base64,AA=="),
    );
    const view = render(renderCards("drop", queue, jobSpy, 2));

    fireIntersections();
    await settleDwell();

    expect(jobSpy).toHaveBeenCalledTimes(1);
    expect(queue.getStats().queued).toBe(1);

    view.rerender(renderCards("drop", queue, jobSpy, 1));
    await act(async () => {
      first.resolve("data:image/png;base64,BB==");
      await Promise.resolve();
    });

    expect(jobSpy).toHaveBeenCalledTimes(1);
    expect(jobSpy.mock.calls[0][0]).toContain("-0/");
    expect(queue.getStats().completed).toBe(1);
    expect(queue.getStats().queued).toBe(0);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("shows the budget message and never calls the job once the session budget is gone", async () => {
    const queue = new PreviewQueue({ sessionBudgetMs: 0 });
    const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const enqueueSpy = vi.spyOn(queue, "enqueue");
    const jobSpy = vi.fn(async () => "data:image/png;base64,AA==");

    render(renderCards("budget", queue, jobSpy, 1));
    fireIntersections();
    await settleDwell();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByText("Preview budget reached")).toBeTruthy();
    expect(jobSpy).not.toHaveBeenCalled();
    expect(enqueueSpy).toHaveBeenCalledTimes(1);
    expect(queue.getStats().budgetDenied).toBe(1);
    expect(consoleWarn).toHaveBeenCalledWith(expect.stringContaining("[preview] session budget exhausted"));

    // An exhausted budget is terminal for the card: no retry, no extra enqueue.
    await settleRetries(10);
    expect(enqueueSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Preview budget reached")).toBeTruthy();
  });

  it("never runs two preview jobs concurrently even when two cards settle together", async () => {
    const queue = new PreviewQueue();
    const releases: Array<() => void> = [];
    let live = 0;
    let maxLive = 0;
    const jobSpy = vi.fn(
      () =>
        new Promise<string>(resolve => {
          live += 1;
          maxLive = Math.max(maxLive, live);
          releases.push(() => {
            live -= 1;
            resolve("data:image/png;base64,AA==");
          });
        }),
    );

    render(renderCards("serial", queue, jobSpy, 2));
    fireIntersections();
    await settleDwell();

    expect(jobSpy).toHaveBeenCalledTimes(1);
    expect(queue.getStats().queued).toBe(1);

    await act(async () => {
      releases.shift()!();
      await Promise.resolve();
    });
    expect(jobSpy).toHaveBeenCalledTimes(2);

    await act(async () => {
      releases.shift()!();
      await Promise.resolve();
    });

    expect(maxLive).toBe(1);
    expect(queue.getStats().completed).toBe(2);
  });
});

describe("ModelSnapshot dropped-card recovery", () => {
  it("retries a dropped-but-visible card until its preview renders", async () => {
    const queue = new PreviewQueue({ maxPending: 1 });
    const enqueueSpy = vi.spyOn(queue, "enqueue");
    const first = deferred<string>();
    const jobSpy = vi.fn((url: string) =>
      url.includes("-0/") ? first.promise : Promise.resolve("data:image/png;base64,AA=="),
    );

    render(renderCards("retry", queue, jobSpy, 3));
    fireIntersections();
    await settleDwell();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // One active plus one queued card are admitted; the third is dropped.
    expect(queue.getStats().started).toBe(1);
    expect(queue.getStats().queued).toBe(1);
    expect(queue.getStats().dropped).toBe(1);
    expect(screen.queryByAltText("Preview")).toBeNull();

    await act(async () => {
      first.resolve("data:image/png;base64,BB==");
      await Promise.resolve();
    });
    expect(queue.getStats().completed).toBe(2);

    // The visible card is not stranded: its bounded retry now gets a slot.
    await settleRetries(1);

    expect(jobSpy).toHaveBeenCalledTimes(3);
    expect(jobSpy.mock.calls[2][0]).toBe("/api/assets/retry-2/file");
    expect(screen.getAllByAltText("Preview")).toHaveLength(3);
    expect(queue.getStats().started).toBe(3);
    expect(queue.getStats().completed).toBe(3);

    // Three first attempts plus one retry: the enqueues outnumber the cards
    // that were admitted on the first pass (the active card and one queued one).
    expect(enqueueSpy.mock.calls.length).toBeGreaterThan(2);
    expect(enqueueSpy).toHaveBeenCalledTimes(4);
  });

  it("stops retrying a card that is never admitted and shows the error state", async () => {
    const queue = new PreviewQueue({ maxPending: 0 });
    const enqueueSpy = vi.spyOn(queue, "enqueue");
    const jobSpy = vi.fn(async () => "data:image/png;base64,AA==");

    render(renderCards("never", queue, jobSpy, 1));
    fireIntersections();
    await settleDwell();
    await settleRetries(10);

    expect(jobSpy).not.toHaveBeenCalled();
    expect(enqueueSpy).toHaveBeenCalledTimes(1 + PREVIEW_MAX_ATTEMPTS);
    expect(screen.getByText("Preview unavailable")).toBeTruthy();

    // Retries are terminal at the cap: more time adds no more work.
    await settleRetries(10);
    expect(enqueueSpy).toHaveBeenCalledTimes(1 + PREVIEW_MAX_ATTEMPTS);
    expect(screen.getByText("Preview unavailable")).toBeTruthy();
  });
});
