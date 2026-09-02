export type VaultRole = "administrator" | "member" | "viewer";

export type VaultCapabilities = {
  readVault: boolean;
  downloadContent: boolean;
  exportContent: boolean;
  createHandoff: boolean;
  manageContent: boolean;
  openTrash: boolean;
  restoreTrash: boolean;
  manageServerSettings: boolean;
  manageDurableJobs: boolean;
  deletePermanently: boolean;
  emptyTrash: boolean;
};


const VIEWER: VaultCapabilities = Object.freeze({
  readVault: true,
  downloadContent: true,
  exportContent: true,
  createHandoff: true,
  manageContent: false,
  openTrash: false,
  restoreTrash: false,
  manageServerSettings: false,
  manageDurableJobs: false,
  deletePermanently: false,
  emptyTrash: false,
});

const MEMBER: VaultCapabilities = Object.freeze({
  ...VIEWER,
  manageContent: true,
  openTrash: true,
  restoreTrash: true,
});

const ADMINISTRATOR: VaultCapabilities = Object.freeze({
  ...MEMBER,
  manageServerSettings: true,
  manageDurableJobs: true,
  deletePermanently: true,
  emptyTrash: true,
});


export function capabilitiesForRole(role: VaultRole): VaultCapabilities {
  switch (role) {
    case "administrator":
      return ADMINISTRATOR;
    case "member":
      return MEMBER;
    case "viewer":
      return VIEWER;
  }
}
