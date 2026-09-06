# Gate 13B — current-build lifecycle and harness qualification

**Opened:** 2026-09-05, after owner acceptance of 13A at `c2e9f94`.

**Authority record:** `79edd47`; local bounded harness repairs and generated
lifecycle verification only. No production feature, policy, schema or publication
change is authorized by this slice.

**Status:** Implementation complete; development drill passed. Clean committed
baseline verification and owner evidence review are pending.

## Implementation boundary

- Current preview/organization/mounted-import fixture clients use cookie sessions
  and exact Origin/CSRF mutation headers. No JWT fallback, redirect forwarding,
  externally persisted cookie, auth-header override, or production bypass exists.
- `scripts/gate13-lifecycle-drill.py` joins production-Compose upgrade, stopped raw
  backup/restore, rollback, portable clean import/startup and fresh-install smoke.
  `gate5-recovery-drill.sh` now invokes it; the original Gate 5 code/evidence remains
  reproducible from `f6ff55b`.
- `release-candidate-smoke.sh` delegates to a current image-identity/HTTPS/schema-17
  smoke. Supplied OCI identities are validated and immutable image IDs are run.
  This is not assembly or qualification of new release artifacts.
- `make verify-harness` and `make verify-lifecycle` join `make verify` and the same
  CI workflow. No CI run or remote publication is claimed from local changes.

## What the joined drill asserts

1. An exact stopped schema-4 backup exists before upgrade. Five legacy artifacts
   cover nested folders, renamed metadata, supporting PDF, internal prepared
   toolpath and summary, legacy thumbnail, interrupted preview, and available/
   absent external no-copy records. Upgrade to schema 17 preserves managed bytes
   and creates the expected five initial revisions.
2. Real HTTPS cookie sessions create an additional revision, Project membership
   and relationship, Machine and links, Trash, a Member, and a pending registration
   ceremony. An offline **public credential fixture** tests structural raw recovery;
   it is not evidence of a physical passkey ceremony.
3. Raw contract-6 restore preserves every stored byte and every table/row except
   the explicitly required copied-session revocation, challenge consumption and
   added recovery marker. The old cookie fails with the same signing secret,
   fresh sign-in works, and startup processes/audits recovery markers. No-copy
   files are unavailable without their separate mount and never modified.
4. Portable export is independently verified without changing its stopped source.
   Clean import reconstructs schema 12 with no identity tables. Staged SQLite and
   all stored-file hashes match the pair copied into empty production volumes.
   Re-export before startup preserves all portable catalogs/content/derived bytes,
   accounting only for the specified external-unavailable state.
5. Production startup migrates the portable instance to schema 17, creates only
   its new Administrator and Optional passkey policy, and rejects the source
   credentials. After startup the only additional portable difference allowed is
   the exact legacy 3MF preview transition described below.
6. Corrupt archive, nonempty raw target and nonempty portable target are refused
   without changing the original database/storage snapshot. Rollback restores the
   exact schema-4 database checksum, table rows and stored-file hashes, stopped;
   it does not run an old application against a migrated database.
7. A blank production installation serves the web shell and API through verified
   TLS, rejects anonymous API reads and invalid Origin/CSRF writes, retains uploaded
   bytes and sessions across restart, runs API/web non-root and revokes logout.
   The shared Node benchmark helper also performs real login/upload/read/Trash/
   logout through this production cookie boundary.

## Discoveries and corrections

- Disposable TLS requires a valid production RP host (`vault.example.test`) and
  writable unprivileged Nginx temporary paths. Fixture-only loopback resolution
  retains certificate hostname validation; no global DNS/trust change, insecure
  TLS flag or development-auth production override is used.
- Logout returns **204**, not 200. Both current clients assert the real contract.
- **Docker portable staging:** the importer atomically renames sibling paths. A
  mounted storage root cannot be renamed and its parent is not a writable staging
  directory. The harness imports beneath a private writable parent, verifies the
  completed pair, then populates only empty volumes. The operator workflow now
  documents this restriction; raw restore is still the direct-volume recovery path.
- **Derived preview reconciliation:** import omits operational preview timestamps.
  `asset_service.backfill_embedded_thumbnails` re-evaluates the fixture's timestamp-
  free legacy 3MF from `skipped_policy / embedded_complexity` to `pending / null`.
  An exact pre-start re-export proves import did not lose the supplied state;
  post-start assertions permit only this named Artifact/current Revision change.
  All other fields, graph records and stored payloads remain binding. This is not
  a broad preview exclusion or a new preview-rendering performance claim.

## Evidence to freeze after committed verification

The development run passed all joined assertions and compared **18 portable
members**. Its dirty-source result is debugging evidence only. Record the clean
revision, immutable local image IDs, complete verification and failure/interruption
regression results here before marking 13B ready for owner review.

## Isolation, limits and next checkpoint

Only generated fixtures and unique `mv-g13-*` projects are touched by the lifecycle
drill. Cleanup removes their containers/networks/volumes and private temporary
files; built local development images remain. The desktop draft and any unrelated
running workload are excluded. Raw/authentication material is never a report field.

13C still owns the complete current browser/corpus/mounted-import matrix (including
current Trash UI expectations), platform/physical-device evidence, fresh dependency
advisories and operator TLS/release-readiness review. No historical browser timing
is reused as a current result. The qualified unpublished Gate 5 candidate remains
`f6ff55b`; release scope/revision and any push, tag, image publication or deployment
require separate owner decisions. Gate 12 remains deferred to desktop.

**Accepted by/date:** Pending; this document does not accept 13B or open 13C.
