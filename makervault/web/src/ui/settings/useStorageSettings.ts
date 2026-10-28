import React from "react";
import { getStorageSettings, updateStorageSettings } from "../../lib/api";
import type { Section } from "./types";
import { useSettingsSave, useSettingsSection } from "./useSettingsSection";

type Props = {
  section: Section;
  onUnauthorized?: () => void;
};

export type StorageSettingsState = {
  template: string;
  initial: string;
  tokens: string[];
  sample: string;
  status: string | null;
  loading: boolean;
  saving: boolean;
  setTemplate: React.Dispatch<React.SetStateAction<string>>;
  setStatus: React.Dispatch<React.SetStateAction<string | null>>;
  save: () => Promise<void>;
};

export function useStorageSettings({ section, onUnauthorized }: Props): StorageSettingsState {
  const [storageTemplate, setStorageTemplate] = React.useState("{folder}/{model}/{filename}");
  const [storageInitial, setStorageInitial] = React.useState("{folder}/{model}/{filename}");
  const [storageTokens, setStorageTokens] = React.useState<string[]>([]);
  const [storageSample, setStorageSample] = React.useState("");
  const [storageStatus, setStorageStatus] = React.useState<string | null>(null);

  const { loading } = useSettingsSection({
    section,
    active: section === "storage",
    load: () => {
      setStorageStatus(null);
      return getStorageSettings();
    },
    onLoaded: data => {
      setStorageTemplate(data.template);
      setStorageInitial(data.template);
      setStorageTokens(data.allowed_tokens || []);
      setStorageSample(data.sample_path || "");
    },
    onUnauthorized,
    onError: () => setStorageStatus("Failed to load storage settings."),
  });

  const { saving, save: runSave } = useSettingsSave({
    onUnauthorized,
    onError: err => setStorageStatus(err instanceof Error ? err.message : "Failed to save storage settings."),
  });

  const save = async () => {
    setStorageStatus(null);
    const data = await runSave(() => updateStorageSettings({ template: storageTemplate }));
    if (!data) return;
    setStorageTemplate(data.template);
    setStorageInitial(data.template);
    setStorageTokens(data.allowed_tokens || []);
    setStorageSample(data.sample_path || "");
    setStorageStatus("Storage structure saved. New uploads and imports use this template; existing files are never moved.");
  };

  return {
    template: storageTemplate,
    initial: storageInitial,
    tokens: storageTokens,
    sample: storageSample,
    status: storageStatus,
    loading,
    saving,
    setTemplate: setStorageTemplate,
    setStatus: setStorageStatus,
    save,
  };
}
