import { useMemo, useState } from "react";

import { Asset, Folder } from "../../lib/api";
import { childFolders } from "../../lib/folderTree";
import { extOf, type GroupBucket, type SortDir, type SortKey } from "./assetGridMeta";

type AssetSortingOptions = {
  items: Asset[];
  folders: Folder[];
  folderId?: string | null;
  /** The toolbar's sort state is owned by the listing hook (it drives requests). */
  sortKey: SortKey;
  setSortKey: (key: SortKey) => void;
  sortDir: SortDir;
  setSortDir: (dir: SortDir) => void;
};

export type AssetSortingApi = {
  sortKey: SortKey;
  setSortKey: (key: SortKey) => void;
  sortDir: SortDir;
  setSortDir: (dir: SortDir) => void;
  sortedItems: Asset[];
  folderGroups: GroupBucket[];
  typeGroups: GroupBucket[];
  collapsedGroups: Set<string>;
  expandedGroups: Set<string>;
  toggleGroup: (id: string) => void;
  toggleGroupExpanded: (id: string) => void;
  folderById: Record<string, Folder>;
  folderNames: Record<string, string>;
  folderOptions: { id: string | null; name: string }[];
  subfolders: Folder[];
  dropTargetName: string;
};

/**
 * Sort order, the grouped buckets, the derived folder lookups and the group
 * collapse state. Pure derivation from the listing: no effects, no requests.
 */
export function useAssetSorting({
  items,
  folders,
  folderId,
  sortKey,
  setSortKey,
  sortDir,
  setSortDir,
}: AssetSortingOptions): AssetSortingApi {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const folderById = useMemo(() => {
    const map: Record<string, Folder> = {};
    folders.forEach(f => { map[f.id] = f; });
    return map;
  }, [folders]);

  const dropTargetName = useMemo(() => {
    if (!folderId) return "All Items";
    return folderById[folderId]?.name || "this folder";
  }, [folderId, folderById]);

  const folderNames = useMemo(() => {
    const m: Record<string, string> = {};
    const pathFor = (f: Folder): string => {
      const parts = [f.name || "Untitled"];
      let current = f;
      const guard = new Set<string>([f.id]);
      while (current.parent_id) {
        const parent = folderById[current.parent_id];
        if (!parent || guard.has(parent.id)) break;
        parts.unshift(parent.name || "Untitled");
        guard.add(parent.id);
        current = parent;
      }
      return parts.join(" / ");
    };
    for (const f of folders) {
      m[f.id] = pathFor(f);
    }
    return m;
  }, [folders, folderById]);

  // Direct subfolders of the open folder, derived from the folder list the grid
  // already fetched — no extra requests.
  const subfolders = useMemo(() => childFolders(folders, folderId ?? null), [folderId, folders]);

  const folderOptions = useMemo(() => {
    return [
      { id: null as string | null, name: "Unassigned" },
      ...folders
        .map(f => ({ id: f.id, name: folderNames[f.id] || f.name || "Untitled" }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    ];
  }, [folders, folderNames]);

  const sortedItems = useMemo(() => {
    // name/size/creator are server-backed: the full listing is already ordered,
    // so re-sorting the loaded page here would undo the global order.
    if (sortKey !== "type" && sortKey !== "folder") return items;

    const copy = [...items];
    const dir = sortDir === "asc" ? 1 : -1;
    const nameForFolder = (a: Asset) => (a.folder_id ? folderNames[a.folder_id] || "" : "");
    copy.sort((a, b) => {
      if (sortKey === "type") {
        return extOf(a.filename).localeCompare(extOf(b.filename)) * dir;
      }
      // folder
      return nameForFolder(a).localeCompare(nameForFolder(b)) * dir;
    });
    return copy;
  }, [items, sortKey, sortDir, folderNames]);

  const folderGroups = useMemo<GroupBucket[]>(() => {
    if (sortKey !== "folder") return [];
    const grouping: Record<string, GroupBucket> = {};
    for (const item of items) {
      const key = item.folder_id || "__ungrouped";
      if (!grouping[key]) {
        grouping[key] = {
          id: `folder:${key}`,
          title: item.folder_id ? folderNames[item.folder_id] || "Untitled" : "Unassigned",
          items: [],
        };
      }
      grouping[key].items.push(item);
    }
    const dir = sortDir === "asc" ? 1 : -1;
    return Object.values(grouping)
      .sort((a, b) => a.title.localeCompare(b.title) * dir)
      .map(group => ({
        ...group,
        items: group.items.sort((a, b) => a.filename.localeCompare(b.filename)),
      }));
  }, [items, folderNames, sortKey, sortDir]);

  const typeGroups = useMemo<GroupBucket[]>(() => {
    if (sortKey !== "type") return [];
    const grouping: Record<string, GroupBucket> = {};
    for (const item of items) {
      const ext = extOf(item.filename) || "other";
      if (!grouping[ext]) {
        grouping[ext] = {
          id: `type:${ext}`,
          title: ext === "other" ? "Other" : ext.toUpperCase(),
          items: [],
        };
      }
      grouping[ext].items.push(item);
    }
    const dir = sortDir === "asc" ? 1 : -1;
    return Object.values(grouping)
      .sort((a, b) => a.title.localeCompare(b.title) * dir)
      .map(group => ({
        ...group,
        items: group.items.sort((a, b) => a.filename.localeCompare(b.filename)),
      }));
  }, [items, sortKey, sortDir]);

  const toggleGroup = (id: string) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleGroupExpanded = (id: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return {
    sortKey,
    setSortKey,
    sortDir,
    setSortDir,
    sortedItems,
    folderGroups,
    typeGroups,
    collapsedGroups,
    expandedGroups,
    toggleGroup,
    toggleGroupExpanded,
    folderById,
    folderNames,
    folderOptions,
    subfolders,
    dropTargetName,
  };
}
