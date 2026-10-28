import { useRef, useState, type ReactNode } from "react";

import { UnauthorizedError, addProjectAssets, type Asset } from "../../lib/api";
import {
  duplicateKey,
  loadProjectMemberKeys,
  splitDuplicates,
  uploadEntriesToProject,
  type AttachDuplicate,
} from "../../lib/projectAttach";
import { dismissToast, notifyError, notifyInfo } from "../../lib/toast";
import type { UploadEntry } from "../../lib/uploadTree";
import { splitZipEntries, uploadViaZipPrompts } from "../uploadZipFlow";
import { useZipImportPrompt } from "../ZipImportModal";

export type AttachToProjectOptions = {
  projectId: string;
  projectName: string;
  /** App/landing refresh hook: membership and counts changed. */
  onAttached: () => void;
  onUnauthorized?: () => void;
};

export type ProjectAttacher = {
  /** Attaches picked/dropped entries; prompts once per zip. */
  attach: (entries: UploadEntry[]) => Promise<void>;
  /** The `<ZipImportModal>` element, `null` while closed. */
  modal: ReactNode;
  busy: boolean;
};

type MembershipFailure = { id: string; error: string };

type MembershipOutcome = {
  /** `res.added.length`: the server's truth, never the client's guess. */
  added: number;
  skipped: string[];
  failed: MembershipFailure[];
};

/** Everything a membership retry needs; it must never re-upload the files. */
type MembershipContext = {
  projectId: string;
  projectName: string;
  assetsById: Map<string, Asset>;
  onAdded: () => void;
  onUnauthorized?: () => void;
};

function errorText(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message.trim()) return err.message.trim();
  return fallback;
}

function detailOption(details: string[]): { details: string[] } | undefined {
  return details.length > 0 ? { details } : undefined;
}

function skipLine(duplicate: AttachDuplicate): string {
  const label = duplicate.reason === "project" ? "already in project" : "duplicate in this batch";
  return `${duplicate.name} — ${label}`;
}

/** One batched `POST /project/{id}/assets`; `null` means the 401 hook ran. */
async function mergeMembership(
  projectId: string,
  ids: string[],
  onUnauthorized?: () => void,
): Promise<MembershipOutcome | null> {
  try {
    const res = await addProjectAssets(projectId, ids);
    return { added: res.added.length, skipped: res.skipped, failed: res.failed };
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      onUnauthorized?.();
      return null;
    }
    // A thrown call names no id, so every uploaded id is reported as failed.
    const message = errorText(err, "Adding the files to the project failed");
    return { added: 0, skipped: [], failed: ids.map(id => ({ id, error: message })) };
  }
}

/**
 * Re-calls ONLY the membership call: the assets already exist, so a re-upload
 * would 409. Skipped ids mean the first call had in fact committed them.
 */
function retryMembership(context: MembershipContext, ids: string[]): () => Promise<void> {
  return async () => {
    const outcome = await mergeMembership(context.projectId, ids, context.onUnauthorized);
    if (!outcome) return;
    if (outcome.failed.length > 0) {
      notifyMembershipFailure(context, outcome.failed);
      return;
    }
    const skipped = outcome.skipped.map(id => `${context.assetsById.get(id)?.filename ?? id} — already in project`);
    if (outcome.added > 0) {
      context.onAdded();
      const count = outcome.added;
      notifyInfo(
        `Attached ${count} file${count === 1 ? "" : "s"} to "${context.projectName}"`,
        detailOption(skipped),
      );
      return;
    }
    notifyInfo(`No new files attached to "${context.projectName}"`, detailOption(skipped));
  };
}

function notifyMembershipFailure(context: MembershipContext, failed: MembershipFailure[]): void {
  const details = failed.map(failure => `${context.assetsById.get(failure.id)?.name ?? failure.id} (${failure.error})`);
  const count = failed.length;
  notifyError(`Failed to add ${count} file${count === 1 ? "" : "s"} to "${context.projectName}"`, {
    details,
    retry: retryMembership(
      context,
      failed.map(failure => failure.id),
    ),
  });
}

/**
 * Attaches the user's own files to an EXISTING project. The project is the
 * destination, so uploads go to the library root (no `folder_id`) and the new
 * asset ids are then added in one batched `POST /project/{id}/assets`.
 */
