import { ScrollText, Settings as SettingsIcon } from "lucide-react";

type Props = {
  activeView?: "library" | "settings" | "audit";
  onOpenSettings?: () => void;
  onOpenAudit?: () => void;
};

/**
 * Settings/Audit entry points shared by both sidebars, so those destinations
 * stay reachable regardless of the library mode.
 */
export default function SidebarFooter({
  activeView = "library",
  onOpenSettings,
  onOpenAudit,
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
      <button
        type="button"
        onClick={onOpenAudit}
        className={`sidebar-settings ${activeView === "audit" ? "is-selected" : ""}`}
        aria-label="Audit log"
      >
        <ScrollText className="h-4 w-4" />
        <span>Audit log</span>
      </button>
    </div>
  );
}
