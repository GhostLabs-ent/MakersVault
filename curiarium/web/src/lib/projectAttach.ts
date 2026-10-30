import { UnauthorizedError, listProjectAssets, uploadAsset, type Asset } from "./api";
import { uploadQueue, type UploadJob, type UploadTransport } from "./uploadQueue";
import type { UploadEntry } from "./uploadTree";

const PAGE_SIZE = 1000;

/**
 * Identity of a file for duplicate purposes: case-folded filename + byte size.
 * The NUL separator keeps `("a", 12)` apart from `("a1", 2)`, which a plain
 * concatenation would fold into the same string.
 */
export function duplicateKey(filename: string, size: number): string {
  return `${filename.toLowerCase()}\0${size}`;
}

export type AttachDuplicateReason = "project" | "batch";
export type AttachDuplicate = { name: string; reason: AttachDuplicateReason };
export type AttachSplit = { unique: UploadEntry[]; duplicates: AttachDuplicate[] };

/**
 * Splits entries whose `duplicateKey` is already in `seen` off into `duplicates`
 * and MUTATES `seen` with the keys it keeps (so a later sink of the same user
 * gesture sees them too). Order is preserved; first occurrence wins.
 */
export function splitDuplicates(
  entries: UploadEntry[],
  seen: Set<string>,
  reasonFor: (key: string) => AttachDuplicateReason,
): AttachSplit {
  const unique: UploadEntry[] = [];
  const duplicates: AttachDuplicate[] = [];
  for (const entry of entries) {
    const key = duplicateKey(entry.file.name, entry.file.size);
    if (seen.has(key)) {
      duplicates.push({ name: entry.file.name, reason: reasonFor(key) });
      continue;
    }
    seen.add(key);
    unique.push(entry);
  }
  return { unique, duplicates };
}

/**
 * Keys of a project's committed members: `filename` + `size`.
 * `Asset.name` is the extension-less model name and must NOT be used.
 */
export function memberKeys(assets: Asset[]): Set<string> {
  const keys = new Set<string>();
  for (const asset of assets) keys.add(duplicateKey(asset.filename, asset.size));
  return keys;
}

/** Every member of the project, paged through `listProjectAssets` (limit 1000). */
export async function loadProjectMemberKeys(projectId: string): Promise<Set<string>> {
  const keys = new Set<string>();
  let offset = 0;
  while (true) {
    const page = await listProjectAssets({ projectId, limit: PAGE_SIZE, offset });
    for (const key of memberKeys(page.items)) keys.add(key);
    if (!page.hasMore) break;
    // Same idiom as `ProjectLanding.loadMoreMembers`: the server's cursor wins,
    // and without one the next page starts after every row delivered so far
    // (the cumulative count, not this page's length, which would re-request).
    offset = page.nextOffset ?? offset + page.items.length;
  }
  return keys;
}

export type ProjectUploadResult = {
  /** Created assets, in the order the entries were given. */
  uploaded: Asset[];
  /** `name (message)` per failed file, in entry order. */
  failed: string[];
  /** Parallel to `failed`, the original entries, for a retry. */
  failedEntries: UploadEntry[];
  cancelled: number;
};

/**
 * Uploads entries to the library root (no folder is created, `folder_id` is not
 * sent) through the global `uploadQueue`, so the upload panel renders them.
 * 401 aborts the gesture and calls `onUnauthorized` once.
 */
export async function uploadEntriesToProject(
  entries: UploadEntry[],
  onUnauthorized?: () => void,
): Promise<ProjectUploadResult> {
  const failed: string[] = [];
  // Parallel to `failed`: the original entries, so callers can offer a retry
  // without guessing which of the inputs failed.
  const failedEntries: UploadEntry[] = [];
  const jobs: UploadJob[] = entries.map(entry => ({ entry, folderId: null }));
  // The queue finishes out of order, so each job records its own asset and the
  // result is rebuilt in entry order below.
  const assetsByJob = new Map<UploadJob, Asset>();
  // The abort flag and the UnauthorizedError rejection can both land; the caller
  // is only told once.
  let notifiedUnauthorized = false;

  const notifyUnauthorized = (): void => {
    if (notifiedUnauthorized) return;
    notifiedUnauthorized = true;
    onUnauthorized?.();
  };

  const transport: UploadTransport = async (job, ctx) => {
    // Empty options on purpose: attaching to a project keeps the file in normal
    // managed storage, so the form must not carry a `folder_id` at all.
    const asset = (await uploadAsset(job.entry.file, {}, {
      onProgress: (loaded, total) => ctx.onProgress({ loaded, total }),
      signal: ctx.signal,
    })) as Asset;
    assetsByJob.set(job, asset);
    return asset;
  };

  // The app singleton, never a private queue: the upload panel renders its tasks.
  const result = await uploadQueue.run(jobs, {
    transport,
    isUnauthorized: err => err instanceof UnauthorizedError,
  });

  // Report failures in entry order, not the order the queue finished them in: the
  // toast's detail list and its retry should read the same way the inputs did.
  const failureMessages = new Map<UploadJob, string>();
  for (const failure of result.failures) failureMessages.set(failure.job, failure.message);
  for (const job of jobs) {
    const failureMessage = failureMessages.get(job);
    if (failureMessage === undefined) continue;
    const name = job.entry.file.name;
    const message = failureMessage.trim();
    console.error("Upload failed for", name, failureMessage);
    failed.push(message && message !== "Upload failed" ? `${name} (${message})` : name);
    failedEntries.push(job.entry);
  }

  // An auth abort is not a user cancel: the queue tallies it as 0 cancellations.
  if (result.aborted) notifyUnauthorized();

  const uploaded: Asset[] = [];
  for (const job of jobs) {
    const asset = assetsByJob.get(job);
    if (asset) uploaded.push(asset);
  }

  return {
    uploaded,
    failed,
    failedEntries,
    cancelled: result.cancelled,
  };
}
