# MakersVault portable vault format v1

**Status:** Normative Gate 10A contract

**Format name:** `makersvault-portable-vault`

**Major version:** `1`

**Media form:** gzip-compressed POSIX PAX tar
**Usual extension:** `.mvault`

This document defines the portable, secret-free whole-vault interchange format.
It does not replace the stopped-server backup described in `BACKUP_AND_RECOVERY.md`.
An archive is trusted only after the independent verifier accepts it; successful
inspection by a general tar program is not sufficient.

## 1. Conformance language

`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. A v1 writer MUST produce
the exact structure below. A v1 reader MUST reject violations, unknown required
features, unknown records or fields, duplicate JSON keys, duplicate records,
dangling references, and an incomplete checksum inventory.

All members MUST be regular files. Member names MUST be normalized relative POSIX
paths beneath `mvault/`; absolute paths, empty components, `.`, `..`, backslashes,
links, devices, directories, and duplicate names are forbidden. User-controlled
filenames MUST NOT form archive member names.

## 2. Deterministic encoding

JSON is UTF-8 with one trailing LF, sorted object keys, no insignificant
whitespace, no duplicate keys, and no non-finite numbers. JSONL applies that rule
to every record and MUST end every record with LF. Tags and feature arrays are
sorted and unique. Catalog records are sorted by the portable key specified in
section 5. Timestamps are ISO-8601 UTC values ending in `Z`. Digests are lowercase
hexadecimal SHA-256 values.

Writers SHOULD set tar `mtime`, `uid`, and `gid` to zero and owner/group names to
empty strings. Those reproducibility fields are not semantic and readers MUST NOT
use them to restore ownership or time.

## 3. Member sequence

Members have this exact high-level order:

1. `mvault/header.json` (always first)
2. zero or more authoritative payload members, sorted by full member path
3. zero or more derived payload members, in the same combined path sort
4. all ten catalog members in the order declared below
5. `mvault/manifest.json`
6. `mvault/checksums.sha256` (always last)

The combined authoritative/derived payload sequence is lexically sorted. The only
payload paths are:

- `mvault/content/revisions/{revision-id}/primary`
- `mvault/content/files/{file-id}/payload`
- `mvault/derived/thumbnails/revisions/{revision-id}`

IDs in paths contain 1–255 ASCII letters, digits, `.`, `_`, `:`, or `-`, begin
with a letter or digit, and are stable record IDs—not display names.

## 4. Header

`mvault/header.json` has exactly these fields:

```json
{"catalogs":["folders","machines","artifacts","revisions","files","projects","project-memberships","project-relationships","artifact-machines","settings"],"created_at":"2026-08-31T12:00:00Z","format":"makersvault-portable-vault","format_version":1,"optional_features":["derived-thumbnails"],"required_features":["canonical-jsonl","sha256-inventory"],"source":{"makersvault_version":"5.1.0","schema_version":12}}
```

`optional_features` MAY be empty. In v1 its only known value is
`derived-thumbnails`, which MUST be declared when a derived thumbnail member is
present. Readers fail closed on unknown required or optional feature names because
v1 defines no generic extension container.

## 5. Catalogs and records

Catalog members are `mvault/catalogs/{catalog}.jsonl`. Every field listed is
required; `null` marks nullable values. No additional fields are allowed.

Common scalar conventions:

- `id` and every `*_id` use the portable ID syntax from section 3.
- `size`, counts, and policy/revision versions are non-negative integers, except
  versions and revision numbers begin at 1.
- `tags` is a sorted, unique string array.
- `prepared_metadata`, file `metadata`, and setting `value` are arbitrary finite
  JSON values or `null`.
- `preview` is exactly `{policy_version, reason, source, status}`; status is one of
  `pending`, `ready`, `failed`, `skipped_policy`, or `retry_requested`.

| Catalog | Portable key | Exact fields |
|---|---|---|
| `folders` | `id` | `id`, `name`, `parent_id`, `tags` |
| `machines` | `id` | `id`, `name`, `category`, `manufacturer`, `model`, `location`, `notes`, `created_at`, `updated_at`, `archived_at` |
| `artifacts` | `id` | `id`, `name`, `filename`, `mime`, `size`, `tags`, `title`, `notes`, `creator`, `collection`, `folder_id`, `supporting_file_count`, `prepared_file_id`, `prepared_metadata`, `prepared_machine_id`, `preview`, `current_revision_id`, `deleted_at`, `trash_original_folder_id`, `trash_original_folder_name` |
| `revisions` | `id` | `id`, `asset_id`, `revision_number`, `created_at`, `origin_revision_id`, `filename`, `mime`, `size`, `sha256`, `content`, `change_note`, `prepared_file_id`, `prepared_metadata`, `prepared_machine_id`, `preview`, `derived_thumbnail_member` |
| `files` | `id` | `id`, `asset_id`, `revision_id`, `filename`, `mime`, `size`, `role`, `sha256`, `member`, `metadata` |
| `projects` | `id` | `id`, `name`, `notes`, `creator`, `source_url`, `license`, `tags`, `created_at`, `updated_at`, `deleted_at` |
| `project-memberships` | `project_id` + unit separator + `asset_id` | `project_id`, `asset_id`, `created_at` |
| `project-relationships` | `id` | `id`, `project_id`, `source_asset_id`, `target_asset_id`, `kind`, `created_at` |
| `artifact-machines` | `asset_id` + unit separator + `machine_id` | `asset_id`, `machine_id`, `created_at` |
| `settings` | `key` | `key`, `value` |

Machine `category` is one of `fdm_printer`, `resin_printer`, `laser`, `cnc`,
`pcb`, or `other`. Relationship `kind` is one of `derived_from`,
`documentation_for`, or `component_of`, and its endpoints differ. Portable v1
setting keys are only `storage_path_template` and `trash_retention`.

### Revision content

`content` has exactly `ownership`, `state`, `member`, and `source_path`.

- Managed content is `{ownership:"managed", state:"ready",
  member:"mvault/content/revisions/{id}/primary", source_path:null}` and requires
  a non-null `sha256`. Its member size and digest MUST match the revision.
- External no-copy content is `{ownership:"external", state:S, member:null,
  source_path:P}`, where `S` is `ready`, `unavailable`, or `changed` and `P` is the
  recorded source path. `S` may also be `pending` or `failed`, preserving an
  unresolved source scan honestly. External bytes are not included and absence does not make
  the archive corrupt.

Every file is authoritative managed content. Its `member` is exactly
`mvault/content/files/{id}/payload`; size and digest MUST match. Prepared G-code or
other machine payloads remain internal file roles and are not exposed as a new
top-level model type.

`derived_thumbnail_member` is null or exactly
`mvault/derived/thumbnails/revisions/{revision-id}`. Derived content is optional,
never substitutes for authoritative bytes, and MAY be regenerated after restore.

### References

All non-null references MUST resolve inside the archive. This includes folder
parents; Artifact folders/current Revision/prepared File/prepared Machine; Revision
Artifact/origin/prepared File/prepared Machine; File Artifact/Revision; Project
memberships and relationships; and Artifact–Machine associations. Every payload
member MUST be claimed by exactly one record. Managed content may not be omitted.

## 6. Manifest

`mvault/manifest.json` has exactly:

```json
{"catalog_records":{"artifact-machines":0,"artifacts":0,"files":0,"folders":0,"machines":0,"project-memberships":0,"project-relationships":0,"projects":0,"revisions":0,"settings":0},"content":{"authoritative_bytes":0,"authoritative_files":0,"complete_managed_content":true,"derived_bytes":0,"derived_files":0},"external":{"available":0,"changed":0,"failed":0,"pending":0,"records":0,"unavailable":0},"format":"makersvault-portable-vault","format_version":1}
```

Counts and byte totals MUST equal observed members and records.
`complete_managed_content` MUST be true. External totals count external Revision
records by state.

## 7. Checksum inventory

The final `mvault/checksums.sha256` contains one line for every prior member, in
archive order, and no line for itself:

```text
{64 lowercase hex characters}  {exact member path}\n
```

The two spaces are literal. The inventory covers the header, every payload,
every catalog, and the manifest. The verifier compares streamed member hashes and
does not trust catalog- or manifest-declared values alone.

## 8. Security and resource bounds

The source-owned verifier reads tar sequentially, hashes payloads in bounded
chunks, limits individual JSON lines and metadata, and uses a disposable SQLite
index for members, records, and graph checks. Default ceilings are 1,000,000
members, 5,000,000 records, and 16 TiB expanded bytes; operators may lower or
raise these explicit limits. PAX extension records are bounded to 1 MiB each
before the Python tar reader buffers them and count against the aggregate member
and expanded-byte ceilings. A limit failure is not evidence of archive corruption,
but the archive remains untrusted until verified under adequate limits.

The verifier never extracts files, imports records, opens the application database,
contacts a storage provider, or evaluates archived strings as host paths.

Run it from the repository root:

```bash
python3 makervault/api/mvault_verify.py path/to/library.mvault
```

Success writes one canonical JSON report and exits 0. Invalid archives write a
single `mvault: invalid:` diagnostic to stderr and exit 2.

### Reference writer

Gate 10B provides a source-owned writer for a stopped or maintenance-mode schema-12
instance. It reads SQLite in batches under an exclusive transaction, streams
managed bytes through the local `ContentStore`, writes metadata/checksum spools to
private temporary disk, independently verifies the completed temporary archive,
and atomically creates the requested output without overwriting an existing path.

```bash
./makervault/scripts/export-mvault.sh \
  --database /path/to/app.db \
  --storage /path/to/storage \
  --output /path/to/library.mvault \
  --makersvault-version 5.1.0 \
  --confirm-stopped
```

`--confirm-stopped` is mandatory. The writer also requires an exclusive SQLite
transaction and refuses a busy database, missing or changed managed content,
unsupported schema, an existing/racing output path, or an archive rejected by the
independent verifier. It creates the final archive with mode `600`. A failed or
interrupted run removes its temporary work and does not publish the requested path.

## 9. Explicit exclusions and compatibility

`.env`, authentication secrets, sessions, remote credentials, mount activation,
workstation bridge state, scan/hash/purge journals, quarantine, and temporary files
MUST NOT appear. v1 import is clean-instance-only and staged, but import behavior is
specified and implemented in Gate 10C, not by this verifier.

Writers emit the current approved major version. Readers reject unknown majors.
When a future major is introduced, MakersVault retains v1 reading and a
source-owned verification/migration path for at least two stable releases. The raw
server backup remains the exact rollback mechanism and has independent versioning.
