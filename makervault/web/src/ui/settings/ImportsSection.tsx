import type { AppSettings } from "../../lib/settings";
import FolderScanCard from "./FolderScanCard";
import ImportCookiesCard from "./ImportCookiesCard";
import ImportRunsCard from "./ImportRunsCard";
import MountImportCard from "./MountImportCard";
import SectionHeader from "./SectionHeader";
import type { FolderScanState } from "./useFolderScan";
import type { ImportRunsState } from "./useImportRuns";
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
  importRuns: ImportRunsState;
  makerworld: CookieDraft;
  thingiverse: CookieDraft;
  onBack: () => void;
};

export default function ImportsSection({
  settings,
  onChange,
  mount,
  folderScan,
  importRuns,
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
  const updateImports = (patch: Partial<AppSettings["imports"]>) => {
    onChange({
      ...settings,
      imports: {
        ...settings.imports,
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
        subtitle="Rate-limit workarounds for public imports, plus local folder scans."
        onBack={onBack}
      />

      <MountImportCard {...mount} />

      <ImportRunsCard state={importRuns} />

      <FolderScanCard {...folderScan} />

      <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-2">
        <label className="text-xs flex items-center gap-2">
          <input
            type="checkbox"
            checked={settings.imports.rememberCookies}
            onChange={e => updateImports({ rememberCookies: e.target.checked })}
            className="accent-current"
          />
          Remember import cookies on this device
        </label>
        <p className="text-xs opacity-70">
          {settings.imports.rememberCookies
            ? "Stored in this browser until you clear it."
            : "Forgotten when you close this tab."}
        </p>
      </div>

      <ImportCookiesCard
        label="MakerWorld"
        summary="Optional rate-limit workaround for free MakerWorld models."
        description="Paste the Cookie header from a logged-in makerworld.com request only to skip anonymous download limits on free models. Never used for paid content - paid or account-gated files are yours to supply, not ours to fetch."
        placeholder="example: mw_session=...; mw_token=...;"
        draft={makerworld.draft}
        editing={makerworld.editing}
        setDraft={makerworld.setDraft}
        setEditing={makerworld.setEditing}
        onSave={cookie => updateMakerWorld({ cookie })}
      />

      <ImportCookiesCard
        label="Thingiverse"
        summary="Optional rate-limit workaround for free Thingiverse models."
        description="Paste your Thingiverse Cookie header only to get past the anonymous rate limit when importing free models. Never used for paid content - paid or account-gated files are yours to supply, not ours to fetch."
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
