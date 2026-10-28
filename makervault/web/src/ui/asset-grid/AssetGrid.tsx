import React, { useEffect, useMemo, useState } from "react";

import { type Asset, type BatchMetaChange, UnauthorizedError, deleteAsset } from "../../lib/api";
import { chunkRows, colsForWidth } from "../../lib/virtualGrid";
import { previewQueue } from "../../lib/previewQueue";
import { EngravingSettings, PreviewSettings, ResolvedTheme, SlicerSettings, engraverLabelFor, slicerLabelFor } from "../../lib/settings";
import { useStableCallback } from "../../lib/useStableCallback";
import AssetDeleteDialog, { type AssetDeleteFailure } from "../AssetDeleteDialog";
import BulkActionBar from "../BulkActionBar";
import BulkMetaDialog from "../BulkMetaDialog";
import ConfirmDialog from "../ConfirmDialog";
import FolderBreadcrumbs, { FolderTiles } from "../FolderNav";
import ProjectPickerDialog from "../ProjectPickerDialog";
import { useUpload } from "../useUpload";
import { useVirtualRows } from "../useVirtualRows";
import AssetGridBody from "./AssetGridBody";
import AssetToolbar from "./AssetToolbar";
import AssetCard from "./AssetCard";
import { AssetPreviewModal } from "./preview";
import { noop } from "./assetGridMeta";
import { useAssetActions } from "./useAssetActions";
import { useAssetDrop } from "./useAssetDrop";
import { useAssetList } from "./useAssetList";
import { useAssetSorting } from "./useAssetSorting";
import { useBulkActions } from "./useBulkActions";

type Props = {
  folderId?: string | null;
  /** When set, the grid shows this project's assets and hides all folder chrome. */
  projectId?: string | null;
  /** Display-only context for project mode (the caller renders the heading). */
  projectName?: string | null;
  foldersVersion?: number;
  assetsVersion?: number;
  onUnauthorized?: () => void;
  slicerSettings?: SlicerSettings;
  engravingSettings?: EngravingSettings;
  previewSettings?: PreviewSettings;
  theme: ResolvedTheme;
  /** Scroll container the grid lives in (the app's `<main>`). */
  scrollElementRef?: React.RefObject<HTMLElement | null>;
  /** Navigate to a folder (or the root) from the breadcrumbs/tiles. */
  onNavigateFolder?: (id: string | null) => void;
  /**
   * Fires after the project picker created a project or changed its membership,
   * so App can refresh the counts it owns (it bumps `assetsVersion`).
   */
  onProjectsChanged?: () => void;
};

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message.trim()) return err.message;
  return fallback;
}

