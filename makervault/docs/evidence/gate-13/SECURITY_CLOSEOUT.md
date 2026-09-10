# Gate 13C security closeout review

**Date:** 2026-09-10. **Status: REVIEW COMPLETE; SECURITY ACCEPTANCE OPEN.**

Owner authorized the security closeout review after parking further performance
tuning. This package records current scans, bounded source/runtime review, proposed
dispositions and the next approval checkpoint. It does not authorize application
or dependency changes, suppress findings, accept residual risk, qualify a release,
or replace the frozen Gate 5 candidate. All work remains local.

## Decision summary

| Item | Finding / recommendation | Closure requirement |
|---|---|---|
| S01 | New development-tool advisories: update Vitest/mocker and HTTPX2/httpcore2 in a narrowly scoped lock refresh | Owner approves patch scope; clean install, API/web/full gate and fresh lock audits pass |
| S02 | Outbound Unicode hostname normalization uses affected CPython IDNA behavior; existing IP/redirect protections remain | Approve a consistent hostname policy and focused hardening/regressions, or explicitly accept this named residual before qualification |
| S03 | Seven Python version exclusions revalidated; archive guard and base64 application boundaries have evidence | Retain the bounded dispositions below, not a claim that Python is universally patched |
| S04 | Native image findings remain, including unresolved critical-rated matches; raw recovery has a trusted-operator boundary | Resolve or individually accept applicable residuals with scope, owner, containment and review trigger; unknown applicability is not an exclusion |

Recommended next authorization is **S01 plus S02's bounded implementation proposal**,
then reassess S04 against the resulting exact images. Do not migrate Python major
versions, replace the base distribution, strip runtime utilities, or waive all
container findings merely to obtain a smaller scanner count.

## Evidence identity and checks

Application revision is `c42614e9cc99b45e32ffd203a4f7e70cb4ff0b30`; the audit source
checkpoint is documentation commit `fb645d7b93d6a52dc1b2fe39ee493801084c882c`.
Verification source paths were clean. Schema 17 and every application lock remain
unchanged by this review. These are local `development-gate13b` images:

| Image | Immutable local ID |
|---|---|
| API | `sha256:b1c67e9f8dad2b29e72a816cc472da9130d02faddf9cd9d35b2a0bd18d633de0` |
| Web | `sha256:7aa39929cd656b8fddaac64d62bc67174f172980e2ab0a1ccad0f298786da5f2` |

The complete audit started at `2026-09-10T20:44:26Z` using
`scripts/gate13-advisory-audit.py --phase all` with those two image IDs.
[Audit evidence](security-closeout-audit.json) retains scanner/DB versions, lock
hashes, raw artifact hashes and new language findings.
[Inventory](security-closeout-inventory.json) preserves every image match and
assigns all **97 unique image CVEs** to a review section without suppressions.

| Scan | Current result |
|---|---|
| npm production | 0 findings |
| npm full web | 2 moderate affected packages, 1 unique advisory |
| npm organization / preview harnesses | 0 / 0 findings |
| Python runtime / build | 0 advisories across 35 / 2 dependencies; none skipped |
| Python development | 6 package/advisory matches across 43 dependencies; 2 affected packages, 5 unique CVEs; none skipped |
| Go source, symbol-level | 0 findings; govulncheck 1.7.0, Go 1.26.6 |
| API image | 181 matches / 96 CVEs: 7 critical, 61 high, 51 medium, 9 low, 45 negligible, 8 unknown |
| Web image | 3 medium matches / 1 CVE |

Image scan used Grype 0.118.0, valid schema-6.1.9 DB built September 10 at 06:30:24Z.
Every reduced API match equals the latest sidebar-menu record; every reduced web
match equals the retained prior web inventory. Equality includes identity,
severity, package/version/type, source/namespace, locations, match types and fix
state/versions—not every field of raw scanner output. Counts alone were not used.
The current image scan does not upgrade `c42614e`'s previous API-only verification
to a complete repository/HTTPS lifecycle repeat.

Focused security tests passed twice: initial test-image tag **68 passed / 15.38 s**,
then explicitly pinned test image
`sha256:4704c6196a007886663402c78668d93160a302cf836e6a65424d48388e3ae3e4`
**68 passed / 15.54 s**. Both used network-disabled disposable containers running
`python -m pytest -q tests/test_archive_compression.py tests/test_safe_http.py tests/test_passkey_foundation.py tests/test_audit.py`.
This is focused regression evidence, not a penetration test or full-gate run.

[Runtime observations](security-closeout-runtime.json) were collected by
[the benign probe](security-closeout-runtime.py) in the exact API image, with
read-only filesystem, no network, no capabilities, no-new-privileges, UID/GID
65534, 256 MiB and one CPU. No application startup, vault mounts, hostile database,
exploit payload, DNS request or live user data was used.

