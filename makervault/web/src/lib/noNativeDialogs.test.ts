/**
 * Ticket-Mf-lv87 acceptance guard: the web app must never call a native
 * `alert()`/`confirm()` again. Dialogs are app-owned (`ConfirmDialog`) and
 * failures are reported through the toast store (`lib/toast`).
 *
 * Still a source scan rather than only a lint rule: unlike `eslint`'s
 * `no-alert`, it reports every offending `file:line` at once, and it also
 * enforces that exactly one module implements the zip prompt.
 *
 * Sources come from Vite's raw glob rather than `node:fs`: the app has no
 * `@types/node` and must not gain one, so the glob keeps this file typechecked
 * by the `vite/client` types already configured.
 */

import { describe, expect, it } from "vitest";

// Keys are relative to this test file, e.g. `"../ui/AssetGrid.tsx"`.
const RAW_SOURCES = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** This test lives in `src/lib`, and glob keys are relative to it. */
const SELF_DIR = "lib";
/** This test's own path, relative to `src`. */
const SELF = `${SELF_DIR}/noNativeDialogs.test.ts`;
const ALERT_CALL = /\balert\s*\(/;
const CONFIRM_CALL = /\bconfirm\s*\(/;

/**
 * Glob keys are relative to this file (`"./toast.ts"`, `"../ui/AssetGrid.tsx"`);
 * resolve them to paths relative to `src` without pulling in `node:path`.
 */
function toSourcePath(globKey: string): string {
  const resolved: string[] = [];
  for (const segment of `${SELF_DIR}/${globKey}`.split("/")) {
    if (segment === "..") resolved.pop();
    else if (segment && segment !== ".") resolved.push(segment);
  }
  return resolved.join("/");
}

/** Every `.ts`/`.tsx` source under `src` except this test, keyed by `src`-relative path. */
const SOURCES: Record<string, string> = {};
for (const [globKey, text] of Object.entries(RAW_SOURCES)) {
  const file = toSourcePath(globKey);
  if (file !== SELF) SOURCES[file] = text;
}

const FILES = Object.keys(SOURCES).sort();

function read(file: string): string {
  return SOURCES[file];
}

describe("no native dialogs", () => {
  it("never calls alert() or confirm(), case-sensitive, bare or window-prefixed", () => {
    const violations: string[] = [];
    for (const file of FILES) {
      read(file)
        .split("\n")
        .forEach((line, index) => {
          if (ALERT_CALL.test(line) || CONFIRM_CALL.test(line)) {
            violations.push(`${file}:${index + 1}: ${line.trim()}`);
          }
        });
    }

    expect(violations).toEqual([]);
  });

  it("keeps the zip prompt implementation single-sourced in useUpload", () => {
    const consumers = FILES.filter(
      file =>
        !/\.test\.tsx?$/.test(file) &&
        file !== "ui/ZipImportModal.tsx" &&
        read(file).includes("useZipImportPrompt"),
    );

    expect(consumers).toEqual(["ui/useUpload.ts"]);
  });

  it("scans the real source tree (never passes on an empty file list)", () => {
    expect(FILES).toContain("ui/AssetGrid.tsx");
    expect(FILES).toContain("lib/toast.ts");
    expect(FILES.length).toBeGreaterThan(30);
  });
});
