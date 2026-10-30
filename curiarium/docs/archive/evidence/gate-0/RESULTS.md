# Gate 0 Evidence Review

> **Historical document — kept for provenance, not as a description of the
> current system.** Written for upstream's v5.1 gate process before this fork
> diverged; its counts, schema versions, roadmap and scope are stale. The
> authoritative documents are listed in [../README.md](../README.md).


**Gate:** 0 — Establish the reproducible baseline and safety harness

**Status:** Evidence review; immutable baseline committed and locally verified;
remote CI pending

**Evidence date:** 2026-08-14

**Starting commit:** `80ddc5bb8849c0532ecf4de91010e450df28b940`

**Immutable source baseline:** `1231565642b8541a7ad36ba4ffdeb2da9527ef89`

## Objective result

The preserved v5.1 working application now has explicit repository ownership,
versioned SQLite migrations, source-owned verification commands, CI definitions,
canonical deployment manifests, a configuration inventory, and a reconciled
security ledger. No real user database or library was modified.

## Owner decisions required

ADRs 0001 and 0002 were accepted by the owner on 2026-08-14. The Compose ADR now
states explicitly that Curiarium remains a two-container application while the
web container provides a one-host `/api` gateway.

The clean Gate 0 baseline was committed and verified locally on 2026-08-14.
The remaining external action is owner authorization to push the baseline so its
GitHub Actions run can be observed.

## Files and data affected

- Source, tests, lockfiles, Compose definitions, CI, ignore policy, and
  documentation changed.
- 8,311 generated/runtime paths were removed from the Git index only.
- Local `api/curiarium.db`, `node_modules`, `dist`, bytecode, and the bridge executable
  remain on disk and are now ignored.
- The real `api/curiarium.db` was mounted read-only, copied inside a disposable
  container, and migrated only at `/tmp/curiarium.db`.
- Smoke verification used project-scoped named volumes and removed them on exit.

## Migration and rollback evidence

The migration ledger records immutable version/name pairs in `schema_migration`.
The current version is 3.

Verified behaviors:

- Fresh database reaches version 3.
- Programmatic pre-v5.1 fixture reaches version 3.
- Repeating migration is idempotent.
- Failed migration is not recorded.
- Recorded version/name mismatch stops startup.
- A database containing an unknown newer version stops an older build.
- A copy of the existing local database reaches version 3.
- Folder-scoped name uniqueness and legacy storage-path backfill are retained.

The migrations are additive. Rollback for a release remains restoration of a
matched database and managed-storage snapshot; Gate 5 proves that operator flow.

## Verification results

| Check | Result | Evidence |
|---|---|---|
| Repository ignore ownership | Pass | `git ls-files -ci --exclude-standard` returns zero. |
| API/migrations | Pass | 8 tests under Python 3.11. |
| Existing-database copy | Pass | Disposable copy reports schema version 3. |
| Web type check | Pass | `tsc --noEmit`. |
| Web tests | Pass | 1 Vitest file, 3 tests. |
| Web production build | Pass | Vite 5.4.21, 1,595 modules transformed. |
| Bridge tests/build | Pass | Go 1.21.13 tests and executable compilation. |
| Compose syntax | Pass | Local, canonical production, compatibility alias, and smoke overlay. |
| Container smoke | Pass | UI/runtime config, direct API, and same-origin `/api/health` reachable; API PID 1 UID 1000; web PID 1 UID 101; schema 3. |
| Full local command | Pass | `make verify`. |
| CI definition | Ready, not remotely observed | GitHub Actions invokes the same Make targets after a commit/push. |

## Known build warnings

The web production build reports:

- Stale browser-compatibility metadata.
- OCCT imports of Node `path` and `crypto` being externalized for browser use.
- A generated JavaScript chunk above 500 kB.

These warnings predate the Gate 0 harness and are now visible/repeatable. They do
not fail the current build. Browser runtime behavior and bundle/preview budgets
are assigned to Gate 2; dependency metadata/toolchain upgrades begin in Gate 1.

## Security result

The authoritative disposition is
[GATE_0_REVALIDATION.md](../../security/GATE_0_REVALIDATION.md).

- 12 findings remain confirmed or partly mitigated and are assigned to later
  gates.
- The production Vite-server finding is resolved in the candidate.
- The v5.1 multi-user premise is superseded; authorization remains a Gate 11
  blocker before multi-user can ship.
- Repository/supply-chain hygiene is partially resolved; release checksums, SBOM,
  and provenance remain Gate 5 work.
- Python auditing reports 52 overlapping advisory records in four runtime pins.
- npm production dependencies audit clean; two Vite/esbuild development-toolchain
  findings require a major toolchain upgrade.
- Go scanning reports zero called vulnerabilities.

These open security findings are expected Gate 1 inputs, not a claim that the
current beta is safe for unrestricted Internet exposure.

## Exit-criterion status

| Gate 0 exit criterion | Status |
|---|---|
| Current work preserved and generated ownership explicit | Passed |
| One documented API/web/bridge/container verification command | Passed |
| Fresh and representative old database converge through repeatable migrations | Passed |
| Canonical manifests and migration mechanism decided | Passed; owner accepted ADRs 0001 and 0002 on 2026-08-14 |
| Security findings revalidated without silent contradictions | Passed |
| Clean immutable source baseline | Passed at `1231565642b8541a7ad36ba4ffdeb2da9527ef89` |
| Remote CI result against immutable baseline | Pending push/workflow run |

## Residual risks and deferrals

- Gate 1 owns known credentials, scoped handoff grants, upload/archive limits,
  dependency upgrades, SSRF redirect/connection control, symlink containment,
  token/session risk decisions, ZIP path normalization, and security headers.
- Gate 2 owns preview/parser budgets and the current web bundle warning.
- Gate 5 owns full upgrade/restore proof, release provenance, checksums, and SBOMs.
- Gate 11 owns multi-user authorization and full session architecture.

## Next-gate recommendation

After the baseline is pushed and its CI result is observed, mark Gate 0 accepted
and begin Gate 1 with secure first-run configuration and bridge handoff design
before dependency or parser changes are merged independently.
