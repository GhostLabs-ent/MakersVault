import { Fragment } from "react";
import { ChevronRight, Folder as FolderIcon } from "lucide-react";

import type { Folder } from "../lib/api";
import { childFolders, folderPath } from "../lib/folderTree";

type FolderNavProps = {
  folders: readonly Folder[];
  folderId: string | null;
  onNavigate: (id: string | null) => void;
};

const crumbLinkClass =
  "px-2 py-1 rounded-md border border-panel-strong text-sm hover:bg-panel-strong";

/**
 * Root → open-folder trail. Navigation only: the caller owns the folder state,
 * so every crumb is a plain button (no links, no history entries).
 */
export default function FolderBreadcrumbs({ folders, folderId, onNavigate }: FolderNavProps) {
  if (!folderId) return null;

  const segments = folderPath(folders, folderId);
  // Nothing to show while the folder list is still loading (or the id is
  // unknown): a lone "All files" crumb would be misleading.
  if (!segments.length) return null;

  return (
    <nav
      aria-label="Folder path"
      data-folder-breadcrumbs
      className="flex flex-wrap items-center gap-1 text-sm"
    >
      <button type="button" className={crumbLinkClass} onClick={() => onNavigate(null)}>
        All files
      </button>
      {segments.map((segment, index) => {
        const isCurrent = index === segments.length - 1;
        // Title is the full trail up to this crumb, which disambiguates
        // same-named folders living in different branches.
        const title = segments.slice(0, index + 1).map(part => part.name).join(" / ");
        return (
          <Fragment key={segment.id}>
            <ChevronRight className="h-4 w-4 opacity-60" aria-hidden="true" />
            <button
              type="button"
              data-folder-crumb={segment.id}
              title={title}
              aria-current={isCurrent ? "page" : undefined}
              className={crumbLinkClass}
              onClick={() => onNavigate(segment.id)}
            >
              {segment.name}
            </button>
          </Fragment>
        );
      })}
    </nav>
  );
}

/**
 * Direct subfolders of the open folder as cards. Without them a folder with
 * only subfolders (and no direct assets) looks empty.
 */
export function FolderTiles({ folders, folderId, onNavigate }: FolderNavProps) {
  if (!folderId) return null;

  const children = childFolders(folders, folderId);
  if (!children.length) return null;

  return (
    <section
      aria-label="Subfolders"
      data-folder-tiles
      className="rounded-lg border border-panel bg-panel-soft p-4"
    >
      <h2 className="mb-3 text-sm font-medium opacity-80">Subfolders</h2>
      <div
        className="grid gap-4"
        style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}
      >
        {children.map(child => {
          const subfolderCount = childFolders(folders, child.id).length;
          return (
            <button
              key={child.id}
              type="button"
              data-folder-tile={child.id}
              onClick={() => onNavigate(child.id)}
              // jsdom does not synthesize a click from Enter/Space on a button;
              // handle the keys explicitly so keyboard navigation works there.
              onKeyDown={event => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                onNavigate(child.id);
              }}
              className="flex items-center gap-3 rounded-lg border border-panel-strong bg-panel px-4 py-3 text-left hover:bg-panel-strong"
            >
              <FolderIcon className="h-5 w-5 shrink-0 opacity-80" aria-hidden="true" />
              <span className="min-w-0 flex flex-col">
                <span className="truncate font-medium">{child.name || "Untitled"}</span>
                {subfolderCount > 0 && (
                  <span className="text-xs opacity-70">
                    {subfolderCount} subfolder{subfolderCount === 1 ? "" : "s"}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
