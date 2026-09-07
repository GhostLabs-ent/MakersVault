# Gate 13C — residual findings and archive scope checkpoint

**Reviewed:** 2026-09-07 UTC (2026-09-06 America/New_York).

**Build:** clean `84b020ddf18795b482040d8b669c081897fff31a`; exact images and full
verification are recorded in [remediation results](REMEDIATION_RESULTS.md).

**Decision owner:** MakersVault maintainer. **Status:** OPEN, no risk accepted.
This is a targeted source/vendor review, not an exhaustive exploitability assessment
or a waiver of unreviewed high/critical/no-fix packages. Recheck before selecting a
candidate, on an upstream security update, and after any affected parser change.

## Interpreter: distinguish vendor ranges from CPE matches

The unfiltered image scan reports 17 matches for Python 3.11.16. The
[captured PSF CNA records](remediation-python-vendor.json), obtained from the
[CVE program's record API](https://cveawg.mitre.org/api/cve/CVE-2026-4224), include
version ranges, vendor update dates and patch/advisory references. Seven records
explicitly exclude this interpreter version; these are vendor-evidenced
not-affected observations, not ignored matches or automatic exemptions for the
other ten records:

| PSF record | Applicable branch boundary |
|---|---|
| [CVE-2026-4224](https://cveawg.mitre.org/api/cve/CVE-2026-4224) | 3.11 affected below 3.11.16 |
| [CVE-2026-7210](https://cveawg.mitre.org/api/cve/CVE-2026-7210) | Affected below 3.11.16; actual bundled Expat reports 2.8.3 |
| [CVE-2026-3644](https://cveawg.mitre.org/api/cve/CVE-2026-3644) | 3.11 affected below 3.11.16 |
| [CVE-2026-4519](https://cveawg.mitre.org/api/cve/CVE-2026-4519) | 3.11 affected below 3.11.16 |
| [CVE-2026-4360](https://cveawg.mitre.org/api/cve/CVE-2026-4360) | 3.11 affected below 3.11.16 |
| [CVE-2025-13462](https://cveawg.mitre.org/api/cve/CVE-2025-13462) | 3.11 affected below 3.11.16 |
| [CVE-2025-13837](https://cveawg.mitre.org/api/cve/CVE-2025-13837) | 3.11 affected below 3.11.15 |

The other records use broader ranges which do not establish a 3.11.16 fix. Initial
application observations below narrow review; they do not silently clear the
interpreter or all transitive use:

- **CVE-2025-12781 / CVE-2026-3446:** base64 alphabet/padding behavior. The passkey
  decoder uses `validate=True`, rejects supplied padding and requires a canonical
  URL-safe re-encoding match. Separate audit-cursor/offline-recovery decoders still
  require their own semantic review; a passkey control is not a global exemption.
- **CVE-2026-15806:** urllib password-manager scheme handling. `safe_http.py`
  implements its own pinned-peer/redirect transport and does not use
  `HTTPPasswordMgr`. This is a source-path observation, not a whole-image waiver.
- **CVE-2025-15366 / CVE-2025-15367 / CVE-2026-6019:** IMAP, POP and
  `http.cookies.Morsel.js_output` paths were not identified in application source.
  Their presence in the standard library remains in the raw inventory.
- **CVE-2026-19672:** tar-filter extraction can create out-of-target empty
  directories. Recovery uses validated `extractfile` streams/private temporary
  directories; it does not rely on `extractall(filter=...)` as its safety boundary.
  Keep the full portable/recovery extraction inventory in the residual review.
- **CVE-2026-3479:** the PSF disputes a vulnerability in `pkgutil.get_data` under
  its intended trusted-input contract. No application call was identified; retain
  the vendor record and do not reinterpret this as a general safe-file-open claim.
- **CVE-2026-17084:** Unicode/stringprep/IDNA behavior remains open for outbound
  hostname/origin review. Existing SSRF regression tests alone do not disposition
  the newly recorded interpreter issue.
- **CVE-2026-15310:** source-reachable archive decompression, detailed below.

## Archive issue requiring a compatibility decision

The PSF [CVE record](https://cveawg.mitre.org/api/cve/CVE-2026-15310) and
[upstream fix](https://github.com/python/cpython/commit/31980e84b9a708424a0a1dfecde3fc991e313f89)
describe unbounded per-call expansion in non-DEFLATE ZIP decompressors. The
upstream fix was inspected, not copied into MakersVault or the interpreter.
Python 3.11 does not supply ZIP Zstandard support, but it does supply BZIP2/LZMA.

The exact audited API image was inspected in a disposable, network-disabled,
256 MiB/one-CPU container. Its `ZipExtFile._read1` bounds DEFLATE decompression,
but calls other decompressors with no output-length argument and only clips the
result afterwards. Requesting a small read does not bound the intermediate
allocation in that branch.

Relevant current application paths:

| Source | Existing control | Gap relevant to this advisory |
|---|---|---|
| `api/archive_limits.py::validate_archive_member` | Declared size and compression-ratio checks | No compression-method restriction; ZIP headers are untrusted and do not cap an internal decompressor allocation |
| `api/zip_service.py::extract_zip_entries_to_assets` and `resource_limits.py::stream_reader_to_file` | Selected-entry/total budgets, bounded reads and actual-byte checks | The interpreter decompresses before the outer reader can enforce its returned-byte budget |
| `api/asset_service.py::extract_3mf_thumbnail*` | Entry count, declared image/aggregate metadata sizes, ratio | Reads selected ZIP members through the same interpreter path |
| `api/prepared_print.py::inspect_prepared_print` | Entry/metadata budgets and a bounded prepared-payload sample | Small `read` or declared metadata limits do not repair that interpreter branch |

This is a source-based applicability finding, not a demonstrated production OOM.
An optional instrumented ordinary-archive diagnostic was blocked before execution
by the local command allowlist; it is not counted as test evidence. No bypass,
allowlist change, large memory-exhaustion fixture or user-vault upload was used.
The separate bounded **fflate ZIP64** regression did run and pass; that patch
does not fix this Python ZIP issue.

### Approved next slice — implementation/evidence recorded separately

The owner approved this proposal on 2026-09-06 (America/New_York), after local
checkpoint `78f6aa3`. Follow [archive guard results](ARCHIVE_GUARD_RESULTS.md) for
actual implementation and verification. Approval is not residual-risk acceptance.

1. Allow **Stored (0) and Deflate (8)** only in server-side member parsing, through
   a shared guard before a member is opened/decompressed. Reject unsupported ZIP
   extraction with an actionable message before target bytes are written. Test
   direct API routes as well as browser-facing upload behavior.
2. For automatic 3MF thumbnail/prepared-metadata inspection, fail safely without
   parsing unsupported members. Preserve original file bytes and existing
   download/handoff behavior; explain unavailable derived metadata/preview using
   the existing failure/fallback surfaces. No image-upload burden, silent file
   rewrite, automatic slicing or deletion of an existing Artifact.
3. Add isolated, bounded tests proving unsupported methods never reach the
   decompressor, including metadata, thumbnail and extraction entry points, with
   successful Stored/Deflate and ZIP64 controls. Retain size/ratio/count limits;
   this does not become a claim of general archive immunity.
4. Rebuild named images, run the complete gate and exact-image HTTPS checks, then
   resume the current preview/organization/Trash/mounted-import browser matrix.
   Retain the image advisory with an application-mitigation disposition until a
   supported interpreter fix is actually shipped and verified.

**Compatibility tradeoff:** general ZIPs using BZIP2/LZMA or other nonstandard-for-
3MF methods would need recompression before MakersVault extracts them. Stored/
Deflate ZIPs and conforming 3MF are retained; this is not a file-count or library-
size quota. The [3MF core specification, §1.1](https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md#11-package)
requires Stored or Deflate members and separately requires ZIP64 support. ZIP64
must not be rejected just because compression methods are restricted.

Alternatives needing their own decision include a verified supported interpreter
fix, release-line migration, or a resource-isolated archive service. No Python
major upgrade, standard-library monkeypatch, broad parser redesign, or waiver is
authorized by this proposal. General browser ZIP upload-worker isolation remains
the already documented separate scope.

## Runtime OS residuals remain owned, not waived

The API has 164 Debian package matches, with no fix version reported in this
snapshot. Scanner `wont-fix` is not a universal vendor refusal and certainly not
MakersVault risk acceptance. For the seven critical-rated matches, the Debian
tracker currently records these more specific conditions:

| Advisory / matched package(s) | Primary vendor review |
|---|---|
| [CVE-2026-5450](https://security-tracker.debian.org/tracker/CVE-2026-5450), libc6/libc-bin | Trixie remains vulnerable; Debian marks a minor issue/no DSA. A particular allocating `scanf` conversion is involved; application/native reachability is not proven absent |
| [CVE-2026-8376](https://security-tracker.debian.org/tracker/CVE-2026-8376), perl-base | Trixie no DSA/minor issue, possible point-release fix; advisory describes attacker-controlled regex compilation on 32-bit builds. This scan is amd64, not certification of every published architecture |
| [CVE-2026-13221](https://security-tracker.debian.org/tracker/CVE-2026-13221), perl-base | Trixie no DSA/minor issue; large regex-trie matching error |
| [CVE-2026-42496](https://security-tracker.debian.org/tracker/CVE-2026-42496), perl-base | Trixie postponed while upstream extraction regressions are resolved; Archive::Tar symlink target handling |
| [CVE-2026-12087](https://security-tracker.debian.org/tracker/CVE-2026-12087), perl-base | Trixie no DSA/minor issue; Socket packing over-read under particular caller inputs |
| [CVE-2026-57433](https://security-tracker.debian.org/tracker/CVE-2026-57433), perl-base | Trixie no DSA/minor issue; crafted Storable deserialization |

These remain package-level findings: a source-package match does not demonstrate
that a particular Perl module or execution path is installed/reachable. Nor do
these representative checks disposition every high/medium/low/unknown match.
Do not strip essential Debian packages or mix unstable distro packages merely
to reduce the count. The maintainer must review/own remaining per-advisory
dispositions before candidate qualification, or approve a separately tested
runtime restructuring if that is necessary.

The web image's three medium matches are **one** BusyBox advisory,
[CVE-2025-60876](https://security.alpinelinux.org/vuln/CVE-2025-60876), attributed
to `busybox`, `busybox-binsh` and `ssl_client` 1.37.0-r31. Alpine reports possible
vulnerability and no fixed version here. The issue concerns `wget` request-line
handling for attacker-controlled URLs, not Nginx HTTP request parsing. This does
not establish an exploit path through MakersVault's static proxy; retain the
finding and review any future shell/download use. No suppression was added.

## Exit conditions

Owner approval of the archive slice above permits that bounded implementation,
not acceptance of all residual risks. Gate 13C remains open for browser/workflow,
remaining vendor/application triage, physical-device/native-platform evidence and
release scope/revision decisions. The unchanged Gate 5 candidate has neither been
replaced nor re-scanned by these current-development results. Keep all work local.
