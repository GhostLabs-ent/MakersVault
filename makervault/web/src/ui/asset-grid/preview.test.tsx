// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("../ModelViewer", () => ({
  default: () => null,
  ModelSnapshot: () => null,
}));

vi.mock("../LightBurnPreview", () => ({
  default: () => null,
}));

import type { PreparedPrint } from "../../lib/api";
import { PreparedPrintSummary } from "./preview";

afterEach(cleanup);

/** The summary line sits on the outer div; the Clear button is a sibling. */
function summaryLine(prepared: PreparedPrint) {
  const { container } = render(<PreparedPrintSummary prepared={prepared} />);
  return (container.firstElementChild as HTMLElement).textContent;
}

describe("PreparedPrintSummary", () => {
  it("renders the prepared title and all four facts in a fixed order", () => {
    expect(
      summaryLine({
        printer: "Prusa MK3S+",
        slicer: "PrusaSlicer",
        material: "PLA",
        nozzle_mm: 0.4,
        layer_height_mm: 0.2,
        estimated_seconds: 11520,
        format: "bgcode",
        removable: true,
      }),
    ).toBe("Prepared for Prusa MK3S+ · PrusaSlicer · PLA · 0.4 mm · 3h 12m");

    // The title is its own span so callers can match it without the facts.
    expect(screen.getByText("Prepared for Prusa MK3S+")).toBeTruthy();
  });

  it("renders the all-unknown line for an unprepared payload", () => {
    expect(
      summaryLine({
        printer: null,
        slicer: "unknown",
        material: null,
        nozzle_mm: null,
        estimated_seconds: null,
      }),
    ).toBe("Prepared print · Unknown slicer · Unknown material · Unknown nozzle · Unknown time");

    expect(screen.getByText("Prepared print")).toBeTruthy();
  });

  it.each([undefined, null, "unknown", "  "])(
    "treats slicer %p as Unknown slicer",
    (slicer) => {
      expect(summaryLine({ slicer })).toBe(
        "Prepared print · Unknown slicer · Unknown material · Unknown nozzle · Unknown time",
      );
      cleanup();
    },
  );

  it("mixes known and unknown slots without dropping any", () => {
    expect(
      summaryLine({
        printer: "",
        slicer: "OrcaSlicer",
        material: "PETG",
        nozzle_mm: 0.6,
        estimated_seconds: 900,
      }),
    ).toBe("Prepared print · OrcaSlicer · PETG · 0.6 mm · 15m");
  });

  it("renders the Clear button only when handled and disables it while clearing", () => {
    const onClear = vi.fn();
    const prepared = { printer: "Voron" };
    const { rerender } = render(
      <PreparedPrintSummary prepared={prepared} onClear={onClear} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onClear).toHaveBeenCalledTimes(1);

    rerender(<PreparedPrintSummary prepared={prepared} onClear={onClear} clearing />);
    const clearingButton = screen.getByRole("button", { name: "Clearing..." });
    expect((clearingButton as HTMLButtonElement).disabled).toBe(true);

    cleanup();
    render(<PreparedPrintSummary prepared={prepared} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
