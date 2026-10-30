import React, { useEffect, useRef, useState } from "react";
import {
  UnauthorizedError,
  importFromLink,
  importToProject,
  importZipFromLink,
  inspectImportLink,
  listImportZipEntries,
  type ImportInspectInfo,
  type ImportProjectResult,
} from "../lib/api";
import { entriesFromFileList } from "../lib/uploadTree";
import { targetPayload, type ImportProjectTarget } from "../lib/importProject";
import { dismissToast, notifyError, notifyInfo } from "../lib/toast";
import ImportProjectTargetControl from "./ImportProjectTarget";
import { useUpload } from "./useUpload";

type Props = {
  /** Contribute capability: every control here uploads or imports. A role
   * below contributor never sees this bar. */
  canContribute: boolean;
  onUploaded: () => void;
  folderId?: string | null;
  makerworldCookie?: string | null;
  thingiverseCookie?: string | null;
  onUnauthorized?: () => void;
  /** Fires after a project import, so the app can open the project it landed in. */
  onProjectImported?: (projectId: string) => void;
};

/** The subset of the import payload a retry has to reproduce verbatim. */
type LinkPayload = {
  url: string;
  folder_id?: string;
  makerworld_cookie?: string;
  thingiverse_cookie?: string;
};

/** A link payload plus the project it lands in (`POST /import/project`). */
type ProjectPayload = LinkPayload & { entries?: string[] } & ReturnType<typeof targetPayload>;

function importErrorMessage(err: unknown): string {
  if (err instanceof Error && err.message.trim()) return err.message;
  return "Import failed";
}

