import { useRef, useState, type DragEvent } from "react";

import { entriesFromDataTransfer, type UploadEntry } from "../../lib/uploadTree";

export type AttachDropApi = {
  dragActive: boolean;
  handleDragEnter: (e: DragEvent<HTMLElement>) => void;
  handleDragOver: (e: DragEvent<HTMLElement>) => void;
  handleDragLeave: (e: DragEvent<HTMLElement>) => void;
  handleDrop: (e: DragEvent<HTMLElement>) => Promise<void>;
};

/**
 * Drag-and-drop for attaching files to a project. Same `dragDepth` idiom as the
 * asset grid's drop hook: enter/leave pairs nest, so only every leave that is
 * not answered by an enter clears the active state.
 *
 * A viewer gets an inert hook: every handler bails before `preventDefault()`,
 * so no drop overlay ever appears and a drop is left to the browser.
 */
export function useAttachDrop(
  onEntries: (entries: UploadEntry[]) => void | Promise<void>,
  canWrite: boolean,
): AttachDropApi {
  const dragDepth = useRef(0);
  const [dragActive, setDragActive] = useState(false);

  const isFileDrag = (e: DragEvent<HTMLElement>): boolean => {
    const types = Array.from(e.dataTransfer?.types || []);
    return types.includes("Files");
  };

  const handleDragEnter = (e: DragEvent<HTMLElement>): void => {
    if (!canWrite) return;
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current += 1;
    setDragActive(true);
  };

  const handleDragOver = (e: DragEvent<HTMLElement>): void => {
    if (!canWrite) return;
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };

  const handleDragLeave = (e: DragEvent<HTMLElement>): void => {
    if (!canWrite) return;
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setDragActive(false);
    }
  };

  const handleDrop = async (e: DragEvent<HTMLElement>): Promise<void> => {
    if (!canWrite) return;
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current = 0;
    setDragActive(false);
    const entries = await entriesFromDataTransfer(e.dataTransfer);
    if (entries.length === 0) return;
    await onEntries(entries);
  };

  return { dragActive, handleDragEnter, handleDragOver, handleDragLeave, handleDrop };
}
