import { useState } from "react";

import { colorForTag } from "../tagColors";
import type { SortDir, SortKey } from "./assetGridMeta";

/**
 * Search box + button.
 *
 * Defined at module scope (and owning its own `value` state) so typing never
 * re-renders the grid or the cards, and so the input instance survives grid
 * re-renders (refetches) instead of being remounted.
 */
function AssetSearch({
  onQueryChange,
  onSearch,
  disabled,
}: {
  onQueryChange: (query: string) => void;
  onSearch: (query: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");
  return (
    <>
      <input
        value={value}
        onChange={e => {
          setValue(e.target.value);
          onQueryChange(e.target.value);
        }}
        onKeyDown={e => {
          if (e.key === "Enter") onSearch(value);
        }}
        placeholder="Search title, filename, notes..."
        className="px-3 py-2 rounded-md border border-panel-strong bg-panel-soft w-80"
      />
      <button
        className="px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
        onClick={() => onSearch(value)}
        disabled={disabled}
      >
        Search
      </button>
    </>
  );
}

type AssetToolbarProps = {
  isProject: boolean;
  loading: boolean;
  sortKey: SortKey;
  setSortKey: (key: SortKey) => void;
  sortDir: SortDir;
  setSortDir: (dir: SortDir) => void;
  allTags: string[];
  activeTags: string[];
  toggleTag: (tag: string) => void;
  creators: string[];
  activeCreator: string | null;
  setActiveCreator: (creator: string | null) => void;
  notInProject: boolean;
  onToggleNotInProject: (next: boolean) => void;
  /** Clears the tag and creator filters together, with one refetch. */
  onReset: () => void;
  onQueryChange: (query: string) => void;
  onSearch: (query: string) => void;
};

/**
 * Search box, sort control and tag-chip filter. Presentational: the grid owns
 * every piece of state and every handler; the only local state is the search
 * box's draft text, held inside `AssetSearch` so typing never re-renders the
 * grid or the cards.
 */
export default function AssetToolbar({
  isProject,
  loading,
  sortKey,
  setSortKey,
  sortDir,
  setSortDir,
  allTags,
  activeTags,
  toggleTag,
  creators,
  activeCreator,
  setActiveCreator,
  notInProject,
  onToggleNotInProject,
  onReset,
  onQueryChange,
  onSearch,
}: AssetToolbarProps) {
  return (
    <>
      <div className="flex items-center gap-3 flex-wrap">
        <AssetSearch
          onQueryChange={onQueryChange}
          onSearch={onSearch}
          disabled={loading}
        />
        {loading && <span className="text-sm opacity-70">Loading...</span>}
        <div className="flex items-center gap-2 text-sm">
          <span className="opacity-70">Sort</span>
          <select
            className="px-2 py-1 rounded-md border border-panel-strong bg-panel-soft"
            value={sortKey}
            onChange={e => setSortKey(e.target.value as typeof sortKey)}
          >
            <option value="name">Name</option>
            <option value="size">Size</option>
            <option value="creator">Creator</option>
            <option value="type">File type</option>
            {!isProject && <option value="folder">Folder</option>}
          </select>
          <button
            type="button"
            onClick={() => setSortDir(sortDir === "asc" ? "desc" : "asc")}
            className="px-2 py-1 rounded-md border border-panel-strong"
          >
            {sortDir === "asc" ? "Asc" : "Desc"}
          </button>
        </div>
        {creators.length > 0 && (
          <div className="flex items-center gap-2 text-sm">
            <span className="opacity-70">Creator</span>
            <select
              aria-label="Creator"
              className="px-2 py-1 rounded-md border border-panel-strong bg-panel-soft"
              value={activeCreator ?? ""}
              onChange={e => setActiveCreator(e.target.value || null)}
            >
              <option value="">All creators</option>
              {creators.map(creator => (
                <option key={creator} value={creator}>
                  {creator}
                </option>
              ))}
            </select>
          </div>
        )}
        {!isProject && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={notInProject}
              onChange={e => onToggleNotInProject(e.target.checked)}
              className="w-4 h-4"
            />
            <span>Not in any project</span>
          </label>
        )}
      </div>

      {(!!allTags.length || activeCreator !== null) && (
        <div className="flex flex-wrap gap-2">
          {allTags.map(t => {
            const colors = colorForTag(t);
            const active = activeTags.includes(t);
            return (
              <button
                key={t}
                className={`px-2 py-1 rounded-full text-sm border transition-colors ${
                  active ? "ring-2 ring-offset-1 ring-[color:var(--mv-accent)] ring-offset-[color:var(--mv-bg)]" : ""
                }`}
                style={{
                  backgroundColor: active ? colors.bg : "transparent",
                  color: colors.text,
                  borderColor: colors.border,
                }}
                onClick={()=>toggleTag(t)}
              >
                {t}
              </button>
            );
          })}
          {(activeTags.length > 0 || activeCreator !== null) && (
            <button
              className="px-2 py-1 rounded-full text-sm border border-panel-strong"
              onClick={onReset}
            >
              Reset
            </button>
          )}
        </div>
      )}
    </>
  );
}
