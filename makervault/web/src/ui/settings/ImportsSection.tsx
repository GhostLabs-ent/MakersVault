import type { AppSettings } from "../../lib/settings";
import FolderScanCard from "./FolderScanCard";
import ImportCookiesCard from "./ImportCookiesCard";
import MountImportCard from "./MountImportCard";
import SectionHeader from "./SectionHeader";
import type { FolderScanState } from "./useFolderScan";
import type { MountImportSettingsState } from "./useMountImportSettings";

export type CookieDraft = {
  draft: string;
  editing: boolean;
  setDraft: (value: string) => void;
  setEditing: (value: boolean) => void;
};

type Props = {
  settings: AppSettings;
  onChange: (next: AppSettings) => void;
  mount: MountImportSettingsState;
  folderScan: FolderScanState;
  makerworld: CookieDraft;
  thingiverse: CookieDraft;
  onBack: () => void;
};

export default function ImportsSection({
  settings,
  onChange,
  mount,
  folderScan,
  makerworld,
  thingiverse,
  onBack,
}: Props) {
  const updateMakerWorld = (patch: Partial<AppSettings["makerworld"]>) => {
    onChange({
      ...settings,
      makerworld: {
        ...settings.makerworld,
        ...patch,
      },
    });
  };
  const updateThingiverse = (patch: Partial<AppSettings["thingiverse"]>) => {
    onChange({
      ...settings,
      thingiverse: {
        ...settings.thingiverse,
        ...patch,
      },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader
        title="Imports"
        subtitle="Manage session cookies and import local folders."
        onBack={onBack}
      />

      <MountImportCard {...mount} />

      <FolderScanCard {...folderScan} />

      <ImportCookiesCard
        label="MakerWorld"
        summary="Optional auth for importing MakerWorld models."
        description="Paste the Cookie header from a logged-in makerworld.com request to lift download limits. This value is stored only in your browser."
        placeholder="example: mw_session=...; mw_token=...;"
        draft={makerworld.draft}
        editing={makerworld.editing}
        setDraft={makerworld.setDraft}
        setEditing={makerworld.setEditing}
        onSave={cookie => updateMakerWorld({ cookie })}
      />

      <ImportCookiesCard
        label="Thingiverse"
        summary="Optional auth for importing Thingiverse models."
        description="Paste your Thingiverse Cookie header to pass Cloudflare checks when importing. This value is stored only in your browser."
        placeholder="example: cf_clearance=...; PHPSESSID=...;"
        draft={thingiverse.draft}
        editing={thingiverse.editing}
        setDraft={thingiverse.setDraft}
        setEditing={thingiverse.setEditing}
        onSave={cookie => updateThingiverse({ cookie })}
      />
    </div>
  );
}
