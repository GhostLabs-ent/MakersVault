import { describe, expect, it } from "vitest";
import { mountOwnership, mountScanStatusLabel } from "./mountImport";

describe("mounted import presentation", () => {
  it("states copy ownership before a scan", () => {
    const copy = mountOwnership(true);
    expect(copy.label).toBe("Copy into MakersVault");
    expect(copy.description).toContain("managed copy");
    expect(copy.description).toContain("never changed or deleted");
  });

  it("states index-in-place availability and deletion consequences", () => {
    const indexed = mountOwnership(false);
    expect(indexed.label).toBe("Index in place");
    expect(indexed.description).toContain("must stay available");
    expect(indexed.description).toContain("does not delete the source");
  });

  it("makes persisted scan states readable", () => {
    expect(mountScanStatusLabel("completed_with_failures")).toBe("completed with failures");
    expect(mountScanStatusLabel(null)).toBe("not run");
  });
});
