# Gate 13C — owner acceptance and C6 follow-up

**Date:** September 12, 2026, America/New_York.
**Owner:** VincentCinque, repository maintainer.
**Status: APPROVAL RECORDED; SEVEN EXCEPTIONS REOPENED; SECURITY CLOSEOUT OPEN.**

The owner's **“yes approved”** responds to the scoped
[S04 proposal](SECURITY_DISPOSITION_PROPOSAL.md) at `f93109f`. The immutable
[approval event](security-owner-acceptance-2026-09-12.json) records each approved ID,
the exact proposal hash, images, conditions and accountable maintainer. It approves
11 exact-image exclusions and 59 temporary local-qualification exceptions,
explicitly including critical-rated CVE-2026-12087 and CVE-2026-13221. It does **not**
accept the ten H entries, authorize implementation of new native patches, or close
S04/G13-04, Gate 13C/13D or a public release.

Approval has day precision: September 12. The recorded UTC observation is not
presented as a second-resolution timestamp of the user's message. The conservative
deadline is **October 12, 2026 at 00:00 America/New_York (04:00 UTC)**, or earlier
candidate freeze/13D or any C6 trigger. All C1–C7 conditions remain binding; there
is no automatic renewal or newly configured scheduled monitor.

## Current disposition after checking the conditions

| Category | CVEs | Current meaning |
|---|---:|---|
| Approved exact-image exclusions | 11 | Same absent preconditions confirmed by fresh component/CLI probes; ten newly available package fixes reviewed without broadening exclusions |
| Active temporary local exceptions | 52 | Remain under the approved C1–C7 conditions and deadline |
| Approved exceptions reopened under C6 | 7 | Supported distribution fixes now identified; no active exception is relied on for these IDs |
| Original holds | 10 | Still unaccepted; three now have an identified supported fix path |

Thus **17 residual CVEs remain open**, not ten, after the required vendor-fix
follow-up. The approval event still truthfully records 59 exception approvals;
the subsequent [dated review](security-acceptance-review-2026-09-12.json) records
seven reopenings. Historical proposals and their zero-acceptance fields remain
unchanged snapshots, not the current decision ledger.

All **181 API / 3 web scanner matches** remain visible. This slice installs no fix,
rescans no image and suppresses no result. The exact development images remain:

- API: `sha256:40aef54d6acf598ce49197d1aac966c96cc38ddd887ca10feff6a3ef4a74edec`
- Web: `sha256:390b8dbb18c868f72366fe4353c2d8a944b3b0b412ad6fd46455dc2e5debcf82`

Both are the reviewed linux/amd64 images from application `ea17494`; no acceptance
transfers automatically to rebuilt images or a different architecture.

## Supported fixes identified since the proposal

The September 12 Debian pages now identify stable Trixie fixes for the following
currently open entries. These are vendor source-version statements, **not** proof
that our images contain them or that an APT transaction has been qualified.

