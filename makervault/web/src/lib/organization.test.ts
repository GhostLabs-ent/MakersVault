import { describe, expect, it } from "vitest";
import { buildFolderTrail, mutateTags, selectionAfterSuccess } from "./organization";

describe("organization workflow helpers", () => {
  it("builds a root-to-leaf trail and terminates malformed cycles", () => {
    const folders = [
      { id: "root", name: "Root" },
      { id: "branch", name: "Branch", parent_id: "root" },
      { id: "leaf", name: "Leaf", parent_id: "branch" },
    ];
    expect(buildFolderTrail("leaf", folders).map(folder => folder.id)).toEqual(["root", "branch", "leaf"]);
    expect(buildFolderTrail("missing", folders)).toEqual([]);
    expect(buildFolderTrail("a", [
      { id: "a", name: "A", parent_id: "b" },
      { id: "b", name: "B", parent_id: "a" },
    ]).map(folder => folder.id)).toEqual(["b", "a"]);
  });

  it("adds and removes tags without replacing unrelated metadata", () => {
    expect(mutateTags(["PLA", "favorite"], ["Favorite", "prototype"], "add"))
      .toEqual(["PLA", "favorite", "prototype"]);
    expect(mutateTags(["PLA", "Favorite", "prototype"], ["pla", "PROTOTYPE"], "remove"))
      .toEqual(["Favorite"]);
  });

  it("keeps only failed or unprocessed IDs selected after successful mutations", () => {
    expect([...selectionAfterSuccess(new Set(["a", "b", "c"]), ["a", "c"])]).toEqual(["b"]);
  });
});
