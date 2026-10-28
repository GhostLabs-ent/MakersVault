import { useEffect, useRef, type KeyboardEvent } from "react";
import { Layers3 } from "lucide-react";

import { fileUrl, type Project } from "../lib/api";
import type {
  EngravingSettings,
  PreviewSettings,
  ResolvedTheme,
  SlicerSettings,
} from "../lib/settings";
import ProjectLanding from "./ProjectLanding";

type Props = {
  /** `null` while the project list is loading. */
  projects: Project[] | null;
  selectedProjectId: string | null;
  onOpenProject: (id: string) => void;
  onCloseProject: () => void;
  onProjectUpdated: (project: Project) => void;
  onProjectDeleted: (id: string) => void;
  onAssetsChanged: () => void;
  assetsVersion: number;
  onUnauthorized?: () => void;
  slicerSettings?: SlicerSettings;
  engravingSettings?: EngravingSettings;
  previewSettings?: PreviewSettings;
  theme: ResolvedTheme;
};

function coverFor(project: Project, className: string) {
  if (project.cover_thumb_url) {
    return <img src={fileUrl(project.cover_thumb_url)} alt="" className={className} />;
  }
  return (
    <span className={`${className} flex items-center justify-center bg-panel-strong opacity-60`}>
      <Layers3 className="h-7 w-7" aria-hidden="true" />
    </span>
  );
}

/**
 * Projects pane: the project card grid, and the project landing page once a
 * project is opened. Focus follows the drill-down: opening focuses Back,
 * closing returns focus to the card that was opened.
 */
export default function ProjectView({
  projects,
  selectedProjectId,
  onOpenProject,
  onCloseProject,
  onProjectUpdated,
  onProjectDeleted,
  onAssetsChanged,
  assetsVersion,
  onUnauthorized,
  slicerSettings,
  engravingSettings,
  previewSettings,
  theme,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const backButtonRef = useRef<HTMLButtonElement | null>(null);
  const previousSelectedId = useRef<string | null>(null);

  useEffect(() => {
    const previous = previousSelectedId.current;
    previousSelectedId.current = selectedProjectId;
    if (selectedProjectId) {
      backButtonRef.current?.focus();
      return;
    }
    if (!previous) return;
    const cards = containerRef.current?.querySelectorAll<HTMLElement>("[data-project-card]");
    const card = Array.from(cards ?? []).find(
      element => element.dataset.projectCard === previous,
    );
    card?.focus();
  }, [selectedProjectId]);

  // A project deleted elsewhere cannot stay open: the detail view would be a
  // dead end. The list owns the truth, so close back to it.
  useEffect(() => {
    if (!selectedProjectId || projects === null) return;
    if (projects.some(project => project.id === selectedProjectId)) return;
    onCloseProject();
  }, [projects, selectedProjectId, onCloseProject]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!selectedProjectId || event.key !== "Escape") return;
    // A child that already handled Escape (e.g. a closing modal) keeps it.
    if (event.defaultPrevented) return;
    // An open dialog owns Escape: closing the project under it would strand
    // the dialog's state on the project list.
    if ((event.target as Element).closest?.('[role="dialog"]')) return;
    event.preventDefault();
    onCloseProject();
  };

  if (projects === null) {
    return <p className="text-sm opacity-70">Loading projects…</p>;
  }

  const selectedProject = selectedProjectId
    ? projects.find(project => project.id === selectedProjectId) ?? null
    : null;

  if (selectedProject) {
    return (
      <div ref={containerRef} className="flex flex-col gap-4" onKeyDown={handleKeyDown}>
        <div>
          <button
            ref={backButtonRef}
            type="button"
            onClick={onCloseProject}
            aria-label="Back to projects"
            className="px-3 py-2 rounded-md border border-panel-strong text-sm"
          >
            ← All projects
          </button>
        </div>
        <ProjectLanding
          project={selectedProject}
          assetsVersion={assetsVersion}
          onProjectUpdated={onProjectUpdated}
          onProjectDeleted={onProjectDeleted}
          onAssetsChanged={onAssetsChanged}
          onUnauthorized={onUnauthorized}
          slicerSettings={slicerSettings}
          engravingSettings={engravingSettings}
          previewSettings={previewSettings}
          theme={theme}
        />
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex flex-col gap-4" onKeyDown={handleKeyDown}>
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-xl font-semibold">Projects</h1>
        <span className="text-sm opacity-70">
          {projects.length} project{projects.length === 1 ? "" : "s"}
        </span>
      </div>
      {projects.length === 0 ? (
        <div className="rounded-lg border border-dashed border-panel-strong bg-panel-soft px-4 py-8 text-center text-sm text-muted">
          <p className="font-medium">No projects yet.</p>
          <p>Projects are collections of files from any folder.</p>
        </div>
      ) : (
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}
        >
          {projects.map(project => (
            <button
              key={project.id}
              type="button"
              data-project-card={project.id}
              aria-label={`Open project ${project.name}`}
              onClick={() => onOpenProject(project.id)}
              className="flex flex-col overflow-hidden rounded-lg border border-panel bg-panel-soft text-left transition-colors hover:bg-panel-strong"
            >
              {coverFor(project, "h-32 w-full object-cover")}
              <span className="flex min-w-0 flex-col gap-1 p-3">
                <span className="truncate font-medium">{project.name}</span>
                {project.description && (
                  <span className="line-clamp-1 text-sm text-muted">{project.description}</span>
                )}
                <span className="text-xs opacity-70">
                  {project.asset_count} file{project.asset_count === 1 ? "" : "s"}
                </span>
                {project.creator && (
                  <span className="text-xs text-muted">By {project.creator}</span>
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
