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
  Settings as SettingsIcon,
  Trash2,
  X,
} from "lucide-react";
import {
  Folder,
  Project,
  UnauthorizedError,
  createFolder,
  createProject as createProjectRecord,
  deleteFolder,
  downloadFolderZip,
  listFolders,
  listProjects,
  updateFolder,
} from "../lib/api";
import { entriesFromDataTransfer, uploadEntriesToFolder } from "../lib/uploadTree";
import { buildUploadEntriesFromZip, isZipFile, readZipEntries } from "../lib/zipUtils";
import TagInput from "./TagInput";
import { useZipImportPrompt } from "./ZipImportModal";
import { useVaultCapabilities } from "../lib/CapabilityContext";
import type { VaultRole } from "../lib/capabilities";

type Props = {
  selectedId?: string | null;
  onSelect: (id: string | null) => void;
  onFoldersChanged?: () => void;
  foldersVersion?: number;
  onUnauthorized?: () => void;
  onOpenSettings?: () => void;
  onOpenTrash?: () => void;
  activeView?: "library" | "project" | "unassigned" | "settings" | "trash";
  onAssetsChanged?: () => void;
  selectedProjectId?: string | null;
  onSelectProject?: (id: string) => void;
  onSelectProjectUnassigned?: () => void;
  projectsVersion?: number;
  onProjectsChanged?: () => void;
  role: VaultRole;
};

const DROP_ALL_ID = "__all";

