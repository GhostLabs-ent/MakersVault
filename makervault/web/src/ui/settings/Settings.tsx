import React from "react";
import type { AppSettings } from "../../lib/settings";
import EngravingSection from "./EngravingSection";
import ImportsSection from "./ImportsSection";
import NetworkSection from "./NetworkSection";
import PreviewsSection from "./PreviewsSection";
import SettingsRootMenu from "./SettingsRootMenu";
import SlicerSection from "./SlicerSection";
import StorageSection from "./StorageSection";
import ThemeSection from "./ThemeSection";
import type { Section } from "./types";
import { useFolderScan } from "./useFolderScan";
import { useImportRuns } from "./useImportRuns";
import { useLibraryScan } from "./useLibraryScan";
import { useMountImportSettings } from "./useMountImportSettings";
import { useStorageSettings } from "./useStorageSettings";

export type { Section };

type Props = {
  settings: AppSettings;
  onChange: (next: AppSettings) => void;
  onAssetsChanged?: () => void;
  onFoldersChanged?: () => void;
  onUnauthorized?: () => void;
  onSelectFolder?: (id: string | null) => void;
};

export default function Settings({
  settings,
  onChange,
  onAssetsChanged,
  onFoldersChanged,
  onUnauthorized,
  onSelectFolder,
}: Props) {
  const [section, setSection] = React.useState<Section>("root");
  const [makerworldDraft, setMakerworldDraft] = React.useState(settings.makerworld.cookie);
  const [thingiverseDraft, setThingiverseDraft] = React.useState(settings.thingiverse.cookie);
  const [makerworldEditing, setMakerworldEditing] = React.useState(!settings.makerworld.cookie);
  const [thingiverseEditing, setThingiverseEditing] = React.useState(!settings.thingiverse.cookie);
  const [networkDraft, setNetworkDraft] = React.useState(settings.network.publicUrl);

  const libraryScan = useLibraryScan();
  const importRuns = useImportRuns();

  React.useEffect(() => {
    if (section !== "imports") return;
    setMakerworldDraft(settings.makerworld.cookie || "");
    setThingiverseDraft(settings.thingiverse.cookie || "");
    setMakerworldEditing(!settings.makerworld.cookie);
    setThingiverseEditing(!settings.thingiverse.cookie);
  }, [section, settings.makerworld.cookie, settings.thingiverse.cookie]);

  const mount = useMountImportSettings({ section, onUnauthorized });

  React.useEffect(() => {
    if (section !== "network") return;
    setNetworkDraft(settings.network.publicUrl || "");
  }, [section, settings.network.publicUrl]);

  const storage = useStorageSettings({ section, onUnauthorized });

  React.useEffect(() => {
    if (!makerworldEditing) {
      setMakerworldDraft(settings.makerworld.cookie || "");
    }
  }, [settings.makerworld.cookie, makerworldEditing]);

  React.useEffect(() => {
    if (!thingiverseEditing) {
      setThingiverseDraft(settings.thingiverse.cookie || "");
    }
  }, [settings.thingiverse.cookie, thingiverseEditing]);

  const folderScan = useFolderScan({
    section,
    onAssetsChanged,
    onFoldersChanged,
    onUnauthorized,
    onSelectFolder,
  });

  const updateNetwork = (patch: Partial<AppSettings["network"]>) => {
    onChange({
      ...settings,
      network: {
        ...settings.network,
        ...patch,
      },
    });
  };

  if (section === "slicer") {
    return <SlicerSection settings={settings} onChange={onChange} onBack={() => setSection("root")} />;
  }

  if (section === "engraving") {
    return <EngravingSection settings={settings} onChange={onChange} onBack={() => setSection("root")} />;
  }

  if (section === "theme") {
    return <ThemeSection settings={settings} onChange={onChange} onBack={() => setSection("root")} />;
  }

  if (section === "network") {
    return (
      <NetworkSection
        settings={settings}
        networkDraft={networkDraft}
        setNetworkDraft={setNetworkDraft}
        updateNetwork={updateNetwork}
        onBack={() => setSection("root")}
      />
    );
  }

  if (section === "storage") {
    return (
      <StorageSection
        storage={storage}
        libraryScanState={libraryScan}
        onUnauthorized={onUnauthorized}
        onBack={() => setSection("root")}
      />
    );
  }

  if (section === "previews") {
    return <PreviewsSection settings={settings} onChange={onChange} onBack={() => setSection("root")} />;
  }

  if (section === "imports") {
    return (
      <ImportsSection
        settings={settings}
        onChange={onChange}
        mount={mount}
        folderScan={folderScan}
        importRuns={importRuns}
        makerworld={{
          draft: makerworldDraft,
          editing: makerworldEditing,
          setDraft: setMakerworldDraft,
          setEditing: setMakerworldEditing,
        }}
        thingiverse={{
          draft: thingiverseDraft,
          editing: thingiverseEditing,
          setDraft: setThingiverseDraft,
          setEditing: setThingiverseEditing,
        }}
        onBack={() => setSection("root")}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <SettingsRootMenu onOpen={setSection} />
    </div>
  );
}
