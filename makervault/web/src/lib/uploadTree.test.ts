// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Only the network layer is mocked: the real queue and the real
// `uploadEntriesToFolder` are exercised end to end.
vi.mock("./api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  },
  createFolder: vi.fn(),
  uploadAsset: vi.fn(),
}));

import { UnauthorizedError, createFolder, uploadAsset } from "./api";
import { clearFinishedUploads, getUploadTasks, uploadQueue } from "./uploadQueue";
import { uploadEntriesToFolder, type UploadEntry } from "./uploadTree";

const createFolderMock = vi.mocked(createFolder);
const uploadAssetMock = vi.mocked(uploadAsset);

function file(name: string, content = "content"): File {
  return new File([content], name, { type: "application/octet-stream" });
}

function entry(name: string, relativePath = name): UploadEntry {
  return { file: file(name), relativePath };
}

async function flushMicrotasks(times = 50): Promise<void> {
  for (let i = 0; i < times; i += 1) await Promise.resolve();
}

describe("uploadEntriesToFolder", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    clearFinishedUploads();
    createFolderMock.mockImplementation(async (name: string) => ({ id: `folder-${name}` }));
    uploadAssetMock.mockImplementation(async () => ({ id: "asset" }));
    // Failed uploads/folders are logged by design; keep the test output readable.
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
    clearFinishedUploads();
  });

  it("bounds in-flight uploads of a 500-entry tree by the shared cap", async () => {
    const state = { current: 0, peak: 0 };
    uploadAssetMock.mockImplementation(async () => {
      state.current += 1;
      state.peak = Math.max(state.peak, state.current);
      await Promise.resolve();
      state.current -= 1;
      return { id: "asset" };
    });
    const entries = Array.from({ length: 500 }, (_unused, index) => entry(`file-${index}.stl`));

    const result = await uploadEntriesToFolder(entries, "folder-1");

    expect(state.peak).toBeLessThanOrEqual(4);
    expect(result.uploaded).toBe(500);
    expect(result.failed).toEqual([]);
    expect(result.failedEntries).toEqual([]);
    expect(result.uploadedEntries).toHaveLength(500);
    expect(result.cancelled).toBe(0);
  });

  it("publishes the batch to the app singleton queue the panel reads", async () => {
    const entries = Array.from({ length: 500 }, (_unused, index) => entry(`file-${index}.stl`));

    await uploadEntriesToFolder(entries, "folder-1");
    const tasks = getUploadTasks();

    expect(tasks).toHaveLength(500);
    expect(tasks.every(task => task.status === "done")).toBe(true);
  });

  it("creates each folder segment once and uploads a shared folder's files once", async () => {
    const entries = [
      entry("one.stl", "a/b/one.stl"),
      entry("two.stl", "a/b/two.stl"),
      entry("three.stl", "a/b/three.stl"),
    ];

    const result = await uploadEntriesToFolder(entries, "root-id");

    expect(createFolderMock.mock.calls).toEqual([
      ["a", [], "root-id"],
      ["b", [], "folder-a"],
    ]);
    expect(uploadAssetMock).toHaveBeenCalledTimes(3);
    for (const call of uploadAssetMock.mock.calls) {
      expect(call[1]).toEqual({ folder_id: "folder-b" });
    }
    expect(result.uploaded).toBe(3);
  });

  it("creates the folder chain of a nested file parent-first", async () => {
    await uploadEntriesToFolder([entry("model.stl", "nested/dir/inner/model.stl")], "root-id");

    expect(createFolderMock.mock.calls).toEqual([
      ["nested", [], "root-id"],
      ["dir", [], "folder-nested"],
      ["inner", [], "folder-dir"],
    ]);
    expect(uploadAssetMock.mock.calls[0][1]).toEqual({ folder_id: "folder-inner" });
  });

  it("reports a failed folder creation without blocking the other entries", async () => {
    createFolderMock.mockImplementation(async (name: string) => {
      if (name === "a") throw new Error("folder exploded");
      return { id: `folder-${name}` };
    });
    const failingEntry = entry("a-file-name", "a/a-file-name");

    const result = await uploadEntriesToFolder([failingEntry, entry("b.stl")], "root-id");

    expect(result.uploaded).toBe(1);
    expect(result.failed).toEqual(["a-file-name"]);
    expect(result.failedEntries).toEqual([failingEntry]);
    expect(uploadAssetMock).toHaveBeenCalledTimes(1);
    expect(consoleError).toHaveBeenCalled();
  });

  it("formats an upload failure with the server message", async () => {
    uploadAssetMock.mockImplementation(async (uploadedFile: File) => {
      if (uploadedFile.name === "b.stl") throw new Error("disk full");
      return { id: "asset" };
    });
    const failingEntry = entry("b.stl");

    const result = await uploadEntriesToFolder([entry("a.stl"), failingEntry], "folder-1");

    expect(result.uploaded).toBe(1);
    expect(result.failed).toEqual(["b.stl (disk full)"]);
    expect(result.failedEntries).toEqual([failingEntry]);
    expect(consoleError).toHaveBeenCalled();
  });

  it("reports multiple failures in entry order, not completion order", async () => {
    // The queue finishes files out of order; the toast detail list and its retry
    // must still read in the order the user handed the files over.
    uploadAssetMock.mockImplementation(async (uploadedFile: File) => {
      const name = uploadedFile.name;
      // "first.stl" is slow to fail so it settles AFTER "second.stl".
      if (name === "first.stl") {
        await Promise.resolve();
        await Promise.resolve();
        throw new Error("first failed");
      }
      if (name === "second.stl") throw new Error("second failed");
      return { id: "asset" };
    });

    const result = await uploadEntriesToFolder(
      [entry("first.stl"), entry("second.stl"), entry("ok.stl")],
      "folder-1",
    );

    expect(result.uploaded).toBe(1);
    expect(result.failed).toEqual(["first.stl (first failed)", "second.stl (second failed)"]);
    expect(result.failedEntries.map(failed => failed.file.name)).toEqual(["first.stl", "second.stl"]);
  });

  it("omits the message suffix for the generic upload failure", async () => {
    uploadAssetMock.mockImplementation(async (uploadedFile: File) => {
      if (uploadedFile.name === "b.stl") throw new Error("Upload failed");
      return { id: "asset" };
    });

    const result = await uploadEntriesToFolder([entry("a.stl"), entry("b.stl")], "folder-1");

    expect(result.uploaded).toBe(1);
    expect(result.failed).toEqual(["b.stl"]);
  });

  it("aborts the batch once on a 401 and never counts it as a cancel", async () => {
    let calls = 0;
    uploadAssetMock.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) throw new UnauthorizedError();
      return { id: "asset" };
    });
    const onUnauthorized = vi.fn();
    const entries = Array.from({ length: 30 }, (_unused, index) => entry(`file-${index}.stl`));

    const result = await uploadEntriesToFolder(entries, "folder-1", onUnauthorized);

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(result.cancelled).toBe(0);
    expect(result.failed).toEqual([]);
    expect(result.failedEntries).toEqual([]);
    expect(result.uploaded).toBe(0);
    expect(calls).toBeLessThan(30);
  });

  it("reports what succeeded when the user cancels the queue", async () => {
    let calls = 0;
    uploadAssetMock.mockImplementation(() => {
      calls += 1;
      if (calls <= 4) return Promise.resolve({ id: "asset" });
      // The rest never settles: they can only end by cancellation.
      return new Promise<never>(() => {});
    });
    const entries = Array.from({ length: 40 }, (_unused, index) => entry(`file-${index}.stl`));

    const promise = uploadEntriesToFolder(entries, "folder-1");
    await flushMicrotasks();
    uploadQueue.cancel();
    const result = await promise;

    expect(result.uploaded).toBe(4);
    expect(result.cancelled).toBe(36);
    expect(result.failed).toEqual([]);
    expect(result.uploadedEntries).toHaveLength(4);
    // 4 completed plus the 4 that were in flight when the cancel landed; the
    // remaining 32 queued uploads never start.
    expect(calls).toBe(8);
  });

  it("uploads to the root with no folder_id and to a real folder with one", async () => {
    await uploadEntriesToFolder([entry("root.stl")], null);
    expect(uploadAssetMock.mock.calls[0][1]).toEqual({});

    uploadAssetMock.mockClear();
    await uploadEntriesToFolder([entry("nested.stl")], "folder-1");
    expect(uploadAssetMock.mock.calls[0][1]).toEqual({ folder_id: "folder-1" });
  });
});