export default function Sidebar({
  selectedId,
  onSelect,
  onFoldersChanged,
  foldersVersion,
  onUnauthorized,
  onOpenSettings,
  onOpenTrash,
  activeView = "library",
  onAssetsChanged,
  selectedProjectId,
  onSelectProject,
  onSelectProjectUnassigned,
  projectsVersion,
  onProjectsChanged,
  role,
}: Props) {
  const capabilities = useVaultCapabilities();
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
  const [query, setQuery] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectQuery, setProjectQuery] = useState("");
  const [projectOffset, setProjectOffset] = useState(0);
  const [projectsHaveMore, setProjectsHaveMore] = useState(false);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const zipPrompt = useZipImportPrompt();

  const uploadWithZipPrompt = async (entries: Awaited<ReturnType<typeof entriesFromDataTransfer>>, folderId: string | null) => {
    const normalEntries = entries.filter(entry => !isZipFile(entry.file.name));
    const zipEntries = entries.filter(entry => isZipFile(entry.file.name));
    let uploaded = 0;
    const failed: string[] = [];
    const applyResult = (result: { uploaded: number; failed: string[] }) => {
      uploaded += result.uploaded;
      failed.push(...result.failed);
    };
    if (normalEntries.length) {
      const result = await uploadEntriesToFolder(
        normalEntries,
        folderId,
        onUnauthorized,
        activeView === "project" ? selectedProjectId : null
      );
      applyResult(result);
    }
    for (const entry of zipEntries) {
      let zipData: Record<string, Uint8Array> | null = null;
      const baseParts = entry.relativePath.split("/").filter(Boolean);
      baseParts.pop();
      const basePath = baseParts.join("/");
      await zipPrompt.prompt({
        label: entry.file.name,
        onImportAsZip: async () => {
          const result = await uploadEntriesToFolder(
            [entry],
            folderId,
            onUnauthorized,
            activeView === "project" ? selectedProjectId : null
          );
          applyResult(result);
        },
        loadEntries: async () => {
          const result = await readZipEntries(entry.file);
          zipData = result.data;
          return result.entries;
        },
        onImportSelected: async (selectedPaths: string[]) => {
          if (!zipData) {
            const result = await readZipEntries(entry.file);
            zipData = result.data;
          }
          const unzipEntries = buildUploadEntriesFromZip(zipData || {}, selectedPaths, basePath);
          const result = await uploadEntriesToFolder(
            unzipEntries,
            folderId,
            onUnauthorized,
            activeView === "project" ? selectedProjectId : null
          );
          applyResult(result);
        },
      });
    }
    if (uploaded) {
      onAssetsChanged?.();
    }
    if (failed.length) {
      alert(`Failed to upload: ${failed.join(", ")}`);
    }
  };

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
    await uploadWithZipPrompt(entries, folderId);
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
      await uploadWithZipPrompt(entries, targetFolderId);
      setDropUploading(false);
    })();
  };

  const filenameFromDisposition = (res: Response, fallback: string) => {
    const dispo = res.headers.get("content-disposition") || "";
    const match = dispo.match(/filename="?([^\";]+)"?/i);
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
    alert(message);
  };

  const refresh = async () => {
    try {
      setFolders(await listFolders());
    } catch (err) {
      handleError(err, "Unable to load folders.");
    }
  };
  useEffect(() => { refresh(); }, [foldersVersion]);

  const refreshProjects = async (reset = true) => {
    if (projectsLoading) return;
    setProjectsLoading(true);
    const offset = reset ? 0 : projectOffset;
    try {
      const result = await listProjects({
        q: projectQuery.trim() || undefined,
        limit: 50,
        offset,
      });
      setProjects(current => reset ? result.items : [...current, ...result.items]);
      setProjectOffset(result.nextOffset ?? offset + result.items.length);
      setProjectsHaveMore(result.hasMore);
    } catch (err) {
      handleError(err, "Unable to load Projects.");
    } finally {
      setProjectsLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => { void refreshProjects(true); }, 250);
    return () => window.clearTimeout(timer);
  }, [projectQuery, projectsVersion]);

  const createProject = async () => {
    const name = newProjectName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const project = await createProjectRecord({ name });
      setCreatingProject(false);
      setNewProjectName("");
      onProjectsChanged?.();
      onSelectProject?.(project.id);
    } catch (err) {
      handleError(err, "Project creation failed.");
    } finally {
      setBusy(false);
    }
  };

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

  const remove = async (id: string) => {
    if (!confirm("Delete this folder? Direct models will become unassigned and direct child folders will move to the root. No model files will be deleted.")) return;
    setBusy(true);
    try {
      await deleteFolder(id);
      await refresh();
      onFoldersChanged?.();
      if (selectedId === id) onSelect(null);
    }
    catch (err) {
      handleError(err, "Failed to delete folder.");
    }
    finally { setBusy(false); }
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
    // Ensure selected folder path is expanded
    if (!selectedId) return;
    const next = new Set(expanded);
    let current = folderById[selectedId];
    const guard = new Set<string>();
    while (current?.parent_id && !guard.has(current.parent_id)) {
      next.add(current.parent_id);
      guard.add(current.parent_id);
      current = folderById[current.parent_id];
    }
    setExpanded(next);
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
    const isOpen = !!query.trim() || expanded.has(folder.id);
    const isDropTarget = dropTargetId === folder.id;
    return (
      <div key={folder.id} className="sidebar-tree-node">
        <div
          className={`sidebar-tree-row ${isSelected ? "is-selected" : ""} ${isDropTarget ? "is-drop-target" : ""}`}
          style={{ paddingLeft: 10 }}
          onDragOver={capabilities.manageContent ? handleDragOverTarget(folder.id) : undefined}
          onDrop={capabilities.manageContent ? handleDropFiles(folder.id) : undefined}
        >
          {children.length ? (
            <button
              onClick={() => toggleExpand(folder.id)}
              className="sidebar-tree-chevron"
              aria-label={isOpen ? "Collapse" : "Expand"}
              aria-expanded={isOpen}
            >
              <ChevronRight className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-90" : ""}`} />
            </button>
          ) : (
            <span className="sidebar-tree-spacer" aria-hidden="true" />
          )}
          <button
            className="sidebar-tree-label"
            onClick={() => onSelect(folder.id)}
            title={folderPath(folder)}
            aria-current={isSelected ? "page" : undefined}
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
                {capabilities.manageContent && <button
                  className="sidebar-menu-item"
                  disabled={busy}
                  onClick={(e) => { closeFolderMenu(e); startCreate(folder.id); }}
                >
                  <FolderPlus className="h-4 w-4" /> Subfolder
                </button>}
                {capabilities.manageContent && <button
                  className="sidebar-menu-item"
                  disabled={busy}
                  onClick={(e) => { closeFolderMenu(e); startEdit(folder); }}
                >
                  <Pencil className="h-4 w-4" /> Rename &amp; edit
                </button>}
                <button
                  className="sidebar-menu-item"
                  disabled={busy}
                  onClick={(e) => { closeFolderMenu(e); downloadFolder(folder); }}
                >
                  <Download className="h-4 w-4" /> Download ZIP
                </button>
                {capabilities.manageContent && <button
                  className="sidebar-menu-item sidebar-menu-danger"
                  disabled={busy}
                  onClick={(e) => { closeFolderMenu(e); remove(folder.id); }}
                >
                  <Trash2 className="h-4 w-4" /> Delete
                </button>}
              </div>
            </details>
          </div>
        </div>
        {isOpen && children.length > 0 && (
          <div className="sidebar-tree-children">
            {children.map(child => renderFolderNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <aside
      className="sidebar-shell"
      onDragOver={capabilities.manageContent ? handleSidebarDragOver : undefined}
      onDragLeave={capabilities.manageContent ? handleSidebarDragLeave : undefined}
      onDrop={capabilities.manageContent ? handleSidebarDrop : undefined}
    >
      <div className="sidebar-header">
        <div className="min-w-0">
          <p className="sidebar-eyebrow">Makers Vault</p>
          <div className="flex items-center gap-2">
            <h2 className="sidebar-title">Workspace</h2>
            <span className="sidebar-count" title={`${projects.length} loaded Projects`}>{projects.length}</span>
          </div>
        </div>
        {capabilities.manageContent && <button className="sidebar-new-button" onClick={() => setCreatingProject(true)} title="New Project">
          <Plus className="h-4 w-4" />
          <span>Project</span>
        </button>}
      </div>

      <div className="min-h-0 max-h-[42%] overflow-y-auto overflow-x-hidden border-b border-panel pb-3 pr-0.5" aria-label="Projects">
        <div className="sidebar-section-heading"><span>Projects</span><span>{projects.length}</span></div>
        <label className="sidebar-search">
          <Search className="h-4 w-4 shrink-0" aria-hidden="true" />
          <input value={projectQuery} onChange={event => setProjectQuery(event.target.value)} placeholder="Search Projects" aria-label="Search Projects" />
          {projectQuery && <button type="button" onClick={() => setProjectQuery("")} aria-label="Clear Project search"><X className="h-3.5 w-3.5" /></button>}
        </label>
        <button
          className={`sidebar-all-items ${activeView === "unassigned" ? "is-selected" : ""}`}
          onClick={onSelectProjectUnassigned}
        >
          <span className="sidebar-all-icon"><Layers3 className="h-4 w-4" /></span>
          <span className="flex-1 text-left">Unassigned</span>
        </button>
        <div className="sidebar-tree">
          {projects.map(project => (
            <button
              key={project.id}
              type="button"
              className={`sidebar-tree-row w-full ${selectedProjectId === project.id && activeView === "project" ? "is-selected" : ""}`}
              onClick={() => onSelectProject?.(project.id)}
              title={project.name}
            >
              <span className="sidebar-tree-spacer" aria-hidden="true" />
              <span className="sidebar-tree-label min-w-0">
                <Layers3 className="sidebar-folder-icon" aria-hidden="true" />
                <span className="truncate">{project.name}</span>
              </span>
              <span className="sidebar-count">{project.member_count}</span>
            </button>
          ))}
          {!projects.length && !projectsLoading && <div className="sidebar-empty"><Layers3 className="h-5 w-5" /><span>{projectQuery ? "No matching Projects" : "No Projects yet"}</span></div>}
          {projectsHaveMore && <button type="button" className="sidebar-menu-item justify-center" disabled={projectsLoading} onClick={() => void refreshProjects(false)}>{projectsLoading ? "Loading…" : "Load more Projects"}</button>}
        </div>
      </div>

      {capabilities.manageContent && creatingProject && (
        <div className="sidebar-editor" role="dialog" aria-label="Create Project">
          <div className="sidebar-editor-heading">
            <span className="sidebar-editor-icon"><Layers3 className="h-4 w-4" /></span>
            <div><strong>New Project</strong><small>The thing you are building</small></div>
            <button onClick={() => setCreatingProject(false)} aria-label="Cancel"><X className="h-4 w-4" /></button>
          </div>
          <label><span>Name</span><input autoFocus value={newProjectName} onChange={event => setNewProjectName(event.target.value)} onKeyDown={event => { if (event.key === "Enter") void createProject(); if (event.key === "Escape") setCreatingProject(false); }} placeholder="Project name" /></label>
          <div className="sidebar-editor-actions"><button className="primary" disabled={busy || !newProjectName.trim()} onClick={createProject}><Check className="h-4 w-4" /> Create</button><button onClick={() => setCreatingProject(false)}>Cancel</button></div>
        </div>
      )}

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
          className={`sidebar-all-items ${activeView === "library" && !selectedId ? "is-selected" : ""} ${dropTargetId === DROP_ALL_ID ? "is-drop-target" : ""}`}
          onClick={() => onSelect(null)}
          onDragOver={capabilities.manageContent ? handleDragOverTarget(DROP_ALL_ID) : undefined}
          onDrop={capabilities.manageContent ? handleDropFiles(null) : undefined}
        >
          <span className="sidebar-all-icon"><Layers3 className="h-4 w-4" /></span>
          <span className="flex-1 text-left">All files</span>
          <span className="sidebar-root-label">ROOT</span>
        </button>

        <div className="sidebar-section-heading">
          <span>Folders</span>
          <span className="flex items-center gap-2">
            <span>{visibleFolderIds ? visibleFolderIds.size : folders.length}</span>
            {capabilities.manageContent && <button
              type="button"
              className="inline-flex items-center gap-1 rounded px-1.5 py-1 normal-case tracking-normal hover:bg-panel-soft hover:text-foreground"
              onClick={() => startCreate(null)}
              title="New root folder"
            >
              <FolderPlus className="h-3.5 w-3.5" /> New
            </button>}
          </span>
        </div>

        <div className="sidebar-tree">
          {(childrenMap["__root"] || []).map(f => renderFolderNode(f, 0))}
          {folders.length === 0 && (
            <div className="sidebar-empty">
              <FolderPlus className="h-5 w-5" />
              <span>No folders yet</span>
              {capabilities.manageContent && <button onClick={() => startCreate(null)}>Create your first folder</button>}
            </div>
          )}
          {!!folders.length && visibleFolderIds?.size === 0 && (
            <div className="sidebar-empty">
              <Search className="h-5 w-5" />
              <span>No matching folders</span>
              <button onClick={() => setQuery("")}>Clear search</button>
            </div>
          )}
        </div>
      </nav>

      {capabilities.manageContent && creating && (
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

      {capabilities.manageContent && editing && (
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

      <div className="sidebar-footer">
        {capabilities.openTrash && <button
          type="button"
          onClick={onOpenTrash}
          className={`sidebar-settings ${activeView === "trash" ? "is-selected" : ""}`}
          aria-label="Trash"
        >
          <Trash2 className="h-4 w-4" />
          <span>Trash</span>
        </button>}
        <button
          type="button"
          onClick={onOpenSettings}
          className={`sidebar-settings ${activeView === "settings" ? "is-selected" : ""}`}
          aria-label="Settings"
        >
          <SettingsIcon className="h-4 w-4" />
          <span>Settings</span>
        </button>
        <span className="sidebar-count" title="Current shared-vault role">{role}</span>
      </div>
      {zipPrompt.modal}
    </aside>
  );
}
