# Gate 10A — normative format and independent verifier results

**Date:** 2026-08-31

**Status:** Accepted

**Accepted:** 2026-08-31

**Scope:** Format contract and verifier only

## Outcome

Gate 10A freezes portable `.mvault` major version 1 and provides an independent,
standard-library-only verifier. It does not export a live vault, import records,
change storage access, create an object-store adapter, encrypt archives, or mutate
user data.

The normative contract is
[`MVAULT_FORMAT_V1.md`](../../MVAULT_FORMAT_V1.md). The executable verifier is
`api/mvault_verify.py`; `scripts/verify-mvault.sh` is its repository-local wrapper.
The verifier imports no MakersVault application module and does not require
FastAPI, SQLModel, the application database, a running container, or a storage
mount.

## Truths frozen by v1

- gzip-compressed POSIX PAX tar with header first, checksum inventory last, only
  regular members, normalized stable-ID paths, and a deterministic member order;
- canonical JSON/JSONL catalogs for Folder, Machine, Artifact, Revision, File,
  Project, membership, relationship, Artifact–Machine, and portable settings data;
- complete authoritative managed Revision/File bytes, optional derived thumbnails,
  and honest external no-copy records including unresolved states;
- prepared print payloads remain internal File roles while exact machine targets
  and prepared metadata remain visible on their Artifact/Revision records;
- full streamed SHA-256 verification of every member before trust; and
- clean separation from secrets, authentication/session state, bridge state, host
  mount activation, operational jobs, purge journals/quarantine, and temporary data.

## Bounded verification design

Payloads are read sequentially in 1 MiB hashing chunks. JSONL is read in bounded
lines. A disposable SQLite index holds member inventory, portable record keys, File
ownership, and graph data, so the verifier does not accumulate the library graph or
payloads in process memory. Defaults cap expanded bytes, members, and records; each
limit is an explicit CLI override rather than an end-user library-size limit.

The verifier does not extract archive content. It rejects unsafe paths, links and
special members, duplicates, ordering violations, unknown features/versions/fields,
noncanonical or hostile JSON, invalid record types, unresolved references,
cross-Artifact ownership errors, unclaimed payloads, size/digest disagreement,
manifest disagreement, and incomplete or altered checksum inventories.

## Deterministic and adversarial evidence

`api/tests/test_mvault_verify.py` builds the same representative archive twice and
requires identical bytes. The frozen golden archive SHA-256 is:

```text
1c2edb89454fd141237c36c649cd78362523dff0c6c52b851ab0eec327318d04
```

The fixture covers managed and missing external revisions, a derived thumbnail, a
prepared G-code role and metadata, exact Machine targeting, Folder/tags/collection,
a Project membership, and both portable settings. Adversarial cases prove failure
for unknown required features, traversal, symbolic links, duplicate members,
checksum tampering, dangling references, orphaned payloads, noncanonical JSON,
truncation, oversized metadata, and configured member/record/expanded-byte limits;
a bounded long-ID PAX fixture proves the permitted extension path as well.

## Verification evidence

Focused Gate 10A verification:

```text
docker build --target test -t makersvault-api-gate10a-test makervault/api
docker run --rm makersvault-api-gate10a-test python -m pytest -q tests/test_mvault_verify.py
14 passed
```

Full repository verification:

```text
make verify
API: 190 passed
Web: production build/verification passed
Slicer bridge: tests and build passed
Compose/security: all canonical manifests and production-secret rejection passed
Container smoke: direct/same-origin API, headers, upload policy, non-root UIDs, schema 12 passed
Release contract: v5.1.0 verified
```

## Gate boundary and next decision

Gate 10A was accepted by the owner on 2026-08-31, freezing this v1 contract as the
input to 10B. The acceptance does not authorize 10B automatically. The next proposed subgate is
the local `ContentStore` seam and stopped/maintenance-mode streaming exporter; raw
format-1 server backup remains unchanged throughout.
