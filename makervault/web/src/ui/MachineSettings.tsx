import React from "react";

import {
  Machine,
  MachineCategory,
  MachineInput,
  UnauthorizedError,
  archiveMachine,
  createMachine,
  listMachines,
  permanentlyDeleteMachine,
  restoreMachine,
  updateMachine,
} from "../lib/api";
import {
  DESCRIPTIVE_CONTEXT_NOTICE,
  MACHINE_CATEGORIES,
  MACHINE_PERMANENT_CONFIRMATION,
  machineCategoryLabel,
} from "../lib/machineContext";
import { useVaultCapabilities } from "../lib/CapabilityContext";


type Props = {
  onBack: () => void;
  onAssetsChanged?: () => void;
  onUnauthorized?: () => void;
};

const EMPTY_FORM: MachineInput = {
  name: "",
  category: "fdm_printer",
  manufacturer: "",
  model: "",
  location: "",
  notes: "",
};

function formFor(machine: Machine): MachineInput {
  return {
    name: machine.name,
    category: machine.category,
    manufacturer: machine.manufacturer || "",
    model: machine.model || "",
    location: machine.location || "",
    notes: machine.notes || "",
  };
}

function cleanForm(form: MachineInput): MachineInput {
  return {
    name: form.name.trim(),
    category: form.category,
    manufacturer: form.manufacturer?.trim() || null,
    model: form.model?.trim() || null,
    location: form.location?.trim() || null,
    notes: form.notes?.trim() || null,
  };
}

