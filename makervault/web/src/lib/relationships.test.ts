import { describe, expect, it } from "vitest";

import { relationshipLabels, relationshipSentence } from "./relationships";


describe("Project relationship presentation", () => {
  it("computes readable forward and inverse labels without inverse rows", () => {
    expect(relationshipLabels("derived_from")).toEqual({
      forward: "Derived from",
      inverse: "Source of",
    });
    expect(relationshipLabels("documentation_for")).toEqual({
      forward: "Documents",
      inverse: "Documented by",
    });
    expect(relationshipLabels("component_of")).toEqual({
      forward: "Component of",
      inverse: "Contains",
    });
  });

  it("describes either endpoint from one canonical directed relationship", () => {
    const relationship = {
      id: "relationship-1",
      project_id: "project-1",
      source_asset_id: "part",
      target_asset_id: "assembly",
      source_name: "Carrier board",
      target_name: "Relay assembly",
      kind: "component_of" as const,
      created_at: "now",
      forward_label: "Component of",
      inverse_label: "Contains",
    };

    expect(relationshipSentence(relationship, "part")).toBe(
      "Component of Relay assembly",
    );
    expect(relationshipSentence(relationship, "assembly")).toBe(
      "Contains Carrier board",
    );
  });
});
