import React from "react";
import UploadBar from "./UploadBar";
import AssetGrid from "./asset-grid/AssetGrid";
import Sidebar from "./Sidebar";
import ModeSwitch from "./ModeSwitch";
import ProjectSidebar from "./ProjectSidebar";
import ProjectView from "./ProjectView";
import Login from "./Login";
import AuditLog from "./AuditLog";
import NotPermitted from "./NotPermitted";
import UploadQueuePanel from "./UploadQueuePanel";
import {
  UnauthorizedError,
  apiHealth,
  getApiBase,
  listProjects,
  logout,
  refreshToken,
  type HealthInfo,
  type Project,
} from "../lib/api";
import { notifyError } from "../lib/toast";
import ConfirmDialog from "./ConfirmDialog";
import {
  clearRefreshToken,
  clearToken,
  readRefreshToken,
  readToken,
  roleAtLeast,
  storeRefreshToken,
  storeToken,
} from "../lib/auth";
import { type AppSettings, type ResolvedTheme, loadSettings, resolveTheme, saveSettings } from "../lib/settings";
import { type LibraryMode, loadMode, saveMode } from "../lib/mode";
import { useSessionRole } from "./useSessionRole";
// Imported from the domain module, not the `../lib/api` barrel: `App.role.test.tsx`
// and `App.mode.test.tsx` replace that barrel with a fixed object, so a new named
// import from it would throw "No export is defined on the mock" in files outside
// this ticket's touch-set. `ui/deferredFileGrants.test.tsx` sets the same precedent
// by importing `../lib/api/grants` directly.
import { OidcExchangeError, exchangeOidcCode } from "../lib/api/auth";

const DEFAULT_REFRESH_SECONDS = 900; // 15 minutes: the access token lifetime

// Settings is not needed to render the library, so it is fetched on demand and
// lands in its own chunk.
const Settings = React.lazy(() => import("./settings/Settings"));

/** Visible stand-in while the lazily loaded Settings chunk is on the wire. */
export function SettingsLoading() {
  return (
    <div className="flex h-full w-full items-center justify-center text-sm text-muted p-6">
      Loading settings…
    </div>
  );
}

/**
 * The API returns the browser to the web app with the handoff code in the URL
 * fragment (`#sso_code=...`, or `#sso_error=...` on a rejection), never the
 * query string: a fragment is not sent to the server nor written to the API's
 * access log. Read synchronously so the very first render already knows a
 * handoff is in flight.
 */
export function readSsoFragment(): { code: string | null; error: string | null } {
  if (typeof window === "undefined") return { code: null, error: null };
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash) return { code: null, error: null };
  let code: string | null = null;
  let error: string | null = null;
  for (const part of hash.split("&")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    const key = part.slice(0, separator);
    if (key !== "sso_code" && key !== "sso_error") continue;
    let value = part.slice(separator + 1);
    try {
      value = decodeURIComponent(value);
    } catch {
      // A malformed escape is not a usable value: keep it raw and let the
      // exchange fail rather than throwing on a hostile URL.
    }
    if (!value) continue;
    if (key === "sso_code") code = value;
    else error = value;
  }
  return { code, error };
}

function hasSsoFragment(): boolean {
  const { code, error } = readSsoFragment();
  return Boolean(code || error);
}

