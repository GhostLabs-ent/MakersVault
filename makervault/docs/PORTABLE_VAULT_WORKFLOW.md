# Portable vault operator workflow

This is the Gate 10D offline workflow for `.mvault` v1. It is intentionally
separate from the raw format-1 server backup. Use the raw backup for disaster
recovery, replacement, and release rollback; use `.mvault` to independently verify
and restore logical vault content into a clean compatible instance.

## Safety boundary

- Stop API and web, or place them behind a proven maintenance boundary, before
  export or import. The CLI verifies SQLite exclusivity but does not stop services.
- V1 import accepts only an absent target or an empty schema-12 database plus empty
  storage. It never merges or replaces a populated vault.
- `.mvault` excludes deployment secrets but contains private designs, notes,
  provenance, Machine descriptions, Trash, and external source paths.
- Keep the working directory mode `700`, keep the process `umask` at `077`, and keep
  archives on operator-controlled encrypted storage.
- Stdout is one canonical JSON result. With `--progress`, stderr contains lines
  prefixed `mvault-progress ` followed by canonical JSON phase events. Redirect the
  two streams separately when automating.

The source checkout needs the API's locked Python dependencies. Development data
normally uses `makervault/data/db/app.db` and `makervault/data/storage`; production
containers use `/app/data/app.db` and `/app/storage`. A production operator may run
the same Python modules in a one-off copy of the matching API image with those
volumes mounted, but must keep the regular API/web services stopped and bind a
private output directory explicitly. Do not copy only SQLite or only storage out of
a live installation.

## Export and verify

From the repository root, substitute stopped-instance paths and a new output name:

```bash
umask 077
install -d -m 700 /secure/makersvault-portable

./makervault/scripts/export-mvault.sh \
  --database /path/to/app.db \
  --storage /path/to/storage \
  --output /secure/makersvault-portable/library.mvault \
  --makersvault-version 5.1.0 \
  --confirm-stopped \
  --progress \
  > /secure/makersvault-portable/export-result.json \
  2> /secure/makersvault-portable/export-progress.jsonl

./makervault/scripts/verify-mvault.sh \
  /secure/makersvault-portable/library.mvault \
  --progress \
  > /secure/makersvault-portable/verify-result.json \
  2> /secure/makersvault-portable/verify-progress.jsonl
```

Export refuses an existing or racing output, independently verifies its temporary
archive, and publishes the final file with mode `600`. A success report includes:

- `content.authoritative_files` and `content.authoritative_bytes`;
- optional derived-file totals;
- `external.records` plus counts by `available`, `unavailable`, `changed`, `pending`,
  and `failed`; and
- catalog counts, total members/expanded bytes, format version, and `valid:true`.

An external count means the logical record is portable but its no-copy bytes are
not in the archive. Preserve the original mounted library separately. A valid
archive with external records is complete according to v1, but those records need
the same paths remounted after restore.

## Import into a clean instance

Verify first even though import independently verifies a private copy again. Keep
the target services stopped for the entire operation:

```bash
umask 077

./makervault/scripts/import-mvault.sh \
  --archive /secure/makersvault-portable/library.mvault \
  --database /path/to/empty/app.db \
  --storage /path/to/empty/storage \
  --confirm-stopped-empty \
  --progress \
  > /secure/makersvault-portable/import-result.json \
  2> /secure/makersvault-portable/import-progress.jsonl
```

The success result repeats `source_verification` and reports
`external_references.records`, `restored_unavailable`, and `requires_remount`.
External records retain their source paths but are deliberately unavailable until
the operator restores the mount. Confirm the final JSON result, remount external
libraries if applicable, preserve the source archive, and only then start the new
instance.

## Cancellation, failure, and retry

Ctrl-C returns exit code `130`; validation/configuration failures return `2`; a
complete operation returns `0`. Export removes private partial work before final
publication. Verification changes no archive or vault state. Import removes
pre-publication staging and rolls back a caught cancellation after publication
begins. An uncatchable process or host failure can leave a mode-600 import journal;
the next invocation with the same database/storage targets validates that journal
and rolls the empty target back before starting new work.

After any export cancellation, check whether the requested output exists and run
the independent verifier before using it. After any import cancellation or error,
keep services stopped, inspect stderr and the target, and retry only with the same
intended empty paths. Never bypass non-empty-target rejection.

## Optional standard `age` envelope

MakersVault does not bundle or invoke `age`, define an encrypted `.mvault` variant,
store identities/passphrases, or escrow recovery keys. Encryption is an outer
[standard age v1 envelope](https://age-encryption.org/v1):

```text
library.mvault -> age recipient encryption -> library.mvault.age
```

Install `age` from a source appropriate for the operator platform and review the
[official age CLI manual](https://filippo.io/age/age.1). Generate and protect an
identity outside the MakersVault host, then keep at least one tested recovery copy
off-host:

```bash
umask 077
install -d -m 700 /secure/age-identity
age-keygen -o /secure/age-identity/makersvault-identity.txt
age-keygen -y /secure/age-identity/makersvault-identity.txt \
  > /secure/age-identity/makersvault-recipients.txt
chmod 600 /secure/age-identity/makersvault-identity.txt \
  /secure/age-identity/makersvault-recipients.txt
```

Recipient files contain public recipients and may list more than one recovery
recipient. Every listed recipient can decrypt independently. Keep private identity
files separate from the archive. With Bash noclobber enabled, encryption will not
silently replace an existing envelope:

```bash
umask 077
set -o noclobber
age -R /secure/age-identity/makersvault-recipients.txt \
  /secure/makersvault-portable/library.mvault \
  > /secure/makersvault-portable/library.mvault.age
set +o noclobber
```

Test decryption before discarding any plaintext archive or considering the backup
usable. Decrypt into a private directory and remove partial output on any `age`
failure; then independently verify the plaintext:

```bash
umask 077
test ! -e /secure/makersvault-recovery-test || exit 1
install -d -m 700 /secure/makersvault-recovery-test
set -o noclobber
if ! age --decrypt \
  -i /secure/age-identity/makersvault-identity.txt \
  /secure/makersvault-portable/library.mvault.age \
  > /secure/makersvault-recovery-test/library.mvault.partial
then
  rm -f /secure/makersvault-recovery-test/library.mvault.partial
  set +o noclobber
  exit 1
fi
set +o noclobber
mv /secure/makersvault-recovery-test/library.mvault.partial \
  /secure/makersvault-recovery-test/library.mvault
./makervault/scripts/verify-mvault.sh \
  /secure/makersvault-recovery-test/library.mvault --progress
```

Only pass the successfully decrypted and verified `.mvault` to the importer. A
wrong identity, truncated envelope, or authentication failure must stop in `age`
before MakersVault staging begins. Plaintext deletion may not securely erase data
from flash, snapshots, or copy-on-write filesystems; use encrypted storage and an
operator-approved retention procedure. Losing every usable identity/passphrase is
irrecoverable, and MakersVault cannot bypass that outcome.

## Deliberate deferrals

There is no authenticated browser orchestration in Gate 10D. A multi-hour operation
must not depend on one browser request. UI support requires durable server-side job
state, progress, cancellation/recovery, authorization, and restart evidence at a
later owner checkpoint. S3, provider credentials, application-managed encryption,
merge/live import, deployment, and publication remain outside this workflow.
