import { describe, expect, it } from "vitest";

import { targetPayload } from "./importProject";

describe("targetPayload", () => {
  it("sends no project fields when the import stays a loose asset", () => {
    expect(targetPayload({ kind: "none" })).toEqual({});
  });

  it("sends no project fields for a new project: the server names it from the page", () => {
    expect(targetPayload({ kind: "new" })).toEqual({});
  });

  it("addresses an existing project by id, not by name", () => {
    expect(
      targetPayload({ kind: "existing", projectId: "p1", projectName: "Hydra" }),
    ).toEqual({ project_id: "p1" });
  });
});
