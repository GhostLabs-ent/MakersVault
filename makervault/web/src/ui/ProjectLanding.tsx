import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import {
  Clock,
  Download,
  ExternalLink,
  File as FileIcon,
  FileBox,
  Files,
  HardDrive,
  Image as ImageIcon,
  Layers3,
  Paperclip,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";

import {
  UnauthorizedError,
  addProjectAssets,
  deleteProject,
  downloadAsset,
  downloadZip,
  fileUrl,
  listAssets,
  listProjectAssets,
  removeProjectAssets,
  updateProject,
  uploadAssetFile,
  type Asset,
  type Project,
  type ProjectPatch,
} from "../lib/api";
import { saveResponseToDisk } from "../lib/download";
import { formatBytes, formatDate } from "../lib/format";
import { is3mfAsset, isImageAsset, isModelAsset, typeLabelFor } from "../lib/assetKinds";
import { sourceHostLabel } from "../lib/provenance";
import {
  slicerLabelFor,
  type EngravingSettings,
  type PreviewSettings,
  type ResolvedTheme,
  type SlicerSettings,
} from "../lib/settings";
import { notifyError, notifyInfo } from "../lib/toast";
import ConfirmDialog, { type ConfirmRequest } from "./ConfirmDialog";
import LicenceChip from "./LicenceChip";
import AttachFilesControl from "./project-attach/AttachFilesControl";
import { useAttachDrop } from "./project-attach/useAttachDrop";
import { useAttachToProject } from "./project-attach/useAttachToProject";
import Markdown from "./Markdown";
import MarkdownEditor from "./project-editor/MarkdownEditor";
import TagBadge from "./TagBadge";

type Props = {
  /** Required, not defaulted: the compiler is what keeps the gating airtight. */
  canWrite: boolean;
  project: Project;
  assetsVersion: number;
  /** App splices the returned row into its project list. */
  onProjectUpdated: (project: Project) => void;
  onProjectDeleted: (id: string) => void;
  /** App bumps `assetsVersion`, which retriggers the member refetch below. */
  onAssetsChanged: () => void;
  onUnauthorized?: () => void;
  slicerSettings?: SlicerSettings;
  engravingSettings?: EngravingSettings;
  previewSettings?: PreviewSettings;
  theme: ResolvedTheme;
};

type Draft = {
  name: string;
  description: string;
  creator: string;
  licence: string;
  licence_url: string;
  source_url: string;
};

function draftFromProject(project: Project): Draft {
  return {
    name: project.name,
    description: project.description ?? "",
    creator: project.creator ?? "",
    licence: project.licence ?? "",
    licence_url: project.licence_url ?? "",
    source_url: project.source_url ?? "",
  };
}

/** Known `metadata_json` keys get pretty labels; everything else is shown as-is. */
const KNOWN_METADATA_LABELS: Record<string, string> = {
  filament: "Filament",
  layer_height: "Layer height (mm)",
  infill: "Infill",
  supports: "Supports",
  perimeters: "Perimeters",
};

type MetadataEntry = { key: string; label: string; value: string };

/**
 * Flattens `metadata_json` into display rows. Known keys get pretty labels,
 * unknown primitives become generic key/value rows, and arrays/objects are
 * stringified — nothing the API sent is silently dropped, except reserved
 * import markers (`_files` and friends): they are bookkeeping, not print
 * settings, so they never get a row.
 */
function metadataEntries(metadata: Record<string, unknown>): MetadataEntry[] {
  return Object.entries(metadata)
    .filter(([key]) => !key.startsWith("_"))
    .map(([key, raw]) => {
      const label = KNOWN_METADATA_LABELS[key] ?? key.replace(/_/g, " ");
      let value: string;
      if (typeof raw === "boolean") value = raw ? "Yes" : "No";
      else if (raw === null || raw === undefined) value = "—";
      else if (typeof raw === "object") value = JSON.stringify(raw);
      else value = String(raw);
      return { key, label, value };
    });
}

/** Placeholder icon for a member without a thumbnail of its own. */
function placeholderIconFor(asset: Asset) {
  if (isImageAsset(asset)) return ImageIcon;
  if (isModelAsset(asset)) return FileBox;
  return FileIcon;
}

const FOCUS_VISIBLE =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const BUTTON_PRIMARY = `inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-sm font-semibold transition-colors hover:bg-accent-strong disabled:opacity-60 ${FOCUS_VISIBLE}`;
const BUTTON_SECONDARY = `inline-flex items-center gap-1.5 rounded-md border border-panel-strong px-3 py-2 text-sm transition-colors hover:bg-panel-soft disabled:opacity-60 ${FOCUS_VISIBLE}`;
const BUTTON_DANGER = `inline-flex items-center gap-1.5 rounded-md border border-red-700/60 px-3 py-2 text-sm text-red-500 transition-colors hover:bg-red-500/10 disabled:opacity-60 ${FOCUS_VISIBLE}`;
const BUTTON_ICON = `inline-flex items-center justify-center rounded-md border border-panel-strong p-1.5 text-muted transition-colors hover:bg-panel-soft hover:text-foreground disabled:opacity-60 ${FOCUS_VISIBLE}`;
const INPUT_BASE = `w-full min-w-0 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm ${FOCUS_VISIBLE}`;
const CHIP = `inline-flex items-center gap-1 rounded-full border border-panel-strong bg-panel-soft px-2.5 py-0.5 text-xs font-medium ${FOCUS_VISIBLE}`;
const EYEBROW = "text-xs font-semibold uppercase tracking-[0.14em] text-subtle";

const MEMBER_PAGE_SIZE = 1000;
const PICKER_PAGE_SIZE = 100;
const MAX_TAG_CHIPS = 8;

/** `metadata_json._files` value the server sets when a model's files are gated. */
const USER_SUPPLIED_FILES = "user-supplied";

/**
 * The project detail landing page (Mf-6cxs): hero with cover + gallery,
 * actions, metadata details, the rendered markdown description and the
 * compact member file list. `ProjectView` owns the navigation chrome (Back
 * button, Escape-to-close); this page only intercepts Escape while editing (it
 * `preventDefault()`s so the project stays open) and lets open dialogs handle
 * their own.
 */
export default function ProjectLanding({
  canWrite,
  project,
  assetsVersion,
  onProjectUpdated,
  onProjectDeleted,
  onAssetsChanged,
  onUnauthorized,
  slicerSettings,
  theme,
}: Props): ReactElement {
  const handleApiError = useCallback(
    (err: unknown, message: string) => {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      notifyError(message);
    },
    [onUnauthorized],
  );

  // --- Attaching the user's own files -------------------------------------

  const attacher = useAttachToProject({
    projectId: project.id,
    projectName: project.name,
    // `onAssetsChanged` bumps `assetsVersion`, which refetches the members.
    onAttached: onAssetsChanged,
    onUnauthorized,
  });
  const attachDrop = useAttachDrop(attacher.attach, canWrite);

  // --- Members (the project's files) --------------------------------------

  const [members, setMembers] = useState<Asset[]>([]);
  const [membersLoading, setMembersLoading] = useState(true);
  const [membersHasMore, setMembersHasMore] = useState(false);
  const [membersNextOffset, setMembersNextOffset] = useState<number | null>(null);
  const [membersLoadingMore, setMembersLoadingMore] = useState(false);
  // Guards against a stale response landing after the project changed.
  const membersRequestRef = useRef(0);

  const refreshMembers = useCallback(async () => {
    const requestId = ++membersRequestRef.current;
    setMembersLoading(true);
    try {
      const res = await listProjectAssets({ projectId: project.id, limit: MEMBER_PAGE_SIZE });
      if (membersRequestRef.current !== requestId) return;
      setMembers(res.items);
      setMembersHasMore(res.hasMore);
      setMembersNextOffset(res.nextOffset ?? null);
    } catch (err) {
      if (membersRequestRef.current !== requestId) return;
      handleApiError(err, "Failed to load the project's files.");
    } finally {
      if (membersRequestRef.current === requestId) setMembersLoading(false);
    }
  }, [project.id, handleApiError]);

  // The accumulation resets whenever the project changes; App's
  // `assetsVersion` bump refetches the truth after membership changes.
  useEffect(() => {
    setMembers([]);
    setMembersHasMore(false);
    setMembersNextOffset(null);
    void refreshMembers();
  }, [refreshMembers, assetsVersion]);

  const loadMoreMembers = async () => {
    if (membersLoadingMore || !membersHasMore) return;
    setMembersLoadingMore(true);
    try {
      const res = await listProjectAssets({
        projectId: project.id,
        limit: MEMBER_PAGE_SIZE,
        offset: membersNextOffset ?? members.length,
      });
      setMembers(previous => [...previous, ...res.items]);
      setMembersHasMore(res.hasMore);
      setMembersNextOffset(res.nextOffset ?? null);
    } catch (err) {
      handleApiError(err, "Failed to load more files.");
    } finally {
      setMembersLoadingMore(false);
    }
  };

  // --- Derived hero data ---------------------------------------------------

  const imageMembers = useMemo(() => members.filter(isImageAsset), [members]);

  // Gallery order: the cover first, then the API's order (the sort only
  // compares the cover flag, so it is stable for everything else).
  const galleryMembers = useMemo(
    () =>
      [...imageMembers].sort(
        (a, b) => Number(b.id === project.cover_asset_id) - Number(a.id === project.cover_asset_id),
      ),
    [imageMembers, project.cover_asset_id],
  );

  // Cover chain: the API's cover thumb, else the first image/3MF member's
  // thumb, else the generated placeholder below.
  const coverUrl = useMemo(() => {
    if (project.cover_thumb_url) return fileUrl(project.cover_thumb_url);
    const fallback = members.find(
      member => (isImageAsset(member) || is3mfAsset(member)) && member.thumb_url,
    );
    return fallback?.thumb_url ? fileUrl(fallback.thumb_url) : null;
  }, [project.cover_thumb_url, members]);

  // The tag union is read-only here and derived from the members this page
  // already loaded, so the chips cost no extra request.
  const allTags = useMemo(() => {
    const set = new Set<string>();
    for (const member of members) {
      for (const tag of member.tags ?? []) set.add(tag);
    }
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [members]);

  const metaEntries = useMemo(
    () => metadataEntries(project.metadata_json ?? {}),
    [project.metadata_json],
  );

  // A gated import (Mf-56z9) recorded the page's details only; the note in the
  // details panel says why the project has no files and where to get them.
  const filesUserSupplied = project.metadata_json?._files === USER_SUPPLIED_FILES;

  // The API returns members in a deterministic order (name, filename, id);
  // the first row is the project's primary file for the hero slicer action.
  const primaryAsset = members.length > 0 ? members[0] : null;

  const slicerEnabled = Boolean(slicerSettings?.enabled);
  const slicerLabel = slicerLabelFor(slicerSettings?.selected);
  const canOpenInSlicer = useCallback(
    (asset: Asset) =>
      slicerEnabled && (Boolean(asset.prepared_print) || isModelAsset(asset)),
    [slicerEnabled],
  );

  // Deep-link convention shared with AssetGrid's per-card action.
  const openInSlicer = (asset: Asset) => {
    if (!slicerEnabled) return;
    const params = new URLSearchParams({
      url: fileUrl(asset.slicer_url || asset.url),
      slicer: slicerSettings?.selected || "orca",
      filename: asset.slicer_filename || asset.filename || "model",
    });
    window.location.href = `makersvault-slicer://open?${params.toString()}`;
  };

  // --- Confirm dialog plumbing (the only confirm mechanism) -----------------

  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const confirmRunningRef = useRef(false);

  const handleConfirm = async () => {
    if (!confirm || confirmRunningRef.current) return;
    confirmRunningRef.current = true;
    setConfirmBusy(true);
    try {
      // Each `run` closure handles (and toasts) its own failures; the dialog
      // always closes once the attempt settles.
      await confirm.run();
    } finally {
      confirmRunningRef.current = false;
      setConfirmBusy(false);
      setConfirm(null);
    }
  };

  // --- Actions --------------------------------------------------------------

  const [downloadingZip, setDownloadingZip] = useState(false);
  const downloadAll = async () => {
    if (project.asset_count === 0 || downloadingZip) return;
    setDownloadingZip(true);
    try {
      const res = await downloadZip({ project_id: project.id });
      await saveResponseToDisk(res, `${project.name}.zip`);
    } catch (err) {
      handleApiError(err, "Failed to download the project archive.");
    } finally {
      setDownloadingZip(false);
    }
  };

  const [coverSavingId, setCoverSavingId] = useState<string | null>(null);
  const setAssetAsCover = async (asset: Asset) => {
    if (coverSavingId) return;
    setCoverSavingId(asset.id);
    try {
      const updated = await updateProject(project.id, { cover_asset_id: asset.id });
      onProjectUpdated(updated);
    } catch (err) {
      handleApiError(err, "Failed to update the cover image.");
    } finally {
      setCoverSavingId(null);
    }
  };

  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const downloadOne = async (asset: Asset) => {
    if (downloadingId) return;
    setDownloadingId(asset.id);
    try {
      const res = await downloadAsset(asset);
      await saveResponseToDisk(res, asset.filename || "download");
    } catch (err) {
      handleApiError(err, "Download failed. Please try again.");
    } finally {
      setDownloadingId(null);
    }
  };

  const requestRemoveAsset = (asset: Asset) =>
    setConfirm({
      title: `Remove ${asset.name}?`,
      body: `"${asset.name}" stays in your library; only its membership in this project is removed.`,
      confirmLabel: "Remove",
      danger: true,
      run: async () => {
        try {
          const res = await removeProjectAssets(project.id, [asset.id]);
          if (res.failed.length > 0) {
            notifyError(`Failed to remove "${asset.name}" from the project.`);
            return;
          }
          setMembers(previous => previous.filter(member => member.id !== asset.id));
          notifyInfo(`Removed "${asset.name}" from the project.`);
          onAssetsChanged();
        } catch (err) {
          handleApiError(err, "Failed to remove the file from the project.");
        }
      },
    });

  const requestDeleteProject = () =>
    setConfirm({
      title: `Delete ${project.name}?`,
      body: "Deleting this project removes only the collection. The files themselves stay in your library.",
      confirmLabel: "Delete",
      danger: true,
      run: async () => {
        try {
          await deleteProject(project.id);
          notifyInfo(`Project "${project.name}" deleted.`);
          onProjectDeleted(project.id);
        } catch (err) {
          handleApiError(err, "Failed to delete the project.");
        }
      },
    });

  // --- Supporting files ------------------------------------------------------

  const supportInputRef = useRef<HTMLInputElement | null>(null);
  const supportTargetRef = useRef<Asset | null>(null);
  const [supportBusyId, setSupportBusyId] = useState<string | null>(null);

  const pickSupportingFile = (asset: Asset) => {
    supportTargetRef.current = asset;
    supportInputRef.current?.click();
  };

  const handleSupportFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    const asset = supportTargetRef.current;
    supportTargetRef.current = null;
    if (!file || !asset) return;
    setSupportBusyId(asset.id);
    try {
      await uploadAssetFile(asset.id, file);
      notifyInfo(`Added "${file.name}" to ${asset.name}.`);
      await refreshMembers();
    } catch (err) {
      handleApiError(err, "Failed to add the supporting file.");
    } finally {
      setSupportBusyId(null);
    }
  };

  // --- Inline editing ---------------------------------------------------------

  const [draft, setDraft] = useState<Draft | null>(null);
  const [focusField, setFocusField] = useState<"name" | "description">("name");
  const [nameError, setNameError] = useState("");
  const [saving, setSaving] = useState(false);

  const dirty =
    draft !== null &&
    (draft.name !== project.name ||
      draft.description !== (project.description ?? "") ||
      draft.creator !== (project.creator ?? "") ||
      draft.licence !== (project.licence ?? "") ||
      draft.licence_url !== (project.licence_url ?? "") ||
      draft.source_url !== (project.source_url ?? ""));

  // The unsaved-changes guard exists only while there is something to lose.
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const startEdit = (focus: "name" | "description") => {
    setDraft(draftFromProject(project));
    setFocusField(focus);
    setNameError("");
  };

  const saveEdit = async () => {
    if (!draft || saving) return;
    const name = draft.name.trim();
    if (!name) {
      setNameError("A project needs a name.");
      return;
    }
    // Only changed fields go over the wire; emptied nullable fields become null.
    const patch: ProjectPatch = {};
    if (name !== project.name) patch.name = name;
    if (draft.description !== (project.description ?? "")) {
      patch.description = draft.description.trim() ? draft.description : null;
    }
    const creator = draft.creator.trim();
    if (creator !== (project.creator ?? "")) patch.creator = creator || null;
    const licence = draft.licence.trim();
    if (licence !== (project.licence ?? "")) patch.licence = licence || null;
    const licenceUrl = draft.licence_url.trim();
    if (licenceUrl !== (project.licence_url ?? "")) patch.licence_url = licenceUrl || null;
    const sourceUrl = draft.source_url.trim();
    if (sourceUrl !== (project.source_url ?? "")) patch.source_url = sourceUrl || null;

    setSaving(true);
    try {
      const updated = await updateProject(project.id, patch);
      onProjectUpdated(updated);
      notifyInfo("Project updated.");
      setDraft(null);
    } catch (err) {
      handleApiError(err, "Failed to update the project.");
    } finally {
      setSaving(false);
    }
  };

  const requestCancelEdit = useCallback(() => {
    if (!dirty) {
      setDraft(null);
      return;
    }
    setConfirm({
      title: "Discard changes?",
      body: "You have unsaved changes to this project. Discard them?",
      confirmLabel: "Discard",
      danger: true,
      run: () => setDraft(null),
    });
  }, [dirty]);

  // A different open project invalidates any in-flight edit/dialog state.
  useEffect(() => {
    setDraft(null);
    setConfirm(null);
  }, [project.id]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") return;
    // An open dialog owns Escape (ConfirmDialog and the add-files picker close
    // themselves); ProjectView also ignores events from inside dialogs.
    if ((event.target as Element | null)?.closest?.('[role="dialog"]')) return;
    if (attacher.busy) {
      // An attach gesture owns Escape too. The shared zip prompt has no Escape
      // handler of its own, so closing the project under it would strand it.
      event.preventDefault();
      return;
    }
    if (canWrite && draft) {
      // Escape while editing must never bubble up as "close the project":
      // ProjectView bails on `defaultPrevented`. A viewer has no editor to
      // cancel, so a stale draft from a demotion must not prompt for one.
      event.preventDefault();
      requestCancelEdit();
    }
  };

  // --- Add-files picker --------------------------------------------------------

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerItems, setPickerItems] = useState<Asset[]>([]);
  const [pickerHasMore, setPickerHasMore] = useState(false);
  const [pickerNextOffset, setPickerNextOffset] = useState<number | null>(null);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerLoadingMore, setPickerLoadingMore] = useState(false);
  const [pickerSelected, setPickerSelected] = useState<string[]>([]);
  const [pickerBusy, setPickerBusy] = useState(false);

  const memberIds = useMemo(() => new Set(members.map(member => member.id)), [members]);

  const loadPickerPage = useCallback(
    async (q: string, offset: number, append: boolean) => {
      const res = await listAssets({ q: q || undefined, limit: PICKER_PAGE_SIZE, offset });
      setPickerItems(previous => (append ? [...previous, ...res.items] : res.items));
      setPickerHasMore(res.hasMore);
      setPickerNextOffset(res.nextOffset ?? null);
    },
    [],
  );

  const openPicker = async () => {
    setPickerOpen(true);
    setPickerQuery("");
    setPickerSelected([]);
    setPickerItems([]);
    setPickerHasMore(false);
    setPickerNextOffset(null);
    setPickerLoading(true);
    try {
      await loadPickerPage("", 0, false);
    } catch (err) {
      handleApiError(err, "Failed to load the library.");
    } finally {
      setPickerLoading(false);
    }
  };

  const searchPicker = async (event?: { preventDefault: () => void }) => {
    event?.preventDefault();
    if (pickerLoading) return;
    setPickerLoading(true);
    try {
      await loadPickerPage(pickerQuery, 0, false);
    } catch (err) {
      handleApiError(err, "Library search failed.");
    } finally {
      setPickerLoading(false);
    }
  };

  const loadMorePicker = async () => {
    if (pickerLoadingMore || !pickerHasMore) return;
    setPickerLoadingMore(true);
    try {
      await loadPickerPage(pickerQuery, pickerNextOffset ?? pickerItems.length, true);
    } catch (err) {
      handleApiError(err, "Failed to load more assets.");
    } finally {
      setPickerLoadingMore(false);
    }
  };

  const togglePickerId = (id: string) => {
    setPickerSelected(previous =>
      previous.includes(id) ? previous.filter(entry => entry !== id) : [...previous, id],
    );
  };

  const addSelectedToProject = async () => {
    if (pickerSelected.length === 0 || pickerBusy) return;
    setPickerBusy(true);
    try {
      const res = await addProjectAssets(project.id, pickerSelected);
      const parts = [`${res.added.length} added`];
      if (res.skipped.length > 0) parts.push(`${res.skipped.length} already in project`);
      if (res.failed.length > 0) parts.push(`${res.failed.length} failed`);
      notifyInfo(`Add files: ${parts.join(", ")}.`);
      setPickerOpen(false);
      onAssetsChanged();
    } catch (err) {
      handleApiError(err, "Failed to add files to the project.");
    } finally {
      setPickerBusy(false);
    }
  };

  const handlePickerKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && !pickerBusy) setPickerOpen(false);
  };

  // --- Render -------------------------------------------------------------------

  // A demotion mid-edit must not leave the editor on screen, so the edit mode
  // is derived from the capability rather than from `draft` alone.
  const editing = canWrite && draft !== null;
  const sourceLabel = project.source_url ? sourceHostLabel(project.source_url) : null;
  const shownTags = allTags.slice(0, MAX_TAG_CHIPS);
  const extraTagCount = allTags.length - shownTags.length;

  return (
    <div className="flex min-w-0 flex-col gap-6" onKeyDown={handleKeyDown} data-theme={theme}>
      {/* Hidden input shared by every row's "add supporting file" action. */}
      <input
        ref={supportInputRef}
        type="file"
        className="hidden"
        aria-hidden="true"
        tabIndex={-1}
        onChange={event => void handleSupportFile(event)}
      />

      <header className="flex min-w-0 flex-col gap-5">
        <div className="flex min-w-0 flex-col gap-5 md:flex-row">
          <div className="min-w-0 md:basis-2/5">
            {coverUrl ? (
              <img
                src={coverUrl}
                alt={`${project.name} cover`}
                className="aspect-[4/3] w-full rounded-lg border border-panel object-cover"
              />
            ) : (
              <div
                role="img"
                aria-label="No cover image"
                className="flex aspect-[4/3] w-full items-center justify-center rounded-lg border border-panel bg-panel-strong"
              >
                <Layers3 className="h-12 w-12 text-subtle" aria-hidden="true" />
              </div>
            )}
          </div>

          <div className="flex min-w-0 flex-1 flex-col gap-2">
            {editing ? (
              <>
                <input
                  aria-label="Project name"
                  className={`${INPUT_BASE} text-xl font-semibold`}
                  value={draft.name}
                  autoFocus={focusField === "name"}
                  onChange={event => {
                    setDraft({ ...draft, name: event.target.value });
                    if (nameError) setNameError("");
                  }}
                />
                {nameError && (
                  <p role="alert" className="text-sm text-red-500">
                    {nameError}
                  </p>
                )}
                <input
                  aria-label="Creator"
                  placeholder="Creator"
                  className={INPUT_BASE}
                  value={draft.creator}
                  onChange={event => setDraft({ ...draft, creator: event.target.value })}
                />
              </>
            ) : (
              <>
                <h1 className="break-words text-2xl font-semibold tracking-tight">
                  {project.name}
                </h1>
                {project.creator && <p className="text-sm text-muted">By {project.creator}</p>}
              </>
            )}

            {!editing && (
              <div className="flex flex-wrap items-center gap-2">
                {project.source_url && (
                  <a
                    href={project.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`${CHIP} text-accent hover:bg-panel`}
                  >
                    {sourceLabel ? `View original on ${sourceLabel}` : "View original"}
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                )}
                {/* Always rendered: an unrecorded licence says so explicitly. */}
                <LicenceChip
                  licence={project.licence}
                  licenceUrl={project.licence_url}
                  linkable
                />
              </div>
            )}

            {allTags.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                {shownTags.map(tag => (
                  <TagBadge key={tag} tag={tag} />
                ))}
                {extraTagCount > 0 && (
                  <span className="rounded-full border border-panel-strong px-2 py-0.5 text-xs text-muted">
                    +{extraTagCount}
                  </span>
                )}
              </div>
            )}

            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
              <span className="inline-flex items-center gap-1.5">
                <Files className="h-4 w-4" aria-hidden="true" />
                {project.asset_count} {project.asset_count === 1 ? "file" : "files"}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <HardDrive className="h-4 w-4" aria-hidden="true" />
                {formatBytes(project.total_size)}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-4 w-4" aria-hidden="true" />
                Updated {formatDate(project.updated_at)}
              </span>
            </div>
          </div>
        </div>

        {galleryMembers.length > 0 && (
          <div className="overflow-x-auto pb-1" data-testid="project-gallery">
            <div className="flex gap-2">
              {galleryMembers.map(asset => (
                <div key={asset.id} className="w-24 shrink-0">
                  <div className="relative">
                    <a
                      href={fileUrl(asset.url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`block rounded-md ${FOCUS_VISIBLE}`}
                    >
                      <img
                        src={fileUrl(asset.thumb_url || asset.url)}
                        alt={asset.name}
                        loading="lazy"
                        className="h-24 w-24 rounded-md border border-panel object-cover"
                      />
                    </a>
                    {asset.id === project.cover_asset_id && (
                      <span className="absolute left-1 top-1 rounded bg-accent px-1.5 py-0.5 text-[10px] font-semibold">
                        Cover
                      </span>
                    )}
                  </div>
                  {canWrite && (
                    <button
                      type="button"
                      aria-label={`Use ${asset.name} as cover`}
                      disabled={coverSavingId === asset.id}
                      onClick={() => void setAssetAsCover(asset)}
                      className={`mt-1 w-full truncate rounded border border-panel-strong px-1 py-0.5 text-[10px] text-muted transition-colors hover:bg-panel-soft hover:text-foreground disabled:opacity-60 ${FOCUS_VISIBLE}`}
                    >
                      {coverSavingId === asset.id ? "Saving…" : "Set cover"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </header>

      <div className="flex flex-wrap gap-2">
        {editing ? (
          <>
            <button
              type="button"
              className={BUTTON_PRIMARY}
              disabled={!dirty || saving}
              onClick={() => void saveEdit()}
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
            <button
              type="button"
              className={BUTTON_SECONDARY}
              disabled={saving}
              onClick={requestCancelEdit}
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className={BUTTON_PRIMARY}
              disabled={project.asset_count === 0 || downloadingZip}
              title={
                project.asset_count === 0
                  ? "This project has no files to download."
                  : undefined
              }
              onClick={() => void downloadAll()}
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {downloadingZip ? "Preparing…" : "Download all as ZIP"}
            </button>
            {canWrite && (
              <>
                <button type="button" className={BUTTON_SECONDARY} onClick={() => void openPicker()}>
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  Add files
                </button>
                <button type="button" className={BUTTON_SECONDARY} onClick={() => startEdit("name")}>
                  <Pencil className="h-4 w-4" aria-hidden="true" />
                  Edit
                </button>
              </>
            )}
            {primaryAsset && canOpenInSlicer(primaryAsset) && (
              <button
                type="button"
                className={BUTTON_SECONDARY}
                onClick={() => openInSlicer(primaryAsset)}
              >
                Open in {slicerLabel}
              </button>
            )}
            {canWrite && (
              <button type="button" className={BUTTON_DANGER} onClick={requestDeleteProject}>
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                Delete
              </button>
            )}
          </>
        )}
      </div>

      <section
        aria-labelledby="project-details-heading"
        className="rounded-lg border border-panel bg-panel-soft p-4"
      >
        <h2 id="project-details-heading" className={EYEBROW}>
          Details
        </h2>
        <dl className="mt-3 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
          <dt className="text-muted">Origin</dt>
          <dd className="min-w-0">
            {project.origin === "imported" ? "Imported" : "Own creation"}
          </dd>

          {/* Always present: a missing licence is stated, not implied by an
              absent row. */}
          <dt className="text-muted">Licence</dt>
          <dd className="min-w-0">
            {editing ? (
              <input
                aria-label="Licence"
                placeholder="e.g. CC-BY-SA"
                className={INPUT_BASE}
                value={draft.licence}
                onChange={event => setDraft({ ...draft, licence: event.target.value })}
              />
            ) : (
              <LicenceChip
                licence={project.licence}
                licenceUrl={project.licence_url}
                linkable
              />
            )}
          </dd>

          {(editing || project.licence_url) && (
            <>
              <dt className="text-muted">Licence URL</dt>
              <dd className="min-w-0">
                {editing ? (
                  <input
                    aria-label="Licence URL"
                    placeholder="https://…"
                    className={INPUT_BASE}
                    value={draft.licence_url}
                    onChange={event => setDraft({ ...draft, licence_url: event.target.value })}
                  />
                ) : (
                  <a
                    href={project.licence_url ?? undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`break-all text-accent underline-offset-2 hover:underline ${FOCUS_VISIBLE}`}
                  >
                    {project.licence_url}
                  </a>
                )}
              </dd>
            </>
          )}

          {(editing || project.source_url) && (
            <>
              <dt className="text-muted">Source</dt>
              <dd className="min-w-0">
                {editing ? (
                  <input
                    aria-label="Source URL"
                    placeholder="https://…"
                    className={INPUT_BASE}
                    value={draft.source_url}
                    onChange={event => setDraft({ ...draft, source_url: event.target.value })}
                  />
                ) : (
                  <a
                    href={project.source_url ?? undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`break-all text-accent underline-offset-2 hover:underline ${FOCUS_VISIBLE}`}
                  >
                    {project.source_url}
                  </a>
                )}
              </dd>
            </>
          )}

          <dt className="text-muted">Created</dt>
          <dd className="min-w-0">{formatDate(project.created_at)}</dd>
          <dt className="text-muted">Updated</dt>
          <dd className="min-w-0">{formatDate(project.updated_at)}</dd>
        </dl>

        {filesUserSupplied && (
          <p className="mt-3 text-sm text-muted">
            Imported details only — the files for this model are gated behind an
            account or a purchase, so they were not downloaded.
            {/* Only an editor can act on it: telling a viewer to use "Attach
                files" points at a control they cannot see. */}
            {canWrite && ' Use "Attach files" to add the files you downloaded yourself.'}
          </p>
        )}

        {metaEntries.length > 0 && (
          <>
            <h3 className={`mt-4 ${EYEBROW}`}>Print settings</h3>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-sm">
                <tbody>
                  {metaEntries.map(entry => (
                    <tr key={entry.key} className="border-b border-panel last:border-0">
                      <th
                        scope="row"
                        className="whitespace-nowrap py-1.5 pr-4 text-left font-medium text-muted"
                      >
                        {entry.label}
                      </th>
                      <td className="break-words py-1.5">{entry.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section aria-labelledby="project-description-heading" className="min-w-0">
        <h2 id="project-description-heading" className={EYEBROW}>
          Description
        </h2>
        {editing ? (
          <MarkdownEditor
            className="mt-2"
            value={draft.description}
            onChange={description => setDraft({ ...draft, description })}
            images={imageMembers}
            rows={10}
            autoFocus={focusField === "description"}
            placeholder="Describe the project — markdown is supported"
            textareaClassName={`${INPUT_BASE} leading-relaxed`}
          />
        ) : project.description ? (
          <div className="mt-2 min-w-0">
            <Markdown>{project.description}</Markdown>
          </div>
        ) : (
          <div className="mt-2 rounded-lg border border-dashed border-panel-strong px-4 py-8 text-center">
            <p className="text-sm text-muted">No description yet.</p>
            {canWrite && (
              <button
                type="button"
                onClick={() => startEdit("description")}
                className={`mt-2 text-sm font-semibold text-accent hover:underline ${FOCUS_VISIBLE}`}
              >
                Add a description
              </button>
            )}
          </div>
        )}
      </section>

      <section
        aria-labelledby="project-files-heading"
        className={`min-w-0 rounded-lg border-2 ${attachDrop.dragActive ? "border-dashed border-accent" : "border-transparent"}`}
        onDragEnter={attachDrop.handleDragEnter}
        onDragOver={attachDrop.handleDragOver}
        onDragLeave={attachDrop.handleDragLeave}
        onDrop={e => void attachDrop.handleDrop(e)}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="project-files-heading" className={EYEBROW}>
            Files
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            {membersHasMore && (
              <span className="text-xs text-muted">
                Showing {members.length} of {project.asset_count}
              </span>
            )}
            {/* One control only: the empty state shows its own, below. */}
            {canWrite && members.length > 0 && <AttachFilesControl attacher={attacher} />}
          </div>
        </div>

        {attachDrop.dragActive && (
          <p className="mt-2 text-sm text-accent">
            Drop files or a folder to attach them to this project
          </p>
        )}

        {membersLoading ? (
          <p className="mt-2 text-sm text-muted">Loading files…</p>
        ) : members.length === 0 ? (
          <div className="mt-2 rounded-lg border border-dashed border-panel-strong px-4 py-8 text-center">
            <p className="text-sm text-muted">This project has no files yet.</p>
            {canWrite && (
              <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
                <button
                  type="button"
                  className={`text-sm font-semibold text-accent hover:underline ${FOCUS_VISIBLE}`}
                  onClick={() => void openPicker()}
                >
                  Add files
                </button>
                <AttachFilesControl attacher={attacher} />
              </div>
            )}
          </div>
        ) : (
          <>
            <ul className="mt-2 flex flex-col gap-2">
              {members.map(asset => {
                const thumbUrl = asset.thumb_url ? fileUrl(asset.thumb_url) : null;
                const ThumbIcon = placeholderIconFor(asset);
                return (
                  <li
                    key={asset.id}
                    className="flex min-w-0 items-center gap-3 rounded-lg border border-panel bg-panel-soft px-3 py-2"
                  >
                    {thumbUrl ? (
                      <img
                        src={thumbUrl}
                        alt=""
                        loading="lazy"
                        className="h-10 w-10 shrink-0 rounded-md border border-panel object-cover"
                      />
                    ) : (
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-panel bg-panel-strong">
                        <ThumbIcon className="h-5 w-5 text-subtle" aria-hidden="true" />
                      </span>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{asset.name}</p>
                      <p className="truncate text-xs text-muted">
                        {formatBytes(asset.size)} · {typeLabelFor(asset)}
                        {asset.supporting_file_count > 0 &&
                          ` · ${asset.supporting_file_count} supporting ${
                            asset.supporting_file_count === 1 ? "file" : "files"
                          }`}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {canOpenInSlicer(asset) && (
                        <button
                          type="button"
                          aria-label={`Open ${asset.name} in ${slicerLabel}`}
                          title={`Open in ${slicerLabel}`}
                          className={BUTTON_ICON}
                          onClick={() => openInSlicer(asset)}
                        >
                          <FileBox className="h-4 w-4" aria-hidden="true" />
                        </button>
                      )}
                      <button
                        type="button"
                        aria-label={`Download ${asset.name}`}
                        title="Download"
                        className={BUTTON_ICON}
                        disabled={downloadingId === asset.id}
                        onClick={() => void downloadOne(asset)}
                      >
                        <Download className="h-4 w-4" aria-hidden="true" />
                      </button>
                      {canWrite && (
                        <>
                          <button
                            type="button"
                            aria-label={`Add supporting file to ${asset.name}`}
                            title="Add supporting file"
                            className={BUTTON_ICON}
                            disabled={supportBusyId === asset.id}
                            onClick={() => pickSupportingFile(asset)}
                          >
                            <Paperclip className="h-4 w-4" aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            aria-label={`Remove ${asset.name} from project`}
                            title="Remove from project"
                            className={BUTTON_ICON}
                            onClick={() => requestRemoveAsset(asset)}
                          >
                            <X className="h-4 w-4" aria-hidden="true" />
                          </button>
                        </>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
            {membersHasMore && (
              <div className="mt-3">
                <button
                  type="button"
                  className={BUTTON_SECONDARY}
                  disabled={membersLoadingMore}
                  onClick={() => void loadMoreMembers()}
                >
                  {membersLoadingMore ? "Loading…" : "Load more"}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      {confirm && (
        <ConfirmDialog
          title={confirm.title}
          body={confirm.body}
          confirmLabel={confirm.confirmLabel}
          danger={confirm.danger}
          busy={confirmBusy}
          onConfirm={() => void handleConfirm()}
          onCancel={() => setConfirm(null)}
        />
      )}

      {pickerOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="add-files-title"
          onKeyDown={handlePickerKeyDown}
        >
          <div className="flex max-h-full w-full max-w-2xl flex-col rounded-lg bg-panel-strong shadow-2xl">
            <div className="flex items-center justify-between gap-2 border-b border-panel px-4 py-3">
              <h2 id="add-files-title" className="truncate text-lg font-semibold">
                Add files to {project.name}
              </h2>
              <button
                type="button"
                aria-label="Close"
                className={BUTTON_ICON}
                disabled={pickerBusy}
                onClick={() => setPickerOpen(false)}
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>

            <form
              className="flex gap-2 border-b border-panel px-4 py-3"
              onSubmit={event => void searchPicker(event)}
            >
              <input
                type="search"
                aria-label="Search the library"
                placeholder="Search the library…"
                className={INPUT_BASE}
                value={pickerQuery}
                autoFocus
                onChange={event => setPickerQuery(event.target.value)}
              />
              <button type="submit" className={BUTTON_SECONDARY} disabled={pickerLoading}>
                <Search className="h-4 w-4" aria-hidden="true" />
                Search
              </button>
            </form>

            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
              {pickerLoading ? (
                <p className="py-4 text-sm text-muted">Loading…</p>
              ) : pickerItems.length === 0 ? (
                <p className="py-4 text-sm text-muted">No assets found.</p>
              ) : (
                <ul className="flex flex-col">
                  {pickerItems.map(asset => {
                    const inProject = memberIds.has(asset.id);
                    const checked = inProject || pickerSelected.includes(asset.id);
                    return (
                      <li key={asset.id}>
                        <label className="flex min-w-0 cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-panel-soft">
                          <input
                            type="checkbox"
                            className={`h-4 w-4 shrink-0 ${FOCUS_VISIBLE}`}
                            checked={checked}
                            disabled={inProject || pickerBusy}
                            aria-label={
                              inProject ? `${asset.name} (already in project)` : `Select ${asset.name}`
                            }
                            onChange={() => togglePickerId(asset.id)}
                          />
                          <span className="min-w-0 flex-1 truncate text-sm">{asset.name}</span>
                          <span className="shrink-0 text-xs text-muted">{typeLabelFor(asset)}</span>
                          {inProject && (
                            <span className="shrink-0 rounded-full border border-panel-strong px-2 py-0.5 text-[10px] font-medium text-muted">
                              In project
                            </span>
                          )}
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
              {!pickerLoading && pickerHasMore && (
                <div className="py-2">
                  <button
                    type="button"
                    className={BUTTON_SECONDARY}
                    disabled={pickerLoadingMore}
                    onClick={() => void loadMorePicker()}
                  >
                    {pickerLoadingMore ? "Loading…" : "Load more"}
                  </button>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-panel px-4 py-3">
              <button
                type="button"
                className={BUTTON_SECONDARY}
                disabled={pickerBusy}
                onClick={() => setPickerOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={BUTTON_PRIMARY}
                disabled={pickerSelected.length === 0 || pickerBusy}
                onClick={() => void addSelectedToProject()}
              >
                {pickerBusy
                  ? "Adding…"
                  : `Add ${pickerSelected.length} ${pickerSelected.length === 1 ? "file" : "files"}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
