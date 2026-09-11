# Gate 13C — approved runtime privilege containment

**Owner approval:** bounded implementation proposed in
[S04 decisions](SECURITY_RESIDUAL_DECISIONS.md). **Implementation:**
`ea17494b610f399b3e9d240748c2aab20e0d8aa5`, local only.
**Date:** September 10, 2026 (America/New_York); captured UTC runs extend into September 11.

**Status:** implementation and full verification complete; final exact-image
audits match the successful lifecycle images. **S04 risk acceptance remains open.**

**Subsequent owner review:** [the disposition proposal](SECURITY_DISPOSITION_PROPOSAL.md)
now supplies named-owner/expiry conditions and recommends E11 exclusions, R59
temporary local-qualification exceptions and H10 holds. Nothing is accepted by
preparing that package; its CLI-specific evidence refines one earlier exclusion.

## Shipped behavior and scope

Both canonical Compose manifests now set `no-new-privileges:true`, drop all default
capabilities, and permit only the API's six initialization/recovery capabilities.
The compatibility alias includes production Compose and requires no duplicated
service definition. Web receives no capabilities.

| Capability retained for API initialization / operator recovery | Necessity evidence |
|---|---|
| CHOWN | Omitting it fails account setup while writing gshadow; ownership changes are also part of startup/recovery |
| SETUID | Omitting it fails the intended UID transition |
| SETGID | Omitting it fails the intended GID transition |
| SETPCAP | Omitting it fails the explicit bounding-set drop |
| DAC_OVERRIDE | Trusted offline operations must read private, differently owned snapshot files; removing it fails the private-file fixture |
| FOWNER | Trusted extraction must restore metadata after restoring ownership; removing it fails chmod on the differently owned fixture |

This is a tested small set for the supported startup **and recovery** operations,
not a claim that every capability is needed for every fresh startup. After setup,
the API entrypoint explicitly clears inheritable, ambient and bounding sets and
sets no-new-privileges before executing the requested application. Under the normal
non-root PUID configuration, effective/permitted sets are empty too. If the
transition fails, the application does not start. The strengthened smoke checks
inspect application PID 1 itself, not an unrelated `docker exec` process.

