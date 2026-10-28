import type { UploadEntry } from "../../lib/uploadTree";

export const SCAN_EXTS = ["stl", "3mf", "step", "stp", "obj", "lbrn", "lbrn2"];
export const SCAN_EXT_SET = new Set(SCAN_EXTS);
export type FileSystemHandle = { kind: "file" | "directory"; name: string };
export type FileSystemFileHandle = FileSystemHandle & { getFile: () => Promise<File> };
export type FileSystemDirectoryHandle = FileSystemHandle & {
  entries: () => AsyncIterableIterator<[string, FileSystemHandle]>;
};
export type DirectoryPicker = () => Promise<FileSystemDirectoryHandle>;

export function extOf(name: string) {
  const match = /\.([^.]+)$/.exec(name || "");
  return (match?.[1] || "").toLowerCase();
}

export function normalizeRelativePath(path: string) {
  return (path || "").replace(/\\/g, "/").replace(/^\/+/, "");
}

export function findRootSegment(entries: UploadEntry[]) {
  if (!entries.length) return "";
  const first = normalizeRelativePath(entries[0].relativePath || entries[0].file.name);
  const parts = first.split("/").filter(Boolean);
  if (parts.length < 2) return "";
  const root = parts[0];
  if (!root) return "";
  for (const entry of entries) {
    const normalized = normalizeRelativePath(entry.relativePath || entry.file.name);
    if (!normalized.startsWith(`${root}/`)) {
      return "";
    }
  }
  return root;
}

export function prepareScanEntries(entries: UploadEntry[], rootSegment: string, stripRoot: boolean) {
  const filtered: UploadEntry[] = [];
  let skipped = 0;
  for (const entry of entries) {
    const ext = extOf(entry.file.name);
    if (!SCAN_EXT_SET.has(ext)) {
      skipped += 1;
      continue;
    }
    let relativePath = normalizeRelativePath(entry.relativePath || entry.file.name);
    if (stripRoot && rootSegment) {
      const parts = relativePath.split("/").filter(Boolean);
      if (parts[0] === rootSegment) {
        parts.shift();
        relativePath = parts.join("/");
      }
    }
    if (!relativePath) {
      relativePath = entry.file.name;
    }
    filtered.push({ ...entry, relativePath });
  }
  return { entries: filtered, skipped };
}

export async function entriesFromDirectoryHandle(root: FileSystemDirectoryHandle) {
  const output: UploadEntry[] = [];
  const walk = async (dir: FileSystemDirectoryHandle, basePath: string) => {
    for await (const [, handle] of dir.entries()) {
      if (handle.kind === "file") {
        const file = await (handle as FileSystemFileHandle).getFile();
        const relativePath = basePath ? `${basePath}/${handle.name}` : handle.name;
        output.push({ file, relativePath });
      } else if (handle.kind === "directory") {
        const nextPath = basePath ? `${basePath}/${handle.name}` : handle.name;
        await walk(handle as FileSystemDirectoryHandle, nextPath);
      }
    }
  };
  const rootPath = root.name || "";
  await walk(root, rootPath);
  return output;
}

export function entryKey(entry: UploadEntry) {
  const relative = normalizeRelativePath(entry.relativePath || entry.file.name);
  return `${relative}::${entry.file.size}::${entry.file.lastModified}`;
}
