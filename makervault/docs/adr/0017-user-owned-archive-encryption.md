# ADR 0017: User-owned portable-archive encryption boundary

**Status:** Proposed

**Proposed:** 2026-08-31

## Context

`.mvault` excludes deployment secrets but still contains private workshop designs,
notes, provenance, Machine descriptions, Trash, and external source paths. Inventing
an encrypted container or storing the only recovery key inside MakersVault would
create cryptographic and disaster-recovery risk. Provider-side encryption and
portable-file encryption are also different boundaries.

The stable `age` v1 specification defines a recipient-based streaming authenticated
file-encryption envelope and supports chunked encryption/decryption:
https://age-encryption.org/v1

## Proposed decision

Core `.mvault` v1 is unencrypted, written atomically with restrictive permissions,
and fully verifiable without MakersVault. Encryption is a user-owned outer envelope:

```text
vault.mvault -> standard age v1 encryption -> vault.mvault.age
```

Gate 10 documents interoperable `age` recipient workflows but does not design
cryptography, store identities/passphrases, escrow a key, or make a cloud account
mandatory. Initial MakersVault import consumes a successfully decrypted `.mvault`;
wrong-key, truncated, or unauthenticated envelope failure occurs before archive
staging or publication.

Built-in orchestration may be reconsidered only if it invokes a pinned, reviewed
implementation, streams without plaintext temporary leakage, keeps key custody with
the user, supports multiple recipients/recovery identities, and has independent
interoperability and lost-key UX evidence. At-rest disk encryption and future S3
server-side/client-side encryption remain separate operator/provider concerns.

## Alternatives considered

- **Custom password encryption:** creates KDF, cipher, nonce, versioning, and recovery
  design obligations already solved by reviewed standards.
- **Store an application-managed recovery key:** the backup may become undecryptable
  precisely when the installation is lost.
- **Put encryption inside `.mvault` v1:** prevents independent plaintext verification
  and couples core format compatibility to key-management choices.
- **Ignore encryption:** leaves users without a documented way to protect portable
  archives copied off-host.

## Consequences

Users must deliberately manage and test recovery identities. Losing all identities
is unrecoverable and MakersVault cannot bypass that outcome. The core format remains
simple and independently verifiable, while a standard streaming envelope provides a
clear optional confidentiality layer.
