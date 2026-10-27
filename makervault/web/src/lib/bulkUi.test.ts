import { describe, expect, it } from "vitest";

import type { Asset, BatchFailure } from "./api";
import {
  applyBatchOutcome,
  applyFolderLocally,
  applyTagsLocally,
  dropIds,
  failureLines,
  mergeTagsLocally,
  unionTags,
} from "./bulkUi";

function asset(id: string, overrides: Partial<Asset> = {}): Asset {
  const base: Asset = {
    id,
    name: id.toUpperCase(),
    filename: `${id}.stl`,
    mime: "model/stl",
    size: 1,
    tags: [],
    url: `/api/assets/${id}/file`,
    folder_id: null,
    supporting_file_count: 0,
  };
  return { ...base, ...overrides };
}

function failure(id: string, error = "failed"): BatchFailure {
  return { id, code: "error", status: 500, error };
}

describe("mergeTagsLocally", () => {
  it("adds tags in order", () => {
    expect(mergeTagsLocally(["pla"], ["strong"], [])).toEqual(["pla", "strong"]);
  });

  it("removes tags before adding, preserving the remaining order", () => {
    expect(mergeTagsLocally(["a", "b"], ["b", "c"], ["a"])).toEqual(["b", "c"]);
  });

  it("de-duplicates and strips empty entries", () => {
    expect(mergeTagsLocally([" pla ", "", "strong"], ["pla", " ", "new"], [])).toEqual([
      "pla",
      "strong",
      "new",
    ]);
  });

  it("matches exact strings only, with no case folding", () => {
    expect(mergeTagsLocally(["PLA"], ["pla"], ["PLA"])).toEqual(["pla"]);
    expect(mergeTagsLocally(["PLA"], [], ["pla"])).toEqual(["PLA"]);
  });

  it("applies removals before additions, so an add wins over a remove", () => {
    expect(mergeTagsLocally(["a"], ["a"], ["b"])).toEqual(["a"]);
    expect(mergeTagsLocally([], ["a"], ["a"])).toEqual(["a"]);
    expect(mergeTagsLocally(["a"], [], ["a"])).toEqual([]);
  });
});

describe("local optimistic helpers", () => {
  const items = [asset("a1"), asset("b2"), asset("c3")];

  it("applies tags to exactly the given ids", () => {
    const next = applyTagsLocally(items, ["a1", "c3"], ["new"], []);
    expect(next.map(item => item.tags)).toEqual([["new"], [], ["new"]]);
    expect(items[0].tags).toEqual([]);
  });

  it("applies a folder to exactly the given ids", () => {
    const next = applyFolderLocally(items, ["b2"], "f9");
    expect(next.map(item => item.folder_id)).toEqual([null, "f9", null]);
  });

  it("drops ids and leaves the rest in order", () => {
    expect(dropIds(items, ["a1", "c3"]).map(item => item.id)).toEqual(["b2"]);
  });
});

describe("applyBatchOutcome delete", () => {
  it("keeps failed ids and reports how many rows left the result set", () => {
    const before = [asset("a1"), asset("b2"), asset("c3")];
    const { items, offsetDelta } = applyBatchOutcome(before, {
      kind: "delete",
      deleted: ["a1", "c3"],
      failed: [failure("b2", "Storage path already exists")],
      view: { folderId: null, activeTags: [] },
    });
    expect(items.map(item => item.id)).toEqual(["b2"]);
    expect(offsetDelta).toBe(2);
  });

  it("reports zero delta when nothing was deleted", () => {
    const before = [asset("a1"), asset("b2")];
    const { items, offsetDelta } = applyBatchOutcome(before, {
      kind: "delete",
      deleted: [],
      failed: [failure("a1"), failure("b2")],
      view: { folderId: null, activeTags: [] },
    });
    expect(items.map(item => item.id)).toEqual(["a1", "b2"]);
    expect(offsetDelta).toBe(0);
  });
});

