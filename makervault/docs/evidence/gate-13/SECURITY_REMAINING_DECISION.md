# Gate 13C — remaining five native findings: owner decision

**Date:** September 12, 2026, America/New_York.
**Entry:** `5985cef77a043c361e5775d44f85f5ca4348e6ec`; application remains `6306ccf`.
**Status: REVIEW COMPLETE; FIVE TEMPORARY LOCAL EXCEPTIONS PROPOSED, NONE ACCEPTED.**

The owner's “go ahead approved” authorized investigation of the five holds after
the [two-exclusion approval](SECURITY_HOLD_OWNER_ACCEPTANCE.md). It did **not** accept
the new risk proposal below. Current native dispositions remain **E4/R52/F26/H5**.

## What the new evidence establishes

Twelve primary pages are now captured privately: five Debian tracker records,
four Red Hat CNA pages, two Ubuntu records and SQLite's upstream fix. New readable
endpoints supplied information absent from the earlier review; previously failed
Bugzilla, Sourceware, Fossil and Debian bug endpoints were not retried.

All five Debian records still mark the installed Trixie sources vulnerable:
[19499](https://security-tracker.debian.org/tracker/CVE-2026-19499),
[19542](https://security-tracker.debian.org/tracker/CVE-2026-19542),
[50812](https://security-tracker.debian.org/tracker/CVE-2026-50812),
[77117](https://security-tracker.debian.org/tracker/CVE-2026-77117),
[80489](https://security-tracker.debian.org/tracker/CVE-2026-80489).
The **20:45:26–20:45:38 UTC** disposable exact-image probe refreshed signed APT
indexes with authentication required. Configured-repository candidates equal
installed versions: libc6/libc-bin `2.41-12+deb13u4` and libsqlite3-0
`3.46.1-7+deb13u2`. No supported update is available from those configured
repositories at this observation—not a claim that no fix exists anywhere.

| CVE | New evidence and consequence | Proposed disposition |
|---|---|---|
| 2026-19499 | [Red Hat](https://access.redhat.com/security/cve/cve-2026-19499) identifies a right-justified monetary-formatting buffer overwrite. `strfmon`/`strfmon_l` are present. Native memory corruption, data loss or code execution remains a potential impact | Temporary local risk exception, not exclusion |
| 2026-19542 | [Red Hat](https://access.redhat.com/security/cve/cve-2026-19542) identifies incorrect stack-array sizing in `tdelete`. The symbol is present. Memory corruption, denial of service or disclosure remains possible | Temporary local risk exception, not exclusion |
| 2026-50812 | Authenticated shipped SQLite source contains the pre-fix shared changeset guard; the upstream regression uses apply_v2. Malformed changeset processing can cause a NULL dereference/process denial of service | Temporary local risk exception, not exclusion |
| 2026-77117 | [Red Hat](https://access.redhat.com/security/cve/cve-2026-77117) identifies non-progress under specific SHIFT_JISX0213 conversion/retry conditions. The converter and alias are installed | Temporary local denial-of-service exception |
| 2026-80489 | [Red Hat prose](https://access.redhat.com/security/cve/cve-2026-80489) names SHIFT_JISX0213, while its bug title and [Ubuntu](https://ubuntu.com/security/CVE-2026-80489) identify EUC_JISX0213. Both converters are installed; retain the mapping disagreement and retry-loop risk | Temporary local denial-of-service exception, including that uncertainty |

The [SQLite fix](https://github.com/sqlite/sqlite/commit/b869ed6b067d623cb1383549f2a18aa35508385d)
requires a non-NULL old value before binding it. The retained authenticated source
has the earlier guard at line 4921 and an unchecked value-type call at line 4557;
none of its 15 active Debian patches changes that source file. The exact installed
library hash again matches prior authenticated archive evidence. This resolves the
shared-code question **against** a version/symbol-only exclusion; it is not a new
exploit test. [Ubuntu's older-branch backports](https://ubuntu.com/security/CVE-2026-50812)
also show why the headline 3.53.1/apply_v3 description cannot clear older builds.

The bounded direct-source review covers 51 top-level API Python files. No exact
named native/changeset/extension-loading call was found. Eighteen broad substring
hits are existing `PermanentDelete` identifiers, not calls to `tdelete`; all are
retained rather than hidden. The Python SQLite connection exposes no changeset
member, but the underlying library has SESSION enabled. These observations limit
the **identified direct application paths**, not all transitive native callers,
malicious input, operator tools, extension loading or recovery. In particular,
authentication and capability removal do not make native parsers safe.

## Recommendation and alternatives

**Propose accepting these five as temporary local-qualification risks under the
unchanged C1–C7 conditions.** This permits finishing local platform/operator
qualification without calling affected packages fixed. Explicitly retain writable
vault access, native memory-corruption/data-loss/disclosure, process/resource
denial of service and incomplete native-call applicability evidence. Four glibc
CVEs account for **eight Unknown-severity raw matches**; SQLite adds **one Medium**.
Do not turn vendor “minor/no-DSA” labels into a low-risk or fixed finding.

Alternatives are to keep H5 open pending applicable supported Debian backports,
or separately approve a supported patched base/maintained-backport plan and its
full qualification. Fixes in Ubuntu or Debian unstable are **not** permission to
mix distribution packages, migrate the base or maintain ad-hoc patches silently.

Scope is the same **linux/amd64 development** images and application `6306ccf`:

- API: `sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`
- Web: `sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67`

The [machine proposal](security-remaining-proposal.json) carries each ID, impact,
evidence limit, original package matches, owner-pending status and unchanged
conditions. Deadline: **October 12, 2026 at 00:00 America/New_York**, or 30 days
after actual acceptance, candidate freeze/13D or C6 reopening, whichever is earlier.
No extension, automatic renewal, rebuild/architecture/desktop transfer or public
deployment approval. Existing BusyBox and other E/R caveats remain unchanged.

**Requested owner decision:** accept these five named temporary local exceptions,
including the stated native-memory, denial-of-service and applicability/mapping
uncertainties, under those conditions. If approved, local native87 becomes
**E4/R57/F26/H0**. That would complete local native dispositions only—not close
S04/G13-04 or Gate 13C/13D. Release-candidate selection, renewed exact-image security
qualification, remaining platform/operator evidence and owner acceptance are still
required before public release. Until that decision, all H5 remain unaccepted.

## Verification and boundaries

Run the [read-only checker](security-remaining-review-check.cjs):

```text
node makervault/docs/evidence/gate-13/security-remaining-review-check.cjs --self-test
```

It joins **17 new private hashes and 205 prior hashes**, twelve captured primary
pages, the exact-image runtime result, 51 source hashes, SQLite's retained source
and prior approvals. It also checks links and rejects fabricated approval,
exclusion, partition, deadline and source claims with five negative controls.
The first preliminary checker failed on GitHub syntax-highlight markup; stripping
presentation tags corrected that parser without fetching again or changing evidence.

The evidence checker and five negative controls pass, including **273 local
documentation links**. Node syntax and the static v5.1.0 release contract are
checked separately; this is not a full application regression run.

The image probe only refreshed indexes, queried metadata, resolved symbols,
listed converters and opened an in-memory database. It did not install packages,
execute vulnerable functions, process a hostile fixture, start MakersVault or mount
the vault. Root/resource flags belong to the disposable probe, not product defaults.
Raw evidence is private; only reproducibility metadata and sanitized results are
committed. Historical approval/proposal JSON is unchanged. No new full suite or
scan is claimed; all **189 API / 3 web raw matches** and interpreter dispositions
remain. No application, dependency, image, schema, release-pin or model-byte change;
no push, publication, deployment or restart of deferred performance work. Owner
roadmap additions and the desktop document remain outside this security commit.