export default function MachineSettings({
  onBack,
  onAssetsChanged,
  onUnauthorized,
}: Props) {
  const capabilities = useVaultCapabilities();
  const [machines, setMachines] = React.useState<Machine[]>([]);
  const [query, setQuery] = React.useState("");
  const [category, setCategory] = React.useState<MachineCategory | "">("");
  const [includeArchived, setIncludeArchived] = React.useState(capabilities.manageContent);
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [form, setForm] = React.useState<MachineInput>({ ...EMPTY_FORM });
  const [message, setMessage] = React.useState<string | null>(null);

  const handleError = React.useCallback((error: unknown, fallback: string) => {
    if (error instanceof UnauthorizedError) {
      onUnauthorized?.();
      return;
    }
    setMessage(error instanceof Error ? error.message : fallback);
  }, [onUnauthorized]);

  const load = React.useCallback(async () => {
    setLoading(true);
    setMessage(null);
    try {
      const result = await listMachines({
        q: query.trim() || undefined,
        category: category || undefined,
        include_archived: includeArchived,
        limit: 200,
      });
      setMachines(result.items);
      if (result.hasMore) {
        setMessage("Showing the first 200 matching Machines. Narrow the search to continue.");
      }
    } catch (error) {
      handleError(error, "Failed to load Machines");
    } finally {
      setLoading(false);
    }
  }, [category, handleError, includeArchived, query]);

  React.useEffect(() => {
    void load();
  }, [includeArchived, category]);

  const resetForm = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
  };

  const save = async () => {
    const payload = cleanForm(form);
    if (!payload.name) return;
    setSaving(true);
    setMessage(null);
    try {
      if (editingId) {
        await updateMachine(editingId, payload);
        setMessage("Machine details saved.");
      } else {
        await createMachine(payload);
        setMessage("Machine created.");
      }
      resetForm();
      await load();
    } catch (error) {
      handleError(error, "Failed to save Machine");
    } finally {
      setSaving(false);
    }
  };

  const archive = async (machine: Machine) => {
    if (!window.confirm(
      `Archive "${machine.name}"? Existing descriptive references remain visible, but no new links can be added.`,
    )) return;
    setBusyId(machine.id);
    try {
      await archiveMachine(machine.id);
      setMessage(`Archived ${machine.name}.`);
      await load();
    } catch (error) {
      handleError(error, "Failed to archive Machine");
    } finally {
      setBusyId(null);
    }
  };

  const restore = async (machine: Machine) => {
    setBusyId(machine.id);
    try {
      await restoreMachine(machine.id);
      setMessage(`Restored ${machine.name}.`);
      await load();
    } catch (error) {
      handleError(error, "Failed to restore Machine");
    } finally {
      setBusyId(null);
    }
  };

  const permanentlyRemove = async (machine: Machine) => {
    const confirmation = window.prompt(
      `Permanently delete "${machine.name}"? Associations will be removed and exact prepared references cleared. Artifacts, revisions, prepared metadata, payloads, and stored bytes remain.\n\nType ${MACHINE_PERMANENT_CONFIRMATION} to continue.`,
    );
    if (confirmation !== MACHINE_PERMANENT_CONFIRMATION) return;
    setBusyId(machine.id);
    try {
      const result = await permanentlyDeleteMachine(machine.id, confirmation);
      setMessage(
        `Deleted ${result.name}: ${result.associations_deleted} association(s) removed and ${result.prepared_references_cleared} prepared reference(s) cleared.`,
      );
      if (editingId === machine.id) resetForm();
      onAssetsChanged?.();
      await load();
    } catch (error) {
      handleError(error, "Failed to permanently delete Machine");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Machines</h2>
          <p className="text-sm opacity-70">Descriptive workshop profiles and Artifact context.</p>
        </div>
        <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={onBack}>Back</button>
      </div>

      <div className="rounded-lg border border-panel bg-panel-soft p-4">
        <p className="text-sm font-semibold">{DESCRIPTIVE_CONTEXT_NOTICE}</p>
        <p className="mt-1 text-xs text-muted">
          Profiles contain no address, credential, device status, queue, telemetry, or control command.
        </p>
      </div>

      {capabilities.manageContent && <section className="rounded-lg border border-panel bg-panel-soft p-4">
        <h3 className="font-semibold">{editingId ? "Edit Machine" : "Add Machine"}</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm"><span>Name</span><input className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.name} maxLength={200} onChange={event => setForm(current => ({ ...current, name: event.target.value }))} /></label>
          <label className="flex flex-col gap-1 text-sm"><span>Category</span><select className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.category} onChange={event => setForm(current => ({ ...current, category: event.target.value as MachineCategory }))}>{MACHINE_CATEGORIES.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
          <label className="flex flex-col gap-1 text-sm"><span>Manufacturer</span><input className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.manufacturer || ""} maxLength={500} onChange={event => setForm(current => ({ ...current, manufacturer: event.target.value }))} /></label>
          <label className="flex flex-col gap-1 text-sm"><span>Model</span><input className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.model || ""} maxLength={500} onChange={event => setForm(current => ({ ...current, model: event.target.value }))} /></label>
          <label className="flex flex-col gap-1 text-sm"><span>Location</span><input className="rounded-md border border-panel-strong bg-panel px-3 py-2" value={form.location || ""} maxLength={500} onChange={event => setForm(current => ({ ...current, location: event.target.value }))} /></label>
          <label className="flex flex-col gap-1 text-sm md:col-span-2"><span>Notes</span><textarea className="rounded-md border border-panel-strong bg-panel px-3 py-2" rows={3} value={form.notes || ""} maxLength={10000} onChange={event => setForm(current => ({ ...current, notes: event.target.value }))} /></label>
        </div>
        <div className="mt-3 flex gap-2">
          <button className="rounded-md bg-accent px-3 py-2 text-sm disabled:opacity-50" disabled={saving || !form.name.trim()} onClick={() => void save()}>{saving ? "Saving…" : editingId ? "Save changes" : "Add Machine"}</button>
          {editingId && <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={resetForm}>Cancel</button>}
        </div>
      </section>}

      <section className="rounded-lg border border-panel bg-panel-soft p-4">
        <div className="flex flex-wrap items-center gap-2">
          <input className="min-w-64 flex-1 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" placeholder="Search Machines" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter") void load(); }} />
          <select className="rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" value={category} onChange={event => setCategory(event.target.value as MachineCategory | "")}><option value="">All categories</option>{MACHINE_CATEGORIES.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select>
          {capabilities.manageContent && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeArchived} onChange={event => setIncludeArchived(event.target.checked)} />Include archived</label>}
          <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" disabled={loading} onClick={() => void load()}>{loading ? "Loading…" : "Search"}</button>
        </div>
        <div className="mt-4 space-y-2">
          {machines.map(machine => (
            <article key={machine.id} className="rounded-md border border-panel-strong bg-panel p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2"><h4 className="font-semibold">{machine.name}</h4><span className="rounded bg-panel-soft px-2 py-0.5 text-xs">{machineCategoryLabel(machine.category)}</span>{machine.archived_at && <span className="rounded bg-amber-500/15 px-2 py-0.5 text-xs">Archived</span>}</div>
                  <p className="mt-1 text-xs text-muted">{[machine.manufacturer, machine.model, machine.location].filter(Boolean).join(" · ") || "No additional details"}</p>
                  {machine.notes && <p className="mt-2 whitespace-pre-wrap text-sm">{machine.notes}</p>}
                </div>
                {capabilities.manageContent && <div className="flex flex-wrap gap-2">
                  {!machine.archived_at ? <><button className="rounded-md border border-panel-strong px-2 py-1 text-xs" disabled={busyId === machine.id} onClick={() => { setEditingId(machine.id); setForm(formFor(machine)); }}>Edit</button><button className="rounded-md border border-panel-strong px-2 py-1 text-xs" disabled={busyId === machine.id} onClick={() => void archive(machine)}>Archive</button></> : <><button className="rounded-md border border-panel-strong px-2 py-1 text-xs" disabled={busyId === machine.id} onClick={() => void restore(machine)}>Restore</button>{capabilities.deletePermanently && <button className="rounded-md border border-red-500/50 px-2 py-1 text-xs text-red-700 dark:text-red-300" disabled={busyId === machine.id} onClick={() => void permanentlyRemove(machine)}>Permanently delete</button>}</>}
                </div>}
              </div>
            </article>
          ))}
          {!loading && !machines.length && <p className="py-6 text-center text-sm text-muted">No Machines match this view.</p>}
        </div>
        {message && <p className="mt-3 text-sm" aria-live="polite">{message}</p>}
      </section>
    </div>
  );
}
