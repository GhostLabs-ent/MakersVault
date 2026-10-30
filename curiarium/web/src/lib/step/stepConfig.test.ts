import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_STEP_BUDGETS,
  resetStepBudgetsForTests,
  resolveStepBudgets,
  type StepBudgets,
  type StepBudgetEnv,
} from "./stepConfig";

const MIB = 1024 * 1024;

const keyByField: Record<keyof StepBudgets, keyof StepBudgetEnv> = {
  sizeWarnBytes: "VITE_STEP_SIZE_WARN_MB",
  jobBudgetMs: "VITE_STEP_JOB_BUDGET_MS",
  sessionBudgetMs: "VITE_STEP_SESSION_BUDGET_MS",
  maxPending: "VITE_STEP_MAX_PENDING",
};

// The resolver memoises, so every case starts from a clean memo instead of
// inheriting the previous case's answer.
beforeEach(() => {
  resetStepBudgetsForTests();
});

describe("resolveStepBudgets", () => {
  it("pins the documented defaults when nothing is configured", () => {
    const budgets = resolveStepBudgets({});

    expect(budgets).toEqual({
      sizeWarnBytes: 20_971_520,
      jobBudgetMs: 120_000,
      sessionBudgetMs: 300_000,
      maxPending: 2,
    });
    // 20 MiB by name, and the same number the wire contract carries, so a
    // deployment that configures nothing shrinks or grows nothing.
    expect(budgets.sizeWarnBytes).toBe(20 * MIB);
    expect(budgets.sizeWarnBytes).toBe(DEFAULT_STEP_BUDGETS.sizeWarnBytes);
  });

  it("reads the size warning threshold as MiB and converts it to bytes", () => {
    expect(resolveStepBudgets({ VITE_STEP_SIZE_WARN_MB: "35" }).sizeWarnBytes).toBe(35 * MIB);

    resetStepBudgetsForTests();

    expect(resolveStepBudgets({ VITE_STEP_SIZE_WARN_MB: "20" }).sizeWarnBytes).toBe(20 * MIB);
  });

  it("accepts an override for every budget", () => {
    const budgets = resolveStepBudgets({
      VITE_STEP_SIZE_WARN_MB: "1",
      VITE_STEP_JOB_BUDGET_MS: "45000",
      VITE_STEP_SESSION_BUDGET_MS: "600000",
      VITE_STEP_MAX_PENDING: "5",
    });

    expect(budgets).toEqual({
      sizeWarnBytes: MIB,
      jobBudgetMs: 45_000,
      sessionBudgetMs: 600_000,
      maxPending: 5,
    });
  });

  it("trims whitespace and drops a fractional part", () => {
    const budgets = resolveStepBudgets({
      VITE_STEP_JOB_BUDGET_MS: " 45000 ",
      VITE_STEP_MAX_PENDING: "3.9",
    });

    expect(budgets.jobBudgetMs).toBe(45_000);
    expect(budgets.maxPending).toBe(3);
  });

  it("falls back per field, leaving the other three overrides in force", () => {
    const budgets = resolveStepBudgets({
      VITE_STEP_SIZE_WARN_MB: "20 megabytes",
      VITE_STEP_JOB_BUDGET_MS: "45000",
      VITE_STEP_SESSION_BUDGET_MS: "600000",
      VITE_STEP_MAX_PENDING: "5",
    });

    expect(budgets.sizeWarnBytes).toBe(DEFAULT_STEP_BUDGETS.sizeWarnBytes);
    expect(budgets.jobBudgetMs).toBe(45_000);
    expect(budgets.sessionBudgetMs).toBe(600_000);
    expect(budgets.maxPending).toBe(5);
  });

  const unusableValues = ["", "   ", "garbage", "0", "-1", "-2048", "NaN"];

  for (const field of [
    "sizeWarnBytes",
    "jobBudgetMs",
    "sessionBudgetMs",
    "maxPending",
  ] as const) {
    it(`keeps the default when ${keyByField[field]} is unusable`, () => {
      const env: StepBudgetEnv = {
        VITE_STEP_SIZE_WARN_MB: "30",
        VITE_STEP_JOB_BUDGET_MS: "45000",
        VITE_STEP_SESSION_BUDGET_MS: "600000",
        VITE_STEP_MAX_PENDING: "5",
      };
      const key = keyByField[field];

      for (const value of unusableValues) {
        resetStepBudgetsForTests();
        env[key] = value;
        expect(resolveStepBudgets({ ...env })[field]).toBe(DEFAULT_STEP_BUDGETS[field]);
      }
    });
  }

  it("resolves once and keeps the first answer until it is reset", () => {
    const first = resolveStepBudgets({ VITE_STEP_JOB_BUDGET_MS: "1000" });

    expect(resolveStepBudgets({ VITE_STEP_JOB_BUDGET_MS: "2000" })).toBe(first);
    expect(first.jobBudgetMs).toBe(1000);

    resetStepBudgetsForTests();

    expect(resolveStepBudgets({ VITE_STEP_JOB_BUDGET_MS: "2000" }).jobBudgetMs).toBe(2000);
    expect(DEFAULT_STEP_BUDGETS.jobBudgetMs).toBe(120_000);
  });
});
