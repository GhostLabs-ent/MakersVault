/**
 * Build-time tunables for STEP previews.
 *
 * This module sits beside `protocol` rather than inside it on purpose: it reads
 * `import.meta.env`, and `step.worker.ts` must never reach that. The worker
 * needs the wire contract and nothing else, so `protocol` stays the source of
 * the byte constants and this module is the only place a `VITE_STEP_*` value
 * is read.
 *
 * Vite bakes these into the bundle, so they are not runtime settings: unlike
 * the API URL there is no `runtime-config.js` path, and changing one means
 * rebuilding the web image.
 */

import { STEP_SIZE_WARN_BYTES } from "./protocol";

export type StepBudgets = {
  sizeWarnBytes: number;
  jobBudgetMs: number;
  sessionBudgetMs: number;
  maxPending: number;
};

/** The `VITE_STEP_*` surface as Vite hands it over: every value is a string. */
export type StepBudgetEnv = {
  VITE_STEP_SIZE_WARN_MB?: string;
  VITE_STEP_JOB_BUDGET_MS?: string;
  VITE_STEP_SESSION_BUDGET_MS?: string;
  VITE_STEP_MAX_PENDING?: string;
};

const BYTES_PER_MIB = 1024 * 1024;

export const DEFAULT_STEP_BUDGETS: StepBudgets = {
  // Imported instead of restated so the wire contract remains the only place
  // the byte threshold is written down.
  sizeWarnBytes: STEP_SIZE_WARN_BYTES,
  jobBudgetMs: 120_000,
  sessionBudgetMs: 300_000,
  maxPending: 2,
};

/**
 * One positive whole number, or `null` for "no usable value". Absent, empty,
 * non-numeric, zero and negative all answer `null` so the caller keeps its
 * default, and every field falls back on its own: a typo in one variable must
 * not take the other three down with it.
 */
function parsePositiveInt(raw: string | undefined): number | null {
  if (raw === undefined) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return null;
  const whole = Math.floor(value);
  if (whole <= 0) return null;
  return whole;
}

let resolved: StepBudgets | null = null;

/**
 * `import.meta.env` is weakly typed (every key is optional by construction),
 * so it has to be named explicitly here rather than asserted at the call site.
 */
function viteEnv(): StepBudgetEnv {
  return import.meta.env as unknown as StepBudgetEnv;
}

/**
 * Resolve the STEP budgets, once per module instance. `env` is a parameter
 * rather than a bare global read so a test can pass its own values instead of
 * mutating `import.meta.env`.
 */
export function resolveStepBudgets(env: StepBudgetEnv = viteEnv()): StepBudgets {
  if (resolved) return resolved;
  const warnMib = parsePositiveInt(env.VITE_STEP_SIZE_WARN_MB);
  const jobBudgetMs = parsePositiveInt(env.VITE_STEP_JOB_BUDGET_MS);
  const sessionBudgetMs = parsePositiveInt(env.VITE_STEP_SESSION_BUDGET_MS);
  const maxPending = parsePositiveInt(env.VITE_STEP_MAX_PENDING);
  resolved = {
    sizeWarnBytes:
      warnMib === null ? DEFAULT_STEP_BUDGETS.sizeWarnBytes : warnMib * BYTES_PER_MIB,
    jobBudgetMs: jobBudgetMs ?? DEFAULT_STEP_BUDGETS.jobBudgetMs,
    sessionBudgetMs: sessionBudgetMs ?? DEFAULT_STEP_BUDGETS.sessionBudgetMs,
    maxPending: maxPending ?? DEFAULT_STEP_BUDGETS.maxPending,
  };
  return resolved;
}

export function resetStepBudgetsForTests(): void {
  resolved = null;
}
