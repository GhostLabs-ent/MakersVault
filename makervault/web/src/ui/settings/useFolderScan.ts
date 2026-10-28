import React from "react";
import { UnauthorizedError, createFolder } from "../../lib/api";
import { entriesFromFileList, uploadEntriesToFolder, type UploadEntry } from "../../lib/uploadTree";
import {
  entriesFromDirectoryHandle,
  entryKey,
  findRootSegment,
  prepareScanEntries,
  type DirectoryPicker,
  type FileSystemDirectoryHandle,
} from "./folderScan";
import type { Section } from "./types";

type Props = {
  section: Section;
  onAssetsChanged?: () => void;
  onFoldersChanged?: () => void;
  onUnauthorized?: () => void;
  onSelectFolder?: (id: string | null) => void;
};

export type FolderScanState = {
  scanBusy: boolean;
  scanStripRoot: boolean;
  setScanStripRoot: (value: boolean) => void;
  folderInputRef: React.MutableRefObject<HTMLInputElement | null>;
  prepareFromFileInput: (event: React.ChangeEvent<HTMLInputElement>) => void;
  chooseFolder: () => Promise<void>;
  rescan: () => Promise<void>;
  resetScan: () => void;
  totalSelected: number;
  supportedSelected: number;
  newSelected: number;
  scanSkipped: number;
  scanRoot: string;
  scanStatus: string | null;
};

/**
 * Local folder scan state. Every value lives here so it survives navigation
 * between settings sections, exactly as it did when the sections were early
 * returns of one component.
 */
