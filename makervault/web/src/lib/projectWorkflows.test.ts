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


describe("Project-scoped upload workflows", () => {
  beforeEach(() => {
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
    });
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
    });
  });
});
