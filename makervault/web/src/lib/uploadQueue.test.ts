// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createUploadQueue,
  uploadQueue,
  type UploadJob,
  type UploadTransport,
} from "./uploadQueue";

function makeJob(name: string): UploadJob {
  return {
    entry: { file: new File(["0123456789"], name), relativePath: `folder/${name}` },
    folderId: "folder-1",
  };
}

function makeJobs(count: number, prefix = "file"): UploadJob[] {
  return Array.from({ length: count }, (_unused, index) => makeJob(`${prefix}-${index}.stl`));
}

async function flushMicrotasks(times = 20): Promise<void> {
  for (let i = 0; i < times; i += 1) await Promise.resolve();
}

function retryableError(message = "flaky"): Error {
  return Object.assign(new Error(message), { retryable: true });
}

function unauthorizedError(): Error {
  return Object.assign(new Error("Unauthorized"), { name: "UnauthorizedError" });
}

/** Transport that resolves on the next microtask, instrumented for concurrency. */
function trackingTransport(state: { current: number; peak: number }): UploadTransport {
  return async () => {
    state.current += 1;
    state.peak = Math.max(state.peak, state.current);
    await Promise.resolve();
    state.current -= 1;
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("createUploadQueue", () => {
  it("keeps peak in-flight uploads at or below the concurrency cap", async () => {
    const state = { current: 0, peak: 0 };
    const queue = createUploadQueue({ concurrency: 4, transport: trackingTransport(state) });

    const result = await queue.run(makeJobs(500));

    expect(state.peak).toBeLessThanOrEqual(4);
    expect(result.uploaded).toHaveLength(500);
    expect(queue.getTasks().every(task => task.status === "done")).toBe(true);
  });

  it("shares one global cap across concurrently started runs", async () => {
    const state = { current: 0, peak: 0 };
    const queue = createUploadQueue({ concurrency: 4, transport: trackingTransport(state) });

    const [first, second] = await Promise.all([queue.run(makeJobs(50, "a")), queue.run(makeJobs(50, "b"))]);

    expect(state.peak).toBeLessThanOrEqual(4);
    expect(first.uploaded).toHaveLength(50);
    expect(second.uploaded).toHaveLength(50);
  });

  it("starts uploads in submission order", async () => {
    const started: string[] = [];
    const transport: UploadTransport = async job => {
      started.push(job.entry.file.name);
    };
    const queue = createUploadQueue({ concurrency: 2, transport });
    const jobs = makeJobs(6);

    await queue.run(jobs);

    expect(started).toEqual(jobs.map(job => job.entry.file.name));
  });

  it("publishes a fresh task array on progress with the latest loaded value", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>(resolve => {
      release = resolve;
    });
    const transport: UploadTransport = async (_job, ctx) => {
      ctx.onProgress({ loaded: 3, total: 10 });
      await gate;
      ctx.onProgress({ loaded: 9, total: 10 });
    };
    const queue = createUploadQueue({ transport });

    const before = queue.getTasks();
    const promise = queue.run([makeJob("part.stl")]);
    const duringFirst = queue.getTasks();
    expect(duringFirst).not.toBe(before);
    expect(duringFirst[0].loaded).toBe(3);

    release();
    await flushMicrotasks();
    const duringSecond = queue.getTasks();

    expect(duringSecond).not.toBe(duringFirst);
    expect(duringSecond[0].loaded).toBe(9);
    await promise;
    expect(queue.getTasks()[0].status).toBe("done");
  });

  it("retries retryable failures with exponential backoff, then succeeds", async () => {
    const sleeps: number[] = [];
    let calls = 0;
    const transport: UploadTransport = async () => {
      calls += 1;
      if (calls <= 2) throw retryableError();
    };
    const queue = createUploadQueue({
      transport,
      sleep: async ms => {
        sleeps.push(ms);
      },
    });

    const result = await queue.run([makeJob("part.stl")]);
    const task = queue.getTasks()[0];

    expect(calls).toBe(3);
    expect(sleeps).toEqual([500, 1000]);
    expect(task.status).toBe("done");
    expect(task.attempts).toBe(3);
    expect(result.failures).toHaveLength(0);
    expect(result.uploaded).toHaveLength(1);
  });

  it("caps the backoff delay at capBackoffMs", async () => {
    const sleeps: number[] = [];
    const queue = createUploadQueue({
      maxAttempts: 5,
      backoffMs: 100,
      capBackoffMs: 250,
      transport: async () => {
        throw retryableError();
      },
      sleep: async ms => {
        sleeps.push(ms);
      },
    });

    await queue.run([makeJob("part.stl")]);

    expect(sleeps).toEqual([100, 200, 250, 250]);
  });

  it("gives a non-retryable failure exactly one attempt and still resolves", async () => {
    let calls = 0;
    const queue = createUploadQueue({
      transport: async () => {
        calls += 1;
        throw new Error("disk full");
      },
    });

    const result = await queue.run([makeJob("part.stl")]);
    const task = queue.getTasks()[0];

    expect(calls).toBe(1);
    expect(task.attempts).toBe(1);
    expect(task.status).toBe("failed");
    expect(task.error).toBe("disk full");
    expect(task.job).toBeDefined();
    expect(result.failures).toHaveLength(1);
    expect(result.failures[0].message).toBe("disk full");
    expect(result.uploaded).toHaveLength(0);
  });

  it("stops retrying at maxAttempts", async () => {
    let calls = 0;
    const queue = createUploadQueue({
      maxAttempts: 2,
      transport: async () => {
        calls += 1;
        throw retryableError();
      },
      sleep: async () => {},
    });

    await queue.run([makeJob("part.stl")]);

    expect(calls).toBe(2);
    expect(queue.getTasks()[0].status).toBe("failed");
  });

  it("cancels queued and in-flight tasks, then accepts a fresh run", async () => {
    const calls: string[] = [];
    const signals: AbortSignal[] = [];
    const hanging: UploadTransport = (job, ctx) => {
      calls.push(job.entry.file.name);
      signals.push(ctx.signal);
      return new Promise<never>(() => {});
    };
    const queue = createUploadQueue({ concurrency: 4, transport: hanging });

    const promise = queue.run(makeJobs(20));
    await flushMicrotasks();
    expect(calls).toHaveLength(4);

    queue.cancel();
    const result = await promise;

    expect(signals).toHaveLength(4);
    expect(signals.every(signal => signal.aborted)).toBe(true);
    expect(calls).toHaveLength(4);
    expect(result.uploaded).toHaveLength(0);
    expect(result.cancelled).toBe(20);
    expect(result.aborted).toBe(false);
    expect(queue.getTasks()).toHaveLength(20);
    expect(queue.getTasks().every(task => task.status === "cancelled")).toBe(true);

    const fresh = await queue.run(makeJobs(3, "fresh"), { transport: async () => {} });
    expect(fresh.uploaded).toHaveLength(3);
  });

  it("does not re-attempt when cancelled during backoff", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const queue = createUploadQueue({
      concurrency: 1,
      transport: async () => {
        calls += 1;
        throw retryableError();
      },
    });

    const promise = queue.run([makeJob("part.stl")]);
    await flushMicrotasks();
    expect(calls).toBe(1);

    queue.cancel();
    await vi.advanceTimersByTimeAsync(60_000);
    await promise;

    expect(calls).toBe(1);
    expect(queue.getTasks()[0].status).toBe("cancelled");
  });

  it("aborts the run on a 401 without counting cancellations", async () => {
    let calls = 0;
    const queue = createUploadQueue({
      concurrency: 2,
      transport: async () => {
        calls += 1;
        await Promise.resolve();
        throw unauthorizedError();
      },
    });

    const result = await queue.run(makeJobs(30));

    expect(result.aborted).toBe(true);
    expect(result.cancelled).toBe(0);
    expect(result.failures).toHaveLength(0);
    expect(calls).toBe(2);
    expect(queue.getTasks().filter(task => task.status === "done")).toHaveLength(0);
    expect(queue.getTasks().every(task => task.status === "cancelled")).toBe(true);
  });

  it("drops job handles on success but keeps them on failure", async () => {
    const queue = createUploadQueue({
      transport: async job => {
        if (job.entry.file.name.startsWith("bad")) throw new Error("nope");
      },
    });

    await queue.run([makeJob("good.stl"), makeJob("bad.stl")]);

    const good = queue.getTasks().find(task => task.name === "good.stl");
    const bad = queue.getTasks().find(task => task.name === "bad.stl");
    expect(good?.job).toBeUndefined();
    expect(good?.transport).toBeUndefined();
    expect(bad?.job).toBeDefined();
    expect(bad?.transport).toBeDefined();
  });

  it("clears finished rows and notifies subscribers until they unsubscribe", async () => {
    const queue = createUploadQueue({ transport: async () => {} });
    let notified = 0;
    const unsubscribe = queue.subscribe(() => {
      notified += 1;
    });

    await queue.run([makeJob("good.stl")]);
    expect(notified).toBeGreaterThan(0);

    const beforeClear = queue.getTasks();
    queue.clearFinished();
    const afterClear = queue.getTasks();
    expect(afterClear).not.toBe(beforeClear);
    expect(afterClear).toHaveLength(0);

    const countAtUnsubscribe = notified;
    unsubscribe();
    await queue.run([makeJob("other.stl")]);
    expect(queue.getTasks()).toHaveLength(1);
    expect(notified).toBe(countAtUnsubscribe);
  });

  it("removes a terminal task and ignores queued, in-flight and unknown ids", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>(resolve => {
      release = resolve;
    });
    const transport: UploadTransport = async job => {
      if (job.entry.file.name.startsWith("bad")) throw new Error("nope");
      await gate;
    };
    const queue = createUploadQueue({ concurrency: 2, transport });
    let notified = 0;
    const unsubscribe = queue.subscribe(() => {
      notified += 1;
    });
    const idOf = (name: string) => queue.getTasks().find(task => task.name === name)?.id ?? -1;

    const promise = queue.run([
      makeJob("bad.stl"),
      makeJob("slow-a.stl"),
      makeJob("slow-b.stl"),
      makeJob("waiting.stl"),
    ]);
    await flushMicrotasks();

    const statusOf = (name: string) => queue.getTasks().find(task => task.name === name)?.status;
    expect(statusOf("bad.stl")).toBe("failed");
    expect(statusOf("slow-a.stl")).toBe("uploading");
    expect(statusOf("waiting.stl")).toBe("queued");

    const before = queue.getTasks();
    const notifiedBefore = notified;
    queue.removeTask(idOf("waiting.stl"));
    queue.removeTask(idOf("slow-a.stl"));
    queue.removeTask(9999);
    expect(queue.getTasks()).toBe(before);
    expect(notified).toBe(notifiedBefore);

    queue.removeTask(idOf("bad.stl"));
    expect(queue.getTasks().map(task => task.name)).toEqual([
      "slow-a.stl",
      "slow-b.stl",
      "waiting.stl",
    ]);
    expect(notified).toBeGreaterThan(notifiedBefore);

    release();
    await promise;
    unsubscribe();
  });

  it("accepts a per-run transport override", async () => {
    const queue = createUploadQueue({
      transport: async () => {
        throw new Error("queue default transport must not run");
      },
    });
    const jobs: UploadJob[] = [];
    const transport: UploadTransport = async job => {
      jobs.push(job);
    };

    const result = await queue.run([makeJob("part.stl")], { transport });

    expect(jobs).toHaveLength(1);
    expect(jobs[0].folderId).toBe("folder-1");
    expect(result.uploaded).toHaveLength(1);
  });

  it("defaults to a concurrency of four, in the factory and in the app singleton", () => {
    // The ticket's headline knob: the UI's panel and the tree both read this one
    // value, so a silent change here would change the whole app's upload pressure.
    expect(createUploadQueue().concurrency).toBe(4);
    expect(uploadQueue.concurrency).toBe(4);
  });

  it("accepts a per-run isUnauthorized override for errors without a name", async () => {
    // Sibling suites mock `UnauthorizedError` without setting `name`, so the
    // duck-typed queue default would miss it: only `instanceof` catches this.
    class Unauthorized extends Error {}
    let calls = 0;
    const queue = createUploadQueue({
      concurrency: 2,
      transport: async () => {
        calls += 1;
        await Promise.resolve();
        throw new Unauthorized("Unauthorized");
      },
    });

    const result = await queue.run(makeJobs(30), {
      isUnauthorized: err => err instanceof Unauthorized,
    });

    expect(result.aborted).toBe(true);
    expect(result.cancelled).toBe(0);
    expect(result.failures).toHaveLength(0);
    expect(result.uploaded).toHaveLength(0);
    expect(calls).toBe(2);
  });
});
