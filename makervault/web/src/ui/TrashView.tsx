import React from "react";
import { RotateCcw, Trash2 } from "lucide-react";
import {
  TrashConflictError,
  TrashItem,
  ProjectTrashItem,
  TrashSettings,
  UnauthorizedError,
  emptyTrash,
  getTrashSettings,
  listTrash,
  listProjectTrash,
  permanentlyDeleteProject,
  permanentlyDeleteTrash,
  restoreProject,
  restoreTrashAsset,
} from "../lib/api";
import {
  PROJECT_PERMANENT_CONFIRMATION,
  projectTrashCountsLabel,
} from "../lib/projectLifecycle";


const RETENTION_LABELS: Record<string, string> = {
  until_needed: "Until space is needed",
  day: "1 day",
  week: "1 week",
  month: "1 month",
  never: "Never",
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export default function TrashView({
  onAssetsChanged,
  onProjectsChanged,
  onUnauthorized,
  onOpenSettings,
}: {
  onAssetsChanged?: () => void;
  onProjectsChanged?: () => void;
  onUnauthorized?: () => void;
  onOpenSettings?: () => void;
}) {
  const [items, setItems] = React.useState<TrashItem[]>([]);
  const [projects, setProjects] = React.useState<ProjectTrashItem[]>([]);
  const [projectOffset, setProjectOffset] = React.useState(0);
  const [projectHasMore, setProjectHasMore] = React.useState(false);
  const [projectBusyId, setProjectBusyId] = React.useState<string | null>(null);
  const [projectLoadingMore, setProjectLoadingMore] = React.useState(false);
  const [settings, setSettings] = React.useState<TrashSettings | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [emptying, setEmptying] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [trash, nextSettings, projectTrash] = await Promise.all([
        listTrash(),
        getTrashSettings(),
        listProjectTrash({ limit: 100, offset: 0 }),
      ]);
      setItems(trash);
      setSettings(nextSettings);
      setProjects(projectTrash.items);
      setProjectOffset(projectTrash.nextOffset ?? projectTrash.items.length);
      setProjectHasMore(projectTrash.hasMore);
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Failed to load Trash");
    } finally {
      setLoading(false);
    }
  }, [onUnauthorized]);

  React.useEffect(() => { void load(); }, [load]);

  const loadMoreProjects = async () => {
    setProjectLoadingMore(true);
    try {
      const result = await listProjectTrash({ limit: 100, offset: projectOffset });
      setProjects(current => [...current, ...result.items]);
      setProjectOffset(result.nextOffset ?? projectOffset + result.items.length);
      setProjectHasMore(result.hasMore);
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Failed to load more Project Trash");
    } finally {
      setProjectLoadingMore(false);
    }
  };

  const restoreTrashedProject = async (project: ProjectTrashItem) => {
    setProjectBusyId(project.id);
    setMessage(null);
    try {
      await restoreProject(project.id);
      setMessage(`Restored Project ${project.name}.`);
      onProjectsChanged?.();
      await load();
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Project restore failed");
    } finally {
      setProjectBusyId(null);
    }
  };

  const permanentlyDeleteTrashedProject = async (project: ProjectTrashItem) => {
    const confirmation = window.prompt(
      `Permanently delete Project "${project.name}" metadata, memberships, and relationships?\n\nMember models and their histories will remain untouched. Type ${PROJECT_PERMANENT_CONFIRMATION} to continue.`,
    );
    if (confirmation !== PROJECT_PERMANENT_CONFIRMATION) return;
    setProjectBusyId(project.id);
    setMessage(null);
    try {
      await permanentlyDeleteProject(project.id, confirmation);
      setMessage(`Permanently deleted Project ${project.name}. Member models were preserved.`);
      onProjectsChanged?.();
      await load();
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Permanent Project deletion failed");
    } finally {
      setProjectBusyId(null);
    }
  };

  const restore = async (item: TrashItem, restoreUnassigned = false) => {
    setBusyId(item.id);
    setMessage(null);
    try {
      await restoreTrashAsset(item.id, restoreUnassigned);
      setMessage(`Restored ${item.name}.`);
      onAssetsChanged?.();
      await load();
    } catch (error) {
      if (error instanceof TrashConflictError && error.code === "original_folder_missing") {
        if (window.confirm(`${error.message}. Restore this model as Unassigned?`)) {
          setBusyId(null);
          await restore(item, true);
          return;
        }
      } else if (error instanceof TrashConflictError && error.code === "name_conflict") {
        setMessage(`${error.message}. Rename or move the active model before restoring this one.`);
      } else if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Restore failed");
    } finally {
      setBusyId(null);
    }
  };

  const permanentlyDelete = async (item: TrashItem) => {
    const confirmation = window.prompt(
      `Permanently delete "${item.name}" and ${item.managed_file_count} managed file(s)?\n\nThis cannot be undone. Type PERMANENTLY DELETE to continue.`,
    );
    if (confirmation !== "PERMANENTLY DELETE") return;
    setBusyId(item.id);
    setMessage(null);
    try {
      const result = await permanentlyDeleteTrash([item.id], confirmation);
      setMessage(result.length ? `Permanently deleted ${item.name}.` : "Nothing was deleted.");
      onAssetsChanged?.();
      await load();
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Permanent deletion failed");
    } finally {
      setBusyId(null);
    }
  };

  const empty = async () => {
    const confirmation = window.prompt(
      `Permanently delete all ${items.length} model(s) in Trash?\n\nThis cannot be undone. Type EMPTY TRASH to continue.`,
    );
    if (confirmation !== "EMPTY TRASH") return;
    setEmptying(true);
    setMessage(null);
    try {
      const results = await emptyTrash(confirmation);
      setMessage(`Permanently deleted ${results.length} model(s).`);
      onAssetsChanged?.();
      await load();
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Empty Trash failed");
    } finally {
      setEmptying(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Trash</h1>
          <p className="mt-1 text-sm text-muted">
            Restore Project organization or models independently. Model retention never deletes Projects.
          </p>
        </div>
        <button
          type="button"
          className="rounded-md border border-red-500/60 px-3 py-2 text-sm text-red-700 disabled:opacity-50 dark:text-red-300"
          disabled={!items.length || emptying || busyId !== null}
          onClick={empty}
        >
          {emptying ? "Emptying..." : "Empty Trash"}
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-panel bg-panel-soft p-3 text-sm">
        <div>
          <span className="font-medium">Retention: </span>
          {settings ? RETENTION_LABELS[settings.policy] : "Loading..."}
          {settings && <span className="ml-2 text-muted">· {formatBytes(settings.managed_bytes)} managed</span>}
        </div>
        <button type="button" className="text-xs underline-offset-2 hover:underline" onClick={onOpenSettings}>
          Change in Settings
        </button>
      </div>

      {settings?.orphaned_quarantine.length ? (
        <div className="rounded-lg border border-amber-500/50 bg-amber-100/60 p-3 text-sm text-amber-950 dark:bg-amber-950/30 dark:text-amber-100">
          Quarantine diagnostics found {settings.orphaned_quarantine.length} unknown operation director{settings.orphaned_quarantine.length === 1 ? "y" : "ies"}. No files were deleted; inspect server diagnostics.
        </div>
      ) : null}
      {message && <div className="rounded-md border border-panel bg-panel-soft p-3 text-sm" aria-live="polite">{message}</div>}

      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold">Project Trash</h2>
          <p className="text-xs text-muted">Projects retain memberships and relationships indefinitely and own no model bytes.</p>
        </div>
        {loading ? (
          <div className="rounded-lg border border-panel bg-panel-soft p-4 text-sm text-muted">Loading Project Trash...</div>
        ) : projects.length ? (
          <div className="divide-y divide-panel overflow-hidden rounded-lg border border-panel bg-panel-soft">
            {projects.map(project => (
              <div key={project.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="truncate font-medium" title={project.name}>{project.name}</div>
                  <div className="mt-1 text-xs text-muted">Deleted {new Date(project.deleted_at).toLocaleString()}</div>
                  <div className="mt-1 text-xs text-muted">{projectTrashCountsLabel(project)}</div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    className="flex items-center gap-1 rounded-md border border-panel-strong px-2 py-1.5 text-xs disabled:opacity-50"
                    disabled={projectBusyId !== null}
                    onClick={() => void restoreTrashedProject(project)}
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    {projectBusyId === project.id ? "Working..." : "Restore"}
                  </button>
                  <button
                    type="button"
                    className="flex items-center gap-1 rounded-md border border-red-500/60 px-2 py-1.5 text-xs text-red-700 disabled:opacity-50 dark:text-red-300"
                    disabled={projectBusyId !== null}
                    onClick={() => void permanentlyDeleteTrashedProject(project)}
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Permanent delete
                  </button>
                </div>
              </div>
            ))}
            {projectHasMore && (
              <div className="p-3 text-center">
                <button type="button" className="rounded-md border border-panel-strong px-3 py-2 text-xs disabled:opacity-50" disabled={projectLoadingMore} onClick={() => void loadMoreProjects()}>
                  {projectLoadingMore ? "Loading..." : "Load more Projects"}
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-panel-strong p-5 text-center text-sm text-muted">Project Trash is empty.</div>
        )}
      </section>

      <div>
        <h2 className="text-lg font-semibold">Model Trash</h2>
        <p className="text-xs text-muted">The retention setting and Empty Trash apply only to models and managed bytes.</p>
      </div>

      {loading ? (
        <div className="py-12 text-center text-sm text-muted">Loading Trash...</div>
      ) : items.length ? (
        <div className="divide-y divide-panel overflow-hidden rounded-lg border border-panel bg-panel-soft">
          {items.map(item => (
            <div key={item.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="truncate font-medium" title={item.name}>{item.name}</div>
                <div className="truncate text-xs text-subtle" title={item.filename}>{item.filename}</div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                  <span>Deleted {new Date(item.deleted_at).toLocaleString()}</span>
                  <span>From {item.original_folder_name || "Unassigned"}</span>
                  <span>{item.revision_count} version{item.revision_count === 1 ? "" : "s"}</span>
                  <span>{item.managed_file_count} managed file{item.managed_file_count === 1 ? "" : "s"}</span>
                  <span>{formatBytes(item.managed_bytes)}</span>
                </div>
                {item.external_source && (
                  <div className="mt-1 text-xs text-muted">External no-copy source will never be deleted by MakersVault.</div>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  className="flex items-center gap-1 rounded-md border border-panel-strong px-2 py-1.5 text-xs disabled:opacity-50"
                  disabled={busyId !== null || emptying}
                  onClick={() => restore(item)}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  {busyId === item.id ? "Working..." : "Restore"}
                </button>
                <button
                  type="button"
                  className="flex items-center gap-1 rounded-md border border-red-500/60 px-2 py-1.5 text-xs text-red-700 disabled:opacity-50 dark:text-red-300"
                  disabled={busyId !== null || emptying}
                  onClick={() => permanentlyDelete(item)}
                >
                  <Trash2 className="h-3.5 w-3.5" /> Permanent delete
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-panel-strong py-14 text-center">
          <Trash2 className="mx-auto mb-3 h-8 w-8 text-muted" />
          <div className="font-medium">Model Trash is empty</div>
          <div className="mt-1 text-sm text-muted">Deleted models will appear here and can be restored.</div>
        </div>
      )}
    </div>
  );
}