export function useAttachToProject(options: AttachToProjectOptions): ProjectAttacher {
  const { projectId, projectName, onAttached, onUnauthorized } = options;
  const [uploading, setUploading] = useState(false);
  // A second gesture while one is running is dropped; a ref, because a render
  // may not have happened yet when the second pick lands.
  const busyRef = useRef(false);
  const prompt = useZipImportPrompt();

  const attach = async (entries: UploadEntry[]): Promise<void> => {
    if (busyRef.current || entries.length === 0) return;
    busyRef.current = true;
    setUploading(true);
    try {
      let memberSet: Set<string>;
      try {
        // Paged: the landing page only knows its first 1000 members, and a
        // duplicate check against a partial list would let a 409 through.
        memberSet = await loadProjectMemberKeys(projectId);
      } catch (err) {
        if (err instanceof UnauthorizedError) onUnauthorized?.();
        else notifyError("Failed to check the project's existing files.");
        return;
      }

      const seen = new Set(memberSet);
      const assetsById = new Map<string, Asset>();
      const skipLines: string[] = [];
      const uploadFailures: string[] = [];
      let added = 0;
      let uploaded = 0;
      let cancelled = 0;
      let membershipFailed = false;

      const context: MembershipContext = {
        projectId,
        projectName,
        assetsById,
        onAdded: () => onAttached(),
        onUnauthorized,
      };

      const offerUploadRetry = (failedEntries: UploadEntry[], details: string[]): void => {
        const count = failedEntries.length;
        const id = notifyError(`Failed to upload ${count} file${count === 1 ? "" : "s"}`, {
          details,
          retry: async () => {
            dismissToast(id);
            // These keys are already in `seen`; forgetting them keeps the retry
            // from being reported as an in-batch duplicate of itself.
            for (const entry of failedEntries) {
              seen.delete(duplicateKey(entry.file.name, entry.file.size));
            }
            const addedBefore = added;
            const skipsBefore = skipLines.length;
            await sink(failedEntries);
            const retried = added - addedBefore;
            if (retried === 0) return;
            // `sink` only accumulates; the gesture-level toast has already been posted.
            onAttached();
            notifyInfo(
              `Attached ${retried} file${retried === 1 ? "" : "s"} to "${projectName}"`,
              detailOption(skipLines.slice(skipsBefore)),
            );
          },
        });
      };

      async function sink(batch: UploadEntry[]): Promise<void> {
        // `seen` is gesture-scoped, so a second zip (or a zip repeating a loose
        // file) is a batch duplicate rather than a 409 on the server.
        const split = splitDuplicates(batch, seen, key => (memberSet.has(key) ? "project" : "batch"));
        for (const duplicate of split.duplicates) skipLines.push(skipLine(duplicate));
        if (split.unique.length === 0) return;

        const result = await uploadEntriesToProject(split.unique, onUnauthorized);
        uploaded += result.uploaded.length;
        cancelled += result.cancelled;
        uploadFailures.push(...result.failed);
        for (const asset of result.uploaded) assetsById.set(asset.id, asset);
        if (result.failedEntries.length > 0) offerUploadRetry(result.failedEntries, result.failed);

        const ids = result.uploaded.map(asset => asset.id);
        // The server rejects an empty list, so an upload-only failure stops here.
        if (ids.length === 0) return;
        const outcome = await mergeMembership(projectId, ids, onUnauthorized);
        if (!outcome) return;
        added += outcome.added;
        for (const id of outcome.skipped) {
          skipLines.push(`${assetsById.get(id)?.filename ?? id} — already in project`);
        }
        if (outcome.failed.length > 0) {
          membershipFailed = true;
          notifyMembershipFailure(context, outcome.failed);
        }
      }

      const { normal, zips } = splitZipEntries(entries);
      if (normal.length > 0) await sink(normal);
      await uploadViaZipPrompts(zips, prompt.prompt, sink);

      if (added > 0) onAttached();

      const total = uploaded + uploadFailures.length + cancelled;
      if (cancelled > 0 && added === 0) {
        // Info, not an error: the user asked for this by clicking Cancel.
        notifyInfo(`Attach cancelled — ${uploaded} of ${total} files attached`);
        return;
      }
      if (added > 0) {
        const cancelledSuffix = cancelled > 0 ? `, ${cancelled} cancelled` : "";
        notifyInfo(
          `Attached ${added} file${added === 1 ? "" : "s"} to "${projectName}"${cancelledSuffix}`,
          detailOption(skipLines),
        );
        return;
      }
      if (uploadFailures.length === 0 && !membershipFailed) {
        notifyInfo(`No new files attached to "${projectName}"`, detailOption(skipLines));
      }
    } finally {
      busyRef.current = false;
      setUploading(false);
    }
  };

  return {
    attach,
    modal: prompt.modal,
    busy: uploading || prompt.isOpen,
  };
}
