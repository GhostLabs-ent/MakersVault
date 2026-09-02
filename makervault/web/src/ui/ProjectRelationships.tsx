import React from "react";
import { Link2, Plus, Search, Trash2, X } from "lucide-react";

import {
  Asset,
  ProjectRelationship,
  RelationshipKind,
  UnauthorizedError,
  createProjectRelationship,
  deleteProjectRelationship,
  listProjectItems,
  listProjectRelationships,
} from "../lib/api";
import { relationshipKindOptions } from "../lib/relationships";
import { useVaultCapabilities } from "../lib/CapabilityContext";


type Props = {
  projectId: string;
  membershipVersion: number;
  onUnauthorized?: () => void;
};

type EndpointPickerProps = {
  label: string;
  projectId: string;
  selected: Asset | null;
  onSelect: (asset: Asset | null) => void;
  onUnauthorized?: () => void;
};

function EndpointPicker({
  label,
  projectId,
  selected,
  onSelect,
  onUnauthorized,
}: EndpointPickerProps) {
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<Asset[]>([]);
  const [loading, setLoading] = React.useState(false);

  const search = async () => {
    setLoading(true);
    try {
      const page = await listProjectItems(projectId, {
        q: query.trim() || undefined,
        limit: 12,
        offset: 0,
      });
      setResults(page.items);
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else alert(error instanceof Error ? error.message : "Unable to search Project items");
    } finally {
      setLoading(false);
    }
  };

  if (selected) {
    return (
      <div className="rounded-lg border border-accent-soft bg-accent-soft p-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
        <div className="mt-1 flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium">{selected.name}</span>
          <button type="button" onClick={() => onSelect(null)} aria-label={`Clear ${label}`}><X className="h-4 w-4" /></button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <label className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</label>
      <div className="flex gap-2">
        <input
          className="min-w-0 flex-1 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm"
          value={query}
          onChange={event => setQuery(event.target.value)}
          onKeyDown={event => { if (event.key === "Enter") void search(); }}
          placeholder="Search Project items"
        />
        <button type="button" className="rounded-md border border-panel-strong px-3" onClick={() => void search()} disabled={loading} aria-label={`Search ${label}`}><Search className="h-4 w-4" /></button>
      </div>
      {!!results.length && (
        <div className="max-h-40 space-y-1 overflow-auto rounded-md border border-panel p-1">
          {results.map(asset => (
            <button key={asset.id} type="button" className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-panel-soft" onClick={() => { onSelect(asset); setResults([]); }}>{asset.name}</button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ProjectRelationships({ projectId, membershipVersion, onUnauthorized }: Props) {
  const capabilities = useVaultCapabilities();
  const [relationships, setRelationships] = React.useState<ProjectRelationship[]>([]);
  const [offset, setOffset] = React.useState(0);
  const [hasMore, setHasMore] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(false);
  const [source, setSource] = React.useState<Asset | null>(null);
  const [target, setTarget] = React.useState<Asset | null>(null);
  const [kind, setKind] = React.useState<RelationshipKind>("derived_from");
  const [saving, setSaving] = React.useState(false);

  const handleError = React.useCallback((error: unknown, fallback: string) => {
    if (error instanceof UnauthorizedError) onUnauthorized?.();
    else alert(error instanceof Error ? error.message : fallback);
  }, [onUnauthorized]);

  const load = React.useCallback(async (reset: boolean) => {
    setLoading(true);
    const pageOffset = reset ? 0 : offset;
    try {
      const page = await listProjectRelationships(projectId, { limit: 50, offset: pageOffset });
      setRelationships(current => reset ? page.items : [...current, ...page.items]);
      setOffset(page.nextOffset ?? pageOffset + page.items.length);
      setHasMore(page.hasMore);
    } catch (error) {
      handleError(error, "Unable to load Project relationships");
    } finally {
      setLoading(false);
    }
  }, [handleError, offset, projectId]);

  React.useEffect(() => {
    setRelationships([]);
    setOffset(0);
    void load(true);
  }, [projectId, membershipVersion]);

  const create = async () => {
    if (!source || !target || source.id === target.id) return;
    setSaving(true);
    try {
      await createProjectRelationship(projectId, {
        source_asset_id: source.id,
        target_asset_id: target.id,
        kind,
      });
      setSource(null);
      setTarget(null);
      setEditing(false);
      await load(true);
    } catch (error) {
      handleError(error, "Unable to create relationship");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (relationship: ProjectRelationship) => {
    if (!confirm(`Remove the relationship between ${relationship.source_name} and ${relationship.target_name}? No Project items or files will be deleted.`)) return;
    try {
      await deleteProjectRelationship(projectId, relationship.id);
      await load(true);
    } catch (error) {
      handleError(error, "Unable to delete relationship");
    }
  };

  return (
    <section className="rounded-xl border border-panel bg-panel-soft p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="flex items-center gap-2 font-semibold"><Link2 className="h-4 w-4" /> Relationships</h2><p className="mt-1 text-xs text-muted">Useful links between items in this Project. No files are copied.</p></div>
        {capabilities.manageContent && <button type="button" className="inline-flex items-center gap-2 rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={() => setEditing(value => !value)}><Plus className="h-4 w-4" /> Add relationship</button>}
      </div>

      {capabilities.manageContent && editing && (
        <div className="mt-4 grid gap-4 rounded-lg border border-panel bg-panel p-4 md:grid-cols-2">
          <EndpointPicker label="First Project item" projectId={projectId} selected={source} onSelect={setSource} onUnauthorized={onUnauthorized} />
          <EndpointPicker label="Second Project item" projectId={projectId} selected={target} onSelect={setTarget} onUnauthorized={onUnauthorized} />
          <label className="flex flex-col gap-1 text-sm md:col-span-2"><span>Relationship</span><select className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={kind} onChange={event => setKind(event.target.value as RelationshipKind)}>{relationshipKindOptions.map(option => <option key={option.kind} value={option.kind}>{option.label}</option>)}</select><small className="text-muted">{relationshipKindOptions.find(option => option.kind === kind)?.help}</small></label>
          <div className="flex gap-2 md:col-span-2"><button type="button" className="rounded-md bg-accent px-3 py-2 text-sm font-medium disabled:opacity-50" disabled={saving || !source || !target || source.id === target.id} onClick={() => void create()}>{saving ? "Saving…" : "Create relationship"}</button><button type="button" className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={() => { setEditing(false); setSource(null); setTarget(null); }}>Cancel</button></div>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {relationships.map(relationship => (
          <div key={relationship.id} className="flex items-center justify-between gap-3 rounded-lg border border-panel bg-panel p-3">
            <div className="min-w-0 text-sm"><p><strong>{relationship.source_name}</strong> <span className="text-muted">{relationship.forward_label.toLocaleLowerCase()}</span> <strong>{relationship.target_name}</strong></p><p className="mt-1 text-xs text-muted">Inverse: {relationship.target_name} — {relationship.inverse_label} — {relationship.source_name}</p></div>
            {capabilities.manageContent && <button type="button" className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-red-600 hover:bg-red-500/10" onClick={() => void remove(relationship)} aria-label="Remove relationship"><Trash2 className="h-4 w-4" /></button>}
          </div>
        ))}
        {!relationships.length && !loading && <p className="rounded-lg border border-dashed border-panel-strong p-5 text-center text-sm text-muted">No relationships yet. Add one when it makes the Project easier to understand.</p>}
        {loading && !relationships.length && <p className="p-4 text-center text-sm text-muted">Loading relationships…</p>}
        {hasMore && <div className="text-center"><button type="button" className="rounded-md border border-panel-strong px-3 py-2 text-sm" disabled={loading} onClick={() => void load(false)}>{loading ? "Loading…" : "Load more relationships"}</button></div>}
      </div>
    </section>
  );
}
