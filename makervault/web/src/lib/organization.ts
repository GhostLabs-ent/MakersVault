export type FolderNode = {
  id: string;
  name: string;
  parent_id?: string | null;
};

export type TagMutationMode = "add" | "remove";

export function buildFolderTrail(folderId: string | null | undefined, folders: FolderNode[]): FolderNode[] {
  if (!folderId) return [];
  const byId = new Map(folders.map(folder => [folder.id, folder]));
  const trail: FolderNode[] = [];
  const visited = new Set<string>();
  let current = byId.get(folderId);
  while (current && !visited.has(current.id)) {
    trail.unshift(current);
    visited.add(current.id);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return trail;
}

export function mutateTags(existing: string[], requested: string[], mode: TagMutationMode): string[] {
  const normalized = requested.map(tag => tag.trim()).filter(Boolean);
  const requestedKeys = new Set(normalized.map(tag => tag.toLocaleLowerCase()));
  if (mode === "remove") {
    return existing.filter(tag => !requestedKeys.has(tag.toLocaleLowerCase()));
  }

  const result = [...existing];
  const present = new Set(existing.map(tag => tag.toLocaleLowerCase()));
  for (const tag of normalized) {
    const key = tag.toLocaleLowerCase();
    if (present.has(key)) continue;
    present.add(key);
    result.push(tag);
  }
  return result;
}

export function selectionAfterSuccess(current: Set<string>, succeededIds: Iterable<string>): Set<string> {
  const next = new Set(current);
  for (const id of succeededIds) next.delete(id);
  return next;
}
