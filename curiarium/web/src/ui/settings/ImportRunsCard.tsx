import type { ImportRunSummary } from "../../lib/api";
import {
  formatImportRunDuration,
  formatImportRunTime,
  importRunCountsLine,
  importRunModeLabel,
  importRunReason,
  importRunRejectedNote,
  importRunStatusLabel,
  isImportRunFailure,
} from "../../lib/importRuns";
import type { ImportRunsState } from "./useImportRuns";

const MAX_VISIBLE_ERRORS = 5;

function timingLine(run: ImportRunSummary): string {
  const started = formatImportRunTime(run.started_at);
  const finished = formatImportRunTime(run.finished_at);
  const duration = formatImportRunDuration(run.started_at, run.finished_at);
  const parts: string[] = [];
  if (started) parts.push(`Started ${started}`);
  if (finished) parts.push(`finished ${finished}`);
  if (duration) parts.push(duration);
  return parts.join(" · ");
}

function statusToneClass(run: ImportRunSummary): string {
  if (isImportRunFailure(run)) return "text-red-400";
  if (run.status === "skipped") return "text-muted";
  return "opacity-80";
}

function reasonToneClass(run: ImportRunSummary): string {
  if (isImportRunFailure(run)) return "text-red-400";
  return "text-muted";
}

type IdleLine = { text: string; className: string };

function idleLine(loading: boolean, error: string | null): IdleLine {
  if (loading) return { text: "Loading import runs...", className: "text-sm" };
  if (error) return { text: error, className: "text-sm text-red-400" };
  return { text: "No mount import has run yet.", className: "text-sm" };
}

function ErrorList({ errors }: { errors: string[] }) {
  const visible = errors.slice(0, MAX_VISIBLE_ERRORS);
  const hidden = errors.length - visible.length;
  if (!visible.length) return null;

  return (
    <div className="rounded-md border border-dashed border-panel-strong p-3 font-mono text-[11px] break-all">
      {visible.map((message, index) => (
        <div key={index}>{message}</div>
      ))}
      {hidden > 0 && <div className="opacity-70">+{hidden} more</div>}
    </div>
  );
}

function RunningRun({ run }: { run: ImportRunSummary }) {
  const rejectedNote = importRunRejectedNote(run);

  return (
    <div className="flex flex-col gap-1">
      <p className="text-sm font-medium">Import in progress</p>
      <p className="text-xs opacity-80">{importRunModeLabel(run)}</p>
      <p className="text-xs opacity-80">{timingLine(run)}</p>
      <p className="text-xs opacity-80">{importRunCountsLine(run)}</p>
      {rejectedNote && <p className="text-xs opacity-80">{rejectedNote}</p>}
    </div>
  );
}

function FinishedRun({ run }: { run: ImportRunSummary & { errors: string[] } }) {
  const rejectedNote = importRunRejectedNote(run);
  const reason = importRunReason(run);

  return (
    <div className="flex flex-col gap-1">
      <p className={`text-sm font-medium ${statusToneClass(run)}`}>{importRunStatusLabel(run)}</p>
      <p className="text-xs opacity-80">{importRunModeLabel(run)}</p>
      <p className="text-xs opacity-80">{timingLine(run)}</p>
      <p className="text-xs opacity-80">{importRunCountsLine(run)}</p>
      {rejectedNote && <p className="text-xs opacity-80">{rejectedNote}</p>}
      {reason && <p className={`text-xs ${reasonToneClass(run)}`}>{reason}</p>}
      <ErrorList errors={run.errors} />
    </div>
  );
}

export default function ImportRunsCard({ state }: { state: ImportRunsState }) {
  const { run, loading, error } = state;
  const idle = idleLine(loading, error);

  return (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div>
        <div className="text-lg font-semibold">Mount import runs</div>
        <p className="text-sm opacity-70">
          The latest run reported by the API. While a run is walking the mount its counters
          update live. Only mounted imports are recorded; storage rescans stay in the log.
        </p>
      </div>
      {run && run.status === "running" && <RunningRun run={run} />}
      {run && run.status !== "running" && <FinishedRun run={run} />}
      {!run && (
        <div className="flex flex-col gap-1">
          <p className={idle.className}>{idle.text}</p>
          <p className="text-xs opacity-70">
            A run is recorded at startup whenever a mount is configured and enabled.
          </p>
        </div>
      )}
    </div>
  );
}