/** Drops the fragment while keeping path and query, without a navigation. */
function clearSsoFragment(): void {
  if (typeof window === "undefined") return;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}

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
  // Top-level browsing mode, persisted per browser. The two panes are mounted
  // lazily (on first visit) and then kept mounted, so each mode keeps its own
  // selection/search/sidebar state while the other is hidden.
  const [mode, setMode] = React.useState<LibraryMode>(() => loadMode());
  const [visitedModes, setVisitedModes] = React.useState(() => ({
    files: mode === "files",
    projects: mode === "projects",
  }));
  const [openProjectId, setOpenProjectId] = React.useState<string | null>(null);
  const [projects, setProjects] = React.useState<Project[] | null>(null);
  const [health, setHealth] = React.useState<HealthInfo | null>(null);
  const [tokenTtl, setTokenTtl] = React.useState<number | null>(null);
  const [sessionExpired, setSessionExpired] = React.useState(false);
  // SSO handoff. `ssoPending` starts true when the URL carries a handoff
  // fragment, so the gate below shows a placeholder instead of the login form
  // while the code is exchanged: the form must never flash.
  const [ssoError, setSsoError] = React.useState<string | null>(null);
  const [ssoPending, setSsoPending] = React.useState<boolean>(() => hasSsoFragment());
  // The handoff code is single-use server-side, so the exchange must run once
  // even though React.StrictMode invokes effects twice.
  const ssoHandled = React.useRef<boolean>(false);
  const [activeView, setActiveView] = React.useState<"library" | "settings" | "audit">("library");
  const [settings, setSettings] = React.useState<AppSettings>(() => loadSettings());
  const [confirmingLogout, setConfirmingLogout] = React.useState(false);
  // Scroll container for the asset grid's virtualization (see useVirtualRows).
  const mainScrollRef = React.useRef<HTMLElement | null>(null);
  // Access token value the post-reload refresh was already fired for. The
  // refresh token is single-use server-side, so the one-shot must not fire
  // twice for the same access token (React.StrictMode runs effects twice).
  const reloadRefreshFor = React.useRef<string | null>(null);
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

  // Stable identity so the SSO effect can depend on it without re-running on
  // every render; it only touches setters and token storage.
  const handleLogin = React.useCallback((tok: string, ttl: number, refresh: string) => {
    storeToken(tok);
    // Never leave a refresh token from a previous sign-in paired with the new
    // access token: store the new one, or drop whatever was stored before.
    if (refresh) {
      storeRefreshToken(refresh);
    } else {
      clearRefreshToken();
    }
    setToken(tok);
    setTokenTtl(ttl);
    setSessionExpired(false);
  }, []);

  const handleUnauthorized = React.useCallback(() => {
    if (sessionExpired) return;
    clearToken();
    setToken(null);
    setTokenTtl(null);
    setSessionExpired(true);
    notifyError("Your session has expired. Please sign in again.");
  }, [sessionExpired]);

  const role = useSessionRole({ token, authRequired, onUnauthorized: handleUnauthorized });

  // WRITE capability, derived exactly once and threaded down as a required
  // prop. It is the same rank helper the nav already uses, so there is one
  // threshold in one place (`roleAtLeast`), not a second opinion per surface.
  // `role` is null until `/me` answers and stays null when the API forbids
  // `/me`, so an unknown role has no write access: fail closed. The API is
  // still the gate; this only stops a viewer being shown controls whose
  // requests the server refuses.
  const canWrite = roleAtLeast(role, "editor");

  const handleFoldersChanged = React.useCallback(() => {
    setFolderVersion(v => v + 1);
  }, []);

  const handleAssetsChanged = React.useCallback(() => {
    setAssetsVersion(n => n + 1);
  }, []);

  const handleSelectFolder = React.useCallback((id: string | null) => {
    setFolderId(id);
    // Selecting a folder is a files-mode action: Settings' "Scan now" and
    // folder navigation call this while the projects pane may be active, so
    // the selection has to bring the files pane back into view.
    saveMode("files");
    setMode("files");
    setVisitedModes(prev => (prev.files ? prev : { ...prev, files: true }));
    setActiveView("library");
  }, []);

  const handleModeChange = React.useCallback((next: LibraryMode) => {
    saveMode(next);
    setMode(next);
    setVisitedModes(prev => (prev[next] ? prev : { ...prev, [next]: true }));
    setActiveView("library");
  }, []);

  const handleOpenProject = React.useCallback((id: string) => {
    setOpenProjectId(id);
    setActiveView("library");
  }, []);

  // A website import that created or joined a project lands the user on it.
  // The project list only loads once projects mode was visited, so the bump
  // of `assetsVersion` (the list effect's other dependency) refetches it even
  // when the import happened from a first, files-mode session.
  const handleProjectImported = React.useCallback(
    (projectId: string) => {
      handleModeChange("projects");
      setOpenProjectId(projectId);
      setAssetsVersion(n => n + 1);
    },
    [handleModeChange],
  );

  const handleCloseProject = React.useCallback(() => {
    setOpenProjectId(null);
  }, []);

  // A project edit (title, cover, ...) returns the fresh row, so the card grid
  // and the sidebar pick it up without a refetch. The cover thumbnail URL is
  // already cache-busted server-side.
  const handleProjectUpdated = React.useCallback((project: Project) => {
    setProjects(list => (list ? list.map(item => (item.id === project.id ? project : item)) : list));
  }, []);

  // One handler for all three effects of a delete, so React batches them into a
  // single render: the open project is already closed on the render where its
  // row disappears, and the version bump refetches counts.
  const handleProjectDeleted = React.useCallback((id: string) => {
    setProjects(list => (list ? list.filter(project => project.id !== id) : list));
    setOpenProjectId(null);
    setAssetsVersion(n => n + 1);
  }, []);

  // The project list is App-owned: the sidebar and the project grid both render
  // from it, and a mutation elsewhere (`assetsVersion`) can change its counts.
  React.useEffect(() => {
    if (!visitedModes.projects) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listProjects();
        if (!cancelled) setProjects(list);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          handleUnauthorized();
          return;
        }
        console.error(err);
        notifyError("Failed to load projects.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visitedModes.projects, assetsVersion, handleUnauthorized]);

  const handleLogout = () => {
    const refresh = readRefreshToken();
    if (refresh) void logout(refresh);
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

  /**
   * Swap the stored refresh token for a fresh token pair and persist both. The
   * refresh token is single-use server-side, so the rotated one has to replace
   * the old value before the next refresh can happen.
   */
  const refreshSession = React.useCallback(async () => {
    const refresh = readRefreshToken();
    if (!refresh) return false;
    try {
      const res = await refreshToken(refresh);
      storeToken(res.token);
      if (res.refresh_token) storeRefreshToken(res.refresh_token);
      setToken(res.token);
      setTokenTtl(res.expires_in);
      return true;
    } catch {
      return false;
    }
  }, []);

  React.useEffect(() => {
    if (!token) return;
    if (tokenTtl === null && reloadRefreshFor.current !== token && readRefreshToken()) {
      // A reload restores the access token but not its age, so it may already
      // have expired. Trade the refresh token for a live one right away instead
      // of waiting for a timer computed from the fallback TTL. The ref makes
      // this one-shot per access token, so a double-invoked effect cannot spend
      // the same single-use refresh token twice.
      reloadRefreshFor.current = token;
      void (async () => {
        if (!(await refreshSession())) handleUnauthorized();
      })();
      return;
    }
    const ttl = tokenTtl ?? DEFAULT_REFRESH_SECONDS;
    const refreshMs = Math.max(
      5 * 60 * 1000,
      Math.min(ttl * 0.8 * 1000, ttl * 1000 - 5 * 60 * 1000)
    );
    const timer = window.setTimeout(async () => {
      if (!(await refreshSession())) handleUnauthorized();
    }, refreshMs);
    return () => window.clearTimeout(timer);
  }, [token, tokenTtl, refreshSession, handleUnauthorized]);

  React.useEffect(() => {
    if (ssoHandled.current) return;
    const { code, error } = readSsoFragment();
    if (!code && !error) return;
    ssoHandled.current = true;
    // Strip the fragment *before* the first await. The handoff code must not
    // survive a reload, a back-navigation or a screenshot, and a re-invoked
    // effect that finds nothing can no longer spend it a second time.
    clearSsoFragment();
    if (error) {
      setSsoError(error);
      setSsoPending(false);
      return;
    }
    if (!code) {
      setSsoPending(false);
      return;
    }
    const handoff = code;
    void (async () => {
      try {
        const res = await exchangeOidcCode(handoff);
        handleLogin(res.token, res.expires_in, res.refresh_token ?? "");
      } catch (err) {
        // The API's message is for the console only: the screen gets a frozen
        // copy value, never server or IdP free text. A 409 is the persistent
        // "no administrator has signed in locally yet" condition, where "please
        // try again" would be actively wrong advice, so it gets its own line.
        console.error(err);
        setSsoError(err instanceof OidcExchangeError && err.status === 409 ? "no_admin_bootstrap" : "exchange_failed");
      } finally {
        setSsoPending(false);
      }
    })();
  }, [handleLogin]);

  if (authRequired && !token) {
    // A handoff in flight renders a placeholder rather than <Login>, so the
    // local password form never flashes before the exchange lands.
    if (ssoPending) {
      return (
        <div className="min-h-screen flex items-center justify-center">
          <p className="text-sm text-muted">Signing you in...</p>
        </div>
      );
    }
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Login onSuccess={handleLogin} apiUp={apiUp} theme={resolvedTheme} ssoError={ssoError} />
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      <div className="library-rail">
        <ModeSwitch mode={mode} onChange={handleModeChange} />
        {/* `hidden` (the attribute, not a class) keeps the inactive pane mounted
            so its state survives mode switches. The shared <main> scroller may
            reset its scroll position on the switch; that is not part of the AC. */}
        <div hidden={mode !== "files"} className="min-h-0 flex-1">
          {visitedModes.files && (
            <Sidebar
              selectedId={folderId}
              onSelect={handleSelectFolder}
              onFoldersChanged={handleFoldersChanged}
              foldersVersion={folderVersion}
              onAssetsChanged={handleAssetsChanged}
              onUnauthorized={handleUnauthorized}
              onOpenSettings={() => setActiveView("settings")}
              onOpenAudit={() => setActiveView("audit")}
              activeView={activeView}
              role={role}
            />
          )}
        </div>
        <div hidden={mode !== "projects"} className="min-h-0 flex-1">
          {visitedModes.projects && (
            <ProjectSidebar
              projects={projects}
              selectedId={openProjectId}
              onSelect={handleOpenProject}
              activeView={activeView}
              onOpenSettings={() => setActiveView("settings")}
              onOpenAudit={() => setActiveView("audit")}
              role={role}
            />
          )}
        </div>
      </div>
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
              alt="Curiarium"
              className="h-40 w-auto max-w-[520px]"
            />
          )}
          <div className="flex flex-wrap items-center gap-3">
            {/* Uploads always land in a files folder, so projects mode hides the bar. */}
            {activeView === "library" && mode === "files" && (
              <UploadBar
                canWrite={canWrite}
                folderId={folderId}
                makerworldCookie={settings.makerworld.cookie}
                thingiverseCookie={settings.thingiverse.cookie}
                onUploaded={handleAssetsChanged}
                onUnauthorized={handleUnauthorized}
                onProjectImported={handleProjectImported}
              />
            )}
            {activeView !== "library" && (
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
        {/* Same lazy-mount rule as the rail: each mode's grid is created on
            first visit and then stays mounted (only hidden), so search, sort,
            selection and loaded pages survive a mode switch. */}
        {activeView === "library" && visitedModes.files && (
          <div hidden={mode !== "files"}>
            <AssetGrid
              canWrite={canWrite}
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
              onProjectsChanged={handleAssetsChanged}
            />
          </div>
        )}
        {activeView === "library" && visitedModes.projects && (
          <div hidden={mode !== "projects"}>
            <ProjectView
              canWrite={canWrite}
              projects={projects}
              selectedProjectId={openProjectId}
              onOpenProject={handleOpenProject}
              onCloseProject={handleCloseProject}
              onProjectUpdated={handleProjectUpdated}
              onProjectDeleted={handleProjectDeleted}
              onAssetsChanged={handleAssetsChanged}
              assetsVersion={assetsVersion}
              onUnauthorized={handleUnauthorized}
              slicerSettings={settings.slicer}
              engravingSettings={settings.engraving}
              previewSettings={settings.previews}
              theme={resolvedTheme}
            />
          </div>
        )}
        {activeView === "settings" && (
          <React.Suspense fallback={<SettingsLoading />}>
            <Settings
              settings={settings}
              onChange={setSettings}
              onAssetsChanged={handleAssetsChanged}
              onFoldersChanged={handleFoldersChanged}
              onUnauthorized={handleUnauthorized}
              onSelectFolder={handleSelectFolder}
              role={role}
            />
          </React.Suspense>
        )}
        {activeView === "audit" && !roleAtLeast(role, "admin") && <NotPermitted />}
        {activeView === "audit" && roleAtLeast(role, "admin") && (
          <AuditLog onUnauthorized={handleUnauthorized} />
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
      {/* Fixed-position sibling of the layout: it never affects App's layout.
          Gated too: its only action is a retry, which is a write. A demotion to
          viewer while an upload is still running would otherwise leave a
          visible button whose click is refused with a raw 403. */}
      {canWrite && (
        <UploadQueuePanel onUploaded={handleAssetsChanged} onUnauthorized={handleUnauthorized} />
      )}
    </div>
  );
}