export function useFolderScan({
  section,
  onAssetsChanged,
  onFoldersChanged,
  onUnauthorized,
  onSelectFolder,
}: Props): FolderScanState {
  const [scanRawEntries, setScanRawEntries] = React.useState<UploadEntry[]>([]);
  const [scanEntries, setScanEntries] = React.useState<UploadEntry[]>([]);
  const [scanRoot, setScanRoot] = React.useState("");
  const [scanSkipped, setScanSkipped] = React.useState(0);
  const [scanStatus, setScanStatus] = React.useState<string | null>(null);
  const [scanBusy, setScanBusy] = React.useState(false);
  const [scanStripRoot, setScanStripRoot] = React.useState(false);
  const [scanHandle, setScanHandle] = React.useState<FileSystemDirectoryHandle | null>(null);
  const [scanFolderId, setScanFolderId] = React.useState<string | null>(null);
  const folderInputRef = React.useRef<HTMLInputElement | null>(null);
  const uploadedKeysRef = React.useRef<Set<string>>(new Set());

  const recordUploadedEntries = (entries: UploadEntry[]) => {
    for (const entry of entries) {
      uploadedKeysRef.current.add(entryKey(entry));
    }
  };

  const filterNewEntries = (entries: UploadEntry[]) => {
    return entries.filter(entry => !uploadedKeysRef.current.has(entryKey(entry)));
  };

  const updateScanSelection = (
    rawEntries: UploadEntry[],
    rootLabel: string,
    stripRoot: boolean,
    resetUploaded: boolean
  ) => {
    const { entries, skipped } = prepareScanEntries(rawEntries, rootLabel, stripRoot);
    if (resetUploaded) {
      uploadedKeysRef.current = new Set();
    }
    setScanRawEntries(rawEntries);
    setScanRoot(rootLabel);
    setScanEntries(entries);
    setScanSkipped(skipped);
    return entries;
  };

  const uploadScanEntries = async (
    entries: UploadEntry[],
    note?: string,
    parentFolderId?: string | null
  ) => {
    const fresh = filterNewEntries(entries);
    if (!fresh.length) {
      setScanStatus(note || "No new files to upload.");
      return;
    }
    setScanBusy(true);
    setScanStatus("Uploading...");
    try {
      const result = await uploadEntriesToFolder(fresh, parentFolderId || null, onUnauthorized);
      if (result.uploadedEntries?.length) {
        recordUploadedEntries(result.uploadedEntries);
      } else if (result.uploaded) {
        recordUploadedEntries(fresh);
      }
      if (result.uploaded) {
        onAssetsChanged?.();
        onFoldersChanged?.();
      }
      if (result.failed.length) {
        setScanStatus(`Uploaded ${result.uploaded} file(s). Failed: ${result.failed.length}.`);
      } else {
        setScanStatus(`Uploaded ${result.uploaded} file(s).`);
      }
    } catch (err) {
      console.error("Folder scan upload failed", err);
      setScanStatus("Upload failed. Please try again.");
    } finally {
      setScanBusy(false);
    }
  };

  const ensureRootFolder = async (name: string) => {
    if (!name || scanStripRoot) {
      setScanFolderId(null);
      return null;
    }
    if (scanFolderId && scanRoot === name) return scanFolderId;
    try {
      const created = await createFolder(name, [], undefined);
      const id = (created as { id: string }).id;
      setScanFolderId(id);
      return id;
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return null;
      }
      console.error("Root folder creation failed", err);
      setScanStatus("Failed to create the top-level folder.");
      return null;
    }
  };

  React.useEffect(() => {
    if (section !== "imports") return;
    if (!folderInputRef.current) return;
    folderInputRef.current.setAttribute("webkitdirectory", "");
    folderInputRef.current.setAttribute("directory", "");
  }, [section]);

  React.useEffect(() => {
    if (!scanRawEntries.length) {
      setScanEntries([]);
      setScanSkipped(0);
      return;
    }
    const stripRoot = Boolean(scanRoot);
    const { entries, skipped } = prepareScanEntries(scanRawEntries, scanRoot, stripRoot);
    setScanEntries(entries);
    setScanSkipped(skipped);
  }, [scanRawEntries, scanRoot]);

  const resetScan = () => {
    setScanRawEntries([]);
    setScanRoot("");
    setScanStatus(null);
    setScanHandle(null);
    setScanFolderId(null);
    uploadedKeysRef.current = new Set();
  };

  const prepareFromFileInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    const entries = entriesFromFileList(event.target.files || []);
    if (!entries.length) {
      setScanRawEntries([]);
      setScanRoot("");
      setScanStatus(null);
      setScanHandle(null);
      setScanFolderId(null);
      uploadedKeysRef.current = new Set();
      return;
    }
    const root = findRootSegment(entries);
    setScanHandle(null);
    setScanFolderId(null);
    const stripRoot = Boolean(root);
    const prepared = updateScanSelection(entries, root, stripRoot, true);
    setScanStatus(null);
    void (async () => {
      const parentFolderId = await ensureRootFolder(root);
      await uploadScanEntries(prepared, undefined, parentFolderId);
      onSelectFolder?.(parentFolderId ?? null);
    })();
    if (folderInputRef.current) folderInputRef.current.value = "";
  };

  const chooseFolder = async () => {
    const picker = typeof window !== "undefined"
      && (window as unknown as { showDirectoryPicker?: DirectoryPicker }).showDirectoryPicker;
    if (picker) {
      try {
        const handle = await picker();
        const entries = await entriesFromDirectoryHandle(handle);
        if (!entries.length) {
          setScanRawEntries([]);
          setScanRoot(handle.name || "");
          setScanHandle(handle);
          setScanFolderId(null);
          uploadedKeysRef.current = new Set();
          setScanStatus("No files found in that folder.");
          return;
        }
        setScanHandle(handle);
        setScanFolderId(null);
        const rootLabel = handle.name || findRootSegment(entries);
        const stripRoot = Boolean(rootLabel);
        const prepared = updateScanSelection(entries, rootLabel, stripRoot, true);
        setScanStatus(null);
        void (async () => {
          const parentFolderId = await ensureRootFolder(rootLabel);
          await uploadScanEntries(prepared, undefined, parentFolderId);
          onSelectFolder?.(parentFolderId ?? null);
        })();
        return;
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        console.warn("Directory picker failed, falling back to file input", err);
      }
    }
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute("webkitdirectory", "");
      folderInputRef.current.setAttribute("directory", "");
    }
    folderInputRef.current?.click();
  };

  const rescan = async () => {
    if (scanHandle) {
      const freshEntries = await entriesFromDirectoryHandle(scanHandle);
      if (!freshEntries.length) {
        setScanRawEntries([]);
        setScanRoot(scanHandle.name || "");
        setScanEntries([]);
        setScanSkipped(0);
        setScanStatus("No files found in that folder.");
        uploadedKeysRef.current = new Set();
        setScanFolderId(null);
        return;
      }
      const rootLabel = scanHandle.name || findRootSegment(freshEntries) || scanRoot;
      const stripRoot = Boolean(rootLabel);
      const prepared = updateScanSelection(freshEntries, rootLabel, stripRoot, false);
      const parentFolderId = await ensureRootFolder(rootLabel);
      await uploadScanEntries(prepared, "No new files to upload.", parentFolderId);
      onSelectFolder?.(parentFolderId ?? null);
      return;
    }
    if (!scanEntries.length) {
      setScanStatus("No supported files selected.");
      return;
    }
    const parentFolderId = await ensureRootFolder(scanRoot);
    await uploadScanEntries(scanEntries, "No new files to upload.", parentFolderId);
    onSelectFolder?.(parentFolderId ?? null);
  };

  return {
    scanBusy,
    scanStripRoot,
    setScanStripRoot,
    folderInputRef,
    prepareFromFileInput,
    chooseFolder,
    rescan,
    resetScan,
    totalSelected: scanRawEntries.length,
    supportedSelected: scanEntries.length,
    newSelected: scanEntries.length ? filterNewEntries(scanEntries).length : 0,
    scanSkipped,
    scanRoot,
    scanStatus,
  };
}
