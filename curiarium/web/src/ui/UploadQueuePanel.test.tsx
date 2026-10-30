// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  clearFinishedUploads,
  uploadQueue,
  type UploadJob,
  type UploadRunResult,
  type UploadTransport,
} from "../lib/uploadQueue";
import UploadQueuePanel from "./UploadQueuePanel";

type Deferred = {
  promise: Promise<void>;
  resolve: () => void;
  reject: (err: unknown) => void;
};

function deferred(): Deferred {
  let resolve: () => void = () => {};
  let reject: (err: unknown) => void = () => {};
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeJob(name: string, size = 100): UploadJob {
  return {
    entry: { file: new File([new Uint8Array(size)], name), relativePath: name },
    folderId: null,
  };
}

/** Lets every `await` in the queue settle; the fake transports never time out. */
async function flushMicrotasks(times = 20): Promise<void> {
  for (let i = 0; i < times; i += 1) await Promise.resolve();
}

function statusText(): string {
  return screen.getByTestId("upload-queue-status").textContent ?? "";
}

beforeEach(() => {
  clearFinishedUploads();
});

afterEach(() => {
  cleanup();
  clearFinishedUploads();
  vi.restoreAllMocks();
});

describe("UploadQueuePanel", () => {
  it("renders nothing while the queue is empty", () => {
    render(<UploadQueuePanel />);

    expect(screen.queryByTestId("upload-queue")).toBeNull();
  });

  it("shows a row per task with its name, percentage and status", async () => {
    const gate = deferred();
    const progressSink: { emit: ((progress: { loaded: number; total: number }) => void) | null } = {
      emit: null,
    };
    const transport: UploadTransport = async (_job, ctx) => {
      progressSink.emit = ctx.onProgress;
      await gate.promise;
    };

    render(<UploadQueuePanel />);

    let run: Promise<UploadRunResult> | null = null;
    await act(async () => {
      run = uploadQueue.run([makeJob("part.stl")], { transport });
      await flushMicrotasks();
    });

    await act(async () => {
      progressSink.emit?.({ loaded: 50, total: 100 });
    });

    const uploadingRow = screen.getByText("part.stl").closest("li");
    expect(uploadingRow?.textContent).toContain("Uploading");
    expect(uploadingRow?.textContent).toContain("50%");

    await act(async () => {
      gate.resolve();
      await run;
    });

    const doneRow = screen.getByText("part.stl").closest("li");
    expect(doneRow?.textContent).toContain("Done");
    expect(doneRow?.textContent).not.toContain("50%");
  });

  it("never shows more than 100% for a file whose body overshot its size", async () => {
    // XHR's `total` is the multipart body length, so `loaded` can exceed the file.
    const gate = deferred();
    const progressSink: { emit: ((progress: { loaded: number; total: number }) => void) | null } = {
      emit: null,
    };
    const transport: UploadTransport = async (_job, ctx) => {
      progressSink.emit = ctx.onProgress;
      await gate.promise;
    };

    render(<UploadQueuePanel />);

    let run: Promise<UploadRunResult> | null = null;
    await act(async () => {
      run = uploadQueue.run([makeJob("tiny.stl", 10)], { transport });
      await flushMicrotasks();
    });

    await act(async () => {
      progressSink.emit?.({ loaded: 30, total: 10 });
    });

    expect(screen.getByText("tiny.stl").closest("li")?.textContent).toContain("100%");

    await act(async () => {
      gate.resolve();
      await run;
    });
  });

  it("summarises aggregate progress while uploading and after completion", async () => {
    const gate = deferred();
    const transport: UploadTransport = async () => {
      await gate.promise;
    };

    render(<UploadQueuePanel />);

    let run: Promise<UploadRunResult> | null = null;
    await act(async () => {
      run = uploadQueue.run([makeJob("a.stl"), makeJob("b.stl")], { transport });
      await flushMicrotasks();
    });

    expect(statusText()).toBe("Uploading 0 of 2 · 0%");

    await act(async () => {
      gate.resolve();
      await run;
    });

    expect(statusText()).toBe("2 of 2 uploaded");
  });

  it("appends failure and cancellation counts once nothing is active", async () => {
    const transport: UploadTransport = job => {
      const name = job.entry.file.name;
      if (name === "bad.stl") return Promise.reject(new Error("nope"));
      if (name === "slow.stl") return new Promise<never>(() => {});
      return Promise.resolve();
    };

    render(<UploadQueuePanel />);

    let run: Promise<UploadRunResult> | null = null;
    await act(async () => {
      run = uploadQueue.run(
        [makeJob("good.stl"), makeJob("bad.stl"), makeJob("slow.stl"), makeJob("also-good.stl")],
        { transport },
      );
      await flushMicrotasks();
    });

    expect(statusText()).toContain("Uploading 3 of 4");

    await act(async () => {
      uploadQueue.cancel();
      await run;
    });

    expect(statusText()).toBe("2 of 4 uploaded · 1 failed · 1 cancelled");
  });

  it("retries exactly the failed file, drops its stale row and calls onUploaded", async () => {
    const received: string[] = [];
    const folderIds: (string | null)[] = [];
    let failBadOnce = true;
    const transport: UploadTransport = async job => {
      const name = job.entry.file.name;
      received.push(name);
      folderIds.push(job.folderId);
      if (name === "bad.stl" && failBadOnce) {
        failBadOnce = false;
        throw new Error("disk full");
      }
    };
    const onUploaded = vi.fn();

    render(<UploadQueuePanel onUploaded={onUploaded} />);

    await act(async () => {
      await uploadQueue.run(
        [
          { ...makeJob("good.stl"), folderId: "folder-1" },
          { ...makeJob("bad.stl"), folderId: "folder-1" },
        ],
        { transport },
      );
    });

    expect(received).toEqual(["good.stl", "bad.stl"]);
    const failedRow = screen.getByText("bad.stl").closest("li");
    expect(failedRow?.textContent).toContain("Failed");
    expect(failedRow?.textContent).toContain("disk full");
    expect(screen.getByRole("button", { name: "Retry bad.stl" })).toBeTruthy();

    received.length = 0;
    folderIds.length = 0;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retry bad.stl" }));
      await flushMicrotasks();
    });

    expect(onUploaded).toHaveBeenCalledTimes(1);
    // Only the failed file was re-sent, to the folder it originally targeted, and
    // the stale failed row is gone.
    expect(received).toEqual(["bad.stl"]);
    expect(folderIds).toEqual(["folder-1"]);
    expect(failedRow?.isConnected).toBe(false);
    expect(screen.getByText("bad.stl").closest("li")?.textContent).toContain("Done");
  });

  it("cancels queued work from the panel and reports what succeeded", async () => {
    let calls = 0;
    const transport: UploadTransport = () => {
      calls += 1;
      return new Promise<never>(() => {});
    };

    render(<UploadQueuePanel />);

    let run: Promise<UploadRunResult> | null = null;
    await act(async () => {
      const jobs = Array.from({ length: 10 }, (_unused, index) => makeJob(`file-${index}.stl`));
      run = uploadQueue.run(jobs, { transport });
      await flushMicrotasks();
    });

    expect(calls).toBe(4);
    expect(screen.getAllByText("Uploading")).toHaveLength(4);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      await run;
    });

    expect(calls).toBe(4);
    expect(screen.getAllByText("Cancelled")).toHaveLength(10);
    expect(statusText()).toBe("0 of 10 uploaded · 10 cancelled");
  });

  it("dismisses finished rows and hides the panel", async () => {
    render(<UploadQueuePanel />);

    await act(async () => {
      await uploadQueue.run([makeJob("a.stl"), makeJob("b.stl")], { transport: async () => {} });
    });

    expect(screen.getByTestId("upload-queue")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByTestId("upload-queue")).toBeNull();
  });

  it("reports a retry that aborts on a 401 exactly once", async () => {
    let calls = 0;
    const transport: UploadTransport = async () => {
      calls += 1;
      if (calls === 1) throw new Error("disk full");
      throw Object.assign(new Error("x"), { name: "UnauthorizedError" });
    };
    const onUnauthorized = vi.fn();
    const onUploaded = vi.fn();

    render(<UploadQueuePanel onUploaded={onUploaded} onUnauthorized={onUnauthorized} />);

    await act(async () => {
      await uploadQueue.run([makeJob("a.stl")], { transport });
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retry a.stl" }));
      await flushMicrotasks();
    });

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(onUploaded).not.toHaveBeenCalled();
    expect(calls).toBe(2);
  });
});
