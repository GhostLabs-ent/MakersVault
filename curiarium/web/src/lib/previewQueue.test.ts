import { afterEach, describe, expect, it, vi } from "vitest";

import { PreviewQueue } from "./previewQueue";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(res => {
    resolve = res;
  });
  return { promise, resolve };
}

async function flushMicrotasks(times = 10) {
  for (let i = 0; i < times; i += 1) {
    await Promise.resolve();
  }
}

/** A queued job that never settles until its deferred is resolved by the test. */
function heldJob(name: string, started: string[], releases: Array<() => void>) {
  return {
    signal: new AbortController().signal,
    run: () =>
      new Promise<string>(resolve => {
        started.push(name);
        releases.push(() => resolve(name));
      }),
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("PreviewQueue", () => {
  it("runs one job at a time in FIFO order", async () => {
    const queue = new PreviewQueue();
    const started: string[] = [];
    const releases: Array<() => void> = [];
    let live = 0;
    let maxLive = 0;

    const make = (name: string) => ({
      signal: new AbortController().signal,
      run: () =>
        new Promise<string>(resolve => {
          started.push(name);
          live += 1;
          maxLive = Math.max(maxLive, live);
          releases.push(() => {
            live -= 1;
            resolve(name);
          });
        }),
    });

    const results = [queue.enqueue(make("a")), queue.enqueue(make("b")), queue.enqueue(make("c"))];
    expect(started).toEqual(["a"]);
    expect(queue.getStats().active).toBe(1);
    expect(queue.getStats().queued).toBe(2);

    for (let i = 0; i < 3; i += 1) {
      await flushMicrotasks();
      expect(releases).toHaveLength(1);
      releases.shift()!();
    }
    await flushMicrotasks();

    expect(await Promise.all(results)).toEqual(["a", "b", "c"]);
    expect(started).toEqual(["a", "b", "c"]);
    expect(maxLive).toBe(1);
    expect(queue.getStats().completed).toBe(3);
    expect(queue.getStats().active).toBe(0);
    expect(queue.getStats().queued).toBe(0);
  });

  it("never starts a job whose card aborted before it was dequeued", async () => {
    const queue = new PreviewQueue();
    const started: string[] = [];
    const releases: Array<() => void> = [];
    const controllers = [new AbortController(), new AbortController(), new AbortController()];
    const make = (name: string, index: number) => ({
      signal: controllers[index].signal,
      run: () =>
        new Promise<string>(resolve => {
          started.push(name);
          releases.push(() => resolve(name));
        }),
    });

    const results = [queue.enqueue(make("a", 0)), queue.enqueue(make("b", 1)), queue.enqueue(make("c", 2))];
    expect(started).toEqual(["a"]);

    controllers[1].abort();
    await flushMicrotasks();
    expect(queue.getStats().aborted).toBe(1);
    expect(started).toEqual(["a"]);

    releases.shift()!();
    await flushMicrotasks();
    expect(started).toEqual(["a", "c"]);
    releases.shift()!();
    await flushMicrotasks();

    expect(await results[0]).toBe("a");
    expect(await results[1]).toBeNull();
    expect(await results[2]).toBe("c");
    expect(started).not.toContain("b");
  });

  it("rejects an already-aborted job on entry without running it", async () => {
    const queue = new PreviewQueue();
    const controller = new AbortController();
    controller.abort();
    const run = vi.fn(async () => "unreachable");

    await expect(queue.enqueue({ signal: controller.signal, run })).resolves.toBeNull();

    expect(run).not.toHaveBeenCalled();
    expect(queue.getStats().aborted).toBe(1);
  });

  it("resolves the caller null on an active abort but holds the slot until the stale run unwinds", async () => {
    const queue = new PreviewQueue();
    const stale = deferred<string>();
    const started: string[] = [];
    let live = 0;
    let maxLive = 0;
    const controllers = [new AbortController(), new AbortController(), new AbortController()];

    const results = [
      queue.enqueue({
        signal: controllers[0].signal,
        run: async () => {
          started.push("a");
          live += 1;
          maxLive = Math.max(maxLive, live);
          try {
            return await stale.promise;
          } finally {
            live -= 1;
          }
        },
      }),
      queue.enqueue({
        signal: controllers[1].signal,
        run: async () => {
          started.push("b");
          live += 1;
          maxLive = Math.max(maxLive, live);
          await Promise.resolve();
          live -= 1;
          return "b";
        },
      }),
    ];

    expect(started).toEqual(["a"]);
    controllers[0].abort();
    await flushMicrotasks();

    // The caller is settled immediately, but the abandoned run still owns the slot.
    expect(await results[0]).toBeNull();
    expect(queue.getStats().aborted).toBe(1);
    expect(queue.getStats().active).toBe(1);
    expect(started).toEqual(["a"]);

    stale.resolve("stale result");
    await flushMicrotasks();

    expect(await results[1]).toBe("b");
    expect(queue.getStats().completed).toBe(1);
    expect(queue.getStats().aborted).toBe(1);
    expect(maxLive).toBe(1);
  });

  it("bounds the pending queue and resolves the overflow immediately", async () => {
    const queue = new PreviewQueue({ maxPending: 2 });
    const started: string[] = [];
    const releases: Array<() => void> = [];

    const results = [queue.enqueue(heldJob("active", started, releases))];
    for (let i = 0; i < 7; i += 1) {
      results.push(queue.enqueue(heldJob(`extra-${i}`, started, releases)));
    }

    const stats = queue.getStats();
    expect(stats.queued).toBe(2);
    expect(stats.dropped).toBe(5);

    const extraResults = await Promise.all(results.slice(3));
    expect(extraResults).toEqual([null, null, null, null, null]);

    // One active plus at most `maxPending` queued jobs ever reach `run`.
    for (let i = 0; i < 3; i += 1) {
      await flushMicrotasks();
      releases.shift()!();
    }
    await flushMicrotasks();
    expect(started).toEqual(["active", "extra-0", "extra-1"]);
  });

  it("denies new work once the per-session budget is spent", async () => {
    vi.useFakeTimers();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const queue = new PreviewQueue({ sessionBudgetMs: 100, jobBudgetMs: 10_000 });
    const run = vi.fn(
      async () => {
        await new Promise(resolve => setTimeout(resolve, 60));
        return "ok";
      },
    );

    const first = queue.enqueue({ signal: new AbortController().signal, run });
    const second = queue.enqueue({ signal: new AbortController().signal, run });
    await vi.advanceTimersByTimeAsync(60);
    await vi.advanceTimersByTimeAsync(60);
    await Promise.all([first, second]);

    const spent = queue.getStats();
    expect(spent.completed).toBe(2);
    expect(spent.spentMs).toBeGreaterThanOrEqual(100);
    expect(spent.exhausted).toBe(true);

    const denied = queue.enqueue({ signal: new AbortController().signal, run });
    await expect(denied).resolves.toBeNull();
    expect(run).toHaveBeenCalledTimes(2);
    expect(queue.getStats().budgetDenied).toBe(1);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("[preview] session budget exhausted"));

    // Further cards are denied silently: the budget warning fires once.
    await expect(queue.enqueue({ signal: new AbortController().signal, run })).resolves.toBeNull();
    expect(queue.getStats().budgetDenied).toBe(2);
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("aborts a job that blows its wall-clock budget and runs the next one", async () => {
    vi.useFakeTimers();
    const queue = new PreviewQueue({ jobBudgetMs: 1_000 });
    const started: string[] = [];
    let innerAborted = false;

    const slow = queue.enqueue({
      signal: new AbortController().signal,
      run: signal =>
        new Promise<string>((_resolve, reject) => {
          started.push("slow");
          signal.addEventListener("abort", () => {
            innerAborted = true;
            reject(new Error("aborted by job budget"));
          });
        }),
    });
    const next = queue.enqueue({
      signal: new AbortController().signal,
      run: async () => {
        started.push("next");
        return "next-result";
      },
    });

    await vi.advanceTimersByTimeAsync(1_000);

    expect(innerAborted).toBe(true);
    expect(await slow).toBeNull();
    expect(await next).toBe("next-result");
    expect(started).toEqual(["slow", "next"]);
    expect(queue.getStats().timedOut).toBe(1);
    expect(queue.getStats().active).toBe(0);
  });

  it("rejects the caller on a genuine failure and keeps the queue moving", async () => {
    const queue = new PreviewQueue();
    const failing = queue.enqueue({
      signal: new AbortController().signal,
      run: async () => {
        throw new Error("boom");
      },
    });
    const next = queue.enqueue({
      signal: new AbortController().signal,
      run: async () => "ok",
    });

    await expect(failing).rejects.toThrow("boom");
    await expect(next).resolves.toBe("ok");
    expect(queue.getStats().active).toBe(0);
    expect(queue.getStats().completed).toBe(1);
  });

  it("emits one observable counter line per settled job", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const queue = new PreviewQueue();
    const run = async () => "done";

    await queue.enqueue({ signal: new AbortController().signal, run });
    await queue.enqueue({ signal: new AbortController().signal, run });

    expect(info.mock.calls.length).toBeGreaterThanOrEqual(2);
    for (const call of info.mock.calls) {
      const line = String(call[0]);
      expect(line).toContain("[preview]");
      expect(line).toContain("spent=");
    }
    const last = String(info.mock.calls[info.mock.calls.length - 1][0]);
    expect(last).toContain("started=2");
    expect(last).toContain("done=2");
  });
});
