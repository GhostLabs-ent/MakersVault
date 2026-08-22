# MakersVault v5.1.0

MakersVault v5.1.0 is a confidence release: faster library browsing, clearer
organization, safer self-hosting, and richer workshop context without turning the
vault into a slicer, printer controller, or multi-user cloud service.

## Highlights

- Bounded persistent model/LightBurn previews use static thumbnails on repeat visits
  and show durable fallback/retry states instead of freezing the library.
- Nested folders, breadcrumbs, incremental loading, folder-path search, and visible
  bulk move/tag/download workflows scale to larger libraries.
- Human-readable folder-scoped model names, creator/collection/tags/notes,
  configurable storage templates, supporting documents, and prepared-print summaries
  keep useful context with each model.
- Prepared toolpaths remain hidden behind summary and slicer handoff. MakersVault does
  not slice files or send jobs to a printer.
- Mounted-library scans are deliberate, restartable, observable, and explicit about
  managed-copy versus externally owned index-in-place content.
- Production auth, browser/host boundaries, remote import, archives/uploads/images,
  free-space reserve, mounted paths, and workstation handoff fail safely under
  explicit limits.
- Ordered additive migrations, stopped matched backups, clean recovery, and exact
  rollback are source-owned and tested.

## Upgrade requirements

Upgrade API, web, and bridge as one matched release. Do not use `latest`. Before
pulling images, follow the tested
[v5.1 upgrade procedure](https://github.com/VincentCinque/MakersVault/blob/v5.1.0/makervault/docs/UPGRADE_V5.1.md)
and create an off-host verified archive using
[Backup and Recovery](https://github.com/VincentCinque/MakersVault/blob/v5.1.0/makervault/docs/BACKUP_AND_RECOVERY.md).

The release schema is version 5. Existing model bytes are not rewritten merely by
applying its additive migrations. Production deployments must provide a unique
administrator password and a distinct random signing secret. Changing the signing
secret invalidates old browser sessions but does not remove vault data.

## Artifacts and verification

- API image: `shotgunwilly555/makersvault-api:v5.1.0`
- Web image: `shotgunwilly555/makersvault-web:v5.1.0`
- Bridge binaries: Linux, Windows, and macOS on amd64 and arm64
- `SHA256SUMS`, per-artifact SPDX JSON SBOMs, and `release-manifest.json`
- GitHub/Sigstore provenance for checksummed files and image digest/SBOM attestations

Verify downloaded files with `sha256sum --check SHA256SUMS`. Image and file
attestations can be verified with the GitHub CLI against this repository.

## Intentional boundaries

v5.1 does not add manual thumbnail uploads, multi-user identity/MFA/SSO, slicing or
printer control, artifact revisions/Trash/Projects, automatic STEP card previews,
continuous NAS watching, server-wide “select every match,” or source-content
hashing/provenance/duplicate detection. See the complete
[Known Limitations](https://github.com/VincentCinque/MakersVault/blob/v5.1.0/makervault/docs/KNOWN_LIMITATIONS.md).

The full change inventory is in
[CHANGELOG.md](https://github.com/VincentCinque/MakersVault/blob/v5.1.0/CHANGELOG.md).
