# ContentStore provider evaluation

**Decision:** No S3-compatible provider ships in Gate 10.

Gate 10B proved the current local filesystem behind a capability-explicit
`ContentStore`. Gate 10E evaluates whether that seam is sufficient to connect a
remote object provider safely. It is not yet sufficient, and no real endpoint,
bucket, credentials, SDK, or provider-specific configuration was introduced.

## Capability matrix

| Required behavior | Local adapter evidence | Remote object-store requirement | Gate 10 result |
|---|---|---|---|
| Bounded streaming read | Regular files stream through bounded readers | Response streaming, timeouts, retries, range/error semantics, and checksum verification | Local proven; remote unproven |
| Staged write | Private same-filesystem staging path | Multipart lifecycle, durable upload ID, retry/abort, orphan cleanup, and server/client checksum agreement | Contract does not model this remotely |
| Create-if-absent publish | Hard link fails atomically if destination exists | Conditional object creation proven on every supported provider and through gateways | Compatibility matrix absent |
| Atomic publish/visibility | Same-filesystem rename/link plus directory fsync | No rename primitive; immutable-key commit and read-after-write/list behavior need a different journal | Contract semantics need refinement |
| Controlled materialization | Direct local path in a context manager | Private bounded cache, eviction, integrity recheck, cancellation, and no cross-user leakage | No cache design or evidence |
| Capacity admission | `disk_usage` reports one filesystem | Quotas, billing limits, multipart overhead, local cache space, and provider error normalization | No portable capacity meaning |
| Bounded enumeration | Iterative directory walk in batches | Continuation tokens, stable pagination under mutation, prefix normalization, and bounded retry | No provider conformance suite |
| Reversible deletion | Same-filesystem quarantine with commit/rollback | Versioning or copy/quarantine ownership, retention/lifecycle conflicts, restoration, and permanent-delete proof | No remote deletion design |
| Durable pairing with SQLite | Import publishes local storage first and SQLite last behind a local fsynced journal | Remote writes and local SQLite cross two failure domains; recovery must reconcile timeout/unknown outcomes | No cross-domain recovery proof |
| Derived versus authoritative lifecycle | Keys and ownership are locally auditable | Separate lifecycle rules must never expire authoritative content or needed rollback versions | Policy not designed |
| Credential/TLS boundary | No provider credentials exist | Secret injection/rotation, endpoint allowlist, TLS verification, proxy behavior, least privilege, and log redaction | Outside current configuration contract |
| Provider interoperability | One source-owned local implementation | AWS plus explicitly named compatible providers, failure injection, clock/skew, throttling, and consistency tests | No provider tested |

## Blocking architectural facts

- `ContentStore.publish` still accepts a local staged `Path`; production workflows
  also use `LocalContentStore.staging_path` and local materialization explicitly.
  This honestly represents current behavior but is not a provider-neutral upload
  transaction.
- Local create-if-absent, rename, fsync, capacity, quarantine, and direct-open
  guarantees cannot be inferred from an S3-shaped API.
- A remote store would split SQLite metadata and authoritative bytes across failure
  domains. Timeout does not reliably mean that an object was not committed.
- Versioning/lifecycle configuration belongs partly to the operator/provider and can
  invalidate MakersVault deletion or recovery assumptions if treated as an
  implementation detail.
- No credentials may enter a conformance test until endpoint scope, cleanup,
  cost/rate limits, secret handling, and owner authorization are explicit.

## Required future entry gate

A future provider gate must first revise the contract around provider-neutral
upload sessions, conditional immutable commit, checksum identity, materialization,
pagination, quota/error normalization, reversible deletion/versioning, and durable
SQLite/provider reconciliation. It then needs:

1. a deterministic fake-provider conformance suite with timeout/unknown-result,
   retry, partial multipart, pagination mutation, conflict, corruption, and delete
   recovery injection;
2. explicitly approved integration tests against every claimed compatible provider;
3. bounded local-cache and multi-gigabyte multipart evidence;
4. credential, TLS, endpoint, proxy, logging, lifecycle, quota, and cost review;
5. raw backup and `.mvault` export/import drills with provider loss; and
6. a new owner checkpoint naming supported providers and rollback guarantees.

Until those conditions are met, `LocalContentStore` is the only implementation and
S3 remains a roadmap evaluation—not a hidden, experimental, or partially supported
feature.
