import React, { useEffect, useRef, useState } from "react";
import {
  type AssetFile,
  type AssetFileLimits,
  deleteAssetFile,
  deletePreparedPrint,
  listAssetFileLimits,
  listAssetFiles,
  renameAssetFile,
  reorderAssetFiles,
  uploadAssetFile,
} from "../../lib/api";
import { formatBytes } from "../../lib/format";
import { normaliseCreator, normaliseName, normaliseNotes } from "../../lib/metadataValidation";
import { notifyError } from "../../lib/toast";
import { useFileGrants } from "../../lib/useFileGrants";
import FileDownloadLink from "../FileDownloadLink";
import TagBadge from "../TagBadge";
import TagInput from "../TagInput";
import AssetFilePreview from "./AssetFilePreview";
import { ENGRAVING_EXTS, MODEL_EXTS, extOf, formatMissingSince } from "./assetGridMeta";
import { PreparedPrintSummary, renderPreviewContent } from "./preview";
import type { AssetCardProps } from "./assetCardProps";

const AssetCard = React.memo(function AssetCard({
  item,
  canContribute,
  canDelete,
  onSaveTags,
  onSaveDetails,
  onRename,
  onPreview,
  onDownloadSingle,
  onDownloadByTag,
  onDownloadSelected,
  downloading,
  onDelete,
  onAddToProject,
  onMoveFolder,
  folderOptions,
  showFolderControls = true,
  moving,
  selected,
  onToggleSelected,
  hasSelection,
  bulkDownloading,
  slicerEnabled,
  slicerLabel,
  onOpenInSlicer,
  engravingEnabled,
  engraverLabel,
  onOpenInEngraving,
  theme,
  previewMode,
  onAssetChanged,
  onForgetMissing,
  onRescanMissing,
  rescanning,
  onRequestConfirm,
}: AssetCardProps) {
  const [editingTags, setEditingTags] = useState(false);
  const [tagList, setTagList] = useState<string[]>(item.tags);
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesValue, setNotesValue] = useState(item.notes || "");
  const [creatorValue, setCreatorValue] = useState(item.creator || "");
  const [notesError, setNotesError] = useState<string | null>(null);
  const [creatorError, setCreatorError] = useState<string | null>(null);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [notesCollapsed, setNotesCollapsed] = useState(true);
  const [renaming, setRenaming] = useState(false);
  const [nameValue, setNameValue] = useState(item.name);
  const nameInputRef = React.useRef<HTMLInputElement | null>(null);
  const [downloadChoice, setDownloadChoice] = useState("");
  const [filesExpanded, setFilesExpanded] = useState(false);
  const [supportingFiles, setSupportingFiles] = useState<AssetFile[]>([]);
  const [fileLimits, setFileLimits] = useState<AssetFileLimits | null>(null);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesUploading, setFilesUploading] = useState(false);
  const [renamingFileId, setRenamingFileId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [fileRenameError, setFileRenameError] = useState<string | null>(null);
  const [fileBusy, setFileBusy] = useState(false);
  const [previewFile, setPreviewFile] = useState<AssetFile | null>(null);
  const [preparedClearing, setPreparedClearing] = useState(false);
  const relatedInputRef = useRef<HTMLInputElement | null>(null);

  // The card's own <img>/model preview re-reads the grant cache on every render,
  // so the cache has to stay warm while the card is mounted: a card that
  // re-renders after expiry (a selection toggle) would otherwise swap a working
  // `src` for an unsigned one, and a remounted row (the virtualized grid keys
  // rows by index, so scrolling out unmounts the cards) starts cold. The result
  // is discarded: a card must never hold back its layout.
  useFileGrants([item.url, item.thumb_url]);

  useEffect(() => {
    if (!editingTags) {
      setTagList(item.tags);
    }
  }, [item.tags, editingTags]);

  useEffect(() => {
    if (!editingNotes) {
      setNotesValue(item.notes || "");
      setCreatorValue(item.creator || "");
    }
  }, [item.notes, item.creator, editingNotes]);

  useEffect(() => {
    if (!renaming) {
      setNameValue(item.name);
    } else {
      setTimeout(() => nameInputRef.current?.select(), 0);
    }
  }, [item.name, renaming]);

  const loadSupportingFiles = async () => {
    setFilesLoading(true);
    try {
      const [files, limits] = await Promise.all([
        listAssetFiles(item.id),
        // A broken limits endpoint must not hide a list that loaded fine.
        listAssetFileLimits(item.id).catch(err => {
          console.error(err);
          return null;
        }),
      ]);
      setSupportingFiles(files);
      setFileLimits(limits);
    } catch (err) {
      console.error(err);
      notifyError(err instanceof Error ? err.message : "Failed to load supporting files");
    } finally {
      setFilesLoading(false);
    }
  };

  useEffect(() => {
    if (filesExpanded) void loadSupportingFiles();
  }, [filesExpanded, item.id]);

  useEffect(() => {
    setPreviewFile(null);
    setRenamingFileId(null);
    setFileRenameError(null);
  }, [item.id]);

  const addRelatedFiles = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    setFilesUploading(true);
    try {
      let updated = item;
      for (const file of files) {
        updated = await uploadAssetFile(item.id, file);
        onAssetChanged(updated);
      }
      setFilesExpanded(true);
      await loadSupportingFiles();
    } catch (err) {
      console.error(err);
      notifyError(err instanceof Error ? err.message : "Failed to add files");
    } finally {
      setFilesUploading(false);
      // Refresh even after a partial failure: files before the failing one are
      // already stored, and a limit error must leave the list showing reality.
      await loadSupportingFiles();
    }
  };

  const removeRelatedFile = (file: AssetFile) => {
    onRequestConfirm({
      title: `Remove ${file.filename} from this model?`,
      danger: true,
      confirmLabel: "Remove",
      run: async () => {
        try {
          const updated = await deleteAssetFile(item.id, file.id);
          onAssetChanged(updated);
          await loadSupportingFiles();
        } catch (err) {
          console.error(err);
          notifyError(err instanceof Error ? err.message : "Failed to remove file");
        }
      },
    });
  };

  const startFileRename = (file: AssetFile) => {
    setRenamingFileId(file.id);
    setRenameValue(file.filename);
    setFileRenameError(null);
  };

  const cancelFileRename = () => {
    setRenamingFileId(null);
    setRenameValue("");
    setFileRenameError(null);
  };

  const commitFileRename = async (file: AssetFile) => {
    const filename = renameValue.trim();
    if (!filename) {
      setFileRenameError("Enter a file name.");
      return;
    }
    if (filename === file.filename) {
      cancelFileRename();
      return;
    }
    setFileBusy(true);
    setFileRenameError(null);
    try {
      const updated = await renameAssetFile(item.id, file.id, filename);
      setSupportingFiles(current => current.map(entry => (entry.id === file.id ? updated : entry)));
      setRenamingFileId(null);
      await loadSupportingFiles();
    } catch (err) {
      console.error(err);
      const message = err instanceof Error && err.message ? err.message : "Rename failed";
      setFileRenameError(message);
      notifyError(message);
    } finally {
      setFileBusy(false);
    }
  };

  const handleFileRenameKey = (event: React.KeyboardEvent<HTMLInputElement>, file: AssetFile) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void commitFileRename(file);
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelFileRename();
    }
  };

  const moveFile = async (file: AssetFile, direction: -1 | 1) => {
    const index = supportingFiles.findIndex(entry => entry.id === file.id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= supportingFiles.length) return;
    const swapped = [...supportingFiles];
    [swapped[index], swapped[target]] = [swapped[target], swapped[index]];
    setFileBusy(true);
    try {
      setSupportingFiles(await reorderAssetFiles(item.id, swapped.map(entry => entry.id)));
      await loadSupportingFiles();
    } catch (err) {
      console.error(err);
      notifyError(err instanceof Error ? err.message : "Failed to reorder supporting files");
    } finally {
      setFileBusy(false);
    }
  };

  const clearPreparedPrint = () => {
    onRequestConfirm({
      title: "Clear the attached prepared print from this model?",
      danger: true,
      confirmLabel: "Clear",
      run: async () => {
        setPreparedClearing(true);
        try {
          onAssetChanged(await deletePreparedPrint(item.id));
        } catch (err) {
          console.error(err);
          notifyError(err instanceof Error ? err.message : "Failed to clear prepared print");
        } finally {
          setPreparedClearing(false);
        }
      },
    });
  };

  const startEditing = () => {
    setTagList(item.tags);
    setEditingTags(true);
  };

  const cancelEditing = () => {
    setEditingTags(false);
    setTagList(item.tags);
  };

  const save = async () => {
    await onSaveTags(item.id, tagList);
    setEditingTags(false);
  };

  const saveNotes = async () => {
    const creator = normaliseCreator(creatorValue);
    const notes = normaliseNotes(notesValue);
    setCreatorError(creator.error);
    setNotesError(notes.error);
    if (creator.error || notes.error) return;
    await onSaveDetails(item.id, { notes: notes.value ?? "", creator: creator.value ?? "" });
    setEditingNotes(false);
  };

  const cancelNotes = () => {
    setEditingNotes(false);
    setNotesValue(item.notes || "");
    setCreatorValue(item.creator || "");
    setNotesError(null);
    setCreatorError(null);
  };

  const noteText = (item.notes || "").trim();

  const commitRename = async () => {
    const normalised = normaliseName(nameValue);
    if (normalised.error) {
      setRenameError(normalised.error);
      return;
    }
    const next = normalised.value ?? "";
    if (next === item.name) {
      setRenameError(null);
      setRenaming(false);
      return;
    }
    setRenameError(null);
    try {
      await onRename(item.id, next);
    } catch {
      // `onRename` already reported the failure once; just revert the field.
      setNameValue(item.name);
    } finally {
      setRenaming(false);
    }
  };

  const cancelRename = () => {
    setNameValue(item.name);
    setRenameError(null);
    setRenaming(false);
  };

  const handleRenameKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitRename();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelRename();
    }
  };

  // A role below editor keeps the name as plain text: rename mode is never entered.
  const handleNameDoubleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!canDelete) return;
    e.stopPropagation();
    setRenaming(true);
  };

  const handleFolderChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const next = e.target.value || null;
    const current = item.folder_id || null;
    if (next === current) return;
    onMoveFolder(item.id, next);
  };

  const handleDownloadChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    if (!val) return;
    setDownloadChoice("");
    if (val === "single") {
      onDownloadSingle(item);
    } else if (val === "selected") {
      onDownloadSelected();
    } else if (val.startsWith("tag:")) {
      onDownloadByTag(val.slice(4));
    }
  };

  const canOpenInSlicer = slicerEnabled && (Boolean(item.prepared_print) || MODEL_EXTS.has(extOf(item.filename)));
  const canOpenInEngraving = engravingEnabled && ENGRAVING_EXTS.has(extOf(item.filename));

  const fileCount = fileLimits?.count ?? item.supporting_file_count ?? 0;
  const maxFileCount = fileLimits?.max_count ?? 0;
  const atFileLimit = maxFileCount > 0 && fileCount >= maxFileCount;
  const fileCountLabel = maxFileCount > 0 ? `${fileCount} / ${maxFileCount}` : String(fileCount);
  const fileLimitsTitle = fileLimits
    ? [
        `Supporting files: ${fileCount} of ${maxFileCount > 0 ? maxFileCount : "unlimited"}`,
        `${formatBytes(fileLimits.total_bytes)} used${
          fileLimits.max_total_bytes > 0
            ? ` of ${formatBytes(fileLimits.max_total_bytes)}`
            : " (no total limit)"
        }`,
        fileLimits.max_file_bytes > 0
          ? `${formatBytes(fileLimits.max_file_bytes)} max per file`
          : "no per-file limit",
      ].join(" · ")
    : undefined;

  return (
    <div
      className="rounded-lg border border-panel overflow-hidden bg-panel-soft"
      data-asset-id={item.id}
    >
      <div
        className="h-40 relative cursor-pointer"
        onDoubleClick={() => onPreview(item)}
        title="Double-click to open large preview"
        onClick={e => e.stopPropagation()}
      >
        {renderPreviewContent(item, "card", theme, previewMode)}
      </div>
      {item.missing_since && (
        <div
          role="status"
          className="m-3 mb-0 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/40 px-3 py-2 text-sm"
        >
          <div className="font-semibold text-red-700 dark:text-red-300">File missing</div>
          <div className="text-xs opacity-80">
            Not found in storage since {formatMissingSince(item.missing_since)}.
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {canDelete && (
              <>
                <button
                  className="text-sm px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
                  onClick={() => onRescanMissing(item)}
                  disabled={rescanning}
                >
                  {rescanning ? "Scanning..." : "Re-scan"}
                </button>
                <button
                  className="text-sm px-2 py-1 rounded-md border border-red-300 text-red-700 dark:text-red-300 disabled:opacity-60"
                  onClick={() => onForgetMissing(item)}
                >
                  Forget entry
                </button>
              </>
            )}
          </div>
        </div>
      )}
      <div className="p-3 flex flex-col gap-2">
        {item.prepared_print && (
          <PreparedPrintSummary
            prepared={item.prepared_print}
            onClear={canDelete && item.prepared_print.removable ? clearPreparedPrint : undefined}
            clearing={preparedClearing}
          />
        )}
        <div className="flex items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelected(item.id)}
              className="w-4 h-4"
            />
            <span>Select</span>
          </label>
          <div className="flex items-center gap-2">
            <select
              value={downloadChoice}
              onChange={handleDownloadChange}
              disabled={downloading || bulkDownloading}
              className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
            >
              <option value="">Download...</option>
              <option value="single">Download file</option>
              <option value="selected" disabled={!hasSelection}>Download all selected</option>
              {item.tags.map(t => (
                <option key={`tag-${t}`} value={`tag:${t}`}>Download tag: {t}</option>
              ))}
            </select>
            {(downloading || bulkDownloading) && (
              <span className="text-xs opacity-70">{downloading ? "Downloading..." : "Preparing..."}</span>
            )}
          </div>
        </div>
        {(canOpenInSlicer || canOpenInEngraving) && (
          <div className="flex flex-wrap gap-2 justify-end">
            {canOpenInSlicer && (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
                onClick={() => onOpenInSlicer(item)}
                disabled={downloading || bulkDownloading}
              >
                Open in {slicerLabel}
              </button>
            )}
            {canOpenInEngraving && (
              <button
                className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
                onClick={() => onOpenInEngraving(item)}
                disabled={downloading || bulkDownloading}
              >
                Open in {engraverLabel}
              </button>
            )}
          </div>
        )}
        {canDelete && showFolderControls && (
          <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold uppercase text-muted">
              {moving ? "Updating..." : "Folder"}
            </label>
            <select
              value={item.folder_id || ""}
              onChange={handleFolderChange}
              disabled={moving}
              className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
            >
              {folderOptions.map(opt => (
                <option key={opt.id || "none"} value={opt.id || ""}>
                  {opt.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div
          className="text-sm font-medium truncate cursor-text"
          title={`${item.name} · ${item.filename}`}
          onDoubleClick={handleNameDoubleClick}
          onClick={e => canDelete && renaming && e.stopPropagation()}
        >
          {canDelete && renaming ? (
            <>
              <input
                ref={nameInputRef}
                value={nameValue}
                onChange={e => {
                  setNameValue(e.target.value);
                  setRenameError(null);
                }}
                onBlur={commitRename}
                onKeyDown={handleRenameKey}
                onClick={e => e.stopPropagation()}
                className="px-2 py-1 w-full rounded-md border border-panel-strong bg-panel-soft text-sm"
                autoFocus
              />
              {renameError && (
                <p role="alert" className="text-xs text-red-700 dark:text-red-300">
                  {renameError}
                </p>
              )}
            </>
          ) : (
            item.name
          )}
        </div>
        <div className="text-[11px] truncate text-subtle" title={item.filename}>{item.filename}</div>
        {(item.creator || item.collection || item.created_by) && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
            {item.creator && <span>By {item.creator}</span>}
            {item.created_by && <span>Added by {item.created_by}</span>}
            {item.collection && <span>Collection (legacy): {item.collection}</span>}
          </div>
        )}
        <div className="flex flex-wrap gap-1">
          {item.tags.length ? (
            item.tags.map(t => <TagBadge key={t} tag={t} />)
          ) : (
            <span className="text-xs opacity-60">No tags</span>
          )}
        </div>
        <div className="rounded-md border border-panel-strong bg-panel-strong/40 text-sm">
          <div className="flex items-center justify-between gap-2 p-2">
            <button
              type="button"
              className="flex min-w-0 items-center gap-2 text-left"
              onClick={() => setFilesExpanded(value => !value)}
              title={fileLimitsTitle}
            >
              <span className="font-medium">Supporting files</span>
              <span className="rounded-full bg-panel px-2 py-0.5 text-[11px] text-muted" title={fileLimitsTitle}>
                {fileCountLabel}
              </span>
            </button>
            {canContribute && (
              <>
                <input
                  ref={relatedInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  accept=".pdf,.txt,.md,.markdown,.csv,.log,.json,.html,.htm,.xml,.yaml,.yml,.png,.jpg,.jpeg,.gif,.webp,.bmp,.doc,.docx,.rtf,.zip,.gcode,.gco,.bgcode,.3mf"
                  onChange={addRelatedFiles}
                />
                <button
                  type="button"
                  className="rounded-md border border-panel-strong px-2 py-1 text-xs disabled:opacity-60"
                  disabled={filesUploading || atFileLimit}
                  onClick={() => relatedInputRef.current?.click()}
                  title={
                    atFileLimit
                      ? `Supporting file limit reached (${maxFileCount})`
                      : "Add documentation or a prepared print"
                  }
                >
                  {filesUploading ? "Adding..." : "Add files"}
                </button>
              </>
            )}
          </div>
          {filesExpanded && (
            <div className="border-t border-panel px-2 py-2">
              {filesLoading ? (
                <div className="text-xs text-muted">Loading files...</div>
              ) : supportingFiles.length ? (
                <div className="space-y-1">
                  {supportingFiles.map((file, index) => (
                    <div key={file.id} className="rounded px-1 py-1 hover:bg-panel-soft">
                      {renamingFileId === file.id ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <input
                            value={renameValue}
                            onChange={event => {
                              setRenameValue(event.target.value);
                              setFileRenameError(null);
                            }}
                            onKeyDown={event => handleFileRenameKey(event, file)}
                            aria-label={`Rename ${file.filename}`}
                            className="min-w-0 flex-1 rounded-md border border-panel-strong bg-panel-soft px-2 py-1 text-xs"
                            autoFocus
                          />
                          <button
                            type="button"
                            className="rounded-md bg-accent px-2 py-1 text-[11px] disabled:opacity-60"
                            disabled={fileBusy}
                            onClick={() => commitFileRename(file)}
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            className="rounded-md border border-panel-strong px-2 py-1 text-[11px] disabled:opacity-60"
                            disabled={fileBusy}
                            onClick={cancelFileRename}
                          >
                            Cancel
                          </button>
                          {fileRenameError && (
                            <p role="alert" className="w-full text-xs text-red-700 dark:text-red-300">
                              {fileRenameError}
                            </p>
                          )}
                        </div>
                      ) : (
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <button
                            type="button"
                            className="min-w-0 truncate text-left text-xs underline-offset-2 hover:underline"
                            title={file.filename}
                            aria-label={`Preview ${file.filename}`}
                            onClick={() => setPreviewFile(file)}
                          >
                            {file.filename}
                          </button>
                          <div className="flex shrink-0 items-center gap-2 text-[11px]">
                            <span className="text-muted">{formatBytes(file.size)}</span>
                            <FileDownloadLink
                              className="underline-offset-2 hover:underline"
                              rel={file.url}
                              filename={file.filename}
                            >
                              Download
                            </FileDownloadLink>
                            {/* Reordering and the display-only rename are
                                contribute surfaces: they rewrite list order and
                                a label, never the bytes. Remove deletes a file,
                                so it keeps the narrower `canDelete` gate. */}
                            {canContribute && (
                              <>
                                <button
                                  type="button"
                                  className="px-1 disabled:opacity-40"
                                  aria-label={`Move ${file.filename} up`}
                                  disabled={fileBusy || index === 0}
                                  onClick={() => moveFile(file, -1)}
                                >
                                  ↑
                                </button>
                                <button
                                  type="button"
                                  className="px-1 disabled:opacity-40"
                                  aria-label={`Move ${file.filename} down`}
                                  disabled={fileBusy || index === supportingFiles.length - 1}
                                  onClick={() => moveFile(file, 1)}
                                >
                                  ↓
                                </button>
                                <button
                                  type="button"
                                  disabled={fileBusy}
                                  onClick={() => startFileRename(file)}
                                >
                                  Rename
                                </button>
                                {canDelete && (
                                  <button
                                    type="button"
                                    className="text-red-700 dark:text-red-300"
                                    onClick={() => removeRelatedFile(file)}
                                  >
                                    Remove
                                  </button>
                                )}
                              </>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted">Add assembly instructions, notes, other documentation, or a prepared print.</div>
              )}
            </div>
          )}
        </div>
        {previewFile && (
          <AssetFilePreview
            key={previewFile.id}
            assetId={item.id}
            file={previewFile}
            onClose={() => setPreviewFile(null)}
          />
        )}
        <div className="border border-dashed border-panel-strong rounded-md p-2 text-sm flex flex-col gap-2">
          <div className="flex items-center justify-between text-xs uppercase tracking-wide text-muted">
            <span>Model details</span>
            <button
              className="text-[11px] px-2 py-0.5 rounded-md border border-panel-strong"
              onClick={() => setNotesCollapsed(v => !v)}
            >
              {notesCollapsed ? "Expand" : "Collapse"}
            </button>
          </div>
          {!notesCollapsed && (
            <>
              {canContribute && editingNotes ? (
                <>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-muted">Creator</span>
                    <input
                      value={creatorValue}
                      onChange={e => {
                        setCreatorValue(e.target.value);
                        setCreatorError(null);
                      }}
                      className="w-full rounded-md border border-panel-strong bg-panel-soft px-2 py-1.5"
                      placeholder="Designer or source"
                    />
                    {creatorError && (
                      <p role="alert" className="text-xs text-red-700 dark:text-red-300">
                        {creatorError}
                      </p>
                    )}
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-muted">Notes</span>
                  <textarea
                    value={notesValue}
                    onChange={e => {
                      setNotesValue(e.target.value);
                      setNotesError(null);
                    }}
                    className="w-full min-h-[80px] rounded-md border border-panel-strong bg-panel-soft p-2"
                    placeholder="Add some details about this asset"
                  />
                  {notesError && (
                    <p role="alert" className="text-xs text-red-700 dark:text-red-300">
                      {notesError}
                    </p>
                  )}
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button className="text-sm px-3 py-1 rounded-md bg-accent" onClick={saveNotes}>Save</button>
                    <button className="text-sm px-3 py-1 rounded-md border border-panel-strong" onClick={cancelNotes}>Cancel</button>
                  </div>
                </>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div><span className="block text-[10px] uppercase text-muted">Creator</span>{item.creator || "Not set"}</div>
                    {item.collection && (
                      <div><span className="block text-[10px] uppercase text-muted">Collection (legacy)</span>{item.collection}</div>
                    )}
                  </div>
                  <div className={`text-sm whitespace-pre-wrap ${noteText ? "text-foreground" : "opacity-60"}`}>
                    {noteText || "Add notes"}
                  </div>
                  {canContribute && (
                    <button
                      className="self-start text-xs px-2 py-1 rounded-md border border-panel-strong"
                      onClick={() => setEditingNotes(true)}
                    >
                      Edit details
                    </button>
                  )}
                </>
              )}
            </>
          )}
          {notesCollapsed && (
            <div className={`text-sm ${noteText ? "text-foreground" : "opacity-60"}`}>
              {noteText
                ? `${noteText.slice(0, 60)}${noteText.length > 60 ? "..." : ""}`
                : [item.creator, item.collection ? `${item.collection} (legacy)` : null].filter(Boolean).join(" · ") || "No details"}
            </div>
          )}
        </div>

        {/* The tag editor, the row that opens it, and the project picker are
            contribute surfaces; the Delete beside them is a destroy, so it
            keeps the narrower `canDelete` gate. A demotion mid-edit therefore
            drops the editor with the buttons. */}
        {canContribute && (editingTags ? (
          <div className="flex flex-col gap-2">
            <TagInput
              value={tagList}
              onChange={setTagList}
              placeholder="Type and press comma/Enter"
            />
            <div className="flex flex-wrap gap-2">
              <button className="text-sm px-3 py-1 rounded-md bg-accent" onClick={save}>Save</button>
              <button className="text-sm px-3 py-1 rounded-md border border-panel-strong" onClick={cancelEditing}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 flex-wrap">
            <button className="text-sm px-2 py-1 rounded-md border border-panel-strong" onClick={startEditing}>Edit tags</button>
            <button
              className="text-sm px-2 py-1 rounded-md border border-panel-strong"
              onClick={() => onAddToProject(item)}
            >
              Add to project…
            </button>
            {canDelete && (
              <button
                className="text-sm px-2 py-1 rounded-md border border-red-300 text-red-700 dark:text-red-300 disabled:opacity-60"
                onClick={() => onDelete(item)}
              >
                Delete
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
});

export default AssetCard;
