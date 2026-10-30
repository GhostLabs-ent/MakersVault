import { type RefObject } from "react";

import { type Asset, type Folder } from "../../lib/api";
import { GRID_GAP_PX } from "../../lib/virtualGrid";
import type { VirtualRowsResult } from "../useVirtualRows";
import { GROUP_CARD_CAP, type GroupBucket, type SortKey } from "./assetGridMeta";

type AssetGridBodyProps = {
  /** Virtualization result from the root; its refs are attached verbatim. */
  virtual: VirtualRowsResult;
  renderedRows: Asset[][];
  renderCard: (item: Asset) => React.ReactNode;
  sortKey: SortKey;
  folderGroups: GroupBucket[];
  typeGroups: GroupBucket[];
  collapsedGroups: Set<string>;
  expandedGroups: Set<string>;
  toggleGroup: (id: string) => void;
  toggleGroupExpanded: (id: string) => void;
  isProject: boolean;
  folderId?: string | null;
  subfolders: Folder[];
  loading: boolean;
  items: Asset[];
  queryRef: RefObject<string>;
  activeTags: string[];
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
};

/**
 * The result area: grouped sections for the grouped sorts, the virtualized flat
 * grid otherwise, plus the empty hints and the "Load more" control. Owns no
 * effects and no state; every value comes from the root.
 */
export default function AssetGridBody({
  virtual,
  renderedRows,
  renderCard,
  sortKey,
  folderGroups,
  typeGroups,
  collapsedGroups,
  expandedGroups,
  toggleGroup,
  toggleGroupExpanded,
  isProject,
  folderId,
  subfolders,
  loading,
  items,
  queryRef,
  activeTags,
  hasMore,
  loadingMore,
  loadMore,
}: AssetGridBodyProps) {
  return (
    <>
      {/* A folder holding only subfolders must never look broken (#15). Applies
          to both the flat and the grouped sort modes. At the root there are no
          subfolder tiles, so the hint stays off. */}
      {!isProject && !!folderId && !loading && !items.length && subfolders.length > 0 && (
        <p className="text-sm opacity-70">
          No files directly in this folder — pick a subfolder above.
        </p>
      )}

      {/* "Empty" only means empty when no filter is narrowing it: a search or
          tag filter that matched nothing is an empty result, not a new project. */}
      {isProject &&
        !loading &&
        !items.length &&
        !queryRef.current &&
        activeTags.length === 0 && (
          <p className="text-sm opacity-70" data-project-empty>
            This project has no files yet.
          </p>
        )}

      {["folder", "type"].includes(sortKey) ? (
        <div className="space-y-4">
          {(sortKey === "folder" ? folderGroups : typeGroups).map(group => {
            const collapsed = collapsedGroups.has(group.id);
            const expanded = expandedGroups.has(group.id);
            const visibleItems = expanded
              ? group.items
              : group.items.slice(0, GROUP_CARD_CAP);
            return (
              <div
                key={group.id}
                className="rounded-lg border border-panel bg-panel-soft"
              >
                <button
                  className="w-full flex items-center justify-between px-4 py-3 text-left"
                  onClick={() => toggleGroup(group.id)}
                >
                  <div>
                    <div className="font-medium">{group.title}</div>
                    <div className="text-xs opacity-70">{group.items.length} item{group.items.length === 1 ? "" : "s"}</div>
                  </div>
                  <span className="text-sm opacity-70">{collapsed ? "Show" : "Hide"}</span>
                </button>
                {!collapsed && (
                  <div className="px-4 pb-4 overflow-x-auto">
                    <div className="flex gap-4 min-h-[280px]">
                      {visibleItems.map(it => (
                        <div key={it.id} className="min-w-[260px] max-w-[320px]">
                          {renderCard(it)}
                        </div>
                      ))}
                      {group.items.length > GROUP_CARD_CAP && (
                        <div className="min-w-[140px] shrink-0 flex items-center justify-center">
                          <button
                            type="button"
                            className="px-3 py-2 rounded-md border border-panel-strong text-sm"
                            onClick={() => toggleGroupExpanded(group.id)}
                          >
                            {expanded ? "Show fewer" : `Show all ${group.items.length}`}
                          </button>
                        </div>
                      )}
                      {!group.items.length && (
                        <div className="px-2 py-4 text-sm opacity-60">No assets in this folder</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div
          ref={virtual.setGridWrapRef}
          data-virtual-grid
          style={{ display: "flex", flexDirection: "column", gap: GRID_GAP_PX }}
        >
          {virtual.startRow > 0 && (
            <div data-virtual-spacer="top" aria-hidden="true" style={{ height: virtual.topSpacer }} />
          )}
          {renderedRows.map((row, offset) => {
            const rowIndex = virtual.startRow + offset;
            return (
              <div
                key={rowIndex}
                data-row-index={rowIndex}
                ref={virtual.setRowRef(rowIndex)}
                className="grid gap-4"
                style={{ gridTemplateColumns: `repeat(${virtual.cols}, minmax(0, 1fr))` }}
              >
                {row.map(item => renderCard(item))}
              </div>
            );
          })}
          {virtual.endRow >= 0 && virtual.endRow < virtual.rowCount - 1 && (
            <div
              data-virtual-spacer="bottom"
              aria-hidden="true"
              style={{ height: virtual.bottomSpacer }}
            />
          )}
        </div>
      )}
      {hasMore && (
        <div className="flex justify-center pt-2">
          <button
            className="px-4 py-2 rounded-md border border-panel-strong text-sm disabled:opacity-60"
            onClick={loadMore}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading..." : "Load more"}
          </button>
        </div>
      )}
    </>
  );
}
