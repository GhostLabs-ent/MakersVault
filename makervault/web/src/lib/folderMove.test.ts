import { describe, expect, it } from "vitest";
import { canMoveToFolder, filterFolderDestinations, sameFolderMoveSource } from "./folderMove";

const options = [
  { id: null, name: "Unassigned" },
  { id: "a", name: "Workshop / Brackets" },
  { id: "b", name: "Office / Brackets" },
];
describe("shared folder destination selection", () => {
  it("searches complete paths without confusing identically named leaves", () => {
    expect(filterFolderDestinations(options, " WORKSHOP / brack ")).toEqual([options[1]]);
    expect(filterFolderDestinations(options, "Brackets")).toHaveLength(2);
  });
  it("retains all destinations for an empty query and represents no results", () => {
    expect(filterFolderDestinations(options, " ")).toBe(options);
    expect(filterFolderDestinations(options, "missing")).toEqual([]);
  });
  it("distinguishes an explicit Unassigned choice from no selection", () => {
    expect(canMoveToFolder(null, "a", options)).toBe(false);
    expect(canMoveToFolder("", "a", options)).toBe(true);
    expect(canMoveToFolder("", null, options)).toBe(false);
  });
  it("rejects the current folder and missing/deleted destinations", () => {
    expect(canMoveToFolder("a", "a", options)).toBe(false);
    expect(canMoveToFolder("deleted", "a", options)).toBe(false);
    expect(canMoveToFolder("b", "a", options)).toBe(true);
  });
  it("permits harmless object replacement but never a departed or changed move source", () => {
    const source = { id: "asset", name: "Model", folder_id: "a", current_revision_id: "revision" };
    expect(sameFolderMoveSource({ ...source }, source)).toBe(true);
    expect(sameFolderMoveSource(undefined, source)).toBe(false);
    for (const change of [{ id: "other" }, { name: "Renamed" }, { folder_id: "b" }, { current_revision_id: "new" }]) {
      expect(sameFolderMoveSource({ ...source, ...change }, source)).toBe(false);
    }
  });
});
