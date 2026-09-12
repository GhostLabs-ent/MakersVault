# Gate 13C — bounded review of the seven remaining holds

**Date:** September 12, 2026, America/New_York.
**Application:** unchanged `6306ccff289d475530a6cacf4cb2e28db456ce08`.
**Status: TWO ADDITIONAL EXCLUSIONS PROPOSED; FIVE UNRESOLVED; NO H ACCEPTANCES.**

**Subsequent decision:** the owner [approved only these two exclusions](SECURITY_HOLD_OWNER_ACCEPTANCE.md)
under unchanged C1–C7/deadline. The current combined register is E4/R52/F26/H5.
The proposal and pending machine review below remain historical evidence, not the
current approval ledger. The five other holds and security closeout remain open.

The owner [approved E2/R52](SECURITY_CURRENT_OWNER_ACCEPTANCE.md), explicitly
including the BusyBox evidence gap, and authorized the package's bounded H review.
That approval does not accept any of H7. This review now supports two narrowly
scoped source-precondition exclusions, proposed below; all seven remain
unaccepted until a separate owner decision. No package change is needed for the
two proposed exclusions.

## Source and runtime evidence

The successful **20:13:06–20:13:53 UTC** probe used a disposable copy of the exact
qualified API image, with no host vault mount or application startup. Its
diagnostic-only APT source list uses the same configured Debian suites, repository
URIs and archive key, adding source indexes only inside the disposable container.
Signed-index authentication remained required. No host/image APT configuration
was changed and nothing was installed or built.

| Source package | Exact runtime binary | Source archive files authenticated | Installed library compared |
|---|---|---:|---|
| SQLite `3.46.1-7+deb13u2` | libsqlite3-0 `3.46.1-7+deb13u2` | 4 | `libsqlite3.so.0.8.6` |
| zlib `1:1.3.dfsg+really1.3.1-1` | zlib1g `1:1.3.dfsg+really1.3.1-1+b1` | 3 | `libz.so.1.3.1` |

All seven `.dsc`/source/packaging archive hashes match authenticated source-index
metadata. Both downloaded binary archives match authenticated binary-index hashes,
and each shared library matches its exact installed runtime bytes. Source versions
come from distribution metadata, not guesses based on upstream version strings.
This trusts Debian's source/binary association; it is **not** an independently
reproduced build or a claim that each archive has its own checked signature.

Selected original source files, packaging rules, active patch names/targets and
hashes are retained privately. All 15 active SQLite patches were accounted for;
none changes `sqlar.c` or `sqlite3session.c`. The zlib source has no Debian patch
series introducing later `gzwrite.c`/`gzguts.h` behavior. Packaging rules were also
read; no relevant source rewrite was identified. No source tree was extracted,
patch applied, compiler invoked or vulnerable function exercised.

## Proposed additional exclusions — owner pending

### CVE-2026-39113 — SQLite SQLar size conversion