describe("applyBatchOutcome folder", () => {
  it("drops a row that moved out of the folder being viewed", () => {
    const before = [asset("a1", { folder_id: "f1" }), asset("b2", { folder_id: "f1" })];
    const { items, offsetDelta } = applyBatchOutcome(before, {
      kind: "folder",
      updated: [asset("a1", { folder_id: "f2" }), asset("b2", { folder_id: "f2" })],
      failed: [],
      view: { folderId: "f1", activeTags: [] },
    });
    expect(items).toEqual([]);
    expect(offsetDelta).toBe(2);
  });

  it("keeps the updated row with its new folder when unfiltered", () => {
    const before = [asset("a1", { folder_id: "f1" })];
    const { items, offsetDelta } = applyBatchOutcome(before, {
      kind: "folder",
      updated: [asset("a1", { folder_id: "f2" })],
      failed: [],
      view: { folderId: null, activeTags: [] },
    });
    expect(items.map(item => item.folder_id)).toEqual(["f2"]);
    expect(offsetDelta).toBe(0);
  });

  it("rolls a failed row back to the snapshot", () => {
    const before = [asset("a1", { folder_id: "f1" })];
    const { items } = applyBatchOutcome(before, {
      kind: "folder",
      updated: [],
      failed: [failure("a1")],
      view: { folderId: "f1", activeTags: [] },
    });
    expect(items).toEqual(before);
  });

  it("leaves rows absent from both lists untouched", () => {
    const before = [asset("a1", { folder_id: "f1" })];
    const { items } = applyBatchOutcome(before, {
      kind: "folder",
      updated: [],
      failed: [],
      view: { folderId: "f2", activeTags: [] },
    });
    expect(items).toEqual(before);
  });
});

describe("applyBatchOutcome tags", () => {
  it("drops a row that lost an active filter tag", () => {
    const before = [asset("a1", { tags: ["pla"] }), asset("b2", { tags: ["pla"] })];
    const { items, offsetDelta } = applyBatchOutcome(before, {
      kind: "tags",
      updated: [
        asset("a1", { tags: ["pla"] }),
        asset("b2", { tags: [] }),
      ],
      failed: [],
      view: { folderId: null, activeTags: ["pla"] },
    });
    expect(items.map(item => item.id)).toEqual(["a1"]);
    expect(offsetDelta).toBe(1);
  });

  it("keeps rows that still satisfy an AND tag filter", () => {
    const before = [asset("a1", { tags: ["pla"] })];
    const { items } = applyBatchOutcome(before, {
      kind: "tags",
      updated: [asset("a1", { tags: ["pla", "strong"] })],
      failed: [],
      view: { folderId: null, activeTags: ["pla", "strong"] },
    });
    expect(items.map(item => item.tags)).toEqual([["pla", "strong"]]);
  });

  it("matches the server's case-insensitive tag filter when reconciling the view", () => {
    // The server filters with `tags_json LIKE '%"pla"%'`, and SQLite LIKE folds
    // ASCII case, so a row tagged "PLA" is still in the result set for `pla`.
    const before = [asset("a1", { tags: ["PLA"] })];
    const { items, offsetDelta } = applyBatchOutcome(before, {
      kind: "tags",
      updated: [asset("a1", { tags: ["PLA", "strong"] })],
      failed: [],
      view: { folderId: null, activeTags: ["pla"] },
    });
    expect(items.map(item => item.id)).toEqual(["a1"]);
    expect(offsetDelta).toBe(0);
  });

  it("keeps updated rows when no tags are filtered", () => {
    const before = [asset("a1")];
    const { items } = applyBatchOutcome(before, {
      kind: "tags",
      updated: [asset("a1", { tags: ["fresh"] })],
      failed: [],
      view: { folderId: null, activeTags: [] },
    });
    expect(items.map(item => item.tags)).toEqual([["fresh"]]);
  });

  it("never reports a negative offset delta", () => {
    const before: Asset[] = [];
    const { items, offsetDelta } = applyBatchOutcome(before, {
      kind: "tags",
      updated: [],
      failed: [],
      view: { folderId: null, activeTags: [] },
    });
    expect(items).toEqual([]);
    expect(offsetDelta).toBe(0);
  });
});

describe("failureLines", () => {
  it("labels a known asset by filename and falls back to the id", () => {
    const items = [asset("b2", { filename: "spool-holder.stl", name: "Spool holder" })];
    expect(failureLines([failure("b2", "Storage path already exists")], items)).toEqual([
      { id: "b2", label: "spool-holder.stl", message: "Storage path already exists" },
    ]);
    expect(failureLines([failure("gone", "not found")], items)).toEqual([
      { id: "gone", label: "gone", message: "not found" },
    ]);
  });
});

describe("unionTags", () => {
  it("appends new tags without removing or duplicating existing ones", () => {
    expect(
      unionTags(["pla", "strong"], [asset("a1", { tags: ["strong", "new"] }), asset("b2", { tags: ["other"] })]),
    ).toEqual(["pla", "strong", "new", "other"]);
  });

  it("returns the same list when there is nothing to add", () => {
    expect(unionTags(["pla"], [asset("a1", { tags: ["pla"] })])).toEqual(["pla"]);
  });
});