## S01 — development dependencies: patch proposed, not installed

Vitest and `@vitest/mocker` are locked at 4.1.10. The vendor describes a redirect
mock path-traversal/file-read problem in particular development-server plugin
configurations; the same-major fix is **4.1.11**.
[Vendor advisory](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9).
Production serves static files with Nginx, not a Vitest server. No custom
`mockerPlugin`/`interceptorPlugin` registration was identified in this repository.
Nevertheless, our Vite configuration uses `host: true` and defaults permissively
for allowed hosts: generic upstream localhost/default-host defenses must not be
assumed here. Keep development servers off untrusted networks pending the update.

Development locks contain `httpx2==2.9.0` and `httpcore2==2.9.0`:

| Unique CVE | Affected path | First vendor fix / source |
|---|---|---|
| CVE-2026-84378 | SSE line-buffer CPU exhaustion | [HTTPX2 2.10.0](https://github.com/pydantic/httpx2/security/advisories/GHSA-f2fp-rgf2-35cp) |
| CVE-2026-84379 | Multipart part-header injection | [HTTPX2 2.11.0](https://github.com/pydantic/httpx2/security/advisories/GHSA-h4x7-gw46-3wm6) |
| CVE-2026-84380 | Conflicting outgoing HTTP framing headers | [HTTPX2 2.11.0](https://github.com/pydantic/httpx2/security/advisories/GHSA-pf96-p4fj-6566) |
| CVE-2026-84381 | WSS over SOCKS without expected TLS; matches both packages | [HTTPX2/httpcore2 2.10.0](https://github.com/pydantic/httpx2/security/advisories/GHSA-7mj9-2mp8-4m2p) |
| CVE-2026-84382 | Compressed-response peak allocation before chunk-size limiting | [HTTPX2 2.12.0](https://github.com/pydantic/httpx2/security/advisories/GHSA-8xx6-hgc6-gc2m) |

Recommend HTTPX2 **at least 2.12.0**, with a compatible locked httpcore2 **at least
2.10.0**, not stopping at the first advisory's older fix. Both packages and pytest
are absent from the inspected production API Python environment. MakersVault's
outbound production transport is `safe_http.py`, not HTTPX2. These are development
exposures, not six production API vulnerabilities; patched tools are still the
preferred low-cost disposition. Re-resolve hashes and test compatibility, without
`audit fix --force` or an unrelated major-version refresh.

## S02 — Unicode hostname policy: reachable, not a demonstrated bypass

[The current PSF CVE record](https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2026/17xxx/CVE-2026-17084.json)
describes stringprep/IDNA identity inconsistencies involving Unicode table versions.
Installed Python is **3.11.16**, not the scanner's listed **3.15.0rc2** fix.
`api/url_utils.py:_normalized_host` calls the affected stdlib codec on remote
hostnames. Offline, the installed codec maps `ẞ.example` to `ss.example`.
That observation alone is neither a successful network request nor a security bypass.

Existing defenses remain meaningful: reject control characters/userinfo and
non-HTTP(S) schemes, normalize before DNS, reject private/non-global resolutions,
connect to a validated numeric peer, validate redirects again, strip cross-origin
credentials and refuse HTTPS downgrade. These address IP/redirect SSRF; they do
not by themselves establish correct Unicode domain identity.
`http_security.py` also invokes IDNA as a validity check, but discards its encoded
result and requires ASCII DNS-host syntax afterward. Do not misdescribe this as
the same canonicalization path or assume an origin/passkey bypass.

**Proposed narrow fix:** one explicit, strict IDNA policy for outbound DNS names,
using the already installed third-party `idna` package as a declared direct
dependency rather than relying on affected stdlib behavior. Preserve ordinary
ASCII names, literal IPv4/IPv6 handling, numeric-peer validation and redirect rules;
reject invalid/ambiguous input before DNS and use the same canonical ASCII name
for DNS, Host and TLS SNI. Test Unicode/punycode equivalence and rejection,
trailing-dot cases, malformed/control-containing hosts, mixed DNS answers and
redirect credential boundaries. Recheck configured Host/Origin/passkey behavior;
do not silently loosen those policies or rewrite stored URLs.

This is a compatibility decision, not merely a package bump. A stricter policy may
reject unusual internationalized URLs previously accepted. An ASCII-only raw-input
policy is a smaller but more restrictive alternative; a Python-major migration
is outside this bounded proposal. None is implemented or accepted by this review.

## S03 — interpreter dispositions with bounded evidence

Fresh PSF branch ranges reconfirm the seven exclusions from
[the historical residual review](REMEDIATION_RESIDUALS.md). The inventory retains
the vendor URL, response hash, update date and affected-version entries:

- CVE-2026-4224, CVE-2026-3644, CVE-2026-4519, CVE-2026-4360 and
  CVE-2025-13462: the 3.11 affected branch ends before installed 3.11.16.
- CVE-2026-7210: installed 3.11.16 and observed Expat **2.8.3** meet the two-part
  fixed boundary (the Expat requirement is at least 2.8.0).
- CVE-2025-13837: the 3.11 affected branch ends before 3.11.15.

The ten other Python matches are not covered by those exclusions:

| CVEs | Application disposition |
|---|---|
| CVE-2026-15310 | Approved Stored/Deflate-only preflight rejects unsupported ZIP methods before member decompression. Actual byte/count/ratio budgets remain. Focused archive regressions pass. Application read paths mitigated; interpreter remains affected |
| CVE-2025-12781 / CVE-2026-3446 | Passkey and recovery inputs enforce canonical alphabet/round-trip rules. Audit cursors are bounded pagination data, not signed identity or authorization grants; decoded values feed parameterized comparisons behind Administrator authorization. No security decision based on alternate cursor spelling was identified. Not a general base64 patch |
| CVE-2026-15806 | No application use of the affected HTTP password manager; custom pinned-peer transport is separate |
| CVE-2025-15366 / CVE-2025-15367 / CVE-2026-6019 | No production call path identified for IMAP, POP or the inline-JavaScript cookie helper |
| CVE-2026-19672 | Production Python archive handling validates regular members and uses bounded `extractfile`, not the vulnerable `extractall` filter behavior. GNU tar in raw restore is a separate residual below |
| CVE-2026-3479 | Vendor-disputed trusted-input `pkgutil.get_data` contract; no direct application caller identified |
| CVE-2026-17084 | S02 remains open |

Source review is scoped to the current application, not proof that no installed
third-party package could ever invoke a stdlib API. No finding is removed from
scanner evidence, and future callers must reopen these dispositions.

## S04 — native image residuals and recovery boundary

The seven critical-rated package matches represent six CVEs:

| CVE | Observed precondition / remaining disposition |
|---|---|
| CVE-2026-5450, libc6 and libc-bin (2 matches) | Particular allocating `scanf` conversion. Native library is present; complete native reachability is not proven absent. [Debian still lists Trixie vulnerable](https://security-tracker.debian.org/tracker/CVE-2026-5450), with no DSA/minor classification. **Unresolved**, not cleared by that classification |
| CVE-2026-8376 | Requires a 32-bit Perl build; inspected Perl is x86_64 with 8-byte pointers. Precondition absent for this image only, not an architecture-wide exemption |
| CVE-2026-42496 / CVE-2026-57433 | Required Archive::Tar / Storable modules are not loadable in the inspected runtime; bounded component-absence evidence |
| CVE-2026-13221 / CVE-2026-12087 | Perl core / Socket module are present. No application-controlled Perl invocation found, but neither an installed patch nor component absence is established. Retain as explicit residuals |

The other native families remain visible rather than being hidden by a global
"unused package" label. Counts below are API package matches, not unique CVEs:

| Source family (matches) | Bounded review / qualification condition |
|---|---|
| glibc (36) | Includes runtime resolver/locale/native interfaces and disputed/local/preconditioned records. No exhaustive native call-graph proof. Four current CNA records were unavailable; do not exclude them |
| util-linux (54) | Advisory paths include login, mount helpers and nsenter. Startup **uses setpriv**; no untrusted mount/nsenter/login command path identified. Preserve the non-root transition and do not strip this family blindly |
| Perl (17) | Additional Archive::Tar, HTTP::Tiny, IO::Uncompress::Unzip, IO::Compress and File::GlobMapper modules are not loadable; exact CVE mappings are in the inventory. Perl core, File::Temp and Socket remain present; no blanket family exclusion |
| SQLite (7) | Runtime 3.46.1 has **FTS5 and SESSION compiled in**. No application FTS MATCH or changeset-merge caller identified, but raw recovery opens supplied database bytes. sqlar/zipfile functions are absent in the default inspected connection, not proof about every extension or a native sandbox |
| zlib (2) | Runtime 1.3.1. CVE-2026-27171 concerns negative combine arguments, not every ordinary decompression call. CVE-2026-85091 has a CNA version range differing from Debian's affected Trixie mapping. Retain unresolved; do not guess a version exclusion or blindly choose 1.3.2 |
| systemd (14), PAM (4), shadow (4) | API process is not a systemd service manager or PAM web-login service; OS account tools are used during startup. Local/operator preconditions constrain exposure but do not patch installed libraries/tools |
| coreutils (4), acl (2), attr (1) | Startup/recovery **use chown**; some advisories require specific recursive/dereference options or privileged path races. Keep storage roots and restore staging operator-controlled; no blanket unused-utility claim |
| GNU tar (4), gzip (2), bzip2 (1) | Raw backup/restore scripts **invoke GNU tar**, including extraction after Python auditing. Parser-differential and native-resource risks are not erased by archive checks or the separate Python ZIP guard. Trusted raw snapshot boundary is required |
| apt (2), diffutils (1), ncurses (8), PCRE2 (1) | No application-controlled package-manager, diff3, terminal-tool or native DFA-regex invocation identified. These remain installed-package residuals pending explicit disposition, not proof of absence from every dependency |

SQLite CVE-2026-11822/11824 involve malformed FTS5 database content; the raw path's
read-only connection is **not** a sandbox against malformed SQLite. The portable
`.mvault` importer instead reconstructs a clean database from validated logical
content. Accept raw backups only from a trusted operator-controlled installation
with protected provenance; do not use raw SQLite/format-1 backups as a public
model-sharing/import format. Checksums detect mismatches, not a malicious author's
authority. GNU tar use in `scripts/restore.sh` makes this trust boundary relevant
to extraction as well. The operator guide now states this limitation explicitly;
documentation is not an implementation fix or a residual-risk waiver.

SQLite CVE-2026-39113/50812 and zlib CVE-2026-85091 also have version/component
details that should not be resolved by comparing only headline upstream versions
against Debian backport versions. Their inventory entries remain unresolved.
See the primary [SQLite FTS5 record](https://security-tracker.debian.org/tracker/CVE-2026-11822)
and [zlib tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091).

Web's three matches are CVE-2025-60876 across BusyBox package entries. The described
path is BusyBox **wget**, not Nginx HTTP parsing. No application URL-to-wget path
was identified in the web packaging/runtime configuration. The installed component
is still reported by [Alpine](https://security.alpinelinux.org/vuln/CVE-2025-60876);
keep it as a scoped residual, not an installed fix or zero-vulnerability image.

## Review completeness, limits and next checkpoint

[Vendor collection](security-closeout-vendor.cjs) obtained all 79 relevant Debian
pages and 93 of 97 CNA records at `2026-09-10T20:51:12Z`. CVE-2026-19499,
CVE-2026-19542, CVE-2026-77117 and CVE-2026-80489 returned CNA 404s. Their Debian
records remain available and affected; missing descriptions limit applicability
review. They are unresolved, never "not vulnerable because lookup failed".
An initial oversized Debian-database attempt and a mis-grouped four-digit-ID
attempt were tooling failures, replaced by bounded per-ID retrieval. Only the
final snapshot is hashed as evidence. The [reducer](security-closeout-analysis.cjs)
asserts exact fresh-inventory coverage before producing the committed records.

[Evidence consistency checks](security-closeout-check.cjs) pass: seven unchanged
lock hashes, 22 raw artifact hashes, the vendor snapshot hash, 184 retained image
matches / 97 distinct CVEs, 187 local document links and zero risk acceptances.
The checks first caught a combined-release Debian table row and a parenthesized
Markdown filename; the reducers/checker were corrected and rerun, without changing
scanner findings. Node syntax checks and `git diff --check` pass. Application,
web, bridge, benchmark and production-script paths have no diff from the entry
checkpoint. Evidence helpers live only under this documentation directory.

Raw scanner output and the full vendor snapshot remain in private temporary
artifacts, not a published vault/log dump. Committed records retain hashes,
inventory, source URLs and decision-relevant facts; they do not contain credentials,
user models, private URLs or exploit payloads. This is a dated source/runtime
review with focused regressions, not full binary reachability analysis or a
third-party penetration test. No claim of exploitation in MakersVault is made.

**Owner checkpoint:** approve the S01/S02 implementation proposal, not a risk
waiver. After verification, present remaining S04 CVEs for explicit disposition
against the actual candidate. Any acceptance must name the maintainer, exact
image/architecture, rationale, deployment containment, and a review deadline
(recommended: before 13D/candidate freeze and within 30 days of acceptance,
whichever comes first). Reopen immediately for a relevant stable/vendor fix,
new reachable path, changed architecture, or weaker deployment boundary.

G13-04 stays open until those decisions and proofs exist. Physical/native-platform
qualification and matched release evidence remain separate next steps. Performance
G13-01 stays deferred; Gate 12 stays desktop-deferred. No push, tag, publication,
deployment, release-pin change, or automatic Gate 13C/13D acceptance occurred.
