# MakersVault v5.1.0

**Working draft:** The highlights below include later local roadmap work through
Gate 13C security hardening. The qualified Gate 5 source remains `f6ff55b` at schema 5. These edits do
not replace that frozen candidate or establish a new release artifact.

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
- Persistent identities use Argon2id credentials and revocable cookie sessions.
  Three fixed shared-vault roles now map to deny-by-default server permissions;
  Viewer remains read/download/export/handoff-only, Member manages recoverable
  shared content, and Administrator owns settings, durable jobs, and irreversible
  deletion. Administrators can create and manage accounts with temporary-password
  replacement, affected-session revocation, recent password confirmation, and
  last-Administrator protection.
- Mandatory durable audit records cover login outcomes, identity/session
  administration, settings/jobs, content changes and imports, exports, handoff,
  Trash/permanent deletion, and audit reads without storing bodies, query strings,
  passwords, tokens, filenames, notes, URLs, or filesystem paths. Administrators
  can review cursor-paginated outcomes in Settings.
- Optional password-plus-passkey MFA uses origin-bound WebAuthn ceremonies while
  retaining the password as the first factor. Users manage their own credentials;
  Administrators can stage Require Administrators or Require Everyone only after
  targeted accounts enroll, and can explicitly reset another account's MFA without
  changing its password.
- Ordered additive migrations, stopped matched backups, clean recovery, and exact
  rollback are source-owned and tested.
- Current local remote-import hardening uses strict IDNA2008 hostname validation
  and one canonical destination across DNS, HTTP Host, TLS and redirects. Vitest
  and HTTPX2 development dependencies receive targeted security updates; native
  container findings still require explicit dispositions before release clearance.
- The API test/runtime base now pins six Debian stable security updates for gzip,
  libc, PCRE2, SQLite and Perl. This keeps Python, schema and user workflows
  unchanged; it is not a distribution migration or blanket security clearance.
  See the [local native-update checkpoint](evidence/gate-13/SECURITY_NATIVE_UPDATE_RESULTS.md)
  and [vendor/byte reconciliation](evidence/gate-13/SECURITY_RECONCILIATION_RESULTS.md):
  26 fixes are verified in the installed packages, while remaining native decisions
  and raw scanner findings stay explicit.

## Upgrade requirements

Current local Docker hardening enables no-new-privileges and explicit capability
allowlists. The API drops all capability sets before serving requests; web runs
without capabilities. Startup ownership and trusted offline recovery remain
supported, without new upload/library or container resource limits. Custom
deployments must retain equivalent controls; native findings are not waived.

Upgrade API, web, and bridge as one matched release. Do not use `latest`. Before
pulling images, follow the tested
[v5.1 upgrade procedure](https://github.com/VincentCinque/MakersVault/blob/v5.1.0/makervault/docs/UPGRADE_V5.1.md)
and create an off-host verified archive using
[Backup and Recovery](https://github.com/VincentCinque/MakersVault/blob/v5.1.0/makervault/docs/BACKUP_AND_RECOVERY.md).

The current development schema is version 17. Existing model bytes are not rewritten merely by
applying its additive migrations. Production deployments must provide a unique
administrator password and a distinct random signing secret. Changing the signing
secret invalidates old browser sessions and pending authentication ceremonies but
does not remove vault data. Passkey use additionally requires one stable HTTPS RP ID
and exact origin as documented in the secure-deployment guide.

Unusual internationalized import hostnames that require Unicode case/compatibility
mapping or contain malformed labels are now rejected. Valid canonical Unicode and
punycode hosts remain supported; stored URLs and original model bytes are unchanged.

## Artifacts and verification

- API image: `shotgunwilly555/makersvault-api:v5.1.0`
- Web image: `shotgunwilly555/makersvault-web:v5.1.0`
- Bridge binaries: Linux, Windows, and macOS on amd64 and arm64
- `SHA256SUMS`, per-artifact SPDX JSON SBOMs, and `release-manifest.json`
- GitHub/Sigstore provenance for checksummed files and image digest/SBOM attestations

Verify downloaded files with `sha256sum --check SHA256SUMS`. Image and file
attestations can be verified with the GitHub CLI against this repository.

## Recorded release-candidate performance

The repeatable 20-file preview corpus totals 66,037,534 bytes and covers small,
medium, large, multipart, multiplate, image-heavy, malformed, STL, OBJ, 3MF, and
STEP inputs. In the headless Chromium release-image run, cold cards appeared in
361 ms and settled in 5.16 s with at most one original-file request active. The warm
run showed cards in 135 ms, issued 14 static-thumbnail requests and zero original
model requests, and recorded zero long tasks. An explicit detail preview completed
in 269 ms; the LightBurn preview also made zero warm source requests.

The 600-asset/104-folder organization workflow passed in Chromium 151, Firefox 153,
and WebKit 26.5. Chromium enforced the deterministic performance budgets (347 ms to
first cards, 139 ms to load the next page, 99 ms exact search, and 102 ms folder
open); Firefox and WebKit ran the same functional assertions and recorded their
timings without treating headless software/container startup as an end-user hardware
benchmark. See [Gate 5 evidence](evidence/gate-5/RESULTS.md) for the full matrix.

## Intentional boundaries

v5.1 does not add manual thumbnail uploads, account self-registration, private
libraries or per-object ACLs, passwordless/TOTP authentication, recovery codes, API
keys or OIDC/SSO, slicing or printer control, automatic STEP card previews,
continuous NAS watching, or server-wide “select every match.” See the complete
[Known Limitations](https://github.com/VincentCinque/MakersVault/blob/v5.1.0/makervault/docs/KNOWN_LIMITATIONS.md).

The full change inventory is in
[CHANGELOG.md](https://github.com/VincentCinque/MakersVault/blob/v5.1.0/CHANGELOG.md).