No-new-privileges is inherited by children and prevents exec-time privilege gains;
bounding-set removal must be accompanied by removing inherited capabilities.
[Upstream setpriv manual](https://man7.org/linux/man-pages/man1/setpriv.1.html).
Docker's capability and security options are a distinct deployment boundary from
the application's UID drop. [Docker documentation](https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities).

PUID/PGID configuration, account setup, minimal/default and opt-in recursive volume
ownership, existing model/metadata bytes, read-only import mounts, and trusted
offline recovery are retained. No upload/library quota, container memory/CPU/PID
cap, read-only-root conversion, network topology restriction, base-image migration,
native package removal, schema migration or dependency-lock change was introduced.
The web application code is unchanged. No manual-thumbnail UI or slicing is added.

These are Compose/entrypoint defaults, not configurable Administrator UI features.
Keep nonzero API PUID/PGID and the shipped entrypoint. Custom Compose, privileged
overrides, manual image launches and operator `exec`/entrypoint overrides are not
automatically covered. The operator tools intentionally retain the six-capability
set; they do not inherit the running API process's emptied bounding set. The root
filesystem remains writable for initialization and runtime configuration.
See [operator guidance](../../SECURE_DEPLOYMENT.md#container-privilege-boundary).

## Verification and retained failed attempts

- The first startup matrix failed when its JSON reader encountered the informational
  `usermod: no changes` line on restart. The helper now preserves startup messages
  and decodes the final probe record. This was a harness failure, not a discarded
  application regression; the original attempt and error remain captured.
- Corrected preflight passes **8 positive cases / 6 capability-removal negative
  controls**. Cases cover default fresh start, same-container restart, existing-volume
  recreation, custom IDs with recursive ownership, custom-ID existing volumes,
  pre-existing group reuse, private recovery reads and restored metadata.
- The same matrix passes on the exact named development API image. Application and
  child probes confirm five empty capability sets, no-new-privileges, refusal to
  acquire UID 0 or clear no-new-privileges, writable owned data/storage, and unchanged
  externally owned bytes on the read-only import mount.
- Old-image negative control fails as expected with `CapBnd=459`, using the previous
  API image and the same new fixture policy. That detects the missing entrypoint
  bounding-set drop; it is not a demonstrated exploit or a claim about old default
  Docker capability counts.
- **422 API tests** pass. **58 web tests** were reexecuted through the existing
  same-source test image, including type check and production build. The cached web
  build layer inside `make verify` is not presented as a separate test execution.
- **25 Python / 28 Node harness tests** pass. Rendered development, production and
  compatibility Compose policies are checked; weakened policy/privileged containers,
  missing process fields, root UID slots and every nonzero capability set are rejected
  by the new verifier tests. Existing authentication, passkeys, CSRF and release checks
  remain in the full gate.

Full `make verify` passes at clean `ea17494`: **exit 0 / 293.671 seconds**, including
the joined production-HTTPS lifecycle. The API (UID 1000), Nginx master and all
**16 workers** (UID 101) have five empty capability sets and no-new-privileges.
Schema 4→17 upgrade, contract-6 raw recovery with pre-start session revocation and
startup audit, portable 17→12→17 fresh-identity bootstrap, 18 portable members,
exact stopped schema-4 rollback and nonempty/corrupt-target refusals all pass.
Existing external bytes and model/preview bytes survive the checked boundaries.
The passkey ceremony uses Chromium's virtual authenticator, not physical keys.

The generated-preview smoke supplies synthetic browser-generated PNG bytes through
the existing internal persistence endpoint, checks native image decode/JPEG output
and exact thumbnail bytes after restart. This proves the server-side preview storage
path under containment, not browser geometry rendering, performance qualification,
physical printer behavior or an end-user image-upload feature.

The native component probe is separately run without network, vault mounts or app
startup. Components equal the previous hardening observations, including Perl
module presence/absence, 64-bit pointers, SQLite FTS5/SESSION and zlib versions.
Its extra read-only filesystem/resource limits are probe-only and are **not**
shipped defaults; only the actual-process/Compose checks establish product policy.

## Exact images and fresh advisory evidence

| Image | Immutable development ID |
|---|---|
| API | `sha256:40aef54d6acf598ce49197d1aac966c96cc38ddd887ca10feff6a3ef4a74edec` |
| Web | `sha256:390b8dbb18c868f72366fe4353c2d8a944b3b0b412ad6fd46455dc2e5debcf82` |

Both were inspected as linux/amd64, labelled `development-gate13b` / `ea17494`.
They are not a release candidate. The language scan began **2026-09-11 00:09:24Z**;
the final image phase began **00:15:47Z**. No single simultaneous scan is claimed.
Language-phase image arguments are unused placeholders, not audited identities.

The initial **00:10:38Z** image phase finished the earlier API scan, then failed
because its web image ID was no longer available. The concurrent lifecycle build
produced the different IDs above. Preserve that incomplete attempt and its partial
API report; do not join its old IDs to the lifecycle proof. The matrix, component
probe and both-image scan were repeated against the actual successful lifecycle
IDs. Same source revision is not assumed to mean identical image bytes, and this
checkpoint does not assert reproducible builds or diagnose the rebuild difference.

Fresh npm web/production/organization/preview results are **0/0/0/0** findings;
Python runtime/development/build are **0/0/0** across **35/43/2** dependencies, with
none skipped; Go symbol-level source analysis reports **0** findings. All seven
audited locks are unchanged from the S01/S02 hardening checkpoint.

The final scan completes at **00:19:49Z**: **181 API / 3 web matches**, representing
**96 / 1 unique CVEs**. All reduced records equal the prior closeout inventory:
identity, severity, source/namespace, package/version/type, locations, match types
and fix metadata; this is not equality of every raw scanner field. API severities
remain **7 critical / 61 high / 51 medium / 9 low / 45 negligible / 8 unknown**;
all three web matches are medium. No match was suppressed or subtracted.
Grype 0.118.0 used a valid schema-6.1.9 database built September 10 at 06:30:24Z.
The per-CVE vendor dispositions retain their dated September 10 sources; this
containment implementation is not a new vendor applicability survey or native fix.

## Durable evidence and remaining decisions

The [capture helper](security-hardening-run.cjs) now supports a private durable
directory under `~/.local/state/makersvault/verification`, in addition to historical
temporary captures. Named `containment-*` attempts refuse existing destinations;
the root/attempt directories are private and command logs are mode 0600. No change
to lean-ctx's global allowlist or other security configuration was made.

New raw logs, scanner reports, source/exit/timing records and hashes remain there;
sanitized, source-matched summaries are committed separately. This does not recover
the prior unavailable `/tmp` artifacts, provide an off-host backup, or qualify a
future release from historical evidence. Keep final candidate raw evidence durable
and private, and include matched identities in any later release record.

The [joined verification/audit record](security-containment-verification.json)
retains all **15 captured attempts**, including failures, negative controls and final
proofs, exact images, lock/raw-log hashes, component observations and the source-bound
S04 carry-forward. The [evidence reducer/checker](security-containment-analysis.cjs) checks retained
logs, private permissions, lock hashes, exact matrix/lifecycle/image agreement,
native match identity, unchanged application/recovery boundaries, and zero owner
acceptances. It refuses to inherit dispositions if new image records appear.
It passes **86 hash checks**, 16 unchanged boundary-file comparisons and local
documentation-link checks. Node syntax, static release contract and `git diff --check`
also pass. Run `node makervault/docs/evidence/gate-13/security-containment-analysis.cjs`
from the repository root to recheck against the retained private evidence.

All 80 [S04 decisions](security-residual-decisions.json) remain owner-pending:
11 proposed precondition exclusions, 10 priority unresolved reviews and 59 scoped
residual decisions. Containment improves the documented deployment boundary; it
does not patch libc/SQLite/Perl/zlib, erase CVEs, sandbox malicious raw snapshots,
protect all vault data from a compromised API, or eliminate denial of service.
Existing raw snapshot provenance and operator-control requirements remain binding.

**Next owner checkpoint:** accept the verified containment implementation and
explicitly disposition the retained S04 exceptions against these exact images and
the documented deployment/backup boundary. Implementation approval did not grant
that acceptance. Use named owner, individual CVEs, rationale and review deadline;
reopen on fixes, new callers, different images/architectures or weaker controls.
Platform/passkey/operator/release qualification follows separately. G13-01 tuning
and Gate 12 desktop work stay deferred; Gate 13C/13D and the frozen Gate 5 candidate
are not automatically accepted or changed. Nothing was pushed, tagged or deployed.
