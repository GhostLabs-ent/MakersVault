# Gate 13B — current-build lifecycle and harness qualification

**Opened:** 2026-09-05, after owner acceptance of 13A at `c2e9f94`.

**Authority record:** `79edd47`; local bounded harness repairs and generated
lifecycle verification only. No production feature, policy, schema or publication
change is authorized by this slice.

**Status:** READY FOR OWNER EVIDENCE REVIEW; not accepted.

**Tested implementation:** `2c68d70dcf36e9e912a6caf23fa33026c7a665bb`.

**Verification date:** 2026-09-05 local / 2026-09-06 UTC. Schema 17, raw outer
format 1 / recovery contract 6, and application behavior remain unchanged.

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

## Committed verification

`make verify` returned zero on `2c68d70`; its lifecycle result explicitly reports
`dirty:false`, `version:development-gate13b` and that full source revision. At entry,
the only untracked file was the unrelated desktop draft. The web test image was
also run directly, so its result does not rely on a cached build layer.

| Check | Result |
|---|---|
| Complete repository gate | PASS, including the new harness/lifecycle targets |
| API | **313 passed in 138.82 s** |
| Web direct test image | Typecheck PASS; **32 tests / 11 files passed**; production build PASS |
| Fixture assertions | **7 Python tests**; missing revocation, changed credentials/policy/content, nonempty volume seeding, and unapproved preview differences cannot silently pass |
| Shared session client | **5 Node tests**; all three consuming browser harnesses also pass syntax checks |
| Canonical production HTTPS lifecycle | PASS: schema **4 → 17**, contract-6 restore, pre-start invalidation, startup audit, exact stopped schema-4 rollback and fresh install |
| Supplied-image smoke entry point | `current-image-smoke.py` separately PASS on the same two immutable IDs and expected version/revision; production web shell, cookie/CSRF, restart, non-root and logout checks |
| Portable startup | PASS: schema **17 export → 12 clean import → 17 startup**; fresh identity only; **18 portable members** compared before and after startup with the exact documented transitions |
| Other repository targets | Bridge tests/build; Compose/security checks; schema-17 development container smoke; Chromium 151 virtual passkey registration/step-up/required-Administrator/login; static release contract PASS |

Immutable **local development** image IDs used by the lifecycle (not registry
release digests):

```text
API sha256:9b8b729644b3938584b293e90713bc40971afd612539dfca4daa94854c018a85
Web sha256:80f1dcdf8f853d2af8b924c046fbf266b3f4db3e755638b4e5c7cb0bf28036f8
```

The lifecycle asserts both OCI version/revision labels and runs these IDs, not
mutable tags. Existing browser-data freshness and >500 kB bundle warnings remain
visible; no dependency or bundling change was made to suppress them.

The secret-free machine-readable lifecycle result is frozen in
[`lifecycle.json`](lifecycle.json). Reproduction commands from the repository root:

```bash
make verify
docker run --rm makersvault-web-gate0-test
python3 makervault/scripts/current-image-smoke.py \
  --api-image sha256:9b8b729644b3938584b293e90713bc40971afd612539dfca4daa94854c018a85 \
  --web-image sha256:80f1dcdf8f853d2af8b924c046fbf266b3f4db3e755638b4e5c7cb0bf28036f8 \
  --version development-gate13b \
  --revision 2c68d70dcf36e9e912a6caf23fa33026c7a665bb
git diff --check
```

The thin shell compatibility wrappers delegate to these Python entry points.
The standalone image check was executed through its Python entry point; it is
not a new release build.

### Failure/interruption evidence by layer

The joined production drill proves three operator refusal paths leave the target
snapshot unchanged. The complete 313-test run also executes:

- `test_mvault_import.py`: capacity failure before publication; failure and
  KeyboardInterrupt after storage publication; next-invocation journal recovery;
  stable CLI cancellation; rejection of untrusted cleanup paths.
- `test_mvault_export.py`: interrupted catalog writes, capacity failure and stable
  CLI cancellation without publishing partial output.
- `test_migrations.py`: prior-version idempotence, failed migration not recorded,
  recorded-name mismatch and unknown-newer-schema startup refusal.
- Schema-17 recovery/session/passkey regressions: preserved public credentials,
  revoked sessions/ceremonies and audited stopped recovery.

Those are source-owned injected failure/recovery tests, not a physical host power-
loss experiment or a live mid-copy interruption of a user vault. Raw rollback is
verified byte-for-byte while stopped; starting the old frozen candidate remains
its historical matched-image proof, not a new Gate 13B execution.

## Isolation, limits and next checkpoint

Only generated fixtures and unique `mv-g13-*` projects are touched by the lifecycle
drill. Cleanup removes their containers/networks/volumes and private temporary
files; built local development images remain. The desktop draft and any unrelated
running workload are excluded. Raw/authentication material is never a report field.
After the committed lifecycle and standalone smoke, read-only Docker inventories
showed no remaining `mv-g13-*` containers, volumes or networks. No user vault data
was removed; the deleted test fixtures were generated and reproducible.

13C still owns the complete current browser/corpus/mounted-import matrix (including
current Trash UI expectations), platform/physical-device evidence, fresh dependency
advisories and operator TLS/release-readiness review. No historical browser timing
is reused as a current result. The qualified unpublished Gate 5 candidate remains
`f6ff55b`; release scope/revision and any push, tag, image publication or deployment
require separate owner decisions. Gate 12 remains deferred to desktop.

**Accepted by/date:** Pending; this document does not accept 13B or open 13C.
