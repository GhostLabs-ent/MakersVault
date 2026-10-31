// Public surface of the API client. Explicit named re-exports only: a wildcard
// re-export would leak the internal helpers (`assertOk`, `readErrorMessage`,
// `apiBase`, `primeListGrants`). Inline `type` markers keep the type-only names
// erasable under isolated-module transforms; a value-position type re-export
// would fail the build.

export { getApiBase } from "./baseUrl";
export { UnauthorizedError, FORBIDDEN_MESSAGE, type HealthInfo, apiHealth } from "./http";
export { UploadRequestError, type UploadTransportOptions, uploadAsset, uploadGeneratedThumbnail, uploadAssetFile } from "./upload";
export { type Asset, type PreparedPrint, type AssetFile, type AssetFileLimits, type ListAssetsResult, type BatchFailure, type BatchTagsResult, type BatchMetaChange, type BatchMetaResult, type BatchFolderResult, type BatchDeleteResult, type AssetDeleteResult, type SnapshotNotice, type AssetDeletePreview, listAssets, listTags, listCreators, setTags, batchSetTags, batchSetMeta, listAssetFiles, listAssetFileLimits, renameAssetFile, reorderAssetFiles, deleteAssetFile, deletePreparedPrint, updateAssetMeta, deleteAsset, batchDeleteAssets, getAssetDeletePreview, renameAsset, updateAssetFolder, batchMoveAssets } from "./assets";
export { type ImportInspectInfo, type ZipEntryInfo, type ImportZipResult, importFromLink, inspectImportLink, listImportZipEntries, importZipFromLink, type ImportProjectResult, importToProject } from "./imports";
export { type Project, type ProjectPatch, type ProjectCreate, type ProjectMembersResult, type ProjectRemovalResult, listProjects, createProject, listProjectAssets, updateProject, deleteProject, addProjectAssets, removeProjectAssets } from "./projects";
export { type Folder, type FolderDeletePreview, type FolderDeleteResult, listFolders, createFolder, updateFolder, deleteFolder, getFolderDeletePreview } from "./folders";
export { type TrashEntry, type TrashList, type TrashPurgeResult, getTrash, purgeTrash } from "./trash";
export { downloadZip, downloadFolderZip, downloadAsset } from "./downloads";
export { fileUrl, assetFilePreviewUrl, stableFileUrl } from "./mediaUrls";
export { mintFileGrants } from "./grants";
export { type MountImportSettings, type StorageSettings, getMountImportSettings, updateMountImportSettings, getStorageSettings, updateStorageSettings, type StorageVolumeCapability, type StorageCapabilities, getStorageCapabilities, type LibraryScanStatus, getLibraryScanStatus, startLibraryScan, type ImportRunSummary, type ImportRunDetail, type ImportRunList, getImportRuns, getImportRun } from "./settings";
export { type Snapshot, type SnapshotList, type SnapshotCreated, type SnapshotPrune, type SnapshotEntry, type SnapshotBrowse, type SnapshotRestore, type SnapshotDeleteResult, type SnapshotRetention, listSnapshots, takeSnapshot, getSnapshotRetention, updateSnapshotRetention, browseSnapshot, restoreSnapshot, deleteSnapshot } from "./snapshots";
export { type AuthTokens, login, refreshToken, type Me, getMe, logout, type OidcStatus, type OidcExchangeResult, getOidcStatus, oidcStartUrl, exchangeOidcCode, OidcExchangeError, SSO_ERROR_COPY, ssoErrorCopy, type MfaChallenge, isMfaChallenge, MfaError, MFA_CODE_REJECTED, MFA_CHALLENGE_EXPIRED, type MfaStatus, getMfaStatus, type MfaEnrolment, mfaEnrol, type MfaRecoveryCodes, mfaConfirm, mfaDisable, mfaRegenerateRecoveryCodes, type MfaStepUpResult, mfaStepUp, type MfaPolicy, setMfaPolicy, mfaVerify } from "./auth";
export { type AuditEvent, type AuditQuery, type AuditPage, listAuditEvents } from "./audit";
export { type UserSession, listSessions, revokeSession, listUserSessions, revokeUserSession } from "./sessions";
export { type User, type UserCreate, type UserPatch, type PasswordReset, listUsers, createUser, updateUser, resetUserPassword } from "./users";
