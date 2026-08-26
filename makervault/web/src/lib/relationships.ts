import { ProjectRelationship, RelationshipKind } from "./api";


export const relationshipKindOptions: Array<{
  kind: RelationshipKind;
  label: string;
  help: string;
}> = [
  { kind: "derived_from", label: "Derived from", help: "The first item was derived from the second." },
  { kind: "documentation_for", label: "Documents", help: "The first item documents the second." },
  { kind: "component_of", label: "Component of", help: "The first item is a component of the second." },
];

export function relationshipLabels(kind: RelationshipKind) {
  switch (kind) {
    case "derived_from":
      return { forward: "Derived from", inverse: "Source of" };
    case "documentation_for":
      return { forward: "Documents", inverse: "Documented by" };
    case "component_of":
      return { forward: "Component of", inverse: "Contains" };
  }
}

export function relationshipSentence(
  relationship: ProjectRelationship,
  perspectiveAssetId: string,
) {
  if (perspectiveAssetId === relationship.source_asset_id) {
    return `${relationship.forward_label} ${relationship.target_name}`;
  }
  return `${relationship.inverse_label} ${relationship.source_name}`;
}
