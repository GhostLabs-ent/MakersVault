import { describe, expect, it } from "vitest";

import {
  PROJECT_PERMANENT_CONFIRMATION,
  projectTrashCountsLabel,
  responseDownloadFilename,
} from "./projectLifecycle";


describe("Project lifecycle presentation", () => {
  it("uses a Project-specific irreversible confirmation", () => {
    expect(PROJECT_PERMANENT_CONFIRMATION).toBe("PERMANENTLY DELETE PROJECT");
  });

  it("keeps retained and trashed member counts explicit", () => {
    expect(projectTrashCountsLabel({
      member_count: 4,
      active_member_count: 3,
      trashed_member_count: 1,
      relationship_count: 2,
    })).toBe("4 retained items · 1 item in model Trash · 2 relationships");
  });

  it("uses a protected response filename with a safe fallback", () => {
    expect(responseDownloadFilename(
      'attachment; filename="relay-enclosure-project.zip"',
      "fallback.zip",
    )).toBe("relay-enclosure-project.zip");
    expect(responseDownloadFilename(null, "fallback.zip")).toBe("fallback.zip");
  });
});
