import {
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  Asset,
  Folder,
  UnauthorizedError,
  listFolders,
  listTags,
} from "../../lib/api";
import { refreshWindow } from "../../lib/assetPaging";
import { notifyError } from "../../lib/toast";
import { useStableCallback } from "../../lib/useStableCallback";
import {
  ROWS_PER_BATCH,
  fetchAssetPage,
  rowsBatchSizeForWidth,
  type RefreshOpts,
} from "./assetGridMeta";

type AssetListOptions = {
  folderId?: string | null;
  projectId?: string | null;
  foldersVersion: number;
  assetsVersion: number;
  onUnauthorized?: () => void;
};

export type AssetListApi = {
  items: Asset[];
  setItems: Dispatch<SetStateAction<Asset[]>>;
  folders: Folder[];
  allTags: string[];
  setAllTags: Dispatch<SetStateAction<string[]>>;
  activeTags: string[];
  setActiveTags: Dispatch<SetStateAction<string[]>>;
  loading: boolean;
  loadingMore: boolean;
  offset: number;
  setOffset: Dispatch<SetStateAction<number>>;
  hasMore: boolean;
  /** Files mode only: the grid is narrowed to assets that belong to no project. */
  notInProject: boolean;
  /** Latest typed query; a ref so typing never re-renders the grid. */
  queryRef: MutableRefObject<string>;
  refresh: (opts?: RefreshOpts) => Promise<void>;
  loadMore: () => Promise<void>;
  toggleTag: (tag: string) => void;
  toggleNotInProject: (next: boolean) => void;
  handleApiError: (err: unknown, message?: string) => boolean;
};

/**
 * Listing state for the grid: the loaded page of assets, the folder tree, the
 * tag chips and every request that fills or extends them.
 */
export function useAssetList({
  folderId,
  projectId,
  foldersVersion,
  assetsVersion,
  onUnauthorized,
}: AssetListOptions): AssetListApi {
  const isProject = projectId != null;
  const [items, setItems] = useState<Asset[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  // Latest typed query. Held in a ref (not state) so typing does not re-render
  // the grid; only submitting a search refetches.
  const queryRef = useRef("");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [notInProject, setNotInProject] = useState(false);
  const [pageSize] = useState<number>(() => {
    if (typeof window === "undefined") return ROWS_PER_BATCH;
    return rowsBatchSizeForWidth(window.innerWidth);
  });

  const handleApiError = useStableCallback((err: unknown, message?: string) => {
    if (err instanceof UnauthorizedError) {
      onUnauthorized?.();
      return true;
    }
    console.error(err);
    if (message) notifyError(message);
    return false;
  });

  const refresh = useStableCallback(async (opts: RefreshOpts = {}) => {
    setLoading(true);
    if (!opts.keepLoadedPages) {
      setHasMore(false);
      setOffset(0);
    }
    const search = opts.search ?? queryRef.current;
    const tags = opts.tags ?? activeTags;
    const targetFolderId = folderId || undefined;
    // One value for both requests, so the chips can never describe a different
    // pile than the grid.
    const effectiveNotInProject = opts.notInProject ?? notInProject;
    const paging = refreshWindow(offset, pageSize, opts.keepLoadedPages);
    const [assetsResult, tagsResult] = await Promise.allSettled([
      fetchAssetPage({
        projectId,
        q: search,
        tags,
        folderId: targetFolderId,
        notInProject: effectiveNotInProject,
        limit: paging.limit,
        offset: paging.offset,
      }),
      listTags({
        q: search,
        folder_id: isProject ? undefined : targetFolderId,
        project_id: projectId ?? undefined,
        not_in_project: isProject ? undefined : effectiveNotInProject,
      }),
    ]);

    if (assetsResult.status === "fulfilled") {
      setItems(assetsResult.value.items);
      setOffset(assetsResult.value.items.length);
      setHasMore(assetsResult.value.hasMore);
    } else {
      handleApiError(assetsResult.reason, "Failed to load assets. Please sign in again or refresh.");
    }

    if (tagsResult.status === "fulfilled") {
      setAllTags(tagsResult.value);
    } else {
      setAllTags([]);
      handleApiError(tagsResult.reason);
    }

    setLoading(false);
  });

  const loadMore = useStableCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const data = await fetchAssetPage({
        projectId,
        q: queryRef.current,
        tags: activeTags,
        folderId: folderId || undefined,
        notInProject,
        limit: pageSize,
        offset,
      });
      setItems(prev => [...prev, ...data.items]);
      setOffset(offset + data.items.length);
      setHasMore(data.hasMore);
    } catch (err) {
      handleApiError(err, "Failed to load more assets.");
    } finally {
      setLoadingMore(false);
    }
  });

  useEffect(() => { refresh(); }, [folderId, projectId, refresh]);
  // `assetsVersion` bumps when another view (upload, folder scan) changed
  // assets. Refetch in place instead of remounting: the ref is seeded with the
  // current version so mounting performs no extra fetch, and comparing values
  // makes the effect idempotent under StrictMode's double mount.
  // The refetch is keyed on the version value; `refresh` is referentially
  // stable (useStableCallback), so listing it as a dependency cannot loop, and
  // the ref guard keeps the effect idempotent under StrictMode.
  // Invariant: no call site bumps `assetsVersion` and `folderId` in the same
  // commit; if one ever does, that is two refreshes.
  const seenAssetsVersion = useRef(assetsVersion);
  useEffect(() => {
    if (seenAssetsVersion.current === assetsVersion) return;
    seenAssetsVersion.current = assetsVersion;
    refresh({ keepLoadedPages: true });
  }, [assetsVersion, refresh]);
  useEffect(() => {
    // Project mode never shows (or needs) the folder tree.
    if (isProject) return;
    (async () => {
      try {
        setFolders(await listFolders());
      } catch (err) {
        handleApiError(err, "Failed to load folders. Please refresh.");
      }
    })();
  }, [foldersVersion, isProject]);

  const toggleTag = (t: string) => {
    const next = activeTags.includes(t) ? activeTags.filter(x => x !== t) : [...activeTags, t];
    setActiveTags(next);
    refresh({ tags: next });
  };

  const toggleNotInProject = useStableCallback((next: boolean) => {
    setNotInProject(next);
    // No `keepLoadedPages`: like every other filter change, the paging window
    // resets to the first page.
    refresh({ notInProject: next });
  });

  return {
    items,
    setItems,
    folders,
    allTags,
    setAllTags,
    activeTags,
    setActiveTags,
    loading,
    loadingMore,
    offset,
    setOffset,
    hasMore,
    notInProject,
    queryRef,
    refresh,
    loadMore,
    toggleTag,
    toggleNotInProject,
    handleApiError,
  };
}
