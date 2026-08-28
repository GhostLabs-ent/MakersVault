import { describe, expect, it } from "vitest";

import {
  DESCRIPTIVE_CONTEXT_NOTICE,
  MACHINE_PERMANENT_CONFIRMATION,
  activePreparedTargets,
  machineCategoryLabel,
  shouldLoadMachineContext,
} from "./machineContext";


const machine = (
  id: string,
  category: "fdm_printer" | "resin_printer" | "laser" | "other",
  archived_at: string | null = null,
) => ({
  id,
  name: id,
  category,
  manufacturer: null,
  model: null,
  location: null,
  notes: null,
  created_at: "now",
  updated_at: "now",
  archived_at,
});


describe("descriptive Machine context", () => {
  it("uses the accepted non-dispatch wording and confirmation", () => {
    expect(DESCRIPTIVE_CONTEXT_NOTICE).toBe(
      "Descriptive context only. No job was sent.",
    );
    expect(MACHINE_PERMANENT_CONFIRMATION).toBe(
      "PERMANENTLY DELETE MACHINE",
    );
    expect(machineCategoryLabel("fdm_printer")).toBe("FDM printer");
  });

  it("offers only active FDM and resin profiles as prepared targets", () => {
    expect(activePreparedTargets([
      machine("active-fdm", "fdm_printer"),
      machine("active-resin", "resin_printer"),
      machine("laser", "laser"),
      machine("archived-fdm", "fdm_printer", "later"),
      machine("other", "other"),
    ]).map(row => row.id)).toEqual(["active-fdm", "active-resin"]);
  });

  it("loads per-Artifact context only for an open detail view", () => {
    expect(shouldLoadMachineContext(false)).toBe(false);
    expect(shouldLoadMachineContext(true)).toBe(true);
  });
});
