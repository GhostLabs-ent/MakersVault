# Security Policy

## Supported versions

| Version | Security updates |
|---|---|
| v5.1.x | Supported after v5.1.0 is published |
| Historical beta / `v5` | Upgrade to the current supported release |

The `main` branch and release-candidate commits are development state, not a
published security-support promise.

## Report a vulnerability privately

Do not open a public issue for an undisclosed vulnerability, exposed credential,
authentication bypass, unsafe file/path behavior, SSRF, code execution, or a report
that includes private deployment data.

Use GitHub's **Report a vulnerability** form in this repository's Security tab:

https://github.com/VincentCinque/MakersVault/security/advisories/new

Include the affected version or source revision, deployment topology, reproduction
steps, impact, and any safe proof-of-concept details. Remove passwords, tokens,
cookies, real model files, `.env` contents, and personal host paths. If private
reporting is unavailable, open a public issue that asks the maintainer to establish
a private channel but does not disclose the vulnerability.

The project will acknowledge a usable report when maintainers are available,
validate scope, coordinate a fix and disclosure, and credit the reporter if desired.
No fixed response-time or bounty program is currently promised.

## Supported deployment boundary

- Use the versioned API, web, and bridge artifacts from the same release.
- Configure unique production credentials and an HTTPS reverse proxy or private VPN
  for remote access. Direct public exposure of application ports is unsupported.
- Verify release checksums/attestations and follow the documented matched backup and
  upgrade procedure before changing versions.
- Mounted libraries are read-only inputs; external no-copy bytes remain outside the
  server backup.

See [Secure Deployment](makervault/docs/SECURE_DEPLOYMENT.md),
[Backup and Recovery](makervault/docs/BACKUP_AND_RECOVERY.md), and
[Known Limitations](makervault/docs/KNOWN_LIMITATIONS.md).
