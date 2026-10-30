import { useState, type ReactNode } from "react";

import { dismissToast, notifyError, notifyInfo } from "../lib/toast";
import { uploadEntriesToFolder, type UploadEntry } from "../lib/uploadTree";
import { splitZipEntries, uploadViaZipPrompts } from "./uploadZipFlow";
import { useZipImportPrompt, type ZipPromptConfig } from "./ZipImportModal";

export type UploadOutcome = {
  uploaded: number;
  failed: string[];
  failedEntries: UploadEntry[];
  cancelled: number;
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
    if (!entries.length) return { uploaded: 0, failed: [], failedEntries: [], cancelled: 0 };
    // Per-call override wins: a sidebar drag targets the folder it was dropped on.
    const effectiveFolderId = requestOptions?.folderId ?? folderId ?? null;
    const { normal, zips } = splitZipEntries(entries);
    let uploaded = 0;
    let cancelled = 0;
    const failed: string[] = [];
    const failedEntries: UploadEntry[] = [];
    const applyResult = (result: UploadOutcome): void => {
      uploaded += result.uploaded;
      cancelled += result.cancelled;
      failed.push(...result.failed);
      failedEntries.push(...result.failedEntries);
    };

    setUploading(true);
    try {
      if (normal.length) {
        applyResult(await uploadEntriesToFolder(normal, effectiveFolderId, onUnauthorized));
      }
      await uploadViaZipPrompts(zips, prompt.prompt, async batch => {
        applyResult(await uploadEntriesToFolder(batch, effectiveFolderId, onUnauthorized));
      });

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
      if (cancelled > 0) {
        // Info, not an error: the user asked for this by clicking Cancel.
        notifyInfo(`Upload cancelled — ${uploaded} of ${uploaded + failed.length + cancelled} files uploaded`);
      }
    } finally {
      setUploading(false);
    }
    return { uploaded, failed, failedEntries, cancelled };
  };

  const promptZip = (config: ZipPromptConfig): Promise<void> => prompt.prompt(config);

  return {
    upload,
    promptZip,
    modal: prompt.modal,
    busy: uploading || prompt.isOpen,
  };
}
