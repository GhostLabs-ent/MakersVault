import { describe, expect, it } from "vitest";
import { strToU8, zipSync } from "fflate";
import { readZipEntries } from "./zipUtils";

// Small in-memory headers only; no unsupported compressor or large payload runs.
function fixture(method: number) {
  const data = zipSync({ "part.scad": strToU8("cube([1, 2, 3]);\n") });
  const view = new DataView(data.buffer);
  const central = view.getUint32(data.length - 22 + 16, true);
  view.setUint16(8, method, true);
  view.setUint16(central + 10, method, true);
  return new File([data], "fixture.zip");
}

describe("browser ZIP compression contract", () => {
  it.each([12, 14, 20, 93, 99, 65535])("rejects method %i with actionable recompression guidance", async method => {
    await expect(readZipEntries(fixture(method))).rejects.toThrow(
      `Unsupported ZIP compression method ${method}: part.scad. Recompress the archive using Stored (no compression) or Deflate.`
    );
  });

  it.each([0, 6] as const)("preserves a level-%i Stored/Deflate archive", async level => {
    const content = strToU8("cube([1, 2, 3]);\n");
    const file = new File([zipSync({ "part.scad": content }, { level })], "fixture.zip");
    const result = await readZipEntries(file);
    expect(result.entries).toEqual([{ path: "part.scad", size: content.length }]);
    expect(result.data["part.scad"]).toEqual(content);
  });
});
