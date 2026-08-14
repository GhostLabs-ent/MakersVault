# Gate 1 Slice 1C Evidence

**Slice:** Server resource budgets, ZIP safety, and mounted-source containment

**Status:** Locally verified candidate

**Evidence date:** 2026-08-14

**Findings:** MV-SEC-006, MV-SEC-011, MV-SEC-013

## Owner-approved policy

| Boundary | Default |
|---|---:|
| Stored/imported file | 512 MiB per file |
| Retained free space | 512 MiB |
| ZIP members scanned | 10,000 |
| ZIP entries selected per extraction | 1,000 |
| Selected ZIP expansion | 2 GiB |
| ZIP member compression ratio | 200:1 |
| Aggregate 3MF metadata/thumbnail read | 16 MiB |
| Decoded image | 64 megapixels |
| Browser-generated thumbnail | 8 MiB |

The owner approved these values after confirming the batch semantics. Direct,
folder, and mounted imports have no cumulative count or byte quota: each file is
evaluated independently. Only ZIP extraction has a selected-entry count and
aggregate expanded-byte budget.

`FILE_MAX_MB` is the new shared setting. Existing deployments that set only
`IMPORT_MAX_MB` retain that value through a compatibility alias. The bundled
Nginx container renders its request-body ceiling from the same setting.

## Implemented controls

- Direct, supporting/prepared, remote, mounted-copy, and ZIP-extracted writes use
  one chunked writer with byte accounting, a free-space reserve, and partial-file
  cleanup. Primary and related uploads also remove provisional database records
  after failure.
- Missing or invalid positive budget configuration fails startup. The storage
  reserve alone permits `0` as an explicit operator opt-out.
- ZIP listing and extraction bound central-directory enumeration, normalized
  duplicate paths, selected count, declared aggregate expansion, individual
  file size, and compression ratio. Actual streamed bytes are checked again
  while extracting.
- 3MF thumbnail and prepared-print inspection bound member enumeration,
  compression ratio, and aggregate read bytes.
- Server thumbnails use only PNG, JPEG, WebP, and BMP decoders. Pillow's
  decompression-bomb warning is treated as a failed derived preview at 64
  megapixels; the primary model remains stored.
- Mounted imports reject symlinks in every component. Copy and no-copy preview
  inspection use an `O_NOFOLLOW` descriptor, verify a regular file beneath the
  configured root, and re-check the opened object before use.
- ZIP download components are sanitized for folder, model, primary, and
  supporting-file names. ZIP imports reject traversal and normalized duplicate
  paths.
- The existing 30-second remote-request timeout remains the server network time
  budget. MakersVault does not parse STL or STEP geometry server-side; browser
  model/parser time and complexity budgets remain explicitly assigned to Gate 2.

Limit failures use HTTP 413. Exhausting the configured storage reserve uses HTTP
507 so an operator can distinguish capacity from an invalid file.

## Adversarial regression evidence

The API suite covers:

- streamed rejection and removal of a partial file;
- removal of a provisional primary-upload database record;
- exhausted-reserve HTTP 507 behavior;
- repeated ordinary file writes without aggregate batch state;
- invalid budget configuration;
- ZIP member-count, selected-count, aggregate expansion, compression-ratio,
  traversal, and normalized-duplicate cases;
- decoded-image pixel rejection; and
- regular mounted files plus symlinks targeting both inside and outside the
  configured root.

The container smoke test additionally proves that the generated Nginx config
enforces `client_max_body_size 513m`: the 512 MiB file policy plus 1 MiB for
multipart framing. Focused container checks prove that a 768 MiB operator file
limit renders a 769 MiB request cap and that a zero value fails startup.

## Verification

| Check | Result |
|---|---|
| API/migration tests | Pass; 33 tests |
| Web type check, tests, and production build | Pass |
| Compose validation and security assertions | Pass |
| Container smoke | Pass; direct and same-origin API, non-root UIDs, schema 3, 512 MiB file policy plus multipart allowance |
| Configurable/invalid Nginx limit checks | Pass |
| Complete repository harness | Pass; `make verify` |

## Compatibility and rollback

No schema or stored-file format changed. Files already above a new ceiling remain
readable. Operators may raise per-file and archive limits for their workload and
must align any external proxy. Rollback restores the prior code and environment;
rejected writes leave no data that requires migration or restoration.

## Residual risk and next slice

MV-SEC-006, MV-SEC-011, and MV-SEC-013 are resolved in the locally verified
candidate. Gate 1 remains open. The next slice owns controlled URL redirects and
connection-target validation for MV-SEC-003; scoped bridge handoff grants,
session decisions, throttling, and response/host policy still follow.
