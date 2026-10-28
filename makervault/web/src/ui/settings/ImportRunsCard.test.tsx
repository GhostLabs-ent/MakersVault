// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import type { ImportRunDetail } from "../../lib/api";
import ImportRunsCard from "./ImportRunsCard";
import type { ImportRunsState } from "./useImportRuns";

function makeRun(overrides: Partial<ImportRunDetail> = {}): ImportRunDetail {
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
    errors: [],
    ...overrides,
  };
}

function makeState(run: ImportRunDetail | null, loading = false): ImportRunsState {
  return { run, loading, error: null, refresh: vi.fn() };
}

function renderCard(state: ImportRunsState): void {
  render(<ImportRunsCard state={state} />);
}

afterEach(() => {
  cleanup();
});

describe("ImportRunsCard", () => {
  it("explains where the data comes from", () => {
    renderCard(makeState(null));

    expect(screen.getByText("Mount import runs")).toBeTruthy();
    expect(screen.getByText(/reported by the API/i)).toBeTruthy();
    expect(screen.getByText(/update live/i)).toBeTruthy();
  });

  it("shows the empty state before any run has been recorded", () => {
    renderCard(makeState(null));

    expect(screen.getByText("No mount import has run yet.")).toBeTruthy();
    expect(screen.getByText(/recorded at startup/i)).toBeTruthy();
  });

  it("shows a loading line instead of the empty state while the first fetch runs", () => {
    renderCard(makeState(null, true));

    expect(screen.getByText("Loading import runs...")).toBeTruthy();
    expect(screen.queryByText("No mount import has run yet.")).toBeNull();
  });

  it("surfaces the fetch error instead of the empty state", () => {
    renderCard({
      run: null,
      loading: false,
      error: "Import run history is unavailable.",
      refresh: async () => {},
    });

    expect(screen.getByText("Import run history is unavailable.")).toBeTruthy();
    expect(screen.queryByText("No mount import has run yet.")).toBeNull();
  });

  it("shows live counters while a run is walking", () => {
    renderCard(
      makeState(
        makeRun({
          status: "running",
          finished_at: null,
          registered: 2,
          known: 1,
          ignored: 0,
          failed: 1,
          discovered: 4,
          skipped: 1,
        }),
      ),
    );

    expect(screen.getByText("Import in progress")).toBeTruthy();
    expect(screen.getByText("4 discovered, 2 registered, 1 skipped, 1 failed")).toBeTruthy();
    expect(screen.queryByText(/finished/i)).toBeNull();
  });

  it("summarises a succeeded run", () => {
    renderCard(makeState(makeRun()));

    expect(screen.getByText("Succeeded")).toBeTruthy();
    expect(screen.getByText("Copied into storage")).toBeTruthy();
    expect(screen.getByText("7 discovered, 4 registered, 3 skipped, 0 failed")).toBeTruthy();
    expect(screen.getByText(/Started .* · finished .* · 42s/)).toBeTruthy();
  });

  it("mentions oversize files only when the server rejected some", () => {
    renderCard(makeState(makeRun({ ignored: 2, rejected: 2, skipped: 4 })));

    expect(
      screen.getByText("7 discovered, 4 registered, 4 skipped, 0 failed, 2 oversize"),
    ).toBeTruthy();
    expect(screen.getByText(/2 oversize files exceeded the size limit/i)).toBeTruthy();
  });

  it("styles a failed run with its reason and errors", () => {
    renderCard(
      makeState(
        makeRun({
          status: "failed",
          reason: "Permission denied on /mnt/models",
          errors: ["a.stl: unreadable", "b.3mf: truncated"],
        }),
      ),
    );

    const status = screen.getByText("Failed");
    expect(status.className).toContain("text-red-400");
    expect(screen.getByText("Permission denied on /mnt/models")).toBeTruthy();
    expect(screen.getByText("a.stl: unreadable")).toBeTruthy();
    expect(screen.getByText("b.3mf: truncated")).toBeTruthy();
  });

  it("treats an interrupted run as a failure and truncates long error lists", () => {
    const errors = ["e1", "e2", "e3", "e4", "e5", "e6", "e7"];
    renderCard(makeState(makeRun({ status: "interrupted", reason: "Process exited", errors })));

    const status = screen.getByText("Interrupted");
    expect(status.className).toContain("text-red-400");
    expect(screen.getByText("e5")).toBeTruthy();
    expect(screen.queryByText("e6")).toBeNull();
    expect(screen.getByText("+2 more")).toBeTruthy();
  });

  it("does not style a skipped run as an error and shows its reason", () => {
    renderCard(
      makeState(makeRun({ status: "skipped", reason: "Mount path is not configured" })),
    );

    const status = screen.getByText("Skipped");
    expect(status.className).toContain("text-muted");
    expect(status.className).not.toContain("text-red-400");
    expect(screen.getByText("Mount path is not configured")).toBeTruthy();
  });

  it("survives a status it does not know", () => {
    renderCard(makeState(makeRun({ status: "reticulating" })));

    expect(screen.getByText("Unknown (reticulating)")).toBeTruthy();
    expect(screen.getByText(/7 discovered/)).toBeTruthy();
  });
});
