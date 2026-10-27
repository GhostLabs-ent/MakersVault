import React from "react";
import UploadBar from "./UploadBar";
import AssetGrid from "./AssetGrid";
import Sidebar from "./Sidebar";
import Login from "./Login";
import Settings from "./Settings";
import { apiHealth, getApiBase, refreshToken, type HealthInfo } from "../lib/api";
import { notifyError } from "../lib/toast";
import ConfirmDialog from "./ConfirmDialog";
import { clearToken, readToken, storeToken } from "../lib/auth";
import { type AppSettings, type ResolvedTheme, loadSettings, resolveTheme, saveSettings } from "../lib/settings";
const DEFAULT_REFRESH_SECONDS = 6 * 60 * 60; // 6 hours

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
  const [token, setToken] = React.useState<string | null>(() => readToken());
  // Generation counter for "assets changed". The grid consumes it to refetch in
  // place; it no longer remounts the grid, so view state (search, sort,
  // selection, loaded pages, scroll) survives uploads and mutations.
  const [assetsVersion, setAssetsVersion] = React.useState(0);
  const [folderId, setFolderId] = React.useState<string | null>(null);
  const [folderVersion, setFolderVersion] = React.useState(0);
  const [health, setHealth] = React.useState<HealthInfo | null>(null);
  const [tokenTtl, setTokenTtl] = React.useState<number | null>(null);
  const [sessionExpired, setSessionExpired] = React.useState(false);
  const [activeView, setActiveView] = React.useState<"library" | "settings">("library");
  const [settings, setSettings] = React.useState<AppSettings>(() => loadSettings());
  const [confirmingLogout, setConfirmingLogout] = React.useState(false);
  // Scroll container for the asset grid's virtualization (see useVirtualRows).
  const mainScrollRef = React.useRef<HTMLElement | null>(null);
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
  React.useEffect(() => { (async ()=> setHealth(await apiHealth()))(); }, [settings.network.publicUrl]);
  React.useEffect(() => {
    saveSettings(settings);
  }, [settings]);
  const apiUp = health?.ok ?? null;
  const authRequired = health?.auth_required ?? true;

  const handleLogin = (tok: string, ttl: number) => {
    storeToken(tok);
    setToken(tok);
    setTokenTtl(ttl);
    setSessionExpired(false);
  };

  const handleUnauthorized = React.useCallback(() => {
    if (sessionExpired) return;
    clearToken();
    setToken(null);
    setTokenTtl(null);
    setSessionExpired(true);
    notifyError("Your session has expired. Please sign in again.");
  }, [sessionExpired]);

  const handleFoldersChanged = React.useCallback(() => {
    setFolderVersion(v => v + 1);
  }, []);

  const handleAssetsChanged = React.useCallback(() => {
    setAssetsVersion(n => n + 1);
  }, []);

  const handleSelectFolder = React.useCallback((id: string | null) => {
    setFolderId(id);
    setActiveView("library");
  }, []);

  const handleLogout = () => {
    clearToken();
    setToken(null);
    setTokenTtl(null);
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

  React.useEffect(() => {
    if (!token) return;
    const ttl = tokenTtl ?? DEFAULT_REFRESH_SECONDS;
    const refreshMs = Math.max(
      5 * 60 * 1000,
      Math.min(ttl * 0.8 * 1000, ttl * 1000 - 5 * 60 * 1000)
    );
    const timer = window.setTimeout(async () => {
      try {
        const res = await refreshToken();
        storeToken(res.token);
        setToken(res.token);
        setTokenTtl(res.expires_in);
      } catch {
        handleUnauthorized();
      }
    }, refreshMs);
    return () => window.clearTimeout(timer);
  }, [token, tokenTtl, handleUnauthorized]);

  if (authRequired && !token) {
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
        onUnauthorized={handleUnauthorized}
        onOpenSettings={() => setActiveView("settings")}
        activeView={activeView}
      />
      {/* The asset grid's virtualizer compensates row-height changes itself (see useVirtualRows), so native scroll anchoring must not apply a second adjustment. */}
      <main ref={mainScrollRef} className="flex-1 p-4 overflow-auto" style={{ overflowAnchor: "none" }}>
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
            {activeView === "library" ? (
              <UploadBar
                folderId={folderId}
                makerworldCookie={settings.makerworld.cookie}
                thingiverseCookie={settings.thingiverse.cookie}
                onUploaded={handleAssetsChanged}
                onUnauthorized={handleUnauthorized}
              />
            ) : (
              <button
                className="px-3 py-2 rounded-md border border-panel-strong text-sm"
                onClick={() => setActiveView("library")}
              >
                Back to library
              </button>
            )}
            <button
              onClick={() => setConfirmingLogout(true)}
              className="px-3 py-2 rounded-md border border-panel-strong text-sm"
            >
              Log out
            </button>
          </div>
        </header>
        {activeView === "library" ? (
          <AssetGrid
            folderId={folderId}
            foldersVersion={folderVersion}
            assetsVersion={assetsVersion}
            onUnauthorized={handleUnauthorized}
            slicerSettings={settings.slicer}
            engravingSettings={settings.engraving}
            previewSettings={settings.previews}
            theme={resolvedTheme}
            scrollElementRef={mainScrollRef}
            onNavigateFolder={handleSelectFolder}
          />
        ) : (
          <Settings
            settings={settings}
            onChange={setSettings}
            onAssetsChanged={handleAssetsChanged}
            onFoldersChanged={handleFoldersChanged}
            onUnauthorized={handleUnauthorized}
            onSelectFolder={handleSelectFolder}
          />
        )}
      </main>
      {confirmingLogout && (
        <ConfirmDialog
          title="Log out?"
          body="Are you sure you want to log out?"
          confirmLabel="Log out"
          onConfirm={() => {
            handleLogout();
            setConfirmingLogout(false);
          }}
          onCancel={() => setConfirmingLogout(false)}
        />
      )}
    </div>
  );
}