export default function UploadBar({
  canContribute,
  onUploaded,
  folderId,
  makerworldCookie,
  thingiverseCookie,
  onUnauthorized,
  onProjectImported,
}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const [importing, setImporting] = useState(false);
  const [linkValue, setLinkValue] = useState("");
  const [target, setTarget] = useState<ImportProjectTarget>({ kind: "none" });
  const uploader = useUpload({
    folderId,
    onUnauthorized,
    onUploaded: () => onUploaded(),
  });
  const isBusy = uploader.busy || importing;

  useEffect(() => {
    if (!folderInputRef.current) return;
    folderInputRef.current.setAttribute("webkitdirectory", "");
    folderInputRef.current.setAttribute("directory", "");
  }, []);

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const entries = entriesFromFileList(e.target.files || []);
    if (!entries.length) return;
    await uploader.upload(entries);
    if (inputRef.current) inputRef.current.value = "";
  };

  const onPickFolder = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const entries = entriesFromFileList(e.target.files || []);
    if (!entries.length) return;
    await uploader.upload(entries);
    if (folderInputRef.current) folderInputRef.current.value = "";
  };

  // Imports only the entries a previous zip import failed on, so a retry never
  // duplicates the assets that already made it.
  const retryZipEntries = (payload: LinkPayload, entries: string[]): void => {
    void importZipEntries(payload, entries).then(imported => {
      if (imported > 0) onUploaded();
    }).catch(err => {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      console.error("Import failed for", payload.url, err);
      const id = notifyError(importErrorMessage(err), {
        details: [payload.url],
        retry: () => {
          dismissToast(id);
          retryZipEntries(payload, entries);
        },
      });
    });
  };

  // Resolves with how many assets the import created; a retry refreshes the
  // grid only when the second attempt actually added something.
  const importZipEntries = async (payload: LinkPayload, entries: string[]): Promise<number> => {
    const result = await importZipFromLink({ ...payload, entries });
    if (!result.failed.length) return result.assets.length;
    const failed = [...result.failed];
    const count = failed.length;
    const id = notifyError(`Failed to import ${count} file${count === 1 ? "" : "s"}`, {
      details: failed,
      retry: () => {
        dismissToast(id);
        retryZipEntries(payload, failed);
      },
    });
    return result.assets.length;
  };

  // --- Project imports (Mf-56z9) -------------------------------------------

  // `POST /import/project` answers for every file of the import, so a partial
  // failure keeps the same "failed entries" toast as the zip path: the retry
  // re-sends only those entries, against the same project.
  const retryProjectEntries = (payload: ProjectPayload, entries: string[]): void => {
    void importProjectEntries({ ...payload, entries })
      .then(result => {
        onUploaded();
        onProjectImported?.(result.project.id);
      })
      .catch(err => {
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
          return;
        }
        console.error("Import failed for", payload.url, err);
        const id = notifyError(importErrorMessage(err), {
          details: [payload.url],
          retry: () => {
            dismissToast(id);
            retryProjectEntries(payload, entries);
          },
        });
      });
  };

  const importProjectEntries = async (payload: ProjectPayload): Promise<ImportProjectResult> => {
    const result = await importToProject(payload);
    // Gated models download nothing at all, so the server's sentence is the
    // only explanation the user gets for the empty project.
    if (result.gated) notifyInfo(result.message);
    if (result.failed.length > 0) {
      const failed = [...result.failed];
      const count = failed.length;
      const id = notifyError(`Failed to import ${count} file${count === 1 ? "" : "s"}`, {
        details: failed,
        retry: () => {
          dismissToast(id);
          retryProjectEntries(payload, failed);
        },
      });
    }
    return result;
  };

  const finishProjectImport = (result: ImportProjectResult): void => {
    setLinkValue("");
    onUploaded();
    onProjectImported?.(result.project.id);
  };

  /**
   * Project-targeted import: both the plain and the zip path go through
   * `POST /import/project`, and both reuse the one zip prompt (never a second
   * modal). "Import and unzip" keeps the archive as a single asset (no
   * `entries`); "Import selected" sends exactly the chosen entries.
   */
  const importIntoProject = async (
    payload: LinkPayload,
    inspect: ImportInspectInfo,
    target: ImportProjectTarget,
  ): Promise<void> => {
    const projectPayload: ProjectPayload = { ...payload, ...targetPayload(target) };
    if (!inspect.is_zip) {
      finishProjectImport(await importProjectEntries(projectPayload));
      return;
    }
    setImporting(false);
    await uploader.promptZip({
      label: inspect.filename,
      onImportAsZip: async () => {
        try {
          finishProjectImport(await importProjectEntries(projectPayload));
        } catch (err) {
          if (err instanceof UnauthorizedError) {
            onUnauthorized?.();
            return;
          }
          throw err;
        }
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
          finishProjectImport(await importProjectEntries({ ...projectPayload, entries }));
        } catch (err) {
          if (err instanceof UnauthorizedError) {
            onUnauthorized?.();
            return;
          }
          throw err;
        }
      },
    });
  };

  // The URL is a parameter, not `linkValue`: a toast retry has to re-run the
  // link that failed even after the input has moved on.
  const importFromUrl = async (url: string): Promise<void> => {
    const payload: LinkPayload = {
      url,
      folder_id: folderId || undefined,
      makerworld_cookie: (makerworldCookie || "").trim() || undefined,
      thingiverse_cookie: (thingiverseCookie || "").trim() || undefined,
    };
    setImporting(true);
    try {
      const inspect = await inspectImportLink(payload);
      if (target.kind !== "none") {
        await importIntoProject(payload, inspect, target);
        return;
      }
      if (!inspect.is_zip) {
        await importFromLink(payload);
        setLinkValue("");
        onUploaded();
        return;
      }
      setImporting(false);
      await uploader.promptZip({
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
            await importZipEntries(payload, entries);
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
      const id = notifyError(importErrorMessage(err), {
        details: [url],
        retry: () => {
          dismissToast(id);
          void importFromUrl(url);
        },
      });
    } finally {
      setImporting(false);
    }
  };

  const onImport = async () => {
    const url = linkValue.trim();
    if (!url) return;
    await importFromUrl(url);
  };

  // Every control in this bar contributes (upload, folder upload, link import,
  // and the project target that steers the import), so a role below contributor
  // gets no bar at all rather than a row of disabled buttons advertising a
  // capability it lacks.
  // The early return sits after every hook so the hook order never changes.
  if (!canContribute) return null;

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
        {uploader.busy ? "Uploading..." : "Upload"}
      </button>
      <button
        className="px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
        disabled={isBusy}
        onClick={() => folderInputRef.current?.click()}
      >
        {uploader.busy ? "Uploading..." : "Upload folder"}
      </button>
      <div className="flex items-center gap-2">
        <input
          type="url"
          value={linkValue}
          onChange={e => setLinkValue(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") {
              e.preventDefault();
              void onImport();
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
      <ImportProjectTargetControl value={target} onChange={setTarget} disabled={isBusy} />
    </div>
    {uploader.modal}
    </>
  );
}
