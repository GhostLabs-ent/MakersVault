# Gate 13C — S04 owner disposition proposal

**Prepared:** September 10, 2026 (America/New_York); September 11 UTC.
**Status: READY FOR OWNER DECISION — NO ACCEPTANCES RECORDED.**

The requested follow-up reviews residual risks against the
[verified containment](SECURITY_CONTAINMENT_RESULTS.md). It does not interpret
permission to prepare this package as permission to waive vulnerabilities.
Application source remains `ea17494`; entry documentation is `290df55`.
Only documentation and read-only evidence tooling change in this slice.

## Recommended decision

| Set | Individual CVEs | Recommendation | Effect if explicitly approved |
|---|---:|---|---|
| E | 11 | Approve exact-image precondition exclusions | Record why a required component or architecture condition is absent; do not suppress package matches |
| R | 59 | Accept time-limited exceptions for continued local qualification, under C1–C7 below | Record known residual risk, including two scanner-rated critical Perl findings; not a finding of safety or public-release clearance |
| H | 10 | Keep on hold; do not accept in this package | Resolve the named evidence gaps, apply an applicable supported fix, or seek a separate informed exception |

These are individual decisions grouped for readability, not a blanket waiver.
The [proposed register](security-disposition-proposal.json) enumerates all 80 IDs,
every matched image/package/version/severity, per-entry rationale, conditions and
exit criteria. **All owner fields are still pending/null.** Approval of E and R
would leave ten S04 holds; **S04/G13-04 and Gate 13C would remain open**.

S04 covers **80 native CVEs / 167 package matches**. The 17 interpreter CVEs /
17 matches remain in S02/S03. All **181 API / 3 web matches** stay in the raw and
reduced inventories, including seven critical-rated API matches. E/R/H do not
replace scanner severity. This does not change product support or require end-user
thumbnail uploads, new quotas, settings, or file reorganization.

## Exact scope and acceptance conditions

| Development image | Immutable ID | Inspected platform |
|---|---|---|
| API | `sha256:40aef54d6acf598ce49197d1aac966c96cc38ddd887ca10feff6a3ef4a74edec` | linux/amd64 |
| Web | `sha256:390b8dbb18c868f72366fe4353c2d8a944b3b0b412ad6fd46455dc2e5debcf82` | linux/amd64 |

Proposed accountable approver: **VincentCinque, repository maintainer**, subject to
confirmation with approval. No date or identity has been manufactured as a signed
acceptance. Record actual approval time and the resulting deadline in a new
append-only decision record referencing this proposal's hash and exact CVE IDs.
Preserve the earlier proposed registers and their evidence hashes.

- **C1 — Identity:** only the development images above. No automatic transfer to a
  rebuild, other architecture, desktop installation or public candidate.
- **C2 — Runtime:** retain canonical Compose/entrypoint, nonzero API PUID/PGID,
  no privileged/capability overrides, five empty application capability sets and
  no-new-privileges for API and Nginx. Operator recovery is a separate process with
  its documented six-capability allowance.
- **C3 — Application:** keep production-style HTTPS, authentication/authorization,
  outbound-hostname protection and existing file/preview guards. Do not expose
  development servers to untrusted networks.
- **C4 — Recovery:** raw snapshots must come from trusted operator-controlled
  installations with protected provenance and private staging. Raw SQLite and
  format-1 snapshots are not public sharing/import formats. GNU tar extraction,
  chown and SQLite parsing are not a hostile-input sandbox. Checksums do not prove
  the author's authority. See [operator guidance](../../SECURE_DEPLOYMENT.md).
- **C5 — Remaining harm:** a compromised API can still access vault bytes within
  its permissions; native corruption, data loss and denial of service remain
  possible. Root filesystems are writable. No container memory/CPU/PID cap or
  whole-native-parser isolation is claimed. Backups and container privileges are
  not substitutes for a native patch.
- **C6 — Expiry:** the earlier of **30 days after acceptance or candidate
  freeze/13D**. Reopen immediately for an applicable vendor fix, new caller/input,
  changed advisory, different image/platform, unavailable evidence or weaker
  controls. No automatic renewal; accepting today is not permission to ignore a
  fix tomorrow. Check again at the next qualification checkpoint, not only at expiry.
- **C7 — Authority:** local qualification only. No public release, push, tag,
  publication, deployment, support-policy change or automatic gate acceptance.
  The H entries remain unwaived. A selected release needs fresh exact-image
  scans, durable matched evidence and its own explicit dispositions.

## E — supported precondition exclusions

All eleven Debian pages were reread for this checkpoint. Each linked record still
reports an affected installed distribution source package; the recommendation is
about a missing execution precondition in this image, **not** an installed fix.