| Installed API package(s) | Current → vendor fixed source version | Open CVEs targeted |
|---|---|---|
| libc6, libc-bin | `2.41-12+deb13u3` → `2.41-12+deb13u4` | H [5450](https://security-tracker.debian.org/tracker/CVE-2026-5450); reopened R [5928](https://security-tracker.debian.org/tracker/CVE-2026-5928) |
| libsqlite3-0 | `3.46.1-7+deb13u1` → `3.46.1-7+deb13u2` | H [11822](https://security-tracker.debian.org/tracker/CVE-2026-11822), [11824](https://security-tracker.debian.org/tracker/CVE-2026-11824) |
| perl-base | `5.40.1-6` → `5.40.1-6+deb13u1` | Reopened R [12087](https://security-tracker.debian.org/tracker/CVE-2026-12087), [13221](https://security-tracker.debian.org/tracker/CVE-2026-13221), [57432](https://security-tracker.debian.org/tracker/CVE-2026-57432) |
| gzip | `1.13-1` → `1.13-1+deb13u1` | Reopened R [41991](https://security-tracker.debian.org/tracker/CVE-2026-41991), [41992](https://security-tracker.debian.org/tracker/CVE-2026-41992) |
| libpcre2-8-0 | `10.46-1~deb13u1` → `10.46-1~deb13u2` | Reopened R [86145](https://security-tracker.debian.org/tracker/CVE-2026-86145) |

All shortened CVE numbers in the table are CVE-2026. The seven reopened R IDs
are exactly **12087, 13221, 41991, 41992, 57432, 5928 and 86145**. Three are Perl
findings, including both critical-rated exceptions explicitly acknowledged by
the owner. Availability of a supported fix triggers review under C6 rather than
silently continuing those exceptions to their maximum deadline.

Twenty S04 CVEs now have fixed Trixie table rows: the ten open entries above and
ten previously excluded Perl-component/architecture findings. Fresh probes on the
same API bytes confirm all exclusion preconditions unchanged, including absent
zipdetails. That completes the reopened applicability review for those ten E
entries; their narrowly approved exclusions remain valid for this image only.
It does not confer an installed patch or automatically clear a future image.

## Remaining H evidence limits

- **19499, 19542, 77117, 80489:** Debian still marks the newer glibc Trixie source
  affected. The 19542 description identifies tdelete; the others remain sparsely
  described. The linked Debian bug pages were unavailable through this browser
  review. Sourceware was not retried and no access-control workaround was used.
  No fix or complete native reachability exclusion is established.
  [19499](https://security-tracker.debian.org/tracker/CVE-2026-19499),
  [19542](https://security-tracker.debian.org/tracker/CVE-2026-19542),
  [77117](https://security-tracker.debian.org/tracker/CVE-2026-77117),
  [80489](https://security-tracker.debian.org/tracker/CVE-2026-80489).
- **39113, 50812:** Debian still marks the newer SQLite source affected. The
  [upstream sqlar commit](https://github.com/sqlite/sqlite/commit/169f68ed88b34cb68f720191c64c058f2ccec508)
  confirms the changed integer conversion, but does not establish whether the
  exact Debian source/backport contains it. SQLite source/detail endpoints were
  unavailable; the absence of apply_v3 and default sqlar functions remains a
  bounded observation, not a blanket SESSION/SQLite exclusion.
  [39113](https://security-tracker.debian.org/tracker/CVE-2026-39113),
  [50812](https://security-tracker.debian.org/tracker/CVE-2026-50812).
- **85091:** the upstream-range versus Debian mapping conflict remains. The
  [upstream tracking issue](https://github.com/madler/zlib/issues/1310) is a request
  for information, not a fix confirmation. The attempted Debian source read timed
  out; no source/build reconciliation was obtained.
  [Debian record](https://security-tracker.debian.org/tracker/CVE-2026-85091).

Local source review confirms recovery opens raw SQLite bytes, calls quick_check,
queries schema/counts and later mutates security tables. There is no new parser
sandbox or trusted-schema protection installed by this review. Absence of a direct
application FTS MATCH call does not make arbitrary raw schemas safe. Trusted
snapshot provenance/private staging remain necessary, and capability controls
do not protect every vault byte from a compromised API.

## Bounded next implementation — approval required

Recommend updating only the **six installed API packages in the table**, across
the test/runtime base stage, to applicable Debian stable fixed versions. Keep
Python 3.11, the existing pinned base, schema 17, language locks, web application,
ownership/volume behavior and user workflows unchanged. This is a proposed native
package refresh, not an authorized distribution migration or broad system upgrade.

Before installation, verify signed configured-repository availability and inspect
APT's proposed transaction. Stop if it requires a different distribution, package
removals or unrelated upgrades beyond necessary compatible dependencies. Do not
guess binary versions solely from source-version labels. If availability or the
transaction differs materially, report it before changing the plan.

After implementation: test old-image negative/installed-version controls and
startup/ownership/recovery, run the full gate and joined HTTPS lifecycle, scan
the **actual final image IDs**, preserve failed attempts and durable private raw
evidence, then update every changed CVE disposition. Rebuilt images require renewed
E/R applicability checks, not copied waivers. This targets ten currently open CVEs;
it does not promise to close the other seven H entries or clear a public release.

No application or Dockerfile change, package install, image rebuild, push, tag,
publication, deployment or frozen Gate 5 release-pin change was performed here.
Performance G13-01 remains deferred, and Gate 12 remains desktop-deferred.

## Evidence and verification

The bounded vendor collector attempted all 80 S04 IDs at **16:23:55–16:23:58 UTC**:
79 Debian pages are retained privately with hashes; Alpine returned HTTP 406. A
separate browser reread of the [Alpine page](https://security.alpinelinux.org/vuln/CVE-2025-60876)
succeeded, but is not presented as an archived successful collector response.
No new fixed-package conclusion or waiver is inferred from the failure.

The collector's diagnostic shortlist also included three ACL/attr prose notes
containing “fixed.” The strict table-row reducer rejects them: they are **not**
new fixed Trixie packages. Raw responses and the misleading intermediate shortlist
are preserved. This is a tooling interpretation correction, not a native fix or
a discarded application test failure.
The first strict-reducer check also rejected a combined `trixie (security), trixie`
release row. The corrected cell-based parser has explicit ordinary/combined-row
assertions and reuses the same retained bytes; no failed check is called a pass.

Fresh offline component and CLI/symbol probes pass at **16:25:54–16:25:56 UTC**,
on the exact API image, without vault mounts, network or application startup.
Their results equal the prior observations. Probe-only read-only/resource flags
are not new shipped defaults. Three capture runs and 79 vendor bodies remain in
durable private storage; only sanitized summaries are committed.

Run the [dated-event/review checker](security-owner-acceptance-check.cjs) from the
repository root:

```text
node makervault/docs/evidence/gate-13/security-owner-acceptance-check.cjs
```

It checks the immutable approval against the precise proposal, all 80 IDs, E/R/H
separation, C1–C7, date/deadline, private capture hashes and the seven C6 reopenings.
It is a consistency check of the documented conversation approval, not a digital
signature or live security monitor. The older proposal checker deliberately still
reports zero historical acceptances; use this dated ledger for current status.
The final checker passes **92 new private hash checks**, plus the existing
86 containment and four proposal-probe checks. Node syntax, local documentation
links, the static release contract and `git diff --check` pass as well.
No fresh all-image/language audit or full application-suite repeat is claimed.
