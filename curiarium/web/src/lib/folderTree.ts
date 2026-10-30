import type { Folder } from "./api";

export type FolderPathSegment = { id: string; name: string };

/** Flat row of the sidebar tree. */
export type FolderTreeRow = { id: string; depth: number; hasChildren: boolean };

const UNTITLED = "Untitled";

function nameOf(folder: Folder): string {
  return folder.name || UNTITLED;
}

/** `folders` keyed by id; later duplicates win, matching the inlined maps in the UI. */
export function indexFolders(folders: readonly Folder[]): Record<string, Folder> {
  const map: Record<string, Folder> = {};
  for (const folder of folders) {
    map[folder.id] = folder;
  }
  return map;
}

function parentOf(folder: Folder): string | null {
  return folder.parent_id ?? null;
}

/**
 * Root→current trail of `folderId`. Returns `[]` for a null/unknown id, stops
 * at a missing parent, and is cycle-guarded so corrupt data cannot hang.
 */
export function folderPath(
  folders: readonly Folder[],
  folderId: string | null | undefined,
): FolderPathSegment[] {
  if (!folderId) return [];
  const byId = indexFolders(folders);
  let current = byId[folderId];
  if (!current) return [];

  const segments: FolderPathSegment[] = [{ id: current.id, name: nameOf(current) }];
  const guard = new Set<string>([current.id]);
  while (parentOf(current)) {
    const parent = byId[parentOf(current) as string];
    if (!parent || guard.has(parent.id)) break;
    segments.unshift({ id: parent.id, name: nameOf(parent) });
    guard.add(parent.id);
    current = parent;
  }
  return segments;
}

/** Direct children of `parentId` (null = roots), ordered by name. */
export function childFolders(folders: readonly Folder[], parentId: string | null): Folder[] {
  return folders
    .filter(folder => parentOf(folder) === parentId)
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Children grouped by parent id, each group name-sorted (`__root` holds the roots). */
function childrenByParent(folders: readonly Folder[]): Record<string, Folder[]> {
  const groups: Record<string, Folder[]> = {};
  for (const folder of folders) {
    const key = parentOf(folder) ?? "__root";
    if (!groups[key]) groups[key] = [];
    groups[key].push(folder);
  }
  for (const list of Object.values(groups)) {
    list.sort((a, b) => a.name.localeCompare(b.name));
  }
  return groups;
}

/**
 * Depth-first rows in the sidebar's render order: roots first, siblings by
 * name, children only under an expanded (or always-expanded) parent. Subtrees
 * rejected by `isVisible` are skipped whole.
 */
export function flattenFolderTree(
  folders: readonly Folder[],
  options: {
    expanded: ReadonlySet<string>;
    alwaysExpanded?: boolean;
    isVisible?: (id: string) => boolean;
  },
): FolderTreeRow[] {
  const groups = childrenByParent(folders);
  const rows: FolderTreeRow[] = [];
  const visited = new Set<string>();

  const visit = (parentId: string | null, depth: number): void => {
    for (const folder of groups[parentId ?? "__root"] ?? []) {
      if (visited.has(folder.id)) continue;
      visited.add(folder.id);
      if (options.isVisible && !options.isVisible(folder.id)) continue;

      const children = groups[folder.id] ?? [];
      rows.push({ id: folder.id, depth, hasChildren: children.length > 0 });
      if (children.length && (options.alwaysExpanded || options.expanded.has(folder.id))) {
        visit(folder.id, depth + 1);
      }
    }
  };

  visit(null, 0);
  return rows;
}
