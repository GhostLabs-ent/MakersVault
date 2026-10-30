import type { UploadEntry } from "../lib/uploadTree";
import { buildUploadEntriesFromZip, isZipFile, readZipEntries } from "../lib/zipUtils";
import type { ZipPromptConfig } from "./ZipImportModal";

export type ZipPromptFn = (config: ZipPromptConfig) => Promise<void>;
export type ZipEntrySink = (entries: UploadEntry[]) => Promise<void>;

/** Splits a picked batch into plain files and zips, preserving order in each. */
export function splitZipEntries(entries: UploadEntry[]): {
  normal: UploadEntry[];
  zips: UploadEntry[];
} {
  const normal: UploadEntry[] = [];
  const zips: UploadEntry[] = [];
  for (const entry of entries) {
    if (isZipFile(entry.file.name)) zips.push(entry);
    else normal.push(entry);
  }
  return { normal, zips };
}

/**
 * Prompts once per zip ("Import as zip" / "Choose files" with per-entry
 * deselection) and hands the entries the user chose to `sink`.
 * Counting, toasts and retries stay in the caller.
 */
export async function uploadViaZipPrompts(
  zipEntries: UploadEntry[],
  prompt: ZipPromptFn,
  sink: ZipEntrySink,
): Promise<void> {
  for (const entry of zipEntries) {
    // Read lazily and cache per zip: one read serves both the entry list and
    // the import, and a zip the user only opens the choice dialog for is never
    // decompressed.
    let zipData: Record<string, Uint8Array> | null = null;
    const baseParts = entry.relativePath.split("/").filter(Boolean);
    baseParts.pop();
    const basePath = baseParts.join("/");
    await prompt({
      label: entry.file.name,
      onImportAsZip: () => sink([entry]),
      loadEntries: async () => {
        const result = await readZipEntries(entry.file);
        zipData = result.data;
        return result.entries;
      },
      onImportSelected: async (selectedPaths: string[]) => {
        if (!zipData) {
          const result = await readZipEntries(entry.file);
          zipData = result.data;
        }
        const unzipEntries = buildUploadEntriesFromZip(zipData || {}, selectedPaths, basePath);
        await sink(unzipEntries);
      },
    });
  }
}
