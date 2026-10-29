import { ScrollText, Settings as SettingsIcon } from "lucide-react";

import { roleAtLeast, type Role } from "../lib/auth";

type Props = {
  activeView?: "library" | "settings" | "audit";
  onOpenSettings?: () => void;
  onOpenAudit?: () => void;
  /** `null` until `/me` answers; admin-only entries stay hidden until then. */
  role?: Role | null;
};

/**
 * Settings/Audit entry points shared by both sidebars, so those destinations
 * stay reachable regardless of the library mode. Admin-only gating lives here
 * only, so the two sidebars cannot drift apart.
 */
export default function SidebarFooter({
  activeView = "library",
  onOpenSettings,
  onOpenAudit,
  role = null,
}: Props) {
  return (
    <div className="sidebar-footer flex flex-col gap-1">
      <button
        type="button"
        onClick={onOpenSettings}
        className={`sidebar-settings ${activeView === "settings" ? "is-selected" : ""}`}
        aria-label="Settings"
      >
        <SettingsIcon className="h-4 w-4" />
        <span>Settings</span>
      </button>
      {roleAtLeast(role, "admin") && (
        <button
          type="button"
          onClick={onOpenAudit}
          className={`sidebar-settings ${activeView === "audit" ? "is-selected" : ""}`}
          aria-label="Audit log"
        >
          <ScrollText className="h-4 w-4" />
          <span>Audit log</span>
        </button>
      )}
    </div>
  );
}
