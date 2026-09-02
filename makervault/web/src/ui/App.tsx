import React from "react";
import UploadBar from "./UploadBar";
import AssetGrid from "./AssetGrid";
import Sidebar from "./Sidebar";
import Login from "./Login";
import Settings from "./Settings";
import TrashView from "./TrashView";
import ProjectWorkspace from "./ProjectWorkspace";
import { apiHealth, getApiBase, getSession, logout, type HealthInfo } from "../lib/api";
import { clearLegacyAuthTokens, setSessionCsrfToken } from "../lib/auth";
import { type AppSettings, type ResolvedTheme, loadSettings, resolveTheme, saveSettings } from "../lib/settings";

const logoForTheme = (theme: ResolvedTheme) => {
  switch (theme) {
    case "neon":
      return "/img/green_theme/Neon_Green_bgrm.png";
    case "purple":
      return "/img/purple_theme/Neon_Purple_logo_bgrm.png";
    case "blue":
      return "/img/blue_theme/Blue_Theme_logo_bgrm.png";
    case "dark":
      return "/img/whitelogo.png";
    default:
      return "/img/blacklogo.png";
  }
};

export default function App() {
  const [authenticated, setAuthenticated] = React.useState<boolean | null>(null);
  const [nonce, setNonce] = React.useState(0);
  const [folderId, setFolderId] = React.useState<string | null>(null);
  const [folderVersion, setFolderVersion] = React.useState(0);
  const [projectId, setProjectId] = React.useState<string | null>(null);
  const [projectsVersion, setProjectsVersion] = React.useState(0);
  const [health, setHealth] = React.useState<HealthInfo | null>(null);
  const [sessionExpired, setSessionExpired] = React.useState(false);
  const [activeView, setActiveView] = React.useState<"library" | "project" | "unassigned" | "settings" | "trash">("library");
  const [settingsSection, setSettingsSection] = React.useState<"root" | "trash">("root");
  const [settings, setSettings] = React.useState<AppSettings>(() => loadSettings());
  const resolvedTheme = React.useMemo(
    () => resolveTheme(settings.theme.selected),
    [settings.theme.selected]
  );
  React.useEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    const isDark =
      resolvedTheme === "dark" ||
      resolvedTheme === "neon" ||
      resolvedTheme === "purple" ||
      resolvedTheme === "blue";
    root.classList.toggle("dark", isDark);
    root.classList.toggle("theme-neon", resolvedTheme === "neon");
    root.classList.toggle("theme-purple", resolvedTheme === "purple");
    root.classList.toggle("theme-blue", resolvedTheme === "blue");
  }, [resolvedTheme]);
  React.useEffect(() => {
    let canceled = false;
    clearLegacyAuthTokens();
    (async () => {
      const currentHealth = await apiHealth();
      if (canceled) return;
      setHealth(currentHealth);
      if (!currentHealth?.ok) {
        setAuthenticated(false);
        return;
      }
      if (!currentHealth.auth_required) {
        setAuthenticated(true);
        return;
      }
      try {
        const session = await getSession();
        if (!canceled) setAuthenticated(Boolean(session?.authenticated));
      } catch {
        if (!canceled) setAuthenticated(false);
      }
    })();
    return () => { canceled = true; };
  }, [settings.network.publicUrl]);
  React.useEffect(() => {
    saveSettings(settings);
  }, [settings]);
  const apiUp = health?.ok ?? null;
  const authRequired = health?.auth_required ?? true;

  const handleLogin = () => {
    setAuthenticated(true);
    setSessionExpired(false);
  };

  const handleUnauthorized = React.useCallback(() => {
    if (sessionExpired) return;
    setSessionCsrfToken(null);
    setAuthenticated(false);
    setSessionExpired(true);
    alert("Your session has expired. Please sign in again.");
  }, [sessionExpired]);

  const handleFoldersChanged = React.useCallback(() => {
    setFolderVersion(v => v + 1);
  }, []);

  const handleAssetsChanged = React.useCallback(() => {
    setNonce(n => n + 1);
    setProjectsVersion(version => version + 1);
  }, []);

  const handleProjectsChanged = React.useCallback(() => {
    setProjectsVersion(version => version + 1);
  }, []);

  const handleSelectFolder = React.useCallback((id: string | null) => {
    setFolderId(id);
    setProjectId(null);
    setActiveView("library");
  }, []);

  const handleSelectProject = React.useCallback((id: string) => {
    setFolderId(null);
    setProjectId(id);
    setActiveView("project");
  }, []);

  const handleSelectProjectUnassigned = React.useCallback(() => {
    setFolderId(null);
    setProjectId(null);
    setActiveView("unassigned");
  }, []);

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      setSessionCsrfToken(null);
      setAuthenticated(false);
      setSessionExpired(false);
    }
  };

  const resetSavedProxyUrl = () => {
    setSettings(prev => ({
      ...prev,
      network: {
        ...prev.network,
        publicUrl: "",
      },
    }));
  };

  if (authenticated === null) {
    return <div className="min-h-screen flex items-center justify-center text-muted">Loading MakersVault…</div>;
  }

  if (authRequired && !authenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Login onSuccess={handleLogin} apiUp={apiUp} theme={resolvedTheme} />
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      <Sidebar
        selectedId={folderId}
        onSelect={handleSelectFolder}
        onFoldersChanged={handleFoldersChanged}
        foldersVersion={folderVersion}
        onAssetsChanged={handleAssetsChanged}
        selectedProjectId={projectId}
        onSelectProject={handleSelectProject}
        onSelectProjectUnassigned={handleSelectProjectUnassigned}
        projectsVersion={projectsVersion}
        onProjectsChanged={handleProjectsChanged}
        onUnauthorized={handleUnauthorized}
        onOpenSettings={() => { setSettingsSection("root"); setActiveView("settings"); }}
        onOpenTrash={() => setActiveView("trash")}
        activeView={activeView}
      />
      <main className="flex-1 p-4 overflow-auto">
        {apiUp === false && (
          <div className="mb-3 p-2 rounded-md bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-100 flex flex-wrap items-center gap-2">
            <span>API unreachable at {getApiBase()}. Ensure the API container is running and reachable.</span>
            {!!settings.network.publicUrl && (
              <button
                className="px-2 py-1 rounded-md border border-red-400/70 text-xs font-medium"
                onClick={resetSavedProxyUrl}
                type="button"
              >
                Reset saved proxy URL
              </button>
            )}
          </div>
        )}
        <header className="flex items-center justify-between mb-4 gap-4 flex-wrap">
          {activeView === "library" && (
            <img
              src={logoForTheme(resolvedTheme)}
              alt="Makers Vault"
              className="h-40 w-auto max-w-[520px]"
            />
          )}
          <div className="flex flex-wrap items-center gap-3">
            {activeView === "library" || activeView === "project" || activeView === "unassigned" ? (
              <UploadBar
                folderId={folderId}
                projectId={activeView === "project" ? projectId : null}
                makerworldCookie={settings.makerworld.cookie}
                thingiverseCookie={settings.thingiverse.cookie}
                onUploaded={handleAssetsChanged}
                onUnauthorized={handleUnauthorized}
              />
            ) : (
              <button
                className="px-3 py-2 rounded-md border border-panel-strong text-sm"
                onClick={() => handleSelectFolder(null)}
              >
                Back to library
              </button>
            )}
            <button
              onClick={() => {
                if (confirm("Are you sure you want to log out?")) {
                  void handleLogout();
                }
              }}
              className="px-3 py-2 rounded-md border border-panel-strong text-sm"
            >
              Log out
            </button>
          </div>
        </header>
        {activeView === "library" ? (
          <AssetGrid
            key={`${nonce + (folderId||'')}-${folderVersion}`}
            folderId={folderId}
            foldersVersion={folderVersion}
            onSelectFolder={handleSelectFolder}
            onUnauthorized={handleUnauthorized}
            slicerSettings={settings.slicer}
            engravingSettings={settings.engraving}
            previewSettings={settings.previews}
            theme={resolvedTheme}
          />
        ) : activeView === "project" && projectId ? (
          <ProjectWorkspace
            key={`${projectId}-${nonce}`}
            projectId={projectId}
            onProjectChanged={handleProjectsChanged}
            onSelectFolder={handleSelectFolder}
            onUnauthorized={handleUnauthorized}
            slicerSettings={settings.slicer}
            engravingSettings={settings.engraving}
            previewSettings={settings.previews}
            theme={resolvedTheme}
          />
        ) : activeView === "unassigned" ? (
          <AssetGrid
            key={`unassigned-${nonce}-${folderVersion}`}
            projectUnassigned
            onSelectFolder={handleSelectFolder}
            onUnauthorized={handleUnauthorized}
            slicerSettings={settings.slicer}
            engravingSettings={settings.engraving}
            previewSettings={settings.previews}
            theme={resolvedTheme}
          />
        ) : activeView === "trash" ? (
          <TrashView
            onAssetsChanged={handleAssetsChanged}
            onProjectsChanged={handleProjectsChanged}
            onUnauthorized={handleUnauthorized}
            onOpenSettings={() => { setSettingsSection("trash"); setActiveView("settings"); }}
          />
        ) : (
          <Settings
            initialSection={settingsSection}
            settings={settings}
            onChange={setSettings}
            onAssetsChanged={handleAssetsChanged}
            onFoldersChanged={handleFoldersChanged}
            onUnauthorized={handleUnauthorized}
            onSelectFolder={handleSelectFolder}
          />
        )}
      </main>
    </div>
  );
}
