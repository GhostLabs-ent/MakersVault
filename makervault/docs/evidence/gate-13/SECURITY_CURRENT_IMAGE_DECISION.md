# Gate 13C — current-image owner decision package

**Prepared:** September 12, 2026, America/New_York.
**Application:** unchanged `6306ccff289d475530a6cacf4cb2e28db456ce08`.
**Entry checkpoint:** `7349f93f2223fce325eaa14131bfdcc262a20fec`.
**Status: READY FOR THE SCOPED OWNER DECISION; ZERO NEW ACCEPTANCES.**

**Historical proposal:** the owner subsequently [approved E2/R52 and the BusyBox caveat](SECURITY_CURRENT_OWNER_ACCEPTANCE.md).
This document and its pending-proposal JSON remain the evidence that was approved;
the separate event records the actual decision. H7 was not accepted.

The owner's “go ahead” authorizes preparing this package after the
[vendor/byte reconciliation](SECURITY_RECONCILIATION_RESULTS.md), not accepting its
risks. This is a new proposal for the rebuilt images, not a transfer or extension
of the old-image E11/R59 event. No application change or further package upgrade
is proposed here.

## Requested decision

| Set | CVEs / package matches | Recommendation |
|---|---:|---|
| F — already verified fixes | 26 / 28 | Retain technical resolution; no risk waiver requested |
| E — absent required components | 2 / 3 | Approve the exact-image exclusions below |
| R — remaining exposure | 52 / 133 | Accept temporary **local-qualification only** exceptions under C1–C7, explicitly acknowledging the BusyBox evidence limitation |
| H — unresolved holds | 7 / 11 | Leave unaccepted; investigate separately |

The [per-CVE proposal](security-current-decision-proposal.json) enumerates all 87
native IDs, current image/package/version/severity matches, individual review,
source evidence, conditions and exit criteria. Every acceptance field remains
null. The [engineering review notes](security-current-decision-review.json) explain
each of the 52 residual judgments; these are not proof of non-exploitability.

The R set has **44 High, 39 Medium, six Low and 44 Negligible package matches**;
none is Critical. Eight R CVEs account for those 44 High matches:
CVE-2025-69720 and CVE-2026-5435, -54369, -54370, -76642, -78408, -78409, -78410.
That is not a severity downgrade: the raw API scan still contains seven Critical
matches, and the complete **189 API / 3 web matches** remain visible. The 17
interpreter CVEs remain separate from this native proposal.

## Exact images and conditions

Only these **linux/amd64 development** images are in scope:

- API: `sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`
- Web: `sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67`

Proposed accountable approver: **VincentCinque, repository maintainer**. Explicit
approval would be recorded in a new append-only event referencing this proposal's
hash, exact images and selected IDs. No acceptance timestamp is invented here.

- **C1 — Identity:** no transfer to another build, architecture, desktop or public
  candidate, even if its source or package versions look similar.
- **C2 — Runtime:** canonical Compose/entrypoint, nonzero API PUID/PGID, no
  privileged/capability overrides, five empty daemon capability sets and
  no-new-privileges. Trusted operator recovery retains its separate six-capability
  allowance; it is not the capability-free daemon.
- **C3 — Application controls:** production-style HTTPS, authentication,
  authorization, outbound-hostname protections and existing file/preview guards
  remain enabled. No untrusted-network exposure of development servers.
- **C4 — Recovery trust:** raw snapshots come only from trusted operator-controlled
  installations, with protected provenance, source/restore roots and private
  staging. GNU tar/SQLite/chown are not a hostile-input sandbox. Checksums alone do
  not establish origin. Follow [secure deployment guidance](../../SECURE_DEPLOYMENT.md).
- **C5 — Residual harm:** native memory corruption, data disclosure/loss, writable
  vault access and denial of service remain possible. Writable root filesystems
  and the absence of container memory/CPU/PID caps are unchanged. Containment and
  backups do not replace a native patch.
- **C6 — Expiry/reopening:** no later than **October 12, 2026 at 00:00
  America/New_York**, 30 days after actual acceptance, or candidate freeze/13D,
  whichever is earliest. Immediately reopen for relevant fixes, changed
  advisories/callers/inputs/images/platforms, missing evidence or weaker controls.
  No automatic renewal or extension; review again at the next checkpoint.
- **C7 — Authority:** local qualification only, not publication, deployment,
  support-policy change, S04/G13-04 closure or Gate 13C/13D acceptance. H7 remains
  unwaived. Any release needs its own fresh matched evidence and decisions.

## E2 — component-based exclusions

