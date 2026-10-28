import { useState, type ReactElement } from "react";

import { UnauthorizedError, listProjects, type Project } from "../lib/api";
import type { ImportProjectTarget as Target } from "../lib/importProject";

const FOCUS_VISIBLE =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const INPUT_BASE = `rounded-md border border-panel-strong bg-panel-soft px-2 py-1.5 text-sm ${FOCUS_VISIBLE}`;

const NO_PROJECTS_NOTE =
  "No projects yet, so the import creates a new project from the page.";
const LOAD_FAILED_NOTE =
  "Could not load the project list, so the import creates a new project from the page.";

type Props = {
  value: Target;
  onChange: (target: Target) => void;
  disabled?: boolean;
};

/** The project list is fetched once, on the first "Existing project" click. */
type ProjectList =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; projects: Project[] }
  | { status: "failed" };

const OPTIONS: { kind: Target["kind"]; label: string }[] = [
  { kind: "none", label: "No project" },
  { kind: "new", label: "New project from the page" },
  { kind: "existing", label: "Existing project" },
];

function existingTarget(project: Project): Target {
  return { kind: "existing", projectId: project.id, projectName: project.name };
}

/**
 * Where a link import lands (Mf-56z9): no project (a loose asset), a project
 * created from the model page, or an existing project. Sits inline in
 * `UploadBar`'s row of buttons, so it stays a compact radio group rather than a
 * modal, and it is fully controlled — the import itself belongs to `UploadBar`.
 */
export default function ImportProjectTarget({ value, onChange, disabled }: Props): ReactElement {
  const [list, setList] = useState<ProjectList>({ status: "idle" });
  // A note outlives the fallback to "new": the user has to read why the list
  // could not be used even though the target moved back to a new project.
  const [note, setNote] = useState<string | null>(null);
  // Keeps "Existing project" checked while its list loads (the target itself
  // is only set once there is a project to name).
  const [loadingExisting, setLoadingExisting] = useState(false);

  const fallBackToNew = (message: string) => {
    setNote(message);
    setLoadingExisting(false);
    onChange({ kind: "new" });
  };

  const loadProjects = async () => {
    setList({ status: "loading" });
    try {
      const projects = await listProjects();
      setList({ status: "ready", projects });
      setLoadingExisting(false);
      if (projects.length === 0) {
        setNote(NO_PROJECTS_NOTE);
        onChange({ kind: "new" });
        return;
      }
      onChange(existingTarget(projects[0]));
    } catch (err) {
      if (!(err instanceof UnauthorizedError)) console.error(err);
      setList({ status: "failed" });
      fallBackToNew(LOAD_FAILED_NOTE);
    }
  };

  const chooseExisting = () => {
    setNote(null);
    switch (list.status) {
      case "ready":
        if (list.projects.length === 0) fallBackToNew(NO_PROJECTS_NOTE);
        else onChange(existingTarget(list.projects[0]));
        return;
      case "failed":
        fallBackToNew(LOAD_FAILED_NOTE);
        return;
      case "loading":
        setLoadingExisting(true);
        return;
      case "idle":
        setLoadingExisting(true);
        void loadProjects();
        return;
    }
  };

  const choose = (kind: Target["kind"]): void => {
    switch (kind) {
      case "none":
        setNote(null);
        onChange({ kind: "none" });
        return;
      case "new":
        setNote(null);
        onChange({ kind: "new" });
        return;
      case "existing":
        chooseExisting();
        return;
    }
  };

  const isChecked = (kind: Target["kind"]): boolean => {
    if (kind === "existing") return value.kind === "existing" || loadingExisting;
    return value.kind === kind;
  };

  const listedProjects = list.status === "ready" ? list.projects : [];
  const currentProjectMissing =
    value.kind === "existing" && !listedProjects.some(project => project.id === value.projectId);

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      <div role="radiogroup" aria-label="Import into" className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {OPTIONS.map(option => (
          <label key={option.kind} className="flex cursor-pointer items-center gap-1.5">
            <input
              type="radio"
              name="import-project-target"
              className={`h-4 w-4 ${FOCUS_VISIBLE}`}
              checked={isChecked(option.kind)}
              disabled={disabled}
              onChange={() => choose(option.kind)}
            />
            {option.label}
          </label>
        ))}
      </div>

      {value.kind === "existing" && (
        <select
          aria-label="Project"
          className={INPUT_BASE}
          value={value.projectId}
          disabled={disabled}
          onChange={event => {
            const picked = listedProjects.find(project => project.id === event.target.value);
            if (picked) onChange(existingTarget(picked));
          }}
        >
          {currentProjectMissing && (
            <option value={value.projectId}>{value.projectName}</option>
          )}
          {listedProjects.map(project => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      )}

      {note && <p className="text-muted">{note}</p>}
    </div>
  );
}
