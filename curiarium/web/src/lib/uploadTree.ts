import { UnauthorizedError, createFolder, uploadAsset } from "./api";
import { uploadQueue, type UploadJob, type UploadTransport } from "./uploadQueue";

export type UploadEntry = {
  file: File;
  relativePath: string;
};

type FileSystemEntry = {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (success: (file: File) => void, error?: (err: unknown) => void) => void;
  createReader?: () => FileSystemDirectoryReader;
};

type FileSystemDirectoryReader = {
  readEntries: (success: (entries: FileSystemEntry[]) => void, error?: (err: unknown) => void) => void;
};

function normalizeRelativePath(path: string) {
  const trimmed = (path || "").replace(/\\/g, "/").replace(/^\/+/, "");
  return trimmed || "";
}

export function entriesFromFileList(files: FileList | File[]): UploadEntry[] {
  return Array.from(files || []).map(file => {
    const anyFile = file as File & { webkitRelativePath?: string };
    const relativePath = normalizeRelativePath(anyFile.webkitRelativePath || file.name);
    return { file, relativePath: relativePath || file.name };
  });
}

async function readAllEntries(reader: FileSystemDirectoryReader) {
  const entries: FileSystemEntry[] = [];
  while (true) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => {
      reader.readEntries(resolve, reject);
    });
    if (!batch.length) break;
    entries.push(...batch);
  }
  return entries;
}

async function traverseEntry(entry: FileSystemEntry, parentPath: string, output: UploadEntry[]) {
  const entryPath = normalizeRelativePath(parentPath ? `${parentPath}/${entry.name}` : entry.name);
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((resolve, reject) => entry.file?.(resolve, reject));
    output.push({ file, relativePath: entryPath || file.name });
    return;
  }
  if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    const entries = await readAllEntries(reader);
    await Promise.all(entries.map(child => traverseEntry(child, entryPath, output)));
  }
}

export async function entriesFromDataTransfer(dataTransfer: DataTransfer): Promise<UploadEntry[]> {
  const output: UploadEntry[] = [];
  const items = Array.from(dataTransfer.items || []);
  const entryItems = items
    .map(item => (item as unknown as { webkitGetAsEntry?: () => FileSystemEntry | null }).webkitGetAsEntry?.())
    .filter(Boolean) as FileSystemEntry[];

  if (entryItems.length) {
    await Promise.all(entryItems.map(entry => traverseEntry(entry, "", output)));
    return output;
  }

  for (const item of items) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (!file) continue;
    const anyFile = file as File & { webkitRelativePath?: string };
    const relativePath = normalizeRelativePath(anyFile.webkitRelativePath || file.name);
    output.push({ file, relativePath: relativePath || file.name });
  }

  if (!output.length) {
    return entriesFromFileList(dataTransfer.files || []);
  }
  return output;
}

export async function uploadEntriesToFolder(
  entries: UploadEntry[],
  parentFolderId: string | null,
  onUnauthorized?: () => void,
): Promise<{
  uploaded: number;
  failed: string[];
  failedEntries: UploadEntry[];
  uploadedEntries: UploadEntry[];
  cancelled: number;
}> {
  const failed: string[] = [];
  // Parallel to `failed`: the original entries, so callers can offer a retry
  // without guessing which of the inputs failed.
  const failedEntries: UploadEntry[] = [];
  const jobs: UploadJob[] = [];
  const folderCache = new Map<string, string>();
  const baseKey = parentFolderId || "root";
  // Phase 1 can report a 401 and phase 2 can too; the caller is only told once.
  let notifiedUnauthorized = false;

  const notifyUnauthorized = (): void => {
    if (notifiedUnauthorized) return;
    notifiedUnauthorized = true;
    onUnauthorized?.();
  };

  const getOrCreateFolder = async (parentId: string | null, parentKey: string, name: string) => {
    const key = `${parentKey}/${name}`;
    const existing = folderCache.get(key);
    if (existing) return existing;
    const created = await createFolder(name, [], parentId || undefined);
    const folderId = (created as { id: string }).id;
    folderCache.set(key, folderId);
    return folderId;
  };

  // Sequential on purpose: the `createFolder` order (parents before children, in
  // entry order) is observable by callers and by the folder tree the UI refreshes
  // afterwards. Only the uploads below run concurrently.
  for (const entry of entries) {
    const normalized = normalizeRelativePath(entry.relativePath || entry.file.name);
    const segments = normalized.split("/").filter(Boolean);
    if (!segments.length) continue;
    segments.pop();
    let targetFolderId = parentFolderId;
    let parentKey = baseKey;
    let folderFailed = false;
    let folderUnauthorized = false;
    for (const segment of segments) {
      try {
        targetFolderId = await getOrCreateFolder(targetFolderId, parentKey, segment);
        parentKey = `${parentKey}/${segment}`;
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          notifyUnauthorized();
          folderUnauthorized = true;
          break;
        }
        console.error("Folder creation failed for", segment, err);
        failed.push(entry.file.name);
        failedEntries.push(entry);
        folderFailed = true;
        break;
      }
    }
    // An auth abort ends the whole batch; a failed folder only skips its own entry.
    if (folderUnauthorized) break;
    if (folderFailed) continue;
    jobs.push({ entry, folderId: targetFolderId });
  }

  const transport: UploadTransport = (job, ctx) =>
    uploadAsset(
      job.entry.file,
      { folder_id: job.folderId || undefined },
      { onProgress: (loaded, total) => ctx.onProgress({ loaded, total }), signal: ctx.signal },
    ) as Promise<unknown>;

  // The app singleton, never a private queue: the upload panel renders its tasks.
  const result = await uploadQueue.run(jobs, {
    transport,
    isUnauthorized: err => err instanceof UnauthorizedError,
  });

  // Report failures in entry order, not the order the queue finished them in: the
  // toast's detail list and its retry should read the same way they did while the
  // uploads were sequential.
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

  return {
    uploaded: result.uploaded.length,
    failed,
    failedEntries,
    uploadedEntries: result.uploaded.map(job => job.entry),
    cancelled: result.cancelled,
  };
}
