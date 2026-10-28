import React, { useRef, useState } from "react";

import { entriesFromDataTransfer } from "../../lib/uploadTree";
import type { Uploader } from "../useUpload";

type AssetDropOptions = {
  isProject: boolean;
  uploader: Uploader;
  dropTargetName: string;
};

export type AssetDropApi = {
  dragActive: boolean;
  dropUploading: boolean;
  showDropOverlay: boolean;
  dropMessage: string;
  handleDragEnter: (e: React.DragEvent<HTMLDivElement>) => void;
  handleDragOver: (e: React.DragEvent<HTMLDivElement>) => void;
  handleDragLeave: (e: React.DragEvent<HTMLDivElement>) => void;
  handleDrop: (e: React.DragEvent<HTMLDivElement>) => Promise<void>;
};

/**
 * Drag-and-drop upload for the grid's root element. The handlers stay bound to
 * that element: `dragDepth` counts enter/leave pairs, so the same node hierarchy
 * must see all four events.
 */
export function useAssetDrop({
  isProject,
  uploader,
  dropTargetName,
}: AssetDropOptions): AssetDropApi {
  const dragDepth = useRef(0);
  const [dragActive, setDragActive] = useState(false);
  const [dropUploading, setDropUploading] = useState(false);

  const isFileDrag = (e: React.DragEvent<HTMLDivElement>) => {
    const types = Array.from(e.dataTransfer?.types || []);
    return types.includes("Files");
  };

  const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    // Uploads always target a files folder, and projects have none.
    if (isProject || !isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current += 1;
    setDragActive(true);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (isProject || !isFileDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    if (isProject || !isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    if (isProject || !isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current = 0;
    setDragActive(false);
    setDropUploading(true);
    try {
      const entries = await entriesFromDataTransfer(e.dataTransfer);
      if (!entries.length) return;
      await uploader.upload(entries);
    } finally {
      setDropUploading(false);
    }
  };

  const showDropOverlay = !isProject && (dragActive || dropUploading);
  const dropMessage = dropUploading
    ? `Uploading to ${dropTargetName}...`
    : `Drop files or folders to upload to ${dropTargetName}`;

  return {
    dragActive,
    dropUploading,
    showDropOverlay,
    dropMessage,
    handleDragEnter,
    handleDragOver,
    handleDragLeave,
    handleDrop,
  };
}
