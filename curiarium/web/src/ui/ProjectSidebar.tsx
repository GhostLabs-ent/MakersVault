import { useRef, type KeyboardEvent } from "react";
import { Layers3 } from "lucide-react";

import { fileUrl, type Project } from "../lib/api";
import type { Role } from "../lib/auth";
import SidebarFooter from "./SidebarFooter";

type Props = {
  /** `null` while the project list is loading. */
  projects: Project[] | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  activeView?: "library" | "settings" | "audit";
  onOpenSettings?: () => void;
  onOpenAudit?: () => void;
  role?: Role | null;
  username?: string | null;
  kind?: string | null;
};

/**
 * Presentational project list. App owns the data and the open project; the
 * arrow keys here only move focus, Enter/Space (a click) opens a project.
 */
export default function ProjectSidebar({
  projects,
  selectedId,
  onSelect,
  activeView = "library",
  onOpenSettings,
  onOpenAudit,
  role = null,
  username = null,
  kind = null,
}: Props) {
  const listRef = useRef<HTMLDivElement | null>(null);

  const rowElements = () =>
    Array.from(listRef.current?.querySelectorAll<HTMLElement>("[data-project-row]") ?? []);

  const handleListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const rows = rowElements();
    if (!rows.length) return;
    const current = rows.indexOf(document.activeElement as HTMLElement);
    const last = rows.length - 1;
    let next: number;
    switch (event.key) {
      case "ArrowDown":
        next = current < 0 ? 0 : Math.min(current + 1, last);
        break;
      case "ArrowUp":
        next = current < 0 ? last : Math.max(current - 1, 0);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = last;
        break;
      default:
        return;
    }
    event.preventDefault();
    // Focus movement only: opening still requires Enter/Space/click.
    rows[next].focus();
  };

  return (
    <aside className="sidebar-shell" aria-label="Projects">
      <div className="sidebar-header">
        <div className="min-w-0">
          <p className="sidebar-eyebrow">Curiarium</p>
          <div className="flex items-center gap-2">
            <h2 className="sidebar-title">Projects</h2>
            <span className="sidebar-count" title={`${projects?.length ?? 0} projects`}>
              {projects?.length ?? 0}
            </span>
          </div>
        </div>
      </div>

      <nav className="sidebar-navigation" aria-label="Project list">
        <div
          ref={listRef}
          className="flex flex-col gap-0.5 pb-3"
          onKeyDown={handleListKeyDown}
        >
          {projects === null && (
            <p className="px-2 py-2 text-xs text-muted">Loading projects…</p>
          )}
          {projects !== null && projects.length === 0 && (
            <div className="sidebar-empty" role="none">
              <Layers3 className="h-5 w-5" />
              <span>No projects yet</span>
              <span>Projects group files from any folder.</span>
            </div>
          )}
          {projects?.map(project => {
            const selected = project.id === selectedId;
            return (
              <button
                key={project.id}
                type="button"
                data-project-row={project.id}
                aria-current={selected ? "page" : undefined}
                onClick={() => onSelect(project.id)}
                onKeyDown={event => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  // jsdom does not synthesize the native click; browsers would.
                  event.preventDefault();
                  onSelect(project.id);
                }}
                className={`sidebar-tree-row ${selected ? "is-selected" : ""} pl-2.5`}
              >
                {project.cover_thumb_url ? (
                  <img
                    src={fileUrl(project.cover_thumb_url)}
                    alt=""
                    className="h-8 w-8 shrink-0 rounded-md object-cover"
                  />
                ) : (
                  <span className="sidebar-all-icon" aria-hidden="true">
                    <Layers3 className="h-4 w-4" />
                  </span>
                )}
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-medium">{project.name}</span>
                  {project.description && (
                    <span className="line-clamp-1 text-[11px] text-subtle">
                      {project.description}
                    </span>
                  )}
                  <span className="text-[11px] text-muted">
                    {project.asset_count} file{project.asset_count === 1 ? "" : "s"}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </nav>

      <SidebarFooter
        username={username}
        kind={kind}
        activeView={activeView}
        onOpenSettings={onOpenSettings}
        onOpenAudit={onOpenAudit}
        role={role}
      />
    </aside>
  );
}
