import { describe, expect, it } from "vitest";

import type { ImportRunSummary } from "./api";
import {
  formatImportRunDuration,
  formatImportRunTime,
  importRunCountsLine,
  importRunModeLabel,
  importRunReason,
  importRunRejectedNote,
  importRunStatusLabel,
  isImportRunFailure,
} from "./importRuns";

function makeRun(overrides: Partial<ImportRunSummary> = {}): ImportRunSummary {
  return {
    id: "run-1",
    status: "succeeded",
    mode: "copy",
    root: "/mnt/models",
    reason: null,
    started_at: 1_700_000_000,
    finished_at: 1_700_000_042,
    registered: 4,
    known: 2,
    ignored: 1,
    failed: 0,
    rejected: 0,
    discovered: 7,
    skipped: 3,
    ...overrides,
  };
}

describe("importRunStatusLabel", () => {
  it.each([
    ["running", "Running"],
    ["succeeded", "Succeeded"],
    ["failed", "Failed"],
    ["interrupted", "Interrupted"],
    ["skipped", "Skipped"],
  ])("labels %s as %s", (status, label) => {
    expect(importRunStatusLabel(makeRun({ status }))).toBe(label);
  });

  it("renders a neutral label for a status the UI does not know", () => {
    expect(importRunStatusLabel(makeRun({ status: "reticulating" }))).toBe("Unknown (reticulating)");
    expect(importRunStatusLabel(makeRun({ status: "" }))).toBe("Unknown");
  });
});

describe("isImportRunFailure", () => {
  it("treats failed and interrupted as failures", () => {
    expect(isImportRunFailure(makeRun({ status: "failed" }))).toBe(true);
    expect(isImportRunFailure(makeRun({ status: "interrupted" }))).toBe(true);
  });

  it("does not treat succeeded, running or skipped as failures", () => {
    expect(isImportRunFailure(makeRun({ status: "succeeded" }))).toBe(false);
    expect(isImportRunFailure(makeRun({ status: "running" }))).toBe(false);
    expect(isImportRunFailure(makeRun({ status: "skipped" }))).toBe(false);
    expect(isImportRunFailure(makeRun({ status: "mystery" }))).toBe(false);
  });
});

describe("importRunModeLabel", () => {
  it("describes copy and reference modes", () => {
    expect(importRunModeLabel(makeRun({ mode: "copy" }))).toBe("Copied into storage");
    expect(importRunModeLabel(makeRun({ mode: "reference" }))).toBe("Referenced in place");
  });

  it("falls back when the mode is missing or unknown", () => {
    expect(importRunModeLabel(makeRun({ mode: null }))).toBe("Mode not recorded");
    expect(importRunModeLabel(makeRun({ mode: "teleport" }))).toBe("Mode not recorded");
  });
});

describe("formatImportRunDuration", () => {
  it("returns an empty string while the run has no finish time", () => {
    expect(formatImportRunDuration(1_700_000_000, null)).toBe("");
  });

  it("formats a zero duration", () => {
    expect(formatImportRunDuration(1_700_000_000, 1_700_000_000)).toBe("0s");
  });

  it("formats seconds, minutes and hours", () => {
    expect(formatImportRunDuration(100, 142)).toBe("42s");
    expect(formatImportRunDuration(100, 220)).toBe("2m");
    expect(formatImportRunDuration(100, 160)).toBe("1m");
    expect(formatImportRunDuration(100, 190)).toBe("1m 30s");
    expect(formatImportRunDuration(0, 7200)).toBe("2h");
    expect(formatImportRunDuration(0, 7500)).toBe("2h 5m");
  });

  it("never renders a negative duration", () => {
    expect(formatImportRunDuration(200, 100)).toBe("0s");
  });
});

describe("formatImportRunTime", () => {
  it("returns an empty string when there is no timestamp", () => {
    expect(formatImportRunTime(null)).toBe("");
  });

  it("converts epoch seconds to a locale date string", () => {
    const formatted = formatImportRunTime(0);
    expect(formatted).toBe(new Date(0).toLocaleString());
    expect(formatted).not.toBe("");
  });

  it("returns an empty string for an unparseable timestamp", () => {
    expect(formatImportRunTime(Number.NaN)).toBe("");
  });
});

describe("importRunCountsLine", () => {
  it("lists discovered, registered, skipped and failed counters", () => {
    expect(importRunCountsLine(makeRun())).toBe("7 discovered, 4 registered, 3 skipped, 0 failed");
  });

  it("appends the oversize subset only when the server counted rejections", () => {
    expect(importRunCountsLine(makeRun({ ignored: 2, rejected: 2, skipped: 4 }))).toBe(
      "7 discovered, 4 registered, 4 skipped, 0 failed, 2 oversize",
    );
  });

  it("keeps a failed counter visible", () => {
    expect(importRunCountsLine(makeRun({ failed: 3, discovered: 10 }))).toBe(
      "10 discovered, 4 registered, 3 skipped, 3 failed",
    );
  });
});

describe("importRunRejectedNote", () => {
  it("is empty when nothing was rejected", () => {
    expect(importRunRejectedNote(makeRun())).toBe("");
  });

  it("explains the oversize subset with the right verb", () => {
    expect(importRunRejectedNote(makeRun({ rejected: 1 }))).toBe(
      "1 oversize file exceeded the size limit and was skipped.",
    );
    expect(importRunRejectedNote(makeRun({ rejected: 3 }))).toBe(
      "3 oversize files exceeded the size limit and were skipped.",
    );
  });
});

describe("importRunReason", () => {
  it("reports the reason for skipped runs", () => {
    expect(
      importRunReason(makeRun({ status: "skipped", reason: "Mount path is not configured" })),
    ).toBe("Mount path is not configured");
  });

  it("reports the reason for failed and interrupted runs", () => {
    expect(importRunReason(makeRun({ status: "failed", reason: "Permission denied" }))).toBe(
      "Permission denied",
    );
    expect(importRunReason(makeRun({ status: "interrupted", reason: "Process exited" }))).toBe(
      "Process exited",
    );
  });

  it("falls back to a placeholder for a skipped run without a reason", () => {
    expect(importRunReason(makeRun({ status: "skipped", reason: null }))).toBe(
      "No reason was recorded.",
    );
    expect(importRunReason(makeRun({ status: "skipped", reason: "   " }))).toBe(
      "No reason was recorded.",
    );
  });

  it("is empty for runs that carry no reason by design", () => {
    expect(importRunReason(makeRun({ status: "succeeded", reason: "ignored" }))).toBe("");
    expect(importRunReason(makeRun({ status: "running", reason: null }))).toBe("");
    expect(importRunReason(makeRun({ status: "failed", reason: null }))).toBe("");
  });
});
