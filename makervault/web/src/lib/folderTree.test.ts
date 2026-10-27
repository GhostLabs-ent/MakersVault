import { describe, expect, it } from "vitest";

import type { Folder } from "./api";
import { childFolders, flattenFolderTree, folderPath, indexFolders } from "./folderTree";

function folder(id: string, name: string, parent_id: string | null = null): Folder {
  return { id, name, tags: [], parent_id };
}

/** Root → child → grandchild, plus an unrelated root and a middle sibling. */
const tree: Folder[] = [
  folder("parts", "Parts"),
  folder("brackets", "Brackets", "parts"),
  folder("corners", "Corners", "brackets"),
  folder("clamps", "Clamps", "parts"),
  folder("elsewhere", "Elsewhere"),
];

describe("indexFolders", () => {
  it("keys every folder by id", () => {
    const byId = indexFolders(tree);
    expect(Object.keys(byId).sort()).toEqual([
      "brackets",
      "clamps",
      "corners",
      "elsewhere",
      "parts",
    ]);
    expect(byId["corners"]).toBe(tree[2]);
  });
});

describe("folderPath", () => {
  it("returns root → leaf segments for a three-deep folder", () => {
    expect(folderPath(tree, "corners")).toEqual([
      { id: "parts", name: "Parts" },
      { id: "brackets", name: "Brackets" },
      { id: "corners", name: "Corners" },
    ]);
  });

  it("returns a single segment for a root folder", () => {
    expect(folderPath(tree, "parts")).toEqual([{ id: "parts", name: "Parts" }]);
  });

  it("returns [] for null and unknown ids", () => {
    expect(folderPath(tree, null)).toEqual([]);
    expect(folderPath(tree, undefined)).toEqual([]);
    expect(folderPath(tree, "nope")).toEqual([]);
  });

  it("falls back to \"Untitled\" for a blank name", () => {
    expect(folderPath([folder("blank", "")], "blank")).toEqual([
      { id: "blank", name: "Untitled" },
    ]);
  });

  it("is cycle-guarded: a parent loop terminates", () => {
    const looped: Folder[] = [
      { id: "a", name: "A", tags: [], parent_id: "b" },
      { id: "b", name: "B", tags: [], parent_id: "a" },
    ];
    expect(folderPath(looped, "a")).toEqual([
      { id: "b", name: "B" },
      { id: "a", name: "A" },
    ]);
  });

  it("stops at a missing parent instead of dropping the known tail", () => {
    const orphaned: Folder[] = [folder("child", "Child", "gone")];
    expect(folderPath(orphaned, "child")).toEqual([{ id: "child", name: "Child" }]);
  });
});

describe("childFolders", () => {
  it("returns direct children only, sorted by name", () => {
    expect(childFolders(tree, "parts").map(f => f.name)).toEqual(["Brackets", "Clamps"]);
  });

  it("never returns grandchildren or siblings", () => {
    const ids = childFolders(tree, "parts").map(f => f.id);
    expect(ids).not.toContain("corners");
    expect(ids).not.toContain("elsewhere");
  });

  it("treats a missing parent_id as a root", () => {
    expect(childFolders(tree, null).map(f => f.name)).toEqual(["Elsewhere", "Parts"]);
    expect(childFolders([{ id: "r", name: "Root", tags: [] }], null).map(f => f.id)).toEqual(["r"]);
  });

  it("returns [] for a leaf", () => {
    expect(childFolders(tree, "corners")).toEqual([]);
  });
});

describe("flattenFolderTree", () => {
  it("renders only the roots when nothing is expanded", () => {
    expect(flattenFolderTree(tree, { expanded: new Set() })).toEqual([
      { id: "elsewhere", depth: 0, hasChildren: false },
      { id: "parts", depth: 0, hasChildren: true },
    ]);
  });

  it("walks into expanded branches depth-first with increasing depth", () => {
    const rows = flattenFolderTree(tree, { expanded: new Set(["parts", "brackets"]) });
    expect(rows).toEqual([
      { id: "elsewhere", depth: 0, hasChildren: false },
      { id: "parts", depth: 0, hasChildren: true },
      { id: "brackets", depth: 1, hasChildren: true },
      { id: "corners", depth: 2, hasChildren: false },
      { id: "clamps", depth: 1, hasChildren: false },
    ]);
  });

  it("stops at a collapsed parent", () => {
    const rows = flattenFolderTree(tree, { expanded: new Set(["parts"]) });
    expect(rows.map(r => r.id)).toEqual(["elsewhere", "parts", "brackets", "clamps"]);
  });

  it("alwaysExpanded ignores the expanded set", () => {
    const rows = flattenFolderTree(tree, { expanded: new Set(), alwaysExpanded: true });
    expect(rows).toEqual([
      { id: "elsewhere", depth: 0, hasChildren: false },
      { id: "parts", depth: 0, hasChildren: true },
      { id: "brackets", depth: 1, hasChildren: true },
      { id: "corners", depth: 2, hasChildren: false },
      { id: "clamps", depth: 1, hasChildren: false },
    ]);
  });

  it("skips whole subtrees rejected by isVisible", () => {
    const rows = flattenFolderTree(tree, {
      expanded: new Set(["parts", "brackets"]),
      isVisible: id => id !== "brackets",
    });
    expect(rows.map(r => r.id)).toEqual(["elsewhere", "parts", "clamps"]);
  });

  it("is cycle-guarded", () => {
    const looped: Folder[] = [
      { id: "a", name: "A", tags: [], parent_id: "b" },
      { id: "b", name: "B", tags: [], parent_id: "a" },
      folder("root", "Root"),
      { id: "a2", name: "A2", tags: [], parent_id: "root" },
      { id: "b2", name: "B2", tags: [], parent_id: "a2" },
    ];
    const rows = flattenFolderTree(looped, { expanded: new Set(["root", "a2", "b2", "a", "b"]), alwaysExpanded: true });
    expect(rows.map(r => r.id)).toEqual(["root", "a2", "b2"]);
  });
});