export default function AssetGrid({
  folderId,
  projectId,
  projectName,
  foldersVersion = 0,
  assetsVersion = 0,
  onUnauthorized,
  slicerSettings,
  engravingSettings,
  previewSettings,
  theme,
  scrollElementRef,
  onNavigateFolder,
  onProjectsChanged,
}: Props) {
  const isProject = projectId != null;
  const [previewItem, setPreviewItem] = useState<Asset | null>(null);
  // The assets the user asked to delete, or null when the dialog is closed. The
  // parent stays the only owner of the request so the grid's optimistic update
  // and selection retention keep a single path.
  const [deleteTargets, setDeleteTargets] = useState<Asset[] | null>(null);
  const [metaDialogOpen, setMetaDialogOpen] = useState(false);
  const [metaRequestError, setMetaRequestError] = useState<string | null>(null);
  const slicerEnabled = Boolean(slicerSettings?.enabled);
  const slicerLabel = slicerLabelFor(slicerSettings?.selected);
  const engravingEnabled = Boolean(engravingSettings?.enabled);
  const engraverLabel = engraverLabelFor(engravingSettings?.selected);

  // "Add to project…" is offered in BOTH files and project mode: adding a
  // project-A member to project-B is a legitimate thing to do.
  const [projectPickerIds, setProjectPickerIds] = useState<string[] | null>(null);
  const openProjectPicker = useStableCallback((ids: string[]) => setProjectPickerIds(ids));

  const {
    items,
    setItems,
    folders,
    allTags,
    setAllTags,
    creators,
    activeCreator,
    setActiveCreator,
    sortKey,
    setSortKey,
    sortDir,
    setSortDir,
    activeTags,
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
    resetFilters,
    handleApiError,
  } = useAssetList({
    folderId,
    projectId,
    foldersVersion,
    assetsVersion,
    onUnauthorized,
  });

  // Opening another folder is a new browsing session, so the per-session
  // preview budget (Mf-04od) is refunded; reset() resolves queued jobs with null.
  useEffect(() => {
    previewQueue.reset();
  }, [folderId]);

  const {
    selectedIds,
    toggleSelected,
    clearSelection,
    selectAllLoaded,
    bulkBusy,
    bulkFailures,
    bulkRequestError,
    bulkFailureLabels,
    dismissBulkFailures,
    bulkDelete,
    bulkMoveToFolder,
    bulkAddTags,
    bulkRemoveTags,
    bulkSetTags,
    bulkSetMeta,
    bulkAddToProject,
    bulkDownloading,
    downloadSelected,
    downloadByTag,
  } = useBulkActions({
    folderId,
    activeTags,
    activeCreator,
    items,
    setItems,
    offset,
    setOffset,
    setAllTags,
    handleApiError,
    onUnauthorized,
    onAddToProject: openProjectPicker,
  });

  const {
    downloadingId,
    movingId,
    rescanning,
    replaceAsset,
    onSaveTags,
    onSaveDetails,
    onRename,
    onMoveFolder,
    downloadSingle,
    openInSlicer,
    openInEngraving,
    removeAsset,
    addToProject,
    forgetMissingAsset,
    rescanMissing,
    pendingConfirm,
    confirmBusy,
    setPendingConfirm,
    requestConfirm,
    runPendingConfirm,
  } = useAssetActions({
    items,
    setItems,
    setPreviewItem,
    refresh,
    handleApiError,
    onUnauthorized,
    slicerSettings,
    engravingSettings,
    selectedIds,
    bulkSetTags,
    onRequestDelete: setDeleteTargets,
    onAddToProject: openProjectPicker,
  });

  // One request per path: a single asset needs its file name confirmed (the
  // server 400s otherwise), a selection is one batch call whose per-asset
  // failures come back for the dialog and stay listed in the bar.
  const runDelete = useStableCallback(async (targets: Asset[]) => {
    if (targets.length > 1) {
      const failures = await bulkDelete(targets.map(target => target.id));
      const failed: AssetDeleteFailure[] = failures.map(failure => ({
        id: failure.id,
        message: failure.error,
      }));
      return { failed };
    }
    const [asset] = targets;
    try {
      await deleteAsset(asset.id, asset.filename);
      await refresh();
      return { failed: [] };
    } catch (err) {
      if (err instanceof UnauthorizedError) onUnauthorized?.();
      return { failed: [{ id: asset.id, message: errorMessage(err, "Delete failed.") }] };
    }
  });

  // The bar's Delete opens the same dialog for exactly the current selection.
  const openBulkDelete = useStableCallback(() => {
    const targets = items.filter(item => selectedIds.has(item.id));
    if (targets.length) setDeleteTargets(targets);
  });

  const closeDeleteDialog = useStableCallback(() => setDeleteTargets(null));

  const openMetaDialog = useStableCallback(() => {
    if (!selectedIds.size) return;
    setMetaRequestError(null);
    setMetaDialogOpen(true);
  });

  const closeMetaDialog = useStableCallback(() => {
    setMetaDialogOpen(false);
    setMetaRequestError(null);
  });

  const submitMeta = useStableCallback(async (change: BatchMetaChange) => {
    const error = await bulkSetMeta(change);
    if (error === null) {
      setMetaDialogOpen(false);
      setMetaRequestError(null);
      return;
    }
    setMetaRequestError(error);
  });

  const {
    sortedItems,
    folderGroups,
    typeGroups,
    collapsedGroups,
    expandedGroups,
    toggleGroup,
    toggleGroupExpanded,
    folderOptions,
    subfolders,
    dropTargetName,
  } = useAssetSorting({
    items,
    folders,
    folderId,
    sortKey,
    setSortKey,
    sortDir,
    setSortDir,
  });

  // Flat-grid virtualization: chunk `sortedItems` into rows and render only
  // those covering the viewport. `colsForWidth(window.innerWidth)` is the seed;
  // the hook refines it from the container's measured width when it can.
  const virtual = useVirtualRows({
    scrollElementRef,
    items: sortedItems,
    cols: colsForWidth(typeof window === "undefined" ? 0 : window.innerWidth),
  });
  const virtualRows = useMemo(
    () => chunkRows(sortedItems, virtual.cols),
    [sortedItems, virtual.cols],
  );
  const renderedRows = virtualRows.slice(virtual.startRow, virtual.endRow + 1);

  // The one zip-aware uploader for the whole grid: its prompt modal is rendered
  // once below, and drag/drop uploads route through the same instance.
  const uploader = useUpload({
    folderId,
    onUnauthorized,
    onUploaded: () => {
      void refresh({ keepLoadedPages: true });
    },
  });

  const {
    showDropOverlay,
    dropMessage,
    handleDragEnter,
    handleDragOver,
    handleDragLeave,
    handleDrop,
  } = useAssetDrop({ isProject, uploader, dropTargetName });

  // Single source of truth for card props so the virtualized flat grid and the
  // grouped rows render exactly the same cards. All callbacks are stable, so
  // `AssetCard`'s memo still skips untouched cards.
  const renderCard = (item: Asset) => (
    <AssetCard
      key={item.id}
      item={item}
      onSaveTags={onSaveTags}
      onSaveDetails={onSaveDetails}
      onRename={onRename}
      onPreview={setPreviewItem}
      onDownloadSingle={downloadSingle}
      downloading={downloadingId === item.id}
      onDelete={removeAsset}
      onAddToProject={addToProject}
      onMoveFolder={onMoveFolder}
      folderOptions={folderOptions}
      showFolderControls={!isProject}
      moving={movingId === item.id}
      onDownloadByTag={downloadByTag}
      onDownloadSelected={downloadSelected}
      selected={selectedIds.has(item.id)}
      onToggleSelected={toggleSelected}
      hasSelection={selectedIds.size > 0}
      bulkDownloading={Boolean(bulkDownloading)}
      slicerEnabled={slicerEnabled}
      slicerLabel={slicerLabel}
      onOpenInSlicer={openInSlicer}
      engravingEnabled={engravingEnabled}
      engraverLabel={engraverLabel}
      onOpenInEngraving={openInEngraving}
      theme={theme}
      previewMode={previewSettings?.mode || "automatic"}
      onAssetChanged={replaceAsset}
      onForgetMissing={forgetMissingAsset}
      onRescanMissing={rescanMissing}
      rescanning={rescanning}
      onRequestConfirm={requestConfirm}
    />
  );

  return (
    <div
      className="relative"
      data-project-id={projectId ?? undefined}
      data-project-name={projectName ?? undefined}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {showDropOverlay && (
        <div className="absolute inset-0 z-40 flex items-center justify-center rounded-lg border-2 border-dashed border-accent bg-panel-overlay pointer-events-none">
          <div className="px-4 py-3 rounded-md border border-panel-strong bg-panel-strong shadow-sm text-sm">
            {dropMessage}
          </div>
        </div>
      )}
      <div className="flex flex-col gap-4">
      {/* Deliberately non-sticky: `BulkActionBar` is the single sticky element
          in this column (top-0 z-30), so the two cannot fight over the slot. */}
      {!isProject && (
        <FolderBreadcrumbs
          folders={folders}
          folderId={folderId ?? null}
          onNavigate={onNavigateFolder ?? noop}
        />
      )}
      <BulkActionBar
        count={selectedIds.size}
        folderOptions={folderOptions}
        showFolderControls={!isProject}
        busy={bulkBusy}
        failures={bulkFailures}
        failureLabels={bulkFailureLabels}
        requestError={bulkRequestError}
        onMove={bulkMoveToFolder}
        onAddTags={bulkAddTags}
        onRemoveTags={bulkRemoveTags}
        onEditMeta={openMetaDialog}
        onAddToProject={bulkAddToProject}
        onDownload={downloadSelected}
        onDelete={openBulkDelete}
        onClear={clearSelection}
        onSelectAll={selectAllLoaded}
        onDismissFailures={dismissBulkFailures}
      />
      {!isProject && uploader.modal}
      <AssetToolbar
        isProject={isProject}
        loading={loading}
        sortKey={sortKey}
        setSortKey={setSortKey}
        sortDir={sortDir}
        setSortDir={setSortDir}
        allTags={allTags}
        activeTags={activeTags}
        toggleTag={toggleTag}
        creators={creators}
        activeCreator={activeCreator}
        setActiveCreator={setActiveCreator}
        notInProject={notInProject}
        onToggleNotInProject={toggleNotInProject}
        onReset={resetFilters}
        onQueryChange={query => { queryRef.current = query; }}
        onSearch={query => { refresh({ search: query }); }}
      />
      {!isProject && (
        <FolderTiles
          folders={folders}
          folderId={folderId ?? null}
          onNavigate={onNavigateFolder ?? noop}
        />
      )}
      <AssetGridBody
        virtual={virtual}
        renderedRows={renderedRows}
        renderCard={renderCard}
        sortKey={sortKey}
        folderGroups={folderGroups}
        typeGroups={typeGroups}
        collapsedGroups={collapsedGroups}
        expandedGroups={expandedGroups}
        toggleGroup={toggleGroup}
        toggleGroupExpanded={toggleGroupExpanded}
        isProject={isProject}
        folderId={folderId}
        subfolders={subfolders}
        loading={loading}
        items={items}
        queryRef={queryRef}
        activeTags={activeTags}
        hasMore={hasMore}
        loadingMore={loadingMore}
        loadMore={loadMore}
      />
      {previewItem && (
        <AssetPreviewModal asset={previewItem} theme={theme} onClose={() => setPreviewItem(null)} />
      )}
      </div>
      {pendingConfirm && (
        <ConfirmDialog
          title={pendingConfirm.title}
          body={pendingConfirm.body}
          confirmLabel={pendingConfirm.confirmLabel}
          danger={pendingConfirm.danger}
          busy={confirmBusy}
          onCancel={() => setPendingConfirm(null)}
          onConfirm={() => { void runPendingConfirm(); }}
        />
      )}
      {deleteTargets && (
        <AssetDeleteDialog
          assets={deleteTargets}
          onDelete={runDelete}
          onCancel={closeDeleteDialog}
          onClosed={closeDeleteDialog}
        />
      )}
      {metaDialogOpen && (
        <BulkMetaDialog
          open={metaDialogOpen}
          count={selectedIds.size}
          busy={Boolean(bulkBusy)}
          requestError={metaRequestError}
          onCancel={closeMetaDialog}
          onSubmit={change => { void submitMeta(change); }}
        />
      )}
      {projectPickerIds && (
        <ProjectPickerDialog
          assetIds={projectPickerIds}
          onClose={() => setProjectPickerIds(null)}
          onChanged={onProjectsChanged}
          onUnauthorized={onUnauthorized}
        />
      )}
    </div>
  );
}