| CVE | Current vendor status | Bounded reason for the proposed exclusion |
|---|---|---|
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | Trixie Perl source remains open | Required `Archive::Tar` module is not loadable in the exact API runtime. This does not exclude GNU tar, which restore uses |
| [CVE-2026-89092](https://security-tracker.debian.org/tracker/CVE-2026-89092) | Trixie glibc source remains open | Required nscd service has no package-manifest match or named executable in the exact API. This does not exclude ordinary libc DNS resolution |

Both observations were freshly reproduced. These exclusions would not cover a
custom image, added module/service, injected executable or new host integration.
Their three package matches stay in the scanner record.

## R52 — what the owner would be accepting

| Source families | CVEs | Main boundary / remaining risk |
|---|---:|---|
| glibc | 12 | Native regex/glob, encoding modes, DNS-printing helpers, word expansion and mitigation disputes; core libc remains active |
| SQLite / zlib | 4 | SQLite database/extension/SESSION paths and checksum-combine behavior; absent observed callers are not whole-library exclusions |
| tar / coreutils / acl / attr | 11 | Privileged archive, path/metadata races and specific utility inputs; protect operator roots and provenance |
| util-linux / shadow / PAM | 9 | Account, mount, namespace and OS-login preconditions; distinguish operator actions from web identity and the capability-free daemon |
| systemd | 7 | Local manager/journal/terminal preconditions; no claim that installed libraries are absent |
| Perl | 3 | File::Temp and regex defects; Perl core is present, no application-controlled invocation identified |
| ncurses / bzip2 / diffutils / APT | 5 | Specific terminal, recovery, diff and package-trust paths; not family-wide unused-code exclusions |
| BusyBox | 1 | wget request manipulation; no application URL-to-wget path identified, with the distribution-fix evidence gap below |

The per-CVE review corrects overly broad family shorthand: the three non-chown
coreutils entries concern `sort`, `uniq` and `unexpand`; the bzip2 entry concerns
`bzip2recover`. Startup/restore source still confirms real account, setpriv, chown
and GNU tar use. For tar, private extraction alone cannot substitute for protected
source/restore paths and trusted origin. SQLite SESSION remains enabled. These
observations support a limited engineering risk judgment, not universal caller
absence, parser isolation or safety of arbitrary operator commands.

**BusyBox needs explicit acknowledgment:** the fresh
[CVE record](https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2025/60xxx/CVE-2025-60876.json)
is byte-identical to the earlier retained record. The exact web manifest still has
`busybox`, `busybox-binsh` and `ssl_client` at `1.37.0-r31`. However, the previous
Alpine advisory collector returned HTTP 406, and this review's Alpine v3.24 secdb
browser read returned a non-retryable error. Neither blocked endpoint was retried.
Current Alpine backport/fix availability is therefore **unverified**, not “no fix
available.” The unchanged CNA is not distribution fix evidence. If the owner does
not accept that limited evidence gap, leave this one R entry pending; it is not
silently accepted with the other 51.

## H7 — excluded from the requested approval

Keep **CVE-2026-19499, CVE-2026-19542, CVE-2026-77117, CVE-2026-80489,
CVE-2026-39113, CVE-2026-50812 and CVE-2026-85091** unaccepted. The fresh feed still
marks their Trixie sources open. The register preserves each source/build/caller
gap and exit criterion. Minor/no-DSA labels, missing source detail, absent single
symbols and headline upstream versions do not close these holds.

## Evidence and limits

At **19:53:05–19:53:21 UTC**, the official
[Debian JSON feed](https://security-tracker.debian.org/tracker/data/json) refreshed
all 86 known Debian-native records. All 86 are unchanged from the reconciliation
capture, including all 51 Debian R entries remaining open without a recorded
Trixie fixed version, both E entries, seven H entries and 26 verified fixes. The
full feed changed elsewhere; this is not a new all-CVE or image scan. Its
Last-Modified is **19:24:50 UTC**; full body/hash and the BusyBox CNA are retained
privately. No package repository, installed byte or scanner rule changed.

Fresh image inspection confirms exact IDs, platform and application revision.
The successful **19:55:20–19:55:22 UTC** probe reproduces all prior runtime/component
observations and reads the web's installed package manifest. Containers are
disposable, networkless, read-only, capability-free and have no vault mounts or
application startup. These probe flags are not newly shipped product defaults.
The first attempt failed an `apk info` output assertion; it is retained as
incomplete. The successful attempt reads `/lib/apk/db/installed` directly, without
weakening restrictions or fetching indexes.

Run `node makervault/docs/evidence/gate-13/security-current-decision-check.cjs`.
It verifies **15 new private hashes plus 182 prior hashes**, immutable historical
inputs, fresh vendor/component joins, exact identities, all 87 dispositions and
null acceptance fields. Prior qualification (424 API / 58 web tests, HTTPS
upgrade/recovery/rollback and containment) is retained against unchanged inputs,
not newly executed. No deployed instance, hostile payload or exhaustive native
call graph was tested. Node syntax, **231 local documentation links**, the static release
contract and `git diff --check` pass.

**Owner checkpoint:** approve only E2/R52 under C1–C7, explicitly acknowledging the
BusyBox distribution-fix evidence gap, and leave H7 unaccepted. Then record the
new exact-image event and continue a bounded H review; any remediation or separate
H exception needs its own informed decision. Gate 13C/security remains open even
if E/R is approved. Performance G13-01, desktop Gate 12, platform/release readiness
and the frozen Gate 5 baseline are unchanged. Nothing pushed, tagged, published
or deployed; no end-user settings, uploads or model bytes changed.
