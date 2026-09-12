# Gate 13C — vendor/scanner reconciliation

**Date:** September 12, 2026, America/New_York.
**Application:** unchanged local `6306ccff289d475530a6cacf4cb2e28db456ce08`.
**Review entry:** `a62bc11bf08742026cd469aec364fc043c1fb277`.
**Status: 26 VENDOR FIXES VERIFIED; REMAINING DISPOSITIONS AND SECURITY ACCEPTANCE OPEN.**

The owner's “go ahead” authorizes the read-only application review proposed in the
[native-update checkpoint](SECURITY_NATIVE_UPDATE_RESULTS.md). This review resolves
the applicability disagreement for all **20 targeted CVEs plus six newly seen
PCRE2 CVEs**: the already-installed packages contain the vendor fixes. No further
package update is needed for this group. This is technical fix evidence, not a
risk waiver, scanner suppression, gate acceptance or release authorization.

## Evidence chain

The [current Debian machine-readable feed](https://security-tracker.debian.org/tracker/data/json)
was captured at **17:12:34–17:12:53 UTC**. It marks each of the 26 IDs `resolved`
for Trixie, with a fixed version exactly equal to the installed pin. The complete
74,114,962-byte decoded body is retained privately with SHA-256
`28c767a2942cabefcccf043e671d37e1f9692754e667b10d290db8eca88dc525`.
Its HTTP Last-Modified is **16:23:59 UTC**, not the date these fixes were released.

A separate disposable container from the exact API image refreshed the configured
APT indexes with authentication required, downloaded the six exact package
versions, and matched every archive SHA-256 against authenticated APT metadata.
It then read their packaged changelogs and compared **931 regular files** under
executable/library directories byte-for-byte with the installed runtime files.
All comparisons passed. This includes scripts/modules; it is not a claim of 931
ELF binaries, a full-filesystem comparison or a source-level exploit test.

| Installed package | Exact verified version | Regular files compared | Fixed CVEs |
|---|---|---:|---:|
| gzip | `1.13-1+deb13u1` | 13 | 2 |
| libc-bin / libc6 | `2.41-12+deb13u4` | 24 / 276 | 2 shared source IDs |
| libpcre2-8-0 | `10.46-1~deb13u2` | 1 | 7 |
| libsqlite3-0 | `3.46.1-7+deb13u2` | 1 | 2 |
| perl-base | `5.40.1-6+deb13u1` | 616 | 13 |

The non-PCRE2 changelog entries explicitly name their reviewed CVEs. PCRE2's entry
records upstream security backports from 10.48; the Debian feed supplies the exact
seven-CVE mapping. The [Debian PCRE2 source-package page](https://security-tracker.debian.org/tracker/source-package/pcre2)
also lists these seven as resolved. Thus the missing individual-page/backport
evidence at the preceding checkpoint is now supplied by the official aggregate
feed and authenticated binary packages. A move to upstream 10.48 or another
distribution is unnecessary for these seven IDs; the installed upstream version
string can remain 10.46 with Debian backports.

For traceability, the verified IDs are:

- gzip: CVE-2026-41991, CVE-2026-41992.
- glibc: CVE-2026-5450, CVE-2026-5928 (both libc packages).
- SQLite: CVE-2026-11822, CVE-2026-11824.
- PCRE2: CVE-2026-86145, CVE-2026-89156, CVE-2026-89157,
  CVE-2026-89158, CVE-2026-89160, CVE-2026-89161, CVE-2026-89162.
- Perl: CVE-2025-15649, CVE-2026-12087, CVE-2026-13221,
  CVE-2026-42496, CVE-2026-42497, CVE-2026-48959, CVE-2026-48961,
  CVE-2026-48962, CVE-2026-57432, CVE-2026-57433, CVE-2026-7010,
  CVE-2026-7017, CVE-2026-8376.

The package probe completed **17:12:35–17:13:10 UTC**. It installed nothing and
started no application. APT indexes/downloads existed only in the disposable
container, with no host vault mounted. Archive metadata/hashes, changelog extracts
and file comparisons are retained; full `.deb` bodies were not retained after
container removal. Authentication is through signed repository metadata and
matching archive hashes, not a claim that each `.deb` has an independent signature.
The probe's root user and resource flags are diagnostic-only, not product defaults.

## Scanner truth and remaining decisions

The retained September 12 scan remains **189 API / 3 web matches**, or **192 matches
and 104 unique CVEs**. It was not rerun, filtered or modified. Its **28 matches for
these 26 fixed CVEs** have empty fixed-version lists and `none (unknown)` version
constraints. The source-feed and exact-byte evidence now resolve package fix
applicability; they do not make those historical raw matches disappear.

The scanner's Debian provider capture is **00:30:55 UTC**, before this feed's
Last-Modified. That supports a metadata-age/disagreement explanation, but does not
independently prove the precise upstream ingestion or refresh failure. No Grype
ignore rule, only-fixed filter, VEX document or global exception was installed.
In particular, do not subtract 28 from the raw inventory or claim a clean scan.

The [new per-CVE register](security-reconciliation.json) accounts for all 87 native
CVEs exactly once:

| Disposition | CVEs | Boundary |
|---|---:|---|
| Vendor-fixed, installed bytes verified | 26 | Technical resolution; no risk waiver required for the verified fix |
| Proposed exact-image exclusions | 2 | CVE-2026-9538 needs absent `Archive::Tar`; CVE-2026-89092 needs absent `nscd`. Neither exclusion newly accepted |
| Pending new-image owner exceptions | 52 | Prior bounded rationales retained; no automatic old-image approval transfer or wholesale renewed review |
| Unresolved, unaccepted holds | 7 | Four glibc, two SQLite and one zlib entry below |

The fresh feed still marks **CVE-2026-19499, CVE-2026-19542, CVE-2026-77117,
CVE-2026-80489, CVE-2026-39113, CVE-2026-50812 and CVE-2026-85091** open for the
installed Trixie sources, with no applicable fixed version recorded. Their prior
source/caller gaps and exit criteria remain in the register. Minor/no-DSA labels
are not fixes or owner acceptance. The two exclusion sources also remain open;
their narrower recommendation depends on exact-image component absence, not a
vendor fix. Debian's [nscd advisory](https://security-tracker.debian.org/tracker/CVE-2026-89092)
requires the nscd service and untrusted DNS responses; the exact-image probe found
no nscd package-manifest match or named executable.

The four newly held PCRE2 entries and two proposed PCRE2 architecture exclusions
from the prior checkpoint are superseded by verified fixes, not waivers. Only nscd
of the seven newly seen CVEs still needs its proposed owner disposition. The 17
separate interpreter CVEs remain unchanged and outside this 87-ID native register.

## Identity, limitations and checks

This review qualifies only the unchanged **linux/amd64 development** images:

- API: `sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`
- Web: `sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67`

The first feed capture failed its 32 MiB decoded-size bound. Its exit-1 record and
error remain; a fresh capture with a diagnostic 128 MiB bound succeeded. No access
control or global allowlist was changed. Earlier unavailable browser pages are not
claimed as successful captures. The current full aggregate feed is separately
retained, not a reconstruction of those pages.

Run `node makervault/docs/evidence/gate-13/security-reconciliation-check.cjs` from
the repository root. It checks **15 new private hashes** plus the previous
checkpoint's **167**, all three attempt records, feed/package/version joins,
archive authentication evidence, 931 comparisons and all 87 dispositions.
Historical native/owner/proposal JSON remains byte-identical. The prior full-gate
results (424 API / 58 web tests, HTTPS lifecycle and containment) remain applicable
to unchanged application inputs; this diagnostic slice did not repeat them or run
a new image scan. It did not audit every source patch/native call path or renew all
52 pending exception rationales. Final Node syntax, **219 local documentation links**, the
static release contract and `git diff --check` pass.

## Next bounded checkpoint

Prepare the exact-image owner decision for the **two proposed exclusions and 52
pending exceptions**, rechecking relevant C6 changes before recommending it; treat
the **seven holds separately**, with authoritative applicability/fix evidence or
a separately informed owner decision. This review grants **zero** new acceptances.
Keep C1–C7 and the earlier **October 12 00:00 America/New_York** deadline (or earlier
freeze/13D/C6 trigger) explicit; no deadline extension or waiver transfer is implied.

Do not rebuild again merely to chase a lower scanner count. Additional package
changes, risk acceptance, S04/G13-04 closeout and Gate 13C/13D acceptance remain
separate checkpoints. G13-01 performance tuning and desktop Gate 12 stay deferred;
real-platform/operator/release readiness and the frozen Gate 5 baseline are
unchanged. No application code, lock, image, schema, deployment or model bytes
changed. Nothing was pushed, tagged or published.
