import React, { useEffect, useRef, useState } from "react";
import {
  UnauthorizedError,
  importFromLink,
  importZipFromLink,
  inspectImportLink,
  listImportZipEntries,
} from "../lib/api";
import { entriesFromFileList, uploadEntriesToFolder } from "../lib/uploadTree";
import { buildUploadEntriesFromZip, isZipFile, readZipEntries } from "../lib/zipUtils";
import { useZipImportPrompt } from "./ZipImportModal";

type Props = {
  onUploaded: () => void;
  folderId?: string | null;
  projectId?: string | null;
  makerworldCookie?: string | null;
  thingiverseCookie?: string | null;
  onUnauthorized?: () => void;
};

export default function UploadBar({ onUploaded, folderId, projectId, makerworldCookie, thingiverseCookie, onUnauthorized }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [linkValue, setLinkValue] = useState("");
  const zipPrompt = useZipImportPrompt();
  const isBusy = uploading || importing || zipPrompt.isOpen;

  useEffect(() => {
    if (!folderInputRef.current) return;
    folderInputRef.current.setAttribute("webkitdirectory", "");
    folderInputRef.current.setAttribute("directory", "");
  }, []);

  const uploadEntries = async (entries: ReturnType<typeof entriesFromFileList>) => {
    if (!entries.length) return;
    setUploading(true);
    try {
      const normalEntries = entries.filter(entry => !isZipFile(entry.file.name));
      const zipEntries = entries.filter(entry => isZipFile(entry.file.name));
      let uploaded = 0;
      const failed: string[] = [];
      const applyResult = (result: { uploaded: number; failed: string[]; aborted?: boolean }) => {
        uploaded += result.uploaded;
        failed.push(...result.failed);
        if (result.aborted) throw new UnauthorizedError();
      };
      if (normalEntries.length) {
        const result = await uploadEntriesToFolder(normalEntries, folderId || null, onUnauthorized, projectId);
        applyResult(result);
      }
      for (const entry of zipEntries) {
        let zipData: Record<string, Uint8Array> | null = null;
        const baseParts = entry.relativePath.split("/").filter(Boolean);
        baseParts.pop();
        const basePath = baseParts.join("/");
        await zipPrompt.prompt({
          label: entry.file.name,
          onImportAsZip: async () => {
            const result = await uploadEntriesToFolder([entry], folderId || null, onUnauthorized, projectId);
            applyResult(result);
          },
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
            const result = await uploadEntriesToFolder(unzipEntries, folderId || null, onUnauthorized, projectId);
            applyResult(result);
          },
        });
      }
      if (uploaded) onUploaded();
      if (failed.length) {
        alert(`Failed to upload: ${failed.join(", ")}`);
      }
    } catch (error) {
      if (!(error instanceof UnauthorizedError)) alert(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const entries = entriesFromFileList(e.target.files || []);
    if (!entries.length) return;
    await uploadEntries(entries);
    if (inputRef.current) inputRef.current.value = "";
  };

  const onPickFolder = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const entries = entriesFromFileList(e.target.files || []);
    if (!entries.length) return;
    await uploadEntries(entries);
    if (folderInputRef.current) folderInputRef.current.value = "";
  };

  const onImport = async () => {
    const url = linkValue.trim();
    if (!url) return;
    setImporting(true);
    try {
      const cookie = (makerworldCookie || "").trim();
      const thingiverse = (thingiverseCookie || "").trim();
      const payload = {
        url,
        folder_id: folderId || undefined,
        project_id: projectId || undefined,
        makerworld_cookie: cookie || undefined,
        thingiverse_cookie: thingiverse || undefined,
      };
      const inspect = await inspectImportLink(payload);
      if (!inspect.is_zip) {
        await importFromLink(payload);
        setLinkValue("");
        onUploaded();
        return;
      }
      setImporting(false);
      await zipPrompt.prompt({
        label: inspect.filename,
        onImportAsZip: async () => {
          try {
            await importFromLink(payload);
          } catch (err) {
            if (err instanceof UnauthorizedError) {
              onUnauthorized?.();
              return;
            }
            throw err;
          }
          setLinkValue("");
          onUploaded();
        },
        loadEntries: async () => {
          try {
            const result = await listImportZipEntries(payload);
            return result.entries;
          } catch (err) {
            if (err instanceof UnauthorizedError) {
              onUnauthorized?.();
            }
            throw err;
          }
        },
        onImportSelected: async (entries: string[]) => {
          try {
            const result = await importZipFromLink({ ...payload, entries });
            if (result.failed.length) {
              alert(`Failed to import: ${result.failed.join(", ")}`);
            }
          } catch (err) {
            if (err instanceof UnauthorizedError) {
              onUnauthorized?.();
              return;
            }
            throw err;
          }
          setLinkValue("");
          onUploaded();
        },
      });
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      console.error("Import failed for", url, err);
      const message = err instanceof Error ? err.message : "Import failed";
      alert(message);
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
    <div className="flex items-center gap-2 flex-wrap">
      <input
        ref={inputRef}
        type="file"
        onChange={onPick}
        multiple
        accept=".png,.jpg,.jpeg,.webp,.bmp,.gif,.svg,.stl,.step,.stp,.3mf,.lbrn,.lbrn2,.zip"
        className="hidden"
      />
      <input
        ref={folderInputRef}
        type="file"
        onChange={onPickFolder}
        multiple
        className="hidden"
      />
      <button
        className="px-3 py-2 rounded-md bg-accent hover:bg-accent-strong disabled:opacity-60"
        disabled={isBusy}
        onClick={() => inputRef.current?.click()}
      >
        {uploading ? "Uploading..." : "Upload"}
      </button>
      <button
        className="px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
        disabled={isBusy}
        onClick={() => folderInputRef.current?.click()}
      >
        {uploading ? "Uploading..." : "Upload folder"}
      </button>
      <div className="flex items-center gap-2">
        <input
          type="url"
          value={linkValue}
          onChange={e => setLinkValue(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") {
              e.preventDefault();
              onImport();
            }
          }}
          placeholder="Paste model link (MakerWorld, Printables, Thingiverse...)"
          className="px-3 py-2 rounded-md border border-panel-strong bg-panel-soft w-80"
          disabled={isBusy}
        />
        <button
          className="px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
          disabled={isBusy || !linkValue.trim()}
          onClick={onImport}
        >
          {importing ? "Importing..." : "Import link"}
        </button>
      </div>
    </div>
    {zipPrompt.modal}
    </>
  );
}
