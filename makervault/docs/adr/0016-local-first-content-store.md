# ADR 0016: Local-first content-store abstraction

**Status:** Proposed

**Proposed:** 2026-08-31

## Context

Current services use local `Path` behavior directly: directory creation, open,
atomic same-filesystem rename, free-space checks, quarantine/rollback, unlink,
temporary export files, and local paths for preview/application workflows. S3 and
compatible providers expose object operations, multipart lifecycle, provider
checksums, listing pagination, credentials, and deletion/versioning semantics—not a
POSIX filesystem.

AWS documents that multipart uploads require an explicit complete or abort lifecycle
and can validate full-object checksums at completion:
https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html
Compatible providers still require conformance evidence rather than assumed parity.

## Proposed decision

Introduce a capability-explicit `ContentStore` consumed by authoritative content,
export, import, integrity, and lifecycle services. Separate concerns include:

- streaming verified read and staged write;
- immutable publish/create-if-absent and provider key allocation;
- stat/existence and bounded enumeration for recovery;
- materialization into a controlled local workspace for preview and application
  handoff;
- capacity/quota admission without assuming `disk_usage`;
- derived/cache storage that may be regenerated; and
- reversible prepare-delete/commit-delete/rollback semantics compatible with the
  Gate 6 ownership journal.

Gate 10 implements and proves only the filesystem adapter. Existing paths and bytes
remain in place; the refactor cannot relocate or rehash content as a side effect.
Every migrated service must pass the shared store conformance suite and its existing
behavioral tests before the next seam moves.

No S3-compatible driver, bucket, endpoint, or credential enters Gate 10. A future
driver requires a separate checkpoint and tests for multipart checksum and abort,
conditional/idempotent publish, read-after-write, pagination, provider versioning or
recoverable deletion, local cache/materialization, quota behavior, TLS/address
validation, credential isolation, outage retry, and multiple compatible providers.

## Alternatives considered

- **Mount S3 through FUSE:** preserves `Path` syntax but hides consistency,
  rename/delete, cache, and failure semantics from the application.
- **Build an S3 driver immediately:** lets provider behavior define the interface
  before local invariants are isolated and tested.
- **Abstract only export/import:** leaves primary mutation, Trash, preview, and
  integrity code provider-coupled.
- **Force lowest-common-denominator operations:** would weaken safe local atomic and
  reversible behavior.

## Consequences

The refactor is substantial and must proceed in bounded slices. Capability checks
remain visible instead of pretending every provider is a filesystem. S3 remains a
future implementation candidate evaluated against the portable model, not a Gate 10
deliverable or hosted-service shortcut.
