# Gate 1 Slice 1C Design

**Slice:** Server resource budgets, ZIP safety, and mounted-source containment

**Status:** Owner-approved and implemented in the local candidate

**Prepared:** 2026-08-14

**Findings:** MV-SEC-006, MV-SEC-011, MV-SEC-013

## Current executable truth

| Path | Current bound | Gap |
|---|---|---|
| Direct primary upload | None | Can fill the storage volume before the request ends. |
| Supporting/prepared upload | 512 MiB per file | Uses the remote-import setting rather than a shared file policy. |
| Remote import | 512 MiB streamed | Bounded, but policy naming is import-specific. |
| Mounted import | 512 MiB from pre-copy `stat` | Copy mode follows symlinks and does not revalidate the opened file. |
| Imported ZIP | 512 MiB compressed file and 512 MiB per extracted entry | Entry count, selected count, total expansion, and compression ratio are unbounded. |
| 3MF thumbnail member | 16 MiB per candidate image | Archive member count is unbounded. |
| Prepared 3MF metadata | 2 MiB per selected member | Total members and aggregate metadata bytes are unbounded. |
| Generated thumbnail upload | 8 MiB | Decoded pixel count and parser allowlist are not explicit. |
| Same-origin Nginx upload | Nginx default | Conflicts with the API's intended large-model behavior. |
| ZIP download names | Files are sanitized; folder labels are not consistently normalized | Archive paths can contain unsafe user-controlled components. |

The API does not parse STL or STEP geometry. Server-side model processing is
limited to bounded 3MF ZIP thumbnail and prepared-print metadata inspection;
browser model/parser budgets remain Gate 2 work.

## Proposed default policy

All values remain operator-configurable. Existing `IMPORT_MAX_MB` continues as a
compatibility alias when the new shared file limit is not set.

| Policy | Proposed default | Reasoning |
|---|---:|---|
| Maximum stored/imported file | 512 MiB | Matches the existing remote, related-file, ZIP-entry, and mounted-file behavior. |
| Storage free-space reserve | 512 MiB | Stops an in-progress write before consuming the final operational space. |
| Maximum compressed ZIP | 512 MiB | Same as the single-file policy. |
| Maximum ZIP members scanned | 10,000 | Matches the security-analysis starting policy and bounds central-directory work. |
| Maximum selected ZIP entries | 1,000 | Keeps one request and its database work finite while supporting large model bundles. |
| Maximum total selected expansion | 2 GiB | Matches the security-analysis starting policy and permits four maximum-size files only when explicitly selected. |
| Maximum member compression ratio | 200:1 | Rejects extreme bombs while leaving substantial room for text-heavy CAD/archive content. |
| Maximum cumulative 3MF metadata read | 16 MiB | Retains the existing 2 MiB per-member sampling but bounds the aggregate. |
| Maximum decoded image size | 64 megapixels | Supports large reference images while bounding Pillow allocation. |
| Accepted thumbnail decoders | PNG, JPEG, WebP, BMP | Matches the application's documented thumbnail formats and avoids unrelated Pillow parsers. |
| Generated thumbnail upload | 8 MiB | Preserve the existing behavior. |

The same-origin web gateway will accept the default 512 MiB file plus 1 MiB of
multipart framing. An
external reverse proxy must set an equal or lower request limit; operators who
raise MakersVault's file limit must deliberately raise their proxy limit too.

## Enforcement design

1. Introduce one configuration module contract for file, archive, image, and
   storage-reserve budgets. Invalid values fail startup; limits must be positive
   except for an explicitly disabled zero-byte storage reserve.
2. Stream direct, related, and remote uploads through shared byte-count and
   free-space checks. Never rely only on `Content-Length`.
3. Remove partial files and database records on every rejected or failed ingest.
4. Preflight ZIP member count, normalized names, declared sizes, selected total,
   and compression ratios; repeat byte accounting while streaming extraction.
5. Bound 3MF member enumeration and aggregate metadata/thumbnail reads.
6. Restrict Pillow to the four supported decoders and turn decompression-bomb
   warnings into a failed derived preview, without rejecting storage of an
   otherwise allowed primary file.
7. Open mounted copy sources without following the final symlink, verify the
   opened descriptor is a regular file beneath the configured root, then copy
   from that descriptor. Reject symlinks in both copy and no-copy modes.
8. Normalize every ZIP download component; preserve readable names without
   allowing absolute paths, traversal, or platform separators.
9. Return HTTP 413 for byte/archive limits and HTTP 507 for exhausted storage
   reserve. ZIP multi-entry imports retain their existing partial-result contract
   but identify rejected entries.

## Compatibility and rollback

- Files already stored above the limit remain visible and downloadable.
- No database migration or stored-file rewrite is required.
- Operators with legitimate files above 512 MiB may raise the shared limit in
  `.env` and align the external proxy.
- Existing `IMPORT_MAX_MB` configuration remains honored during v5.1.
- Rollback restores the previous configuration and code; no data restoration is
  required because rejected writes are cleaned up atomically.

## Owner decision

The owner approved the proposed defaults on 2026-08-14 after confirming that
the policy does not impose a cumulative quota on ordinary multi-file imports.
Only ZIP extraction has per-request entry-count and aggregate-expansion limits.
