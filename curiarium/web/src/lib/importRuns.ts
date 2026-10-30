import type { ImportRunSummary } from "./api";

/** Server-defined run outcomes; any other value renders as a neutral label. */
const FAILURE_STATUSES = new Set(["failed", "interrupted"]);
const REASON_STATUSES = new Set(["skipped", "failed", "interrupted"]);

export function importRunStatusLabel(run: ImportRunSummary): string {
  switch (run.status) {
    case "running":
      return "Running";
    case "succeeded":
      return "Succeeded";
    case "failed":
      return "Failed";
    case "interrupted":
      return "Interrupted";
    case "skipped":
      return "Skipped";
    default:
      return run.status ? `Unknown (${run.status})` : "Unknown";
  }
}

/** Failed and interrupted runs are the two the UI should style as a problem. */
export function isImportRunFailure(run: ImportRunSummary): boolean {
  return FAILURE_STATUSES.has(run.status);
}

export function importRunModeLabel(run: ImportRunSummary): string {
  if (run.mode === "copy") return "Copied into storage";
  if (run.mode === "reference") return "Referenced in place";
  return "Mode not recorded";
}

function formatSeconds(totalSeconds: number): string {
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 60) {
    const seconds = totalSeconds % 60;
    return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes === 0 ? `${hours}h` : `${hours}h ${restMinutes}m`;
}

/** Human duration for a finished run; "" while it is still running. */
export function formatImportRunDuration(
  startedAt: number,
  finishedAt: number | null,
): string {
  if (finishedAt === null) return "";
  return formatSeconds(Math.max(0, Math.round(finishedAt - startedAt)));
}

/** Local time for an epoch-seconds timestamp; "" when there is no timestamp. */
export function formatImportRunTime(value: number | null): string {
  if (value === null) return "";
  const date = new Date(value * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString();
}

function fileNoun(count: number): string {
  return count === 1 ? "file" : "files";
}

export function importRunCountsLine(run: ImportRunSummary): string {
  const parts = [
    `${run.discovered} discovered`,
    `${run.registered} registered`,
    `${run.skipped} skipped`,
    `${run.failed} failed`,
  ];
  if (run.rejected > 0) {
    parts.push(`${run.rejected} oversize`);
  }
  return parts.join(", ");
}

/** Explains the oversize subset, which is counted inside `skipped`. */
export function importRunRejectedNote(run: ImportRunSummary): string {
  if (run.rejected <= 0) return "";
  const noun = fileNoun(run.rejected);
  return `${run.rejected} oversize ${noun} exceeded the size limit and ${
    run.rejected === 1 ? "was" : "were"
  } skipped.`;
}

/**
 * Why a run did nothing or went wrong. Only skipped/failed/interrupted runs
 * carry one; a missing reason still renders a placeholder for skipped runs.
 */
export function importRunReason(run: ImportRunSummary): string {
  if (!REASON_STATUSES.has(run.status)) return "";
  const reason = (run.reason || "").trim();
  if (reason) return reason;
  if (run.status === "skipped") return "No reason was recorded.";
  return "";
}
