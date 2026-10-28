import React, { useEffect, useState } from "react";
import {
  Check,
  ChevronRight,
  Download,
  Folder as FolderIcon,
  FolderOpen,
  FolderPlus,
  Layers3,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  ScrollText,
  Settings as SettingsIcon,
  Trash2,
  X,
} from "lucide-react";
import { Folder, UnauthorizedError, createFolder, downloadFolderZip, listFolders, updateFolder } from "../lib/api";
import { flattenFolderTree } from "../lib/folderTree";
import { entriesFromDataTransfer } from "../lib/uploadTree";
import { notifyError } from "../lib/toast";
import TagInput from "./TagInput";
import { useUpload } from "./useUpload";
import FolderDeleteDialog from "./FolderDeleteDialog";

type Props = {
  selectedId?: string | null;
  onSelect: (id: string | null) => void;
  onFoldersChanged?: () => void;
  foldersVersion?: number;
  onUnauthorized?: () => void;
  onOpenSettings?: () => void;
  onOpenAudit?: () => void;
  activeView?: "library" | "settings" | "audit";
  onAssetsChanged?: () => void;
};

const DROP_ALL_ID = "__all";

export default function Sidebar({
  selectedId,
  onSelect,
  onFoldersChanged,
  foldersVersion,
  onUnauthorized,
  onOpenSettings,
  onOpenAudit,
  activeView = "library",
  onAssetsChanged,
}: Props) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newParent, setNewParent] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editTags, setEditTags] = useState<string[]>([]);
  const [editParent, setEditParent] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);
  const [dropUploading, setDropUploading] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);
  const [query, setQuery] = useState("");
  const [activeFolderId, setActiveFolderId] = useState<string | null>(selectedId ?? null);
  const uploader = useUpload({
    onUnauthorized,
    onUploaded: () => onAssetsChanged?.(),
  });

  const isFileDrag = (e: React.DragEvent<HTMLElement>) => {
    const types = Array.from(e.dataTransfer?.types || []);
    return types.includes("Files");
  };

  const handleDragOverTarget = (targetId: string) => (e: React.DragEvent<HTMLElement>) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    if (!dropUploading) {
      setDropTargetId(targetId);
    }
    e.dataTransfer.dropEffect = "copy";
  };

  const handleDropFiles = (folderId: string | null) => async (
    e: React.DragEvent<HTMLElement>
  ) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    if (dropUploading) return;
    setDropTargetId(null);
    setDropUploading(true);
    const entries = await entriesFromDataTransfer(e.dataTransfer);
    if (!entries.length) {
      setDropUploading(false);
      return;
    }
    await uploader.upload(entries, { folderId });
    setDropUploading(false);
  };

  const handleSidebarDragOver = (e: React.DragEvent<HTMLElement>) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
  };

  const handleSidebarDragLeave = (e: React.DragEvent<HTMLElement>) => {
    if (!isFileDrag(e)) return;
    if (e.currentTarget !== e.target) return;
    e.preventDefault();
    setDropTargetId(null);
  };

  const handleSidebarDrop = (e: React.DragEvent<HTMLElement>) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    if (dropUploading) return;
    const targetFolderId =
      dropTargetId === DROP_ALL_ID ? null : dropTargetId;
    setDropTargetId(null);
    if (!targetFolderId && dropTargetId !== DROP_ALL_ID) return;
    setDropUploading(true);
    void (async () => {
      const entries = await entriesFromDataTransfer(e.dataTransfer);
      if (!entries.length) {
        setDropUploading(false);
        return;
      }
      await uploader.upload(entries, { folderId: targetFolderId });
      setDropUploading(false);
    })();
  };

  const filenameFromDisposition = (res: Response, fallback: string) => {
    const dispo = res.headers.get("content-disposition") || "";
    const match = dispo.match(/filename="?([^";]+)"?/i);
    return (match && match[1]) || fallback;
  };

  const saveResponseToDisk = async (res: Response, fallback: string) => {
    const filename = filenameFromDisposition(res, fallback);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleError = (err: unknown, message: string) => {
    if (err instanceof UnauthorizedError) {
      onUnauthorized?.();
      return;
    }
    console.error(err);
    notifyError(message);
  };

  const refresh = async () => {
    try {
      setFolders(await listFolders());
    } catch (err) {
      handleError(err, "Unable to load folders.");
    }
  };
  useEffect(() => { refresh(); }, [foldersVersion]);

  const startCreate = (parentId: string | null = null) => {
    setEditing(null);
    setCreating(true);
    setNewName("");
    setNewParent(parentId ?? (selectedId || null));
  };
  const create = async () => {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      await createFolder(newName.trim(), [], newParent || undefined);
      await refresh();
      if (newParent) {
        setExpanded(prev => new Set(prev).add(newParent));
      }
      onFoldersChanged?.();
    } catch (err) {
      handleError(err, "Folder creation failed. Please try again.");
    } finally { setBusy(false); setCreating(false); }
  };

  const startEdit = (f: Folder) => {
    setCreating(false);
    setEditing(f.id);
    setEditName(f.name);
    setEditTags(f.tags);
    setEditParent(f.parent_id || null);
  };
  const saveEdit = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      await updateFolder(editing, editName.trim() || "Untitled", editTags, editParent || undefined);
      await refresh();
      onFoldersChanged?.();
    } catch (err) {
      handleError(err, "Folder update failed. Please try again.");
    } finally { setBusy(false); setEditing(null); setEditTags([]); setEditParent(null); }
  };

  const handleDeleted = async () => {
    const deletedId = pendingDelete?.id;
    setPendingDelete(null);
    await refresh();
    onFoldersChanged?.();
    if (deletedId && selectedId === deletedId) {
      // Selecting the root refetches assets through the grid's folderId effect.
      onSelect(null);
    } else {
      // Deleting a folder takes its assets with it, so the grid needs an
      // explicit refetch; the selected-folder branch above must not also bump
      // this counter or the grid would fetch twice.
      onAssetsChanged?.();
    }
  };

  const downloadFolder = async (folder: Folder) => {
    setBusy(true);
    try {
      const res = await downloadFolderZip(folder.id);
      const safe = (folder.name || "folder").replace(/\s+/g, "_") || "folder";
      await saveResponseToDisk(res, `${safe}.zip`);
    } catch (err) {
      handleError(err, "Unable to download folder.");
    } finally {
      setBusy(false);
    }
  };

  const folderById = React.useMemo(() => {
    const map: Record<string, Folder> = {};
    folders.forEach(f => { map[f.id] = f; });
    return map;
  }, [folders]);

  useEffect(() => {
    // Keep the tab stop on the selected folder when navigation happens outside
    // the tree (breadcrumbs, subfolder tiles).
    setActiveFolderId(selectedId ?? null);
  }, [selectedId]);

  useEffect(() => {
    // Ensure the selected folder's ancestors are expanded. The functional
    // update keeps manual collapses intact and avoids depending on `expanded`.
    if (!selectedId) return;
    setExpanded(prev => {
      const next = new Set(prev);
      let current = folderById[selectedId];
      const guard = new Set<string>();
      while (current?.parent_id && !guard.has(current.parent_id)) {
        next.add(current.parent_id);
        guard.add(current.parent_id);
        current = folderById[current.parent_id];
      }
      return next;
    });
  }, [selectedId, folderById]);

  const isDescendant = React.useCallback(
    (candidateId: string, targetId: string) => {
      let current = folderById[candidateId];
      const guard = new Set<string>();
      while (current) {
        if (!current.parent_id) return false;
        if (current.parent_id === targetId) return true;
        if (guard.has(current.parent_id)) break;
        guard.add(current.parent_id);
        current = folderById[current.parent_id];
      }
      return false;
    },
    [folderById]
  );

  const folderPath = React.useCallback(
    (folder: Folder) => {
      const segments = [folder.name || "Untitled"];
      let current = folder;
      const guard = new Set<string>([folder.id]);
      while (current.parent_id) {
        const parent = folderById[current.parent_id];
        if (!parent || guard.has(parent.id)) break;
        segments.unshift(parent.name || "Untitled");
        guard.add(parent.id);
        current = parent;
      }
      return segments.join(" / ");
    },
    [folderById]
  );

  const folderOptions = React.useMemo(() => {
    const opts = [{ id: null as string | null, name: "(Root)" }];
    const sorted = [...folders].sort((a, b) => folderPath(a).localeCompare(folderPath(b)));
    sorted.forEach(f => opts.push({ id: f.id, name: folderPath(f) }));
    return opts;
  }, [folders, folderPath]);

  const childrenMap = React.useMemo(() => {
    const map: Record<string, Folder[]> = {};
    const push = (key: string, f: Folder) => {
      if (!map[key]) map[key] = [];
      map[key].push(f);
    };
    folders.forEach(f => push(f.parent_id || "__root", f));
    Object.values(map).forEach(list => list.sort((a, b) => a.name.localeCompare(b.name)));
    return map;
  }, [folders]);

  const visibleFolderIds = React.useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return null;

    const visible = new Set<string>();
    folders.forEach(folder => {
      if (!folderPath(folder).toLocaleLowerCase().includes(normalizedQuery)) return;
      let current: Folder | undefined = folder;
      const guard = new Set<string>();
      while (current && !guard.has(current.id)) {
        visible.add(current.id);
        guard.add(current.id);
        current = current.parent_id ? folderById[current.parent_id] : undefined;
      }
    });
    return visible;
  }, [folderById, folderPath, folders, query]);

  // Default-expand root folders so they are visible
  useEffect(() => {
    const roots = childrenMap["__root"] || [];
    if (!roots.length) return;
    setExpanded(prev => {
      const next = new Set(prev);
      roots.forEach(r => next.add(r.id));
      return next;
    });
  }, [childrenMap]);

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const isFolderOpen = (id: string) => !!query.trim() || expanded.has(id);

  // Visible rows in DOM order, shared with the keyboard navigation below.
  const treeRows = React.useMemo(
    () =>
      flattenFolderTree(folders, {
        expanded,
        alwaysExpanded: !!query.trim(),
        isVisible: visibleFolderIds ? (id: string) => visibleFolderIds.has(id) : undefined,
      }),
    [expanded, folders, query, visibleFolderIds]
  );

  const treeRowIds = React.useMemo(
    () => new Set(treeRows.map(row => row.id)),
    [treeRows]
  );

  // Exactly one visible row owns the tab stop. If the tracked row is hidden
  // (ancestor collapsed, filtered out) fall back to the first visible row.
  const rovingFolderId =
    activeFolderId && treeRowIds.has(activeFolderId)
      ? activeFolderId
      : treeRows[0]?.id ?? null;

  const rowElements = React.useRef(new Map<string, HTMLElement>());

  const setRowElement = (id: string) => (element: HTMLDivElement | null) => {
    if (element) rowElements.current.set(id, element);
    else rowElements.current.delete(id);
  };

  const focusTreeRow = (id: string | null) => {
    if (!id) return;
    setActiveFolderId(id);
    rowElements.current.get(id)?.focus();
  };

  const handleTreeKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const rowElement = target.closest<HTMLElement>("[data-tree-row]");
    const rowId = rowElement?.dataset.treeRow;
    if (!rowId) return;
    const index = treeRows.findIndex(row => row.id === rowId);
    if (index === -1) return;
    const row = treeRows[index];

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusTreeRow(treeRows[Math.min(index + 1, treeRows.length - 1)].id);
        return;
      case "ArrowUp":
        event.preventDefault();
        focusTreeRow(treeRows[Math.max(index - 1, 0)].id);
        return;
      case "ArrowRight":
        event.preventDefault();
        if (!row.hasChildren) return;
        if (!isFolderOpen(row.id)) {
          toggleExpand(row.id);
          return;
        }
        if (treeRows[index + 1]?.depth === row.depth + 1) {
          focusTreeRow(treeRows[index + 1].id);
        }
        return;
      case "ArrowLeft":
        event.preventDefault();
        if (row.hasChildren && isFolderOpen(row.id)) {
          toggleExpand(row.id);
          return;
        }
        for (let i = index - 1; i >= 0; i -= 1) {
          if (treeRows[i].depth === row.depth - 1) {
            focusTreeRow(treeRows[i].id);
            return;
          }
        }
        return;
      case "Home":
        event.preventDefault();
        focusTreeRow(treeRows[0].id);
        return;
      case "End":
        event.preventDefault();
        focusTreeRow(treeRows[treeRows.length - 1].id);
        return;
      case "Enter":
      case " ":
        // Only the row itself opens the folder. A focused descendant (the
        // actions menu, its items, the chevron) keeps its native activation,
        // otherwise Enter/Space would select the folder instead.
        if (target !== rowElement) return;
        event.preventDefault();
        onSelect(row.id);
        return;
      default:
        return;
    }
  };

  const closeFolderMenu = (e: React.MouseEvent<HTMLElement>) => {
    const details = e.currentTarget.closest("details") as HTMLDetailsElement | null;
    if (details?.open) {
      details.open = false;
    }
  };

  const renderFolderNode = (folder: Folder, depth = 0): React.ReactNode => {
    if (visibleFolderIds && !visibleFolderIds.has(folder.id)) return null;
    const children = (childrenMap[folder.id] || []).filter(
      child => !visibleFolderIds || visibleFolderIds.has(child.id)
    );
    const isSelected = selectedId === folder.id;
    const isOpen = isFolderOpen(folder.id);
    const hasChildren = children.length > 0;
    const isDropTarget = dropTargetId === folder.id;
    return (
      // `role="none"`: the wrapper only carries indentation, so the treeitem
      // stays directly owned by the tree/group.
      <div key={folder.id} role="none" className="sidebar-tree-node">
        <div
          className={`sidebar-tree-row ${isSelected ? "is-selected" : ""} ${isDropTarget ? "is-drop-target" : ""}`}
          style={{ paddingLeft: 10 }}
          role="treeitem"
          aria-level={depth + 1}
          aria-expanded={hasChildren ? isOpen : undefined}
          aria-selected={isSelected}
          aria-current={isSelected ? "page" : undefined}
          data-tree-row={folder.id}
          tabIndex={folder.id === rovingFolderId ? 0 : -1}
          ref={setRowElement(folder.id)}
          onDragOver={handleDragOverTarget(folder.id)}
          onDrop={handleDropFiles(folder.id)}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={() => toggleExpand(folder.id)}
              className="sidebar-tree-chevron"
              aria-label={isOpen ? "Collapse" : "Expand"}
              aria-expanded={isOpen}
              tabIndex={-1}
            >
              <ChevronRight className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-90" : ""}`} />
            </button>
          ) : (
            <span className="sidebar-tree-spacer" aria-hidden="true" />
          )}
          <button
            type="button"
            className="sidebar-tree-label"
            onClick={() => onSelect(folder.id)}
            title={folderPath(folder)}
            tabIndex={-1}
          >
            {isOpen && children.length ? (
              <FolderOpen className="sidebar-folder-icon" aria-hidden="true" />
            ) : (
              <FolderIcon className="sidebar-folder-icon" aria-hidden="true" />
            )}
            <span className="truncate">{folder.name || "Untitled"}</span>
          </button>
          <div className="relative sidebar-folder-actions">
            <details>
              <summary className="sidebar-action-trigger" aria-label={`Actions for ${folder.name || "Untitled"}`}>
                <MoreHorizontal className="h-4 w-4" />
              </summary>
              <div className="sidebar-folder-menu">
                <button
                  className="sidebar-menu-item"
                  disabled={busy}
                  onClick={(e) => { closeFolderMenu(e); startCreate(folder.id); }}
                >
                  <FolderPlus className="h-4 w-4" /> Subfolder
                </button>
                <button
                  className="sidebar-menu-item"
                  disabled={busy}
                  onClick={(e) => { closeFolderMenu(e); startEdit(folder); }}
                >
                  <Pencil className="h-4 w-4" /> Rename &amp; edit
                </button>
                <button
                  className="sidebar-menu-item"
                  disabled={busy}
                  onClick={(e) => { closeFolderMenu(e); downloadFolder(folder); }}
                >
                  <Download className="h-4 w-4" /> Download ZIP
                </button>
                <button
                  className="sidebar-menu-item sidebar-menu-danger"
                  disabled={busy}
                  onClick={(e) => {
                    closeFolderMenu(e);
                    setPendingDelete({ id: folder.id, name: folder.name || "Untitled" });
                  }}
                >
                  <Trash2 className="h-4 w-4" /> Delete
                </button>
              </div>
            </details>
          </div>
        </div>
        {isOpen && hasChildren && (
          <div className="sidebar-tree-children" role="group">
            {children.map(child => renderFolderNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <aside
      className="sidebar-shell"
      onDragOver={handleSidebarDragOver}
      onDragLeave={handleSidebarDragLeave}
      onDrop={handleSidebarDrop}
    >
      <div className="sidebar-header">
        <div className="min-w-0">
          <p className="sidebar-eyebrow">Makers Vault</p>
          <div className="flex items-center gap-2">
            <h2 className="sidebar-title">Library</h2>
            <span className="sidebar-count" title={`${folders.length} folders`}>{folders.length}</span>
          </div>
        </div>
        <button className="sidebar-new-button" onClick={() => startCreate(null)} title="New folder">
          <Plus className="h-4 w-4" />
          <span>New</span>
        </button>
      </div>

      <label className="sidebar-search">
        <Search className="h-4 w-4 shrink-0" aria-hidden="true" />
        <input
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder="Search folders"
          aria-label="Search folders"
        />
        {query && (
          <button type="button" onClick={() => setQuery("")} aria-label="Clear folder search">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </label>

      <nav className="sidebar-navigation" aria-label="Library folders">
        <button
          type="button"
          className={`sidebar-all-items ${!selectedId ? "is-selected" : ""} ${dropTargetId === DROP_ALL_ID ? "is-drop-target" : ""}`}
          onClick={() => onSelect(null)}
          onKeyDown={event => {
            if (event.key !== "ArrowDown") return;
            event.preventDefault();
            focusTreeRow(treeRows[0]?.id ?? null);
          }}
          onDragOver={handleDragOverTarget(DROP_ALL_ID)}
          onDrop={handleDropFiles(null)}
        >
          <span className="sidebar-all-icon"><Layers3 className="h-4 w-4" /></span>
          <span className="flex-1 text-left">All files</span>
          <span className="sidebar-root-label">ROOT</span>
        </button>

        <div className="sidebar-section-heading">
          <span>Folders</span>
          <span>{visibleFolderIds ? visibleFolderIds.size : folders.length}</span>
        </div>

        <div
          className="sidebar-tree"
          role="tree"
          aria-label="Folders"
          onKeyDown={handleTreeKeyDown}
        >
          {(childrenMap["__root"] || []).map(f => renderFolderNode(f, 0))}
          {folders.length === 0 && (
            <div className="sidebar-empty" role="none">
              <FolderPlus className="h-5 w-5" />
              <span>No folders yet</span>
              <button onClick={() => startCreate(null)}>Create your first folder</button>
            </div>
          )}
          {!!folders.length && visibleFolderIds?.size === 0 && (
            <div className="sidebar-empty" role="none">
              <Search className="h-5 w-5" />
              <span>No matching folders</span>
              <button onClick={() => setQuery("")}>Clear search</button>
            </div>
          )}
        </div>
      </nav>

      {creating && (
        <div className="sidebar-editor" role="dialog" aria-label="Create folder">
          <div className="sidebar-editor-heading">
            <span className="sidebar-editor-icon"><FolderPlus className="h-4 w-4" /></span>
            <div><strong>New folder</strong><small>Choose a name and location</small></div>
            <button onClick={() => { setCreating(false); setNewParent(null); }} aria-label="Cancel"><X className="h-4 w-4" /></button>
          </div>
          <label>
            <span>Name</span>
            <input
              autoFocus
              value={newName}
              onChange={e=>setNewName(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") void create();
                if (e.key === "Escape") { setCreating(false); setNewParent(null); }
              }}
              placeholder="Folder name"
            />
          </label>
          <label>
            <span>Location</span>
            <select value={newParent || ""} onChange={e => setNewParent(e.target.value || null)}>
              {folderOptions.map(opt => (
                <option key={opt.id ?? "root"} value={opt.id || ""}>{opt.name}</option>
              ))}
            </select>
          </label>
          <div className="sidebar-editor-actions">
            <button disabled={busy || !newName.trim()} className="primary" onClick={create}><Check className="h-4 w-4" /> Create</button>
            <button onClick={()=>{ setCreating(false); setNewParent(null); }}>Cancel</button>
          </div>
        </div>
      )}

      {editing && (
        <div className="sidebar-editor" role="dialog" aria-label="Edit folder">
          <div className="sidebar-editor-heading">
            <span className="sidebar-editor-icon"><Pencil className="h-4 w-4" /></span>
            <div><strong>Edit folder</strong><small>Update its details</small></div>
            <button onClick={()=>{ setEditing(null); setEditTags([]); setEditParent(null); }} aria-label="Cancel"><X className="h-4 w-4" /></button>
          </div>
          <label>
            <span>Name</span>
            <input
              autoFocus
              value={editName}
              onChange={e=>setEditName(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") void saveEdit();
                if (e.key === "Escape") { setEditing(null); setEditTags([]); setEditParent(null); }
              }}
            />
          </label>
          <label>
            <span>Location</span>
            <select value={editParent || ""} onChange={e => setEditParent(e.target.value || null)}>
              {folderOptions
                .filter(opt => !editing || (opt.id !== editing && !(opt.id && isDescendant(opt.id, editing))))
                .map(opt => (
                  <option key={opt.id ?? "root"} value={opt.id || ""}>{opt.name}</option>
                ))}
            </select>
          </label>
          <TagInput value={editTags} onChange={setEditTags} placeholder="Add folder tags" />
          <div className="sidebar-editor-actions">
            <button disabled={busy} className="primary" onClick={saveEdit}><Check className="h-4 w-4" /> Save changes</button>
            <button onClick={()=>{ setEditing(null); setEditTags([]); setEditParent(null); }}>Cancel</button>
          </div>
        </div>
      )}

      <div className="sidebar-footer flex flex-col gap-1">
        <button
          type="button"
          onClick={onOpenSettings}
          className={`sidebar-settings ${activeView === "settings" ? "is-selected" : ""}`}
          aria-label="Settings"
        >
          <SettingsIcon className="h-4 w-4" />
          <span>Settings</span>
        </button>
        <button
          type="button"
          onClick={onOpenAudit}
          className={`sidebar-settings ${activeView === "audit" ? "is-selected" : ""}`}
          aria-label="Audit log"
        >
          <ScrollText className="h-4 w-4" />
          <span>Audit log</span>
        </button>
      </div>
      {pendingDelete && (
        <FolderDeleteDialog
          folder={pendingDelete}
          onCancel={() => setPendingDelete(null)}
          onDeleted={handleDeleted}
          onUnauthorized={onUnauthorized}
        />
      )}
      {uploader.modal}
    </aside>
  );
}
