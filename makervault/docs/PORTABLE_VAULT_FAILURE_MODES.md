# Portable vault failure and rollback matrix

This matrix is the Gate 10E operator truth for `.mvault` v1. The raw format-1
server backup remains the only in-place disaster-recovery and release-rollback
mechanism. Portable import is a clean-instance reconstruction, never a substitute
for a pre-change matched SQLite/storage snapshot.

| Condition | Detection/result | Output or target state | Required operator action |
|---|---|---|---|
| Corrupt, truncated, non-gzip, unsafe-path, duplicate, checksum-mismatched, or graph-invalid `.mvault` | Independent verifier/import exits `2` | No import publication; export never publishes an archive rejected by its verifier | Preserve the source and diagnostics; obtain or create a valid archive |
| Unknown format major, required/optional feature, field, member, or catalog | Fails closed with exit `2` | No target mutation | Upgrade to a reader that explicitly supports the format; never edit version markers |
| Configured member, record, JSON/PAX, or expanded-byte limit is too low | Verification exits `2`; the diagnostic identifies the limit | Archive remains untrusted; no import publication | Re-run on a controlled host with a deliberately reviewed higher limit if capacity permits |
| Export destination already exists or appears during export | Export exits `2` | Existing file is untouched | Choose a new output name; do not use overwrite scripts around the CLI |
| Filesystem capacity is exhausted during export | Export exits `2` | Requested output is absent; private work is removed on caught failure | Free space and retry to a new output; account for temporary archive/checksum/catalog work |
| Filesystem capacity is exhausted during import staging | Import exits `2` | Absent/empty target remains unpublished; private staging is removed | Free space and retry with the same intended empty target |
| Capacity/failure occurs after import publication begins | Journaled rollback runs for caught errors | Original absent or empty target pair is restored | Keep services stopped, inspect diagnostics/target, then retry only after confirming emptiness |
| Missing external no-copy source | Valid archive/report counts it by state; import succeeds | Logical Revision is restored `unavailable` with `external_remount_required`; managed content remains usable | Restore the external library at the recorded container-visible paths, then rescan/recheck |
| Changed/pending/failed external source state | Preserved in export summary; import still makes every external reference unavailable | No external bytes are invented or silently converted to managed content | Resolve/remount the source explicitly; a future include-snapshot mode is not present in v1 |
| Non-empty, busy, wrong-schema, overlapping, or symbolic-link import target | Import exits `2` before staging/publication | Target is untouched | Stop services and provide absent or compatible empty schema-12 paths; merge/replace is unsupported |
| Ctrl-C | CLI exits `130` | Export unpublished work and import staging are cleaned; caught publish-phase import is rolled back | Follow the workflow's inspection rule before retrying |
| SIGKILL, power loss, or host crash during export | No catch/final message is possible | A private `.mvault-export-*` directory may remain; requested output is absent unless valid publication already completed | Keep services stopped, independently verify any final output, and remove confirmed stale private work |
| SIGKILL, power loss, or host crash during import publication | Validated mode-600 journal remains | Storage may be temporarily published before SQLite by design | Re-run import with the same targets; journal validation and rollback occur before new work |
| Wrong `age` identity/passphrase, truncated envelope, or envelope authentication failure | External `age` command returns nonzero | Workflow removes its protected `.partial`; MakersVault import has not started | Recover a valid identity/envelope; never pass partial plaintext to the verifier/importer |
| Every `age` recovery identity/passphrase is lost | No decryption is possible | Encrypted archive is unrecoverable | Restore from another tested backup; MakersVault has no escrow or bypass |
| Decrypted plaintext cleanup | Ordinary removal may not securely erase flash/COW/snapshot copies | Plaintext may persist below the filesystem view | Use encrypted storage and an operator-approved retention/destruction procedure |
| Imported clean instance later proves unsuitable | Application-level rollback is not schema contraction or reverse import | Original installation is unchanged only if the operator imported into separate empty targets | Stop the new instance and return to the separately preserved raw format-1 backup/old deployment |

There is no exact free-space preflight in v1. Export compression ratio and temporary
spools are data-dependent. Import requires room for the private compressed archive
copy, expanded authoritative/derived bytes, staged SQLite/inventory files, and the
published pair. Capacity errors are fail-safe, not a sizing guarantee.

See [`PORTABLE_VAULT_WORKFLOW.md`](PORTABLE_VAULT_WORKFLOW.md) for commands and
[`BACKUP_AND_RECOVERY.md`](BACKUP_AND_RECOVERY.md) for raw rollback.
