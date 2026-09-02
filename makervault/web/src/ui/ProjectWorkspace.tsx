import React from "react";
import { Download, ExternalLink, Pencil, Plus, Search, X } from "lucide-react";

import {
  Asset,
  Project,
  UnauthorizedError,
  addProjectItem,
  downloadProjectExport,
  getProject,
  listProjectCandidates,
  updateProject,
} from "../lib/api";
import { responseDownloadFilename } from "../lib/projectLifecycle";
import {
  EngravingSettings,
  PreviewSettings,
  ResolvedTheme,
  SlicerSettings,
} from "../lib/settings";
import AssetGrid from "./AssetGrid";
import ProjectRelationships from "./ProjectRelationships";
import TagBadge from "./TagBadge";
import TagInput from "./TagInput";
import { useVaultCapabilities } from "../lib/CapabilityContext";

type Props = {
  projectId: string;
  onProjectChanged: () => void;
  onUnauthorized?: () => void;
  onSelectFolder: (id: string | null) => void;
  slicerSettings?: SlicerSettings;
  engravingSettings?: EngravingSettings;
  previewSettings?: PreviewSettings;
  theme: ResolvedTheme;
};

const CANDIDATE_PAGE_SIZE = 40;

export default function ProjectWorkspace({
  projectId,
  onProjectChanged,
  onUnauthorized,
  onSelectFolder,
  slicerSettings,
  engravingSettings,
  previewSettings,
  theme,
}: Props) {
  const capabilities = useVaultCapabilities();
  const [project, setProject] = React.useState<Project | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [form, setForm] = React.useState({
    name: "",
    notes: "",
    creator: "",
    source_url: "",
    license: "",
    tags: [] as string[],
  });
  const [showCandidates, setShowCandidates] = React.useState(false);
  const [candidateQuery, setCandidateQuery] = React.useState("");
  const [candidates, setCandidates] = React.useState<Asset[]>([]);
  const [candidateOffset, setCandidateOffset] = React.useState(0);
  const [candidateHasMore, setCandidateHasMore] = React.useState(false);
  const [candidateLoading, setCandidateLoading] = React.useState(false);
  const [addingId, setAddingId] = React.useState<string | null>(null);
  const [membershipVersion, setMembershipVersion] = React.useState(0);
  const [exporting, setExporting] = React.useState(false);

  const handleError = React.useCallback((error: unknown, fallback: string) => {
    if (error instanceof UnauthorizedError) {
      onUnauthorized?.();
      return;
    }
    console.error(error);
    alert(error instanceof Error ? error.message : fallback);
  }, [onUnauthorized]);

  const applyProject = React.useCallback((value: Project) => {
    setProject(value);
    setForm({
      name: value.name,
      notes: value.notes || "",
      creator: value.creator || "",
      source_url: value.source_url || "",
      license: value.license || "",
      tags: value.tags || [],
    });
  }, []);

  const refreshProject = React.useCallback(async () => {
    try {
      applyProject(await getProject(projectId));
      onProjectChanged();
    } catch (error) {
      handleError(error, "Unable to load Project");
    } finally {
      setLoading(false);
    }
  }, [applyProject, handleError, onProjectChanged, projectId]);

  React.useEffect(() => {
    setLoading(true);
    setEditing(false);
    setShowCandidates(false);
    void refreshProject();
  }, [projectId]);

  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const updated = await updateProject(projectId, {
        name: form.name.trim(),
        notes: form.notes.trim() || null,
        creator: form.creator.trim() || null,
        source_url: form.source_url.trim() || null,
        license: form.license.trim() || null,
        tags: form.tags,
      });
      applyProject(updated);
      setEditing(false);
      onProjectChanged();
    } catch (error) {
      handleError(error, "Unable to update Project");
    } finally {
      setSaving(false);
    }
  };

  const loadCandidates = async (reset: boolean, query = candidateQuery) => {
    if (candidateLoading) return;
    setCandidateLoading(true);
    const offset = reset ? 0 : candidateOffset;
    try {
      const result = await listProjectCandidates(projectId, {
        q: query.trim() || undefined,
        limit: CANDIDATE_PAGE_SIZE,
        offset,
      });
      setCandidates(current => reset ? result.items : [...current, ...result.items]);
      setCandidateOffset(result.nextOffset ?? offset + result.items.length);
      setCandidateHasMore(result.hasMore);
    } catch (error) {
      handleError(error, "Unable to load available artifacts");
    } finally {
      setCandidateLoading(false);
    }
  };

  const openCandidates = () => {
    setShowCandidates(true);
    setCandidateQuery("");
    setCandidates([]);
    setCandidateOffset(0);
    setCandidateHasMore(false);
    queueMicrotask(() => void loadCandidates(true, ""));
  };

  const addCandidate = async (asset: Asset) => {
    setAddingId(asset.id);
    try {
      await addProjectItem(projectId, asset.id);
      setCandidates(current => current.filter(item => item.id !== asset.id));
      setMembershipVersion(value => value + 1);
      await refreshProject();
    } catch (error) {
      handleError(error, "Unable to add Project item");
    } finally {
      setAddingId(null);
    }
  };

  const membershipChanged = () => {
    setMembershipVersion(value => value + 1);
    void refreshProject();
  };

  const exportProject = async () => {
    setExporting(true);
    try {
      const response = await downloadProjectExport(projectId);
      const filename = responseDownloadFilename(
        response.headers.get("content-disposition"),
        `${project?.name || "makersvault"}-project.zip`,
      );
      const objectUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      handleError(error, "Unable to export Project");
    } finally {
      setExporting(false);
    }
  };

  if (loading && !project) {
    return <div className="rounded-xl border border-panel bg-panel-soft p-6 text-sm text-muted">Loading Project…</div>;
  }
  if (!project) return null;

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-panel bg-panel-soft p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Project</p>
            <h1 className="mt-1 text-2xl font-semibold">{project.name}</h1>
            <p className="mt-1 text-sm text-muted">
              {project.member_count} active Project item{project.member_count === 1 ? "" : "s"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-md border border-panel-strong px-3 py-2 text-sm disabled:opacity-50"
              disabled={exporting}
              onClick={() => void exportProject()}
            >
              <Download className="h-4 w-4" /> {exporting ? "Exporting…" : "Export Project"}
            </button>
            {capabilities.manageContent && <button
              type="button"
              className="inline-flex items-center gap-2 rounded-md bg-accent px-3 py-2 text-sm font-medium"
              onClick={openCandidates}
            >
              <Plus className="h-4 w-4" /> Add existing items
            </button>}
            {capabilities.manageContent && <button
              type="button"
              className="inline-flex items-center gap-2 rounded-md border border-panel-strong px-3 py-2 text-sm"
              onClick={() => setEditing(value => !value)}
            >
              {editing ? <X className="h-4 w-4" /> : <Pencil className="h-4 w-4" />}
              {editing ? "Cancel edit" : "Edit details"}
            </button>}
          </div>
        </div>

        {capabilities.manageContent && editing ? (
          <div className="mt-4 grid gap-3 border-t border-panel pt-4 md:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm"><span>Name</span><input className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.name} onChange={event => setForm(current => ({ ...current, name: event.target.value }))} /></label>
            <label className="flex flex-col gap-1 text-sm"><span>Creator</span><input className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.creator} onChange={event => setForm(current => ({ ...current, creator: event.target.value }))} /></label>
            <label className="flex flex-col gap-1 text-sm"><span>Source URL</span><input type="url" className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.source_url} onChange={event => setForm(current => ({ ...current, source_url: event.target.value }))} /></label>
            <label className="flex flex-col gap-1 text-sm"><span>License</span><input className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.license} onChange={event => setForm(current => ({ ...current, license: event.target.value }))} /></label>
            <label className="flex flex-col gap-1 text-sm md:col-span-2"><span>Notes</span><textarea rows={3} className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.notes} onChange={event => setForm(current => ({ ...current, notes: event.target.value }))} /></label>
            <div className="md:col-span-2"><TagInput value={form.tags} onChange={tags => setForm(current => ({ ...current, tags }))} placeholder="Add Project tags" /></div>
            <div className="flex gap-2 md:col-span-2">
              <button type="button" className="rounded-md bg-accent px-3 py-2 text-sm font-medium disabled:opacity-50" disabled={saving || !form.name.trim()} onClick={save}>{saving ? "Saving…" : "Save Project"}</button>
              <button type="button" className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={() => { applyProject(project); setEditing(false); }}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="mt-4 grid gap-3 border-t border-panel pt-4 text-sm md:grid-cols-2">
            {project.notes && <p className="whitespace-pre-wrap md:col-span-2">{project.notes}</p>}
            {project.creator && <p><span className="text-muted">Creator:</span> {project.creator}</p>}
            {project.license && <p><span className="text-muted">License:</span> {project.license}</p>}
            {project.source_url && <p className="md:col-span-2"><a className="inline-flex items-center gap-1 text-accent underline-offset-2 hover:underline" href={project.source_url} target="_blank" rel="noreferrer">Project source <ExternalLink className="h-3.5 w-3.5" /></a></p>}
            {!!project.tags.length && <div className="flex flex-wrap gap-1 md:col-span-2">{project.tags.map(tag => <TagBadge key={tag} tag={tag} />)}</div>}
            {!project.notes && !project.creator && !project.license && !project.source_url && !project.tags.length && <p className="text-muted md:col-span-2">Add provenance, license, notes, or tags when they are useful.</p>}
          </div>
        )}
      </section>

      <ProjectRelationships
        projectId={projectId}
        membershipVersion={membershipVersion}
        onUnauthorized={onUnauthorized}
      />

      <AssetGrid
        key={`${projectId}-${membershipVersion}`}
        projectId={projectId}
        projectName={project.name}
        onMembershipChanged={membershipChanged}
        onSelectFolder={onSelectFolder}
        onUnauthorized={onUnauthorized}
        slicerSettings={slicerSettings}
        engravingSettings={engravingSettings}
        previewSettings={previewSettings}
        theme={theme}
      />

      {capabilities.manageContent && showCandidates && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label="Add existing Project items">
          <section className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-panel-strong bg-panel shadow-xl">
            <header className="flex items-center justify-between gap-3 border-b border-panel p-4">
              <div><h2 className="font-semibold">Add existing Project items</h2><p className="text-xs text-muted">Artifacts stay in their current folders and keep one shared history.</p></div>
              <button type="button" className="grid h-9 w-9 place-items-center rounded-md border border-panel-strong" onClick={() => setShowCandidates(false)} aria-label="Close"><X className="h-4 w-4" /></button>
            </header>
            <div className="flex gap-2 border-b border-panel p-4">
              <label className="flex flex-1 items-center gap-2 rounded-md border border-panel-strong bg-panel-soft px-3"><Search className="h-4 w-4" /><input className="min-w-0 flex-1 bg-transparent py-2 outline-none" value={candidateQuery} onChange={event => setCandidateQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter") void loadCandidates(true); }} placeholder="Search the library" /></label>
              <button type="button" className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={() => void loadCandidates(true)} disabled={candidateLoading}>Search</button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {candidates.length ? <div className="space-y-2">{candidates.map(asset => (
                <div key={asset.id} className="flex items-center justify-between gap-3 rounded-lg border border-panel p-3">
                  <div className="min-w-0"><p className="truncate font-medium">{asset.name}</p><p className="truncate text-xs text-muted">{asset.filename}</p></div>
                  <button type="button" className="rounded-md bg-accent px-3 py-2 text-sm font-medium disabled:opacity-50" disabled={addingId === asset.id} onClick={() => void addCandidate(asset)}>{addingId === asset.id ? "Adding…" : "Add"}</button>
                </div>
              ))}</div> : !candidateLoading && <p className="py-8 text-center text-sm text-muted">No available artifacts match this search.</p>}
              {candidateHasMore && <div className="mt-4 text-center"><button type="button" className="rounded-md border border-panel-strong px-3 py-2 text-sm" disabled={candidateLoading} onClick={() => void loadCandidates(false)}>{candidateLoading ? "Loading…" : "Load more"}</button></div>}
              {candidateLoading && !candidates.length && <p className="py-8 text-center text-sm text-muted">Loading available artifacts…</p>}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
