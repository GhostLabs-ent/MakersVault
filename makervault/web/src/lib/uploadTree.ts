import { UnauthorizedError, createFolder, uploadAsset } from "./api";
import { startUploadBatch } from "./uploadProgress";

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
  projectId?: string | null,
) {
  const failed: string[] = [];
  let uploaded = 0;
  let aborted = false;
  const uploadedEntries: UploadEntry[] = [];
  const folderCache = new Map<string, string>();
  const baseKey = parentFolderId || "root";
  if (!entries.length) return { uploaded, failed, uploadedEntries, aborted };
  const progress = startUploadBatch(entries.map(entry => entry.file));

  const getOrCreateFolder = async (parentId: string | null, parentKey: string, name: string) => {
    const key = `${parentKey}/${name}`;
    const existing = folderCache.get(key);
    if (existing) return existing;
    const created = await createFolder(name, [], parentId || undefined);
    const folderId = (created as { id: string }).id;
    folderCache.set(key, folderId);
    return folderId;
  };

  try {
    for (const entry of entries) {
      if (progress.signal.aborted) { aborted = true; break; }
      const normalized = normalizeRelativePath(entry.relativePath || entry.file.name);
      progress.beginFile(normalized, entry.file.size);
      const segments = normalized.split("/").filter(Boolean);
      if (!segments.length) { failed.push(entry.file.name); progress.failed(); continue; }
      segments.pop();
      let targetFolderId = parentFolderId;
      let parentKey = baseKey;
      for (const segment of segments) {
        try {
          targetFolderId = await getOrCreateFolder(targetFolderId, parentKey, segment);
          parentKey = `${parentKey}/${segment}`;
          if (progress.signal.aborted) { aborted = true; break; }
        } catch (err) {
          if (err instanceof UnauthorizedError) {
            onUnauthorized?.();
            aborted = true;
            break;
          }
          console.error("Folder creation failed for", segment, err);
          failed.push(entry.file.name);
          progress.failed();
          targetFolderId = null;
          break;
        }
      }
      if (aborted) break;
      if (targetFolderId === null && segments.length) continue;
      try {
        progress.transfer({ fraction: 0, phase: "uploading" });
        await uploadAsset(entry.file, {
          folder_id: targetFolderId || undefined,
          project_id: projectId || undefined,
        }, { onProgress: progress.transfer, signal: progress.signal });
        uploaded += 1;
        uploadedEntries.push(entry);
        progress.saved();
      } catch (err) {
        if (progress.signal.aborted) { aborted = true; break; }
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
          aborted = true;
          break;
        }
        console.error("Upload failed for", entry.file.name, err);
        const message = err instanceof Error ? err.message.trim() : "";
        failed.push(message && message !== "Upload failed" ? `${entry.file.name} (${message})` : entry.file.name);
        progress.failed();
      }
    }
  } finally {
    progress.finish(aborted || progress.signal.aborted);
  }
  return { uploaded, failed, uploadedEntries, aborted };
}
