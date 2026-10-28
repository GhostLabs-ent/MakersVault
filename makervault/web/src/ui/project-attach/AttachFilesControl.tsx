import { useEffect, useRef, type ChangeEvent, type ReactElement } from "react";
import { FolderUp, Upload } from "lucide-react";

import { entriesFromFileList } from "../../lib/uploadTree";
import type { ProjectAttacher } from "./useAttachToProject";

const FOCUS_VISIBLE =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const BUTTON_SECONDARY = `inline-flex items-center gap-1.5 rounded-md border border-panel-strong px-3 py-2 text-sm transition-colors hover:bg-panel-soft disabled:opacity-60 ${FOCUS_VISIBLE}`;

// Same list as `UploadBar`'s file input: everything the library accepts.
const ACCEPT = ".png,.jpg,.jpeg,.webp,.bmp,.gif,.svg,.stl,.step,.stp,.3mf,.lbrn,.lbrn2,.zip";

type Props = {
  attacher: ProjectAttacher;
};

/**
 * The "attach my own files" entry points of a project's Files section: a
 * multi-select picker, a folder picker and the zip prompt modal owned by
 * `useAttachToProject`.
 */
export default function AttachFilesControl({ attacher }: Props): ReactElement {
  const filesRef = useRef<HTMLInputElement | null>(null);
  const folderRef = useRef<HTMLInputElement | null>(null);

  // `webkitdirectory`/`directory` are not React props; set them on the node the
  // way `UploadBar` does so the picker browses folders instead of files.
  useEffect(() => {
    if (!folderRef.current) return;
    folderRef.current.setAttribute("webkitdirectory", "");
    folderRef.current.setAttribute("directory", "");
  }, []);

  const attachPicked = (e: ChangeEvent<HTMLInputElement>): void => {
    const input = e.target;
    const entries = entriesFromFileList(input.files || []);
    if (entries.length === 0) return;
    // Cleared afterwards so picking the same folder again fires `change` too.
    void attacher.attach(entries).finally(() => {
      input.value = "";
    });
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={filesRef}
          data-testid="attach-files-input"
          type="file"
          multiple
          accept={ACCEPT}
          onChange={attachPicked}
          className="hidden"
        />
        <input
          ref={folderRef}
          data-testid="attach-folder-input"
          type="file"
          multiple
          onChange={attachPicked}
          className="hidden"
        />
        <button
          type="button"
          className={BUTTON_SECONDARY}
          disabled={attacher.busy}
          onClick={() => filesRef.current?.click()}
        >
          <Upload className="h-4 w-4" aria-hidden="true" />
          Attach files
        </button>
        <button
          type="button"
          className={BUTTON_SECONDARY}
          disabled={attacher.busy}
          onClick={() => folderRef.current?.click()}
        >
          <FolderUp className="h-4 w-4" aria-hidden="true" />
          Attach folder
        </button>
      </div>
      {attacher.modal}
    </>
  );
}