| CVEs / vendor records | Required precondition and exact-image evidence |
|---|---|
| [42496](https://security-tracker.debian.org/tracker/CVE-2026-42496), [42497](https://security-tracker.debian.org/tracker/CVE-2026-42497), [9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) — all CVE-2026 | Archive::Tar is not loadable. This does not exclude GNU tar, which recovery actually uses |
| [CVE-2026-57433](https://security-tracker.debian.org/tracker/CVE-2026-57433) | Storable is not loadable |
| [CVE-2025-15649](https://security-tracker.debian.org/tracker/CVE-2025-15649), [CVE-2026-48959](https://security-tracker.debian.org/tracker/CVE-2026-48959) | IO::Uncompress::Unzip is not loadable |
| [CVE-2026-48962](https://security-tracker.debian.org/tracker/CVE-2026-48962) | File::GlobMapper is not loadable |
| [CVE-2026-7010](https://security-tracker.debian.org/tracker/CVE-2026-7010), [CVE-2026-7017](https://security-tracker.debian.org/tracker/CVE-2026-7017) | HTTP::Tiny is not loadable; this is not an exclusion for MakersVault's Python HTTP clients |
| [CVE-2026-8376](https://security-tracker.debian.org/tracker/CVE-2026-8376) | Described defect requires 32-bit Perl; inspected Perl has eight-byte pointers on x86_64 |
| [CVE-2026-48961](https://security-tracker.debian.org/tracker/CVE-2026-48961) | Defect is in the zipdetails CLI. New probe finds no package-manifest entry or executable in the inspected PATH/standard bin directories |

**Evidence correction:** the earlier module-absence rationale for 48961 was
insufficient: the vendor distinguishes the CLI defect from library calls. The new
CLI observation supplies the relevant bounded evidence; do not reuse IO::Compress
module absence as the sole proof. This is not a claim that a custom mount, injected
script, changed PATH or future image cannot introduce the command.

## R — exceptions recommended only under the stated conditions

The register retains all **59 individual R IDs**, not a source-package wildcard.
The [dated source review](SECURITY_CLOSEOUT.md#s04--native-image-residuals-and-recovery-boundary)
provides the underlying advisory mapping. Most R vendor pages were not reread in
this slice; the exact image records and application boundaries remain matched to
the prior review through the current containment evidence.

Two R findings need explicit critical-severity acknowledgment:

- **CVE-2026-12087:** Perl Socket is present. The described helper can disclose a
  small amount of adjacent heap data when given a short source argument. No
  application-controlled Perl invocation was identified. This supports a bounded
  temporary exception, not module absence or a proven complete call graph.
  [Reread Debian record](https://security-tracker.debian.org/tracker/CVE-2026-12087).
- **CVE-2026-13221:** Perl core is present. A particular large regex trie can make
  incorrect matching decisions. No application-controlled Perl invocation was
  identified; the installed code remains affected. Do not silently downgrade the
  scanner's critical label based on Debian's triage classification.
  [Reread Debian record](https://security-tracker.debian.org/tracker/CVE-2026-13221).

For the other R entries, the recommendation relies on the recorded local/operator
preconditions or lack of an identified application-controlled invocation, plus
verified containment and time limits. This is engineering judgment, **not proof
of non-exploitability**. In particular:

- glibc, SQLite and zlib remain active native dependencies; do not mark them unused.
- setpriv/account setup, chown and GNU tar are used by startup/recovery. Keep their
  privileged operator boundary distinct from the capability-free daemon.
- systemd/PAM/shadow findings are not evidence of a vulnerable web-login service,
  but installed libraries/account tools remain present.
- BusyBox wget's three web matches remain; absence of an identified URL-to-wget
  application path is not an absent package or Nginx-wide security clearance.

If the owner does not accept these residual harms under C1–C7, leave the selected
entries pending and request a bounded remediation plan. Do not begin a distribution
migration or native-package stripping as an implicit consequence of this proposal.

## H — ten holds and their concrete exit criteria

All ten Debian pages were reread for this checkpoint. No new installed fix or
complete reachability proof was established.

| CVE / primary source | Why held | Evidence needed to change the disposition |
|---|---|---|
| [CVE-2026-5450](https://security-tracker.debian.org/tracker/CVE-2026-5450) | Critical glibc allocating-scanf defect; installed Trixie source remains affected | Applicable supported fix plus requalification, or authoritative affected-call/input mapping; otherwise a separately explicit exception |
| [CVE-2026-19499](https://security-tracker.debian.org/tracker/CVE-2026-19499) | Insufficient description; installed glibc affected | Authoritative preconditions/source or supported installed fix |
| [CVE-2026-19542](https://security-tracker.debian.org/tracker/CVE-2026-19542) | tdelete stack-access issue; installed glibc affected | Native caller/input applicability or supported installed fix |
| [CVE-2026-77117](https://security-tracker.debian.org/tracker/CVE-2026-77117) | Insufficient description; installed glibc affected | Authoritative preconditions/source or supported installed fix |
| [CVE-2026-80489](https://security-tracker.debian.org/tracker/CVE-2026-80489) | Insufficient description; installed glibc affected | Authoritative preconditions/source or supported installed fix |
| [CVE-2026-11822](https://security-tracker.debian.org/tracker/CVE-2026-11822) | FTS5 is enabled; malformed DB plus MATCH path; raw recovery opens DB bytes | Raw-schema/query reachability analysis or applicable SQLite fix; read-only mode is not parser isolation |
| [CVE-2026-11824](https://security-tracker.debian.org/tracker/CVE-2026-11824) | FTS5 continuation-page defect; same raw-input boundary | Same bounded source/input analysis or applicable SQLite fix |
| [CVE-2026-39113](https://security-tracker.debian.org/tracker/CVE-2026-39113) | sqlar/default-connection and upstream-introduction versus Debian-mapping uncertainty | Reconcile affected source/build/component; not headline versions alone |
| [CVE-2026-50812](https://security-tracker.debian.org/tracker/CVE-2026-50812) | Newly checked apply_v3 symbol absent, but SESSION/older apply functions present and Debian still affected | Reconcile affected implementation/backport, not a whole-SESSION exclusion from one missing symbol |
| [CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091) | Described nonblocking gzwrite/gzprintf path and upstream version range differ from Debian mapping | Reconcile distribution source and relevant native calls; do not blindly upgrade to the headline newer version |

Targeted CNA retrieval for 19499/19542/77117/80489 again returned 404. The referenced
Sourceware bug pages were unavailable through this review (one access-denied page,
three tool open failures); no access-control bypass was attempted. Debian text and
the limited 19542 description are retained as the basis. Missing vendor text is
an evidence gap, not proof of safety or absence of the vulnerability. A newer fix
in Debian sid/forky is not an installed Trixie fix.

The next bounded investigation, after the owner decision, is the H list above:
authoritative source/build applicability first, then only any specifically approved
remediation. Do not rerun broad benchmarks or migrate distributions just to make
scanner totals smaller. If public source evidence remains unavailable, return the
specific unresolved ID and decision; do not loop indefinitely or grant a waiver.

## Verification and limitations

The existing [containment checker](security-containment-analysis.cjs) was rerun
against retained durable private logs and passes its 86 hash checks. No new full
application test run or all-image advisory scan is claimed here; the immediately
preceding 422 API / 58 web / 25 Python / 28 Node verification remains the named
application evidence.

The new [benign probe](security-disposition-components.py) ran in a disposable,
networkless, read-only container of the exact API ID, with no vault mounts or
application startup. At **2026-09-11 00:37:23Z**, it returned the zipdetails absence
observations and SQLite apply/apply_v2 present, apply_v3 absent. It invoked no
vulnerable function or malicious payload. Its isolation flags are probe controls,
not new product defaults. Four private capture files and their digests are retained
under the `containment-disposition-components` evidence directory.

The [proposal checker](security-disposition-check.cjs) joins the prior 80-entry
register to the exact lifecycle/scanner IDs, confirms 167 native matches and the
other 17 interpreter CVEs, validates the new probe and condition coverage, and
rejects invented acceptance fields or application drift. Run from the repo root:

```text
node makervault/docs/evidence/gate-13/security-disposition-check.cjs
```

`--write` only creates a missing generated proposal and refuses overwrites. The
checker verifies evidence consistency; it does not automate human risk judgment.
Current checks pass: **E 11/11, R 59/141, H 10/15** (CVEs/package matches), zero
acceptances, 86 containment hashes and four new probe hashes. Local documentation
links, Node syntax, the static release contract and `git diff --check` also pass.
The 23 targeted Debian rereads and four failed CNA lookups are dated source review,
not a new complete vulnerability scan or a separately archived vendor snapshot.
Historical unavailable temporary reports remain unavailable; current durable
captures do not retroactively replace them.

**Requested owner response:** approve E11 and the C1–C7 local-qualification R59
exceptions (explicitly including CVE-2026-12087 and CVE-2026-13221), confirm the
named approver, and keep H10 unaccepted. Approval would authorize recording those
decisions and continuing the bounded H review, **not** implementing an unreviewed
native-library migration or releasing v5.1.
