import type { Asset } from "../../lib/api";
import type { PreviewSettings, ResolvedTheme } from "../../lib/settings";
import type { ConfirmRequest } from "../ConfirmDialog";

export type AssetCardProps = {
  item: Asset;
  /**
   * Contribute capability: upload, import, tag and organise. Required, no
   * default, so a missed call site is a type error rather than a silent false.
   */
  canContribute: boolean;
  /**
   * Delete capability: destroy, rename and move. Separate from
   * `canContribute` because the API splits CONTRIBUTE from WRITE.
   */
  canDelete: boolean;
  onSaveTags: (id: string, tags: string[]) => void;
  onSaveDetails: (id: string, payload: { notes: string; creator: string }) => void;
  onRename: (id: string, filename: string) => void;
  onPreview: (asset: Asset | null) => void;
  onDownloadSingle: (asset: Asset) => void;
  onDownloadByTag: (tag: string) => void;
  onDownloadSelected: () => void;
  downloading: boolean;
  onDelete: (asset: Asset) => void;
  onAddToProject: (asset: Asset) => void;
  onMoveFolder: (id: string, folder_id: string | null) => void;
  folderOptions: { id: string | null; name: string }[];
  /** Project mode hides every folder control (projects have no folder axis). */
  showFolderControls?: boolean;
  moving: boolean;
  selected: boolean;
  onToggleSelected: (id: string) => void;
  hasSelection: boolean;
  bulkDownloading: boolean;
  slicerEnabled: boolean;
  slicerLabel: string;
  onOpenInSlicer: (asset: Asset) => void;
  engravingEnabled: boolean;
  engraverLabel: string;
  onOpenInEngraving: (asset: Asset) => void;
  theme: ResolvedTheme;
  previewMode: PreviewSettings["mode"];
  onAssetChanged: (asset: Asset) => void;
  onForgetMissing: (asset: Asset) => void;
  onRescanMissing: (asset: Asset) => void;
  rescanning: boolean;
  onRequestConfirm: (request: ConfirmRequest) => void;
};
