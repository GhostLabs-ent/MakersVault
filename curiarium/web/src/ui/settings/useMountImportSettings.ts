import React from "react";
import { getMountImportSettings, updateMountImportSettings } from "../../lib/api";
import type { Section } from "./types";
import { useSettingsSave, useSettingsSection } from "./useSettingsSection";

type Props = {
  section: Section;
  onUnauthorized?: () => void;
  /** Admin-only: a non-admin must never fire the request that 403s. */
  enabled: boolean;
};

export type MountImportSettingsState = {
  mountEnabled: boolean;
  mountCopyFiles: boolean;
  mountPath: string | null;
  mountInitial: { enabled: boolean; copy: boolean };
  mountLoading: boolean;
  mountSaving: boolean;
  setMountEnabled: (value: boolean) => void;
  setMountCopyFiles: (value: boolean) => void;
  saveMountSettings: () => Promise<void>;
};

export function useMountImportSettings({ section, onUnauthorized, enabled }: Props): MountImportSettingsState {
  const [mountEnabled, setMountEnabled] = React.useState(false);
  const [mountCopyFiles, setMountCopyFiles] = React.useState(true);
  const [mountPath, setMountPath] = React.useState<string | null>(null);
  const [mountInitial, setMountInitial] = React.useState({ enabled: false, copy: true });

  const { loading } = useSettingsSection({
    section,
    active: enabled && section === "imports",
    load: getMountImportSettings,
    onLoaded: data => {
      setMountEnabled(Boolean(data.enabled));
      setMountCopyFiles(Boolean(data.copy_files));
      setMountPath(data.path || null);
      setMountInitial({ enabled: Boolean(data.enabled), copy: Boolean(data.copy_files) });
    },
    onUnauthorized,
    onError: err => console.error(err),
  });

  const { saving, save: runSave } = useSettingsSave({
    onUnauthorized,
    onError: err => console.error(err),
  });

  const save = async () => {
    await runSave(async () => {
      const data = await updateMountImportSettings({
        enabled: mountEnabled,
        copy_files: mountCopyFiles,
      });
      setMountEnabled(Boolean(data.enabled));
      setMountCopyFiles(Boolean(data.copy_files));
      setMountPath(data.path || null);
      setMountInitial({ enabled: Boolean(data.enabled), copy: Boolean(data.copy_files) });
    });
  };

  return {
    mountEnabled,
    mountCopyFiles,
    mountPath,
    mountInitial,
    mountLoading: loading,
    mountSaving: saving,
    setMountEnabled,
    setMountCopyFiles,
    saveMountSettings: save,
  };
}