The [Debian description](https://security-tracker.debian.org/tracker/CVE-2026-39113)
identifies the March 11, 2026 SQLar change. The linked
[upstream commit](https://github.com/sqlite/sqlite/commit/169f68ed88b34cb68f720191c64c058f2ccec508)
switches the requested output-size read from `sqlite3_value_int` to
`sqlite3_value_int64`. This is the concrete conversion relevant to the reported
allocation-size mismatch, not just a release-number comparison.

The authenticated shipped source still uses the older 32-bit size read. No active
Debian patch alters that file. The installed library matches the authenticated
archive, and the earlier exact-runtime probe has no default SQLar functions.
Together these support excluding **this described defect on this exact image**.
They do not exclude every SQLite extension, corruption scenario or raw database
recovery risk.

**Recommendation:** approve a source-precondition exclusion for this ID under
C1–C7. Debian still marks the source affected; retain that disagreement and the raw
package match. This is not a newly installed fix or a corrected vendor record.

### CVE-2026-85091 — later zlib nonblocking-write implementation

The [Debian description](https://security-tracker.debian.org/tracker/CVE-2026-85091)
names `gz_vacate` and nonblocking write-stall handling introduced after upstream
1.3.1. The [upstream issue](https://github.com/madler/zlib/issues/1310) reports the
assignment but the retrieved page does not provide a maintainer-confirmed fix or
affected-version adjudication.

The authenticated shipped 1.3.1 source has no `gz_vacate`, `EAGAIN` or
`EWOULDBLOCK` handling in `gzwrite.c`. Its write-error path sets `Z_ERRNO` and
returns; the printf path checks the error state before continuing. No Debian
patch introduces the newer implementation. Installed libz bytes match the exact
authenticated `+b1` binary package, whose source version excludes that suffix.

**Recommendation:** approve a source-precondition exclusion for this specific
newer-code defect under C1–C7. This does not declare zlib unused or safe for all
inputs, clear the separate checksum-combine exception, or alter Debian's affected
source classification. Preserve the raw match and reopen on contrary evidence.

## Five unresolved holds — no exception requested here

| CVEs | Evidence obtained / remaining gap |
|---|---|
| [CVE-2026-19499](https://security-tracker.debian.org/tracker/CVE-2026-19499), [CVE-2026-77117](https://security-tracker.debian.org/tracker/CVE-2026-77117), [CVE-2026-80489](https://security-tracker.debian.org/tracker/CVE-2026-80489) | Current Debian pages have no advisory description and still mark the installed Trixie source affected. Referenced Red Hat and Debian bug pages were unavailable; missing details do not establish safety |
| [CVE-2026-19542](https://security-tracker.debian.org/tracker/CVE-2026-19542) | tdelete stack-access defect is identified, but the named upstream fix page was unavailable and no exact native caller/source exclusion was established |
| [CVE-2026-50812](https://security-tracker.debian.org/tracker/CVE-2026-50812) | Authenticated source confirms apply_v3 is absent, but older apply/apply_v2, SESSION and value-type call paths remain. The upstream fix page was unavailable, leaving shared-code applicability unresolved |

The seven Debian pages were freshly read; none reports an applicable installed
Trixie fix. Newer sid/forky fixes and minor/no-DSA labels are not release clearance.
The [dated primary review](security-hold-primary-review.json) records successful
reads and eight non-retryable browser failures. Those pages were not retried;
earlier failed CNA/Sourceware bug lookups were also not repeated. Browser page
bodies were not separately archived. No external issue/comment was posted.

## Reproducibility and authority

The [machine review](security-hold-review.json) retains exact identities, archive
and selected-source hashes, patch targets, source-to-binary metadata, both attempts
and each pending recommendation. Run:

```text
node makervault/docs/evidence/gate-13/security-hold-review-check.cjs
```

It checks **eight new private hashes plus 197 prior hashes**, the explicit E2/R52
event, two authenticated source packages, two matched runtime libraries and all
seven H dispositions. The first attempt failed because it incorrectly expected
zlib's binary and source versions to be equal; `+b1` is a binary rebuild suffix.
The corrected diagnostic pins both exact versions and retains the failed attempt.
This was a probe correction, not a package change. APT also reported root download
fallback inside private disposable scratch directories; repository authentication
remained enabled. Probe resource/root flags are not product defaults.

Full source/binary downloads disappeared with the disposable scratch directories;
selected text, patch data, metadata and hashes remain in private logs. No new full
suite, image scan, deployed-instance test, exploit or exhaustive call graph is
claimed. Current raw scans stay **189 API / 3 web matches**. The approval event,
historical proposals, application inputs and frozen release pins remain unchanged.
Node syntax, **251 local documentation links**, the static release contract and
the staged patch whitespace check pass. The whole-worktree whitespace check finds
a trailing space in the owner's concurrently added roadmap notes; those notes are
preserved and excluded from this security commit, not silently reformatted.

**Next owner checkpoint:** approve only the two additional source-precondition
exclusions above for the same exact images under C1–C7, with the unchanged October
12-or-earlier deadline. That would make E4/R52/F26 with five unresolved holds;
it would not accept those five or close security/Gate 13C. Before any release,
those five still need authoritative resolution or a separately explicit, informed
owner disposition. Do not keep retrying unavailable public pages or migrate
distributions merely to change scanner totals. No application change, push,
publication, deployment or restart of deferred performance work occurred.
