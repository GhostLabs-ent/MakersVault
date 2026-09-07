# Gate 13C — approved archive compression guard

**Authority:** owner approved the proposal in `78f6aa3` on 2026-09-06
(America/New_York). This is not approval of residual risks or release publication.

**Status:** IMPLEMENTED AND VERIFIED at `ddf8cf4`; browser qualification remains
open. This is not 13C acceptance or a residual-risk waiver.

## Bounded changes

- Shared server guard permits Stored (0) and Deflate (8); ZIP64 remains independent
  of compression and supported. Byte, ratio, entry-count and capacity limits stay
  in place; no library-size or ordinary multi-file batch quota was introduced.
- Import listing rejects unsupported members with HTTP 400 and recompression
  guidance. Extraction preflights the complete selected set before creating any
  Artifact/folder or writing extracted bytes, including a mixed archive where the
  unsupported member follows a valid one. Unselected members are not decompressed.
- Automatic 3MF thumbnail reads use the shared guard. Prepared metadata preflights
  member methods; an unsupported package retains its prepared role and 3MF format
  from the existing filename/member-name contract, without claiming unread printer
  or material settings. Original bytes/download/slicer handoff remain available;
  prepared attachments stay out of the supporting-file list.
- Browser ZIP entry reading reports matching actionable compression guidance.
  The prepared summary explains missing settings without asking for an uploaded
  thumbnail. Existing preview worker failure/fallback surfaces remain in use.
- No interpreter monkeypatch, Python release-line update, archive service, new
  thumbnail-upload requirement or general browser upload-worker redesign.

## Verification

Focused API container: **44 passed** (38 new compression cases plus six existing
archive-limit tests), with networking disabled, 512 MiB memory and two CPUs.
Fixtures are tiny ordinary archives or metadata headers, not memory-exhaustion
payloads. Spies forbid opening unsupported members and constructing their
decompressors; teardown asserts no forbidden call even if an outer catch hides it.

Coverage includes unknown methods as well as BZIP2/LZMA, mixed selection/no partial
import, direct API routes, size-enforcement on/off, ordinary and forced-ZIP64
Stored/Deflate, both thumbnail helpers, prepared metadata and payload reads, and
unchanged original downloads/scoped slicer handoff for primary and attached 3MF.

An initial web test import required Node typings absent from the browser TypeScript
configuration; the test now uses Node 20's existing global File instead. No new
dependency or application compiler relaxation was introduced. Only completed
reruns will be counted below.

Complete `make verify` at clean `ddf8cf4b41cf261e6129fcdace0f789feb573cce` passed:
**351 API / 45 web tests**, web typecheck/build, Go tests/build, Compose/security
checks, fresh development smoke, Chromium virtual-passkey ceremonies, 12 Python
harness / 5 Node client tests, three browser-script syntax checks and the static
release contract. The joined production-HTTPS lifecycle also passed schema 4→17
upgrade, exact schema-4 rollback, contract-6 raw restore with pre-start revocation,
portable 17→12→17 fresh-identity startup and nonempty/corrupt-target refusals.
See [verification identities/results](archive-guard-verification.json).

The exact lifecycle images were then rescanned without rebuilding:

- API `sha256:2becf609d3033b9656b38e5eb074ce9deb98dde9f9a964716daad6a16039d2c5`
- Web `sha256:281509774b12153d02afca540256a0d1d705c9173bbac85d8fd611660ee2dc7b`

Their reused helper label is `development-gate13b`; the revision and immutable IDs,
not that historical label, bind them to this guard. Grype 0.118.0 with a valid
2026-09-06 database reports **181 API / 3 web matches**, unchanged in count.
[New scan metadata and raw-report hashes](archive-guard-audit.json) preserve this
images-only invocation; language locks were unchanged, not rescanned in this run.
Every reduced match (including severity, package/version, namespace, locations and
fix fields) equals the corresponding [prior reduced record](remediation-image-matches.json)
after sorting; this is an explicit comparison, not inference from equal totals.

Browser harness `4fbdcdf` adds unique trusted-HTTPS fixtures, hostname-negative
checks, current Trash/restore assertions and null unavailable metrics. Its focused
gate passed **16 Python harness / 5 Node client tests**, four script syntax checks
and the static release contract. It does not change the application images above.
The first actual Chromium organization run completed functional assertions but
failed the unchanged first-card budget (1620.3 ms versus <1000 ms); it is not a pass.
Further [workflow results](BROWSER_WORKFLOW_RESULTS.md) are recorded separately,
never inferred from API tests. They preserve failed Firefox preflights and a later
Chromium restore/search visibility timeout as well as the completed preview/mount
probes; the browser matrix remains unqualified.

CVE-2026-15310 remains
in the interpreter inventory pending an upstream runtime fix; this change is an
application-path mitigation, not a clean-image claim. Other advisory dispositions,
physical/native-platform evidence and release decisions remain open. All work local.
