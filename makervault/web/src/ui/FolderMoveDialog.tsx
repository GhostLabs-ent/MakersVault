import React, { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { canMoveToFolder, filterFolderDestinations, type FolderDestination } from "../lib/folderMove";

type Props = {
  name: string;
  currentFolderId?: string | null;
  currentFolderName: string;
  options: FolderDestination[];
  onConfirm: (destination: string | null) => Promise<void>;
  onClose: () => void;
};

/** Mounted once, only while a card's explicit move action is open. */
export default function FolderMoveDialog({ name, currentFolderId, currentFolderName, options, onConfirm, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const destinations = useRef<HTMLSelectElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  const alive = useRef(false);
  const inFlight = useRef(false);
  const [query, setQuery] = useState("");
  const [destination, setDestination] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const titleId = useId();
  const descriptionId = useId();
  const results = useMemo(() => filterFolderDestinations(options, query), [options, query]);
  const canConfirm = canMoveToFolder(destination, currentFolderId, results);

  useLayoutEffect(() => {
    alive.current = true;
    const element = dialog.current!;
    const previousFocus = document.activeElement;
    element.showModal();
    search.current?.focus();
    return () => {
      alive.current = false;
      element.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (inFlight.current || !canConfirm) return;
    inFlight.current = true;
    setBusy(true);
    dialog.current?.focus(); // Do not leave focus on a control about to become disabled.
    setError("");
    try {
      await onConfirm(destination || null);
    } catch (error) {
      if (alive.current) setError(error instanceof Error ? error.message : "Folder update failed. Please try again.");
    } finally {
      if (alive.current) { inFlight.current = false; setBusy(false); }
    }
  };

  return createPortal(
    <dialog ref={dialog} tabIndex={-1} aria-labelledby={titleId} aria-describedby={descriptionId}
      className="m-auto w-[calc(100%_-_2rem)] max-w-xl max-h-[90vh] overflow-y-auto rounded-xl border border-panel-strong bg-panel-strong p-5 text-foreground shadow-xl backdrop:bg-black/60"
      onKeyDown={event => {
        if (event.key !== "Tab" || event.altKey || event.ctrlKey || event.metaKey) return;
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("input:not(:disabled), select:not(:disabled), button:not(:disabled)"))
          .filter(element => element.getClientRects().length > 0);
        const first = controls[0], last = controls[controls.length - 1];
        if (!first) { event.preventDefault(); event.currentTarget.focus(); }
        else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }}
      onCancel={event => { event.preventDefault(); if (!inFlight.current) onClose(); }}
      onDragEnter={event => { event.preventDefault(); event.stopPropagation(); }}
      onDragOver={event => { event.preventDefault(); event.stopPropagation(); }}
      onDrop={event => { event.preventDefault(); event.stopPropagation(); }}
      onClick={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}>
      <form onSubmit={submit} className="flex flex-col gap-4" aria-busy={busy}>
        <div>
          <h2 id={titleId} className="text-lg font-semibold">Move to folder</h2>
          <p id={descriptionId} className="mt-1 break-words text-sm text-muted">
            {name}<br />Current folder: {currentFolderName}
          </p>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          Search destinations
          <input ref={search} value={query} disabled={busy} type="search"
            className="rounded-md border border-panel-strong bg-panel-soft px-3 py-2"
            onChange={event => { setQuery(event.target.value); setDestination(null); setError(""); }}
            onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); destinations.current?.focus(); } }} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Destination folder
          <select ref={destinations} size={8} value={destination ?? "__choose__"} disabled={busy || !results.length}
            className="w-full rounded-md border border-panel-strong bg-panel-soft p-2 text-sm"
            onChange={event => { setDestination(event.target.value); setError(""); }}
            onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); confirm.current?.focus(); } }}>
            <option value="__choose__" disabled>Choose a destination</option>
            {results.map(option => <option key={option.id || "unassigned"} value={option.id || ""}>{option.name}</option>)}
          </select>
        </label>
        <p className="text-xs text-muted" role="status">{results.length ? `${results.length} destinations. Nothing moves until you confirm.` : "No matching folders."}</p>
        {error && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="rounded-md border border-panel-strong px-3 py-2 disabled:opacity-50" disabled={busy} onClick={onClose}>Cancel</button>
          <button ref={confirm} type="submit" className="rounded-md bg-accent px-3 py-2 font-medium disabled:opacity-50" disabled={busy || !canConfirm}>
            {busy ? "Moving…" : "Move model"}
          </button>
        </div>
      </form>
    </dialog>, document.body,
  );
}
