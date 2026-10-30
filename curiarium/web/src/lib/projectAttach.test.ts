// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Only the network layer is mocked: the real queue singleton and the real
// `splitDuplicates`/`uploadEntriesToProject` are exercised end to end.
vi.mock("./api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  },
  listProjectAssets: vi.fn(),
  uploadAsset: vi.fn(),
}));

import { UnauthorizedError, listProjectAssets, uploadAsset, type Asset } from "./api";
import { resetToasts } from "./toast";
import { clearFinishedUploads } from "./uploadQueue";
import type { UploadEntry } from "./uploadTree";
import {
  duplicateKey,
  loadProjectMemberKeys,
  memberKeys,
  splitDuplicates,
  uploadEntriesToProject,
  type AttachDuplicateReason,
} from "./projectAttach";

const listProjectAssetsMock = vi.mocked(listProjectAssets);
const uploadAssetMock = vi.mocked(uploadAsset);

function file(name: string, content = "content"): File {
  return new File([content], name, { type: "application/octet-stream" });
}

function entry(name: string, content = "content"): UploadEntry {
  return { file: file(name, content), relativePath: name };
}

function asset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: "asset-1",
    name: "model",
    filename: "model.stl",
    mime: "application/octet-stream",
    size: 7,
    tags: [],
    url: "/api/asset/asset-1/file",
    supporting_file_count: 0,
    ...overrides,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise<void>(resolve => setTimeout(resolve, ms));
}

describe("duplicateKey", () => {
  it("case-folds the filename and keeps the size apart", () => {
    expect(duplicateKey("Benchy.STL", 100)).toBe(duplicateKey("benchy.stl", 100));
    expect(duplicateKey("benchy.stl", 100)).not.toBe(duplicateKey("benchy.stl", 101));
  });

  it("never folds two different name/size pairs into one key", () => {
    expect(duplicateKey("a", 12)).not.toBe(duplicateKey("a1", 2));
  });
});

describe("splitDuplicates", () => {
  const reasonFor = (): AttachDuplicateReason => "batch";

  it("drops an in-batch duplicate, keeps the first occurrence and preserves order", () => {
    const entries = [entry("A.stl"), entry("b.stl"), entry("a.STL")];
    const seen = new Set<string>();

    const split = splitDuplicates(entries, seen, reasonFor);

    expect(split.unique.map(item => item.file.name)).toEqual(["A.stl", "b.stl"]);
    expect(split.duplicates).toEqual([{ name: "a.STL", reason: "batch" }]);
    expect(seen).toEqual(new Set([duplicateKey("A.stl", entries[0].file.size), duplicateKey("b.stl", entries[1].file.size)]));
  });

  it("reports a member-seeded key as a project duplicate", () => {
    const entries = [entry("benchy.stl")];
    const seen = new Set([duplicateKey("Benchy.STL", entries[0].file.size)]);

    const split = splitDuplicates(entries, seen, () => "project");

    expect(split.unique).toEqual([]);
    expect(split.duplicates).toEqual([{ name: "benchy.stl", reason: "project" }]);
  });
});

describe("memberKeys", () => {
  it("keys on filename and size, never on the extension-less model name", () => {
    const members = memberKeys([asset({ name: "Benchy", filename: "benchy.stl", size: 100 })]);
    const incoming = [entry("benchy.stl", "x".repeat(100))];

    expect(members).toEqual(new Set([duplicateKey("benchy.stl", 100)]));
    const split = splitDuplicates(incoming, new Set(members), () => "project");
    expect(split.duplicates).toEqual([{ name: "benchy.stl", reason: "project" }]);
  });
});

