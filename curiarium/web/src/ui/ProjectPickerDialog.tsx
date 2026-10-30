import { useEffect, useState, type KeyboardEvent, type ReactElement } from "react";

import {
  UnauthorizedError,
  addProjectAssets,
  createProject,
  listProjects,
  type Project,
  type ProjectMembersResult,
} from "../lib/api";
import { notifyError, notifyInfo } from "../lib/toast";

type Props = {
  /** The exact selection the picker adds; one request for the whole list. */
  assetIds: string[];
  onClose: () => void;
  /** Fires after the picker created a project or changed its membership. */
  onChanged?: () => void;
  onUnauthorized?: () => void;
};

export type MembersSummary = {
  tone: "info" | "error";
  message: string;
  details?: string[];
};

/**
 * Toast payload for one add-to-project request, using ProjectLanding's "parts"
 * idiom: only nonzero counts are named, and a request that added nothing but
 * failed something is an error.
 */
export function membersSummary(
  projectName: string,
  result: ProjectMembersResult,
): MembersSummary {
  const parts = [`${result.added.length} added`];
  if (result.skipped.length > 0) parts.push(`${result.skipped.length} already in project`);
  if (result.failed.length > 0) parts.push(`${result.failed.length} failed`);
  const details = result.failed.map(failure => `${failure.id}: ${failure.error}`);
  const summary: MembersSummary = {
    tone: result.added.length === 0 && result.failed.length > 0 ? "error" : "info",
    message: `Add to "${projectName}": ${parts.join(", ")}.`,
  };
  if (details.length > 0) summary.details = details;
  return summary;
}

const FOCUS_VISIBLE =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const BUTTON_PRIMARY = `inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-sm font-semibold transition-colors hover:bg-accent-strong disabled:opacity-60 ${FOCUS_VISIBLE}`;
const BUTTON_SECONDARY = `inline-flex items-center gap-1.5 rounded-md border border-panel-strong px-3 py-2 text-sm transition-colors hover:bg-panel-soft disabled:opacity-60 ${FOCUS_VISIBLE}`;
const INPUT_BASE = `w-full min-w-0 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm ${FOCUS_VISIBLE}`;

/**
 * "Add to project…" picker for an existing selection (Mf-1sfc).
 *
 * There is no role gating here on purpose: the client is not the security
 * boundary (docs/PERMISSIONS.md), so everybody sees the affordance and a
 * viewer's attempt surfaces the server's 403 detail as a toast.
 */
export default function ProjectPickerDialog({
  assetIds,
  onClose,
  onChanged,
  onUnauthorized,
}: Props): ReactElement {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await listProjects();
        if (!cancelled) setProjects(list);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
          return;
        }
        console.error(err);
        setLoadFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onUnauthorized]);

  const selected = projects?.find(project => project.id === selectedId) ?? null;
  const fileCount = assetIds.length;
  const fileWord = fileCount === 1 ? "file" : "files";
  const addLabel = selected
    ? `Add ${fileCount} ${fileWord} to "${selected.name}"`
    : `Add ${fileCount} ${fileWord}`;

  /** The single request path: create-and-add reuses it for the new project. */
  const addToProject = async (project: Project) => {
    if (busy || fileCount === 0) return;
    setBusy(true);
    try {
      const result = await addProjectAssets(project.id, assetIds);
      const summary = membersSummary(project.name, result);
      if (summary.tone === "error") notifyError(summary.message, { details: summary.details });
      else notifyInfo(summary.message, { details: summary.details });
      onChanged?.();
      onClose();
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      notifyError(
        err instanceof Error && err.message
          ? err.message
          : "Failed to add files to the project.",
      );
    } finally {
      setBusy(false);
    }
  };

  const createAndAdd = async () => {
    const name = draft.trim();
    if (!name || busy) return;
    setBusy(true);
    let created: Project;
    try {
      created = await createProject({ name });
    } catch (err) {
      setBusy(false);
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      // The typed name stays in the input so the user can retry it.
      notifyError(
        err instanceof Error && err.message ? err.message : "Failed to create the project.",
      );
      return;
    }
    // The project now exists, so it is kept and shown even if the add fails.
    onChanged?.();
    setProjects(current => (current ? [...current, created] : [created]));
    setSelectedId(created.id);
    setDraft("");
    setBusy(false);
    await addToProject(created);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && !busy) onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-to-project-title"
      onKeyDown={handleKeyDown}
    >
      <div className="flex max-h-full w-full max-w-lg flex-col rounded-lg bg-panel-strong shadow-2xl">
        <div className="border-b border-panel px-4 py-3">
          <h2 id="add-to-project-title" className="truncate text-lg font-semibold">
            Add to project
          </h2>
        </div>

        <p className="border-b border-panel px-4 py-3 text-sm text-muted">
          {fileCount} {fileWord} will be added to the project you choose. Files already in the
          project are skipped.
        </p>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
          {loadFailed ? (
            <p className="py-4 text-sm text-muted">Failed to load projects.</p>
          ) : projects === null ? (
            <p className="py-4 text-sm text-muted">Loading projects…</p>
          ) : projects.length === 0 ? (
            <p className="py-4 text-sm text-muted">No projects yet. Create one below.</p>
          ) : (
            <ul className="flex flex-col">
              {projects.map(project => (
                <li key={project.id}>
                  <label className="flex min-w-0 cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-panel-soft">
                    <input
                      type="radio"
                      name="add-to-project"
                      className={`h-4 w-4 shrink-0 ${FOCUS_VISIBLE}`}
                      aria-label={project.name}
                      checked={selectedId === project.id}
                      disabled={busy}
                      onChange={() => setSelectedId(project.id)}
                    />
                    <span className="min-w-0 flex-1 truncate text-sm">{project.name}</span>
                    <span className="shrink-0 text-xs text-muted">
                      {project.asset_count} {project.asset_count === 1 ? "file" : "files"}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        <form
          className="flex gap-2 border-t border-panel px-4 py-3"
          onSubmit={event => {
            event.preventDefault();
            void createAndAdd();
          }}
        >
          <input
            aria-label="New project name"
            placeholder="New project name"
            className={INPUT_BASE}
            value={draft}
            disabled={busy}
            onChange={event => setDraft(event.target.value)}
          />
          <button type="submit" className={BUTTON_SECONDARY} disabled={busy || !draft.trim()}>
            Create and add
          </button>
        </form>

        <div className="flex items-center justify-end gap-2 border-t border-panel px-4 py-3">
          <button type="button" className={BUTTON_SECONDARY} disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={BUTTON_PRIMARY}
            disabled={!selected || busy}
            onClick={() => {
              if (selected) void addToProject(selected);
            }}
          >
            {busy && selected ? "Adding…" : addLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
