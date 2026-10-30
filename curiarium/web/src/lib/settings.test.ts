import { describe, expect, it } from "vitest";

import {
  engraverLabelFor,
  resolveTheme,
  slicerLabelFor,
} from "./settings";


describe("application settings helpers", () => {
  it("uses stable labels for configured applications", () => {
    expect(slicerLabelFor("orca")).toBe("OrcaSlicer");
    expect(engraverLabelFor("lightburn")).toBe("LightBurn");
  });

  it("uses safe fallback labels for unknown applications", () => {
    expect(slicerLabelFor("unknown")).toBe("Slicer");
    expect(engraverLabelFor(null)).toBe("Engraving");
  });

  it("resolves system theme safely without a browser window", () => {
    expect(resolveTheme("system")).toBe("light");
    expect(resolveTheme("purple")).toBe("purple");
  });
});
