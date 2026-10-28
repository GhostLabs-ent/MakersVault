/**
 * Where a website import should land: nowhere (today's loose-asset import), a
 * project created from the model page, or an existing project.
 */
export type ImportProjectTarget =
  | { kind: "none" }
  | { kind: "new" }
  | { kind: "existing"; projectId: string; projectName: string };

/**
 * The project fields `POST /import/project` takes for a target. An existing
 * project is addressed by id; a new one is named by the server from the page,
 * so `none` and `new` both send nothing.
 *
 * URL canonicalisation and "same page imported twice reuses the project" are
 * server-side: do not grow a client copy of that logic here.
 */
export function targetPayload(target: ImportProjectTarget): {
  project_id?: string;
  project_name?: string;
} {
  if (target.kind === "existing") return { project_id: target.projectId };
  return {};
}
