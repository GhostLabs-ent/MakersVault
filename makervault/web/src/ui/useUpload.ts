import { useState, type ReactNode } from "react";

import { dismissToast, notifyError } from "../lib/toast";
import { uploadEntriesToFolder, type UploadEntry } from "../lib/uploadTree";
import { buildUploadEntriesFromZip, isZipFile, readZipEntries } from "../lib/zipUtils";
import { useZipImportPrompt, type ZipPromptConfig } from "./ZipImportModal";

export type UploadOutcome = {
  uploaded: number;
  failed: string[];
  failedEntries: UploadEntry[];
};

export type UploadRequestOptions = {
  folderId?: string | null;
};

type Options = {
  folderId?: string | null;
  onUnauthorized?: () => void;
  onUploaded?: (outcome: { uploaded: number }) => void | Promise<void>;
};

export type Uploader = {
  /** Uploads a batch, prompting once per zip. Resolves with the combined outcome. */
  upload: (entries: UploadEntry[], requestOptions?: UploadRequestOptions) => Promise<UploadOutcome>;
  /** Opens the zip prompt (link imports reuse it so only one modal exists). */
  promptZip: (config: ZipPromptConfig) => Promise<void>;
  /** The `<ZipImportModal>` element, `null` while closed. */
  modal: ReactNode;
  /** Awaiting an upload, or waiting on the zip prompt. */
  busy: boolean;
};

// The single implementation of the "split zips out, upload the rest, prompt
// once per zip" flow: UploadBar, Sidebar and the asset grid all route here.
export function useUpload(options: Options): Uploader {
  const { folderId, onUnauthorized, onUploaded } = options;
  const [uploading, setUploading] = useState(false);
  const prompt = useZipImportPrompt();

  const upload = async (
    entries: UploadEntry[],
    requestOptions?: UploadRequestOptions,
  ): Promise<UploadOutcome> => {
    if (!entries.length) return { uploaded: 0, failed: [], failedEntries: [] };
    // Per-call override wins: a sidebar drag targets the folder it was dropped on.
    const effectiveFolderId = requestOptions?.folderId ?? folderId ?? null;
    const normalEntries = entries.filter(entry => !isZipFile(entry.file.name));
    const zipEntries = entries.filter(entry => isZipFile(entry.file.name));
    let uploaded = 0;
    const failed: string[] = [];
    const failedEntries: UploadEntry[] = [];
    const applyResult = (result: UploadOutcome): void => {
      uploaded += result.uploaded;
      failed.push(...result.failed);
      failedEntries.push(...result.failedEntries);
    };

    setUploading(true);
    try {
      if (normalEntries.length) {
        applyResult(await uploadEntriesToFolder(normalEntries, effectiveFolderId, onUnauthorized));
      }
      for (const entry of zipEntries) {
        let zipData: Record<string, Uint8Array> | null = null;
        const baseParts = entry.relativePath.split("/").filter(Boolean);
        baseParts.pop();
        const basePath = baseParts.join("/");
        await prompt.prompt({
          label: entry.file.name,
          onImportAsZip: async () => {
            applyResult(await uploadEntriesToFolder([entry], effectiveFolderId, onUnauthorized));
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
            applyResult(await uploadEntriesToFolder(unzipEntries, effectiveFolderId, onUnauthorized));
          },
        });
      }

      if (uploaded > 0) await onUploaded?.({ uploaded });
      if (failedEntries.length > 0) {
        const count = failedEntries.length;
        const id = notifyError(`Failed to upload ${count} file${count === 1 ? "" : "s"}`, {
          details: failed,
          retry: () => {
            dismissToast(id);
            // A failed zip entry re-enters the prompt when retried; acceptable.
            void upload(failedEntries, { folderId: effectiveFolderId });
          },
        });
      }
    } finally {
      setUploading(false);
    }
    return { uploaded, failed, failedEntries };
  };

  const promptZip = (config: ZipPromptConfig): Promise<void> => prompt.prompt(config);

  return {
    upload,
    promptZip,
    modal: prompt.modal,
    busy: uploading || prompt.isOpen,
  };
}