describe("loadProjectMemberKeys", () => {
  it("pages through every member and unions the keys", async () => {
    listProjectAssetsMock
      .mockResolvedValueOnce({
        items: [asset({ id: "a1", filename: "one.stl", size: 10 })],
        hasMore: true,
        nextOffset: 1000,
      })
      .mockResolvedValueOnce({
        items: [asset({ id: "a2", filename: "two.stl", size: 20 })],
        hasMore: false,
      });

    const keys = await loadProjectMemberKeys("project-1");

    expect(listProjectAssetsMock).toHaveBeenNthCalledWith(1, { projectId: "project-1", limit: 1000, offset: 0 });
    expect(listProjectAssetsMock).toHaveBeenNthCalledWith(2, { projectId: "project-1", limit: 1000, offset: 1000 });
    expect(keys).toEqual(new Set([duplicateKey("one.stl", 10), duplicateKey("two.stl", 20)]));
  });

  it("continues after every row delivered so far when a page has no nextOffset", async () => {
    // This describe shares one mock instance across its tests; start from a
    // clean call log so the `nth` assertions below name this test's requests.
    vi.clearAllMocks();
    listProjectAssetsMock
      .mockResolvedValueOnce({
        items: [asset({ id: "a1", filename: "one.stl", size: 10 })],
        hasMore: true,
      })
      .mockResolvedValueOnce({
        items: [asset({ id: "a2", filename: "two.stl", size: 20 })],
        hasMore: true,
      })
      .mockResolvedValueOnce({ items: [], hasMore: false });

    const keys = await loadProjectMemberKeys("project-1");

    // Cumulative, not the current page's length: page 2's single row must not
    // send the third request back to offset 1.
    expect(listProjectAssetsMock).toHaveBeenNthCalledWith(2, { projectId: "project-1", limit: 1000, offset: 1 });
    expect(listProjectAssetsMock).toHaveBeenNthCalledWith(3, { projectId: "project-1", limit: 1000, offset: 2 });
    expect(keys).toEqual(new Set([duplicateKey("one.stl", 10), duplicateKey("two.stl", 20)]));
  });
});

describe("uploadEntriesToProject", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    resetToasts();
    clearFinishedUploads();
    uploadAssetMock.mockImplementation(async () => asset());
    // Failed uploads are logged by design; keep the test output readable.
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
    clearFinishedUploads();
  });

  it("uploads flat to the root and returns the assets in entry order", async () => {
    // The queue finishes out of order on purpose: the result must not follow it.
    uploadAssetMock.mockImplementation(async (uploadedFile: File) => {
      await sleep(uploadedFile.name.startsWith("a") ? 20 : 1);
      return asset({ id: `asset-${uploadedFile.name}`, filename: uploadedFile.name });
    });
    const entries = [entry("a.stl"), entry("b.stl"), entry("c.stl")];

    const result = await uploadEntriesToProject(entries);

    expect(uploadAssetMock).toHaveBeenCalledTimes(3);
    for (const call of uploadAssetMock.mock.calls) expect(call[1]).toEqual({});
    expect(result.uploaded.map(item => item.id)).toEqual(["asset-a.stl", "asset-b.stl", "asset-c.stl"]);
    expect(result.failed).toEqual([]);
    expect(result.failedEntries).toEqual([]);
    expect(result.cancelled).toBe(0);
  });

  it("reports failures in entry order with the server message", async () => {
    uploadAssetMock.mockImplementation(async (uploadedFile: File) => {
      if (uploadedFile.name === "part.stl") throw new Error("boom");
      return asset({ id: `asset-${uploadedFile.name}` });
    });

    const result = await uploadEntriesToProject([entry("part.stl"), entry("ok.stl")]);

    expect(result.failed).toEqual(["part.stl (boom)"]);
    expect(result.failedEntries).toEqual([entry("part.stl")]);
    expect(result.uploaded.map(item => item.id)).toEqual(["asset-ok.stl"]);
  });

  it("falls back to the bare name when the failure message is empty", async () => {
    uploadAssetMock.mockRejectedValue(new Error(""));

    const result = await uploadEntriesToProject([entry("part.stl")]);

    expect(result.failed).toEqual(["part.stl"]);
    expect(result.failedEntries).toEqual([entry("part.stl")]);
  });

  it("surfaces the server text of a 409", async () => {
    uploadAssetMock.mockRejectedValue(
      Object.assign(new Error('A model named "a" already exists in this folder'), { status: 409 }),
    );

    const result = await uploadEntriesToProject([entry("a.stl")]);

    expect(result.failed).toEqual(['a.stl (A model named "a" already exists in this folder)']);
    expect(result.uploaded).toEqual([]);
  });

  it("aborts the gesture and reports a 401 exactly once", async () => {
    const onUnauthorized = vi.fn();
    uploadAssetMock.mockRejectedValue(new UnauthorizedError());

    const result = await uploadEntriesToProject([entry("a.stl"), entry("b.stl")], onUnauthorized);

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(result.uploaded).toEqual([]);
  });
});
