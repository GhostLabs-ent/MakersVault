import React from "react";

import {
  type Asset,
  type AssetMachineContext,
  type Machine,
  UnauthorizedError,
  addAssetMachine,
  getAssetMachineContext,
  listMachines,
  removeAssetMachine,
  setAssetPreparedMachine,
} from "../lib/api";
import {
  DESCRIPTIVE_CONTEXT_NOTICE,
  activePreparedTargets,
  machineCategoryLabel,
} from "../lib/machineContext";


type Props = {
  asset: Asset;
  onAssetChanged?: (asset: Asset) => void;
  onContextChanged?: () => void;
  onUnauthorized?: () => void;
};

export default function MachineContextPanel({
  asset,
  onAssetChanged,
  onContextChanged,
  onUnauthorized,
}: Props) {
  const [context, setContext] = React.useState<AssetMachineContext | null>(null);
  const [machines, setMachines] = React.useState<Machine[]>([]);
  const [addId, setAddId] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);

  const handleError = React.useCallback((error: unknown, fallback: string) => {
    if (error instanceof UnauthorizedError) {
      onUnauthorized?.();
      return;
    }
    setMessage(error instanceof Error ? error.message : fallback);
  }, [onUnauthorized]);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setMessage(null);
    Promise.all([
      getAssetMachineContext(asset.id),
      listMachines({ include_archived: true, limit: 200 }),
    ]).then(([nextContext, result]) => {
      if (cancelled) return;
      setContext(nextContext);
      setMachines(result.items);
    }).catch(error => {
      if (!cancelled) handleError(error, "Failed to load Machine context");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [asset.id, handleError]);

  const mutate = async (
    operation: () => Promise<AssetMachineContext>,
    success: string,
  ) => {
    setBusy(true);
    setMessage(null);
    try {
      const next = await operation();
      setContext(next);
      setMessage(success);
      onContextChanged?.();
      return next;
    } catch (error) {
      handleError(error, "Failed to update Machine context");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const associatedIds = new Set(context?.associations.map(row => row.machine.id) || []);
  const availableAssociations = machines.filter(machine => (
    !machine.archived_at && !associatedIds.has(machine.id)
  ));
  const preparedTargets = activePreparedTargets(machines);
  const currentPrepared = context?.prepared_machine || null;

  const addAssociation = async () => {
    if (!addId) return;
    const next = await mutate(
      () => addAssetMachine(asset.id, addId),
      "Associated Machine added.",
    );
    if (next) setAddId("");
  };

  const changePreparedMachine = async (machineId: string) => {
    const next = await mutate(
      () => setAssetPreparedMachine(asset.id, machineId || null),
      machineId ? "Prepared Machine updated." : "Prepared Machine cleared.",
    );
    if (next) {
      onAssetChanged?.({
        ...asset,
        prepared_machine_id: next.prepared_machine?.id || null,
      });
    }
  };

  return (
    <section className="rounded-lg border border-panel bg-panel-soft p-4">
      <div>
        <h3 className="font-semibold">Machine context</h3>
        <p className="mt-1 text-sm font-medium">{DESCRIPTIVE_CONTEXT_NOTICE}</p>
        {asset.prepared_print?.printer && (
          <p className="mt-2 text-xs text-muted">
            Supplied printer text: <span className="font-medium text-foreground">{asset.prepared_print.printer}</span>
          </p>
        )}
      </div>

      {loading ? (
        <p className="mt-4 text-sm text-muted">Loading Machine context…</p>
      ) : context ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <h4 className="text-sm font-semibold">Associated Machine</h4>
            <div className="mt-2 space-y-2">
              {context.associations.map(row => (
                <div key={row.machine.id} className="flex items-center justify-between gap-2 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm">
                  <span>
                    {row.machine.name}
                    <span className="ml-2 text-xs text-muted">{machineCategoryLabel(row.machine.category)}</span>
                    {row.machine.archived_at && <span className="ml-2 text-xs text-amber-700 dark:text-amber-300">Archived</span>}
                  </span>
                  <button
                    type="button"
                    className="text-xs underline disabled:opacity-50"
                    disabled={busy}
                    onClick={() => void mutate(
                      () => removeAssetMachine(asset.id, row.machine.id),
                      "Machine association removed.",
                    )}
                  >
                    Remove
                  </button>
                </div>
              ))}
              {!context.associations.length && <p className="text-xs text-muted">No associated Machines.</p>}
            </div>
            <div className="mt-3 flex gap-2">
              <select
                className="min-w-0 flex-1 rounded-md border border-panel-strong bg-panel px-2 py-2 text-sm"
                value={addId}
                disabled={busy || !availableAssociations.length}
                onChange={event => setAddId(event.target.value)}
              >
                <option value="">Select a Machine…</option>
                {availableAssociations.map(machine => (
                  <option key={machine.id} value={machine.id}>{machine.name} · {machineCategoryLabel(machine.category)}</option>
                ))}
              </select>
              <button type="button" className="rounded-md border border-panel-strong px-3 py-2 text-sm disabled:opacity-50" disabled={busy || !addId} onClick={() => void addAssociation()}>Add</button>
            </div>
          </div>

          <div>
            <label className="flex flex-col gap-2 text-sm font-semibold">
              <span>Prepared for Machine</span>
              <select
                className="rounded-md border border-panel-strong bg-panel px-2 py-2 font-normal disabled:opacity-60"
                value={currentPrepared?.id || ""}
                disabled={busy || !asset.prepared_print}
                onChange={event => void changePreparedMachine(event.target.value)}
              >
                <option value="">No exact Machine target</option>
                {currentPrepared?.archived_at && !preparedTargets.some(machine => machine.id === currentPrepared.id) && (
                  <option value={currentPrepared.id} disabled>{currentPrepared.name} (Archived)</option>
                )}
                {preparedTargets.map(machine => <option key={machine.id} value={machine.id}>{machine.name}</option>)}
              </select>
            </label>
            {!asset.prepared_print && (
              <p className="mt-2 text-xs text-muted">Attach prepared-print metadata before selecting an exact Machine target.</p>
            )}
            {currentPrepared && (
              <p className="mt-2 text-xs text-muted">
                Exact target: {currentPrepared.name}{currentPrepared.archived_at ? " (Archived)" : ""}
              </p>
            )}
          </div>
        </div>
      ) : null}
      {message && <p className="mt-3 text-sm" aria-live="polite">{message}</p>}
    </section>
  );
}
