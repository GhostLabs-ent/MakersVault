import { beforeEach, describe, expect, it, vi } from "vitest";

const { createFolder, uploadAsset } = vi.hoisted(() => ({
  createFolder: vi.fn(),
  uploadAsset: vi.fn(),
}));

vi.mock("./api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {},
  createFolder,
  uploadAsset,
}));

import { uploadEntriesToFolder } from "./uploadTree";
import { UnauthorizedError } from "./api";
import { clearUploads, getUploadBatches } from "./uploadProgress";


describe("Project-scoped upload workflows", () => {
  beforeEach(() => {
    clearUploads();
    createFolder.mockReset();
    uploadAsset.mockReset();
    createFolder.mockResolvedValue({ id: "nested-folder" });
    uploadAsset.mockResolvedValue({ id: "asset" });
  });

  it("keeps nested folder placement and Project membership as independent inputs", async () => {
    const file = { name: "part.stl" } as File;

    const result = await uploadEntriesToFolder(
      [{ file, relativePath: "assembly/part.stl" }],
      "root-folder",
      undefined,
      "project-1",
    );

    expect(result.uploaded).toBe(1);
    expect(createFolder).toHaveBeenCalledWith("assembly", [], "root-folder");
    expect(uploadAsset).toHaveBeenCalledWith(file, {
      folder_id: "nested-folder",
      project_id: "project-1",
    }, { onProgress: expect.any(Function), signal: expect.any(AbortSignal) });
  });

  it("preserves legacy Unassigned uploads when no Project is selected", async () => {
    const file = { name: "standalone.stl" } as File;

    await uploadEntriesToFolder(
      [{ file, relativePath: "standalone.stl" }],
      null,
    );

    expect(createFolder).not.toHaveBeenCalled();
    expect(uploadAsset).toHaveBeenCalledWith(file, {
      folder_id: undefined,
      project_id: undefined,
    }, { onProgress: expect.any(Function), signal: expect.any(AbortSignal) });
  });

  it("counts only confirmed saves and continues after one rejected file", async () => {
    uploadAsset.mockRejectedValueOnce(new Error("file ceiling"));
    const entries = ["large.stl", "small.stl"].map(name => ({ file: { name, size: 10 } as File, relativePath: name }));
    const result = await uploadEntriesToFolder(entries, null);
    expect(result.uploaded).toBe(1);
    expect(result.failed).toEqual(["large.stl (file ceiling)"]);
    expect(getUploadBatches()[0]).toMatchObject({ phase: "partial", savedFiles: 1, failedFiles: 1, transferredBytes: 10 });
  });

  it("reports failed folder creation without uploading into the wrong folder", async () => {
    createFolder.mockRejectedValueOnce(new Error("forbidden"));
    const file = { name: "part.stl", size: 100 } as File;
    const result = await uploadEntriesToFolder([{ file, relativePath: "blocked/part.stl" }], "parent");
    expect(result.failed).toEqual(["part.stl"]);
    expect(uploadAsset).not.toHaveBeenCalled();
    expect(getUploadBatches()[0]).toMatchObject({ phase: "partial", failedFiles: 1, transferredBytes: 0 });
  });

  it("stops at unauthorized upload without sending later files", async () => {
    uploadAsset.mockRejectedValueOnce(new UnauthorizedError());
    const unauthorized = vi.fn();
    const entries = ["one.stl", "two.stl"].map(name => ({ file: { name, size: 10 } as File, relativePath: name }));
    const result = await uploadEntriesToFolder(entries, null, unauthorized);
    expect(result.aborted).toBe(true);
    expect(uploadAsset).toHaveBeenCalledTimes(1);
    expect(unauthorized).toHaveBeenCalledTimes(1);
    expect(getUploadBatches()[0].phase).toBe("stopped");
  });

  it("stops at unauthorized folder creation", async () => {
    createFolder.mockRejectedValueOnce(new UnauthorizedError());
    const unauthorized = vi.fn();
    const file = { name: "one.stl", size: 10 } as File;
    const result = await uploadEntriesToFolder([{ file, relativePath: "nested/one.stl" }], null, unauthorized);
    expect(result.aborted).toBe(true);
    expect(uploadAsset).not.toHaveBeenCalled();
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it("does not send an old-account file after pending folder creation finishes", async () => {
    createFolder.mockImplementationOnce(async () => { clearUploads(); return { id: "folder" }; });
    const file = { name: "one.stl", size: 10 } as File;
    const result = await uploadEntriesToFolder([{ file, relativePath: "nested/one.stl" }], null);
    expect(result.aborted).toBe(true);
    expect(uploadAsset).not.toHaveBeenCalled();
    expect(getUploadBatches()).toEqual([]);
  });

  it("does not create progress work for an empty selection", async () => {
    expect((await uploadEntriesToFolder([], null)).uploaded).toBe(0);
    expect(getUploadBatches()).toEqual([]);
  });
});
