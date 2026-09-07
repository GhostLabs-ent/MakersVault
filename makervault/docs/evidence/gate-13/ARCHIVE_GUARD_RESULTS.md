# Gate 13C — approved archive compression guard

**Authority:** owner approved the proposal in `78f6aa3` on 2026-09-06
(America/New_York). This is not approval of residual risks or release publication.

**Status:** IMPLEMENTED; complete-gate/image/browser verification in progress.

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

## Evidence so far

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

The full repository gate, exact rebuilt-image identities/HTTPS smoke, and current
browser workflows are not inferred from these focused tests. CVE-2026-15310 remains
in the interpreter inventory pending an upstream runtime fix; this change is an
application-path mitigation, not a clean-image claim. Other advisory dispositions,
physical/native-platform evidence and release decisions remain open. All work local.
