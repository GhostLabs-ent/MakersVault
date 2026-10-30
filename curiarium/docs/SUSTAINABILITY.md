# Curiarium Sustainability Policy

## Commitment

> **Curiarium will remain free and open-source at its core.**

Users should always be able to self-host Curiarium, organize their files, use
core project features and local integrations, modify the software, build
extensions, and export their data without payment.

The goal is sustainable development, not a deliberately incomplete community
edition.

## Governing model

> **Open software, paid convenience.**

GhostLabs may charge for operating infrastructure, providing expertise, or saving
users operational work. It should not charge merely to remove artificial limits
from the self-hosted product.

## Principles

### Keep the self-hosted product complete

Do not impose artificial limits on:

- File count.
- Local storage.
- Project organization.
- Core metadata.
- Local application integrations.
- Export and backup access.

Do not remove an existing open-source feature simply to move it behind a
subscription.

### Monetize real convenience and cost

Reasonable paid services include:

- Managed Curiarium hosting.
- Automatic upgrades and monitoring.
- Managed encrypted backups.
- Cloud storage and off-site recovery.
- Hosted preview processing.
- Cross-device synchronization.
- Professional installation and migration support.
- Optional hosted capabilities that incur meaningful compute, storage, or
  bandwidth costs.

Whenever practical, keep a local or self-hostable path for users willing to
operate the required infrastructure themselves.

### Avoid pressure tactics

- No advertising inside the application.
- No repeated donation popups.
- No intentionally degraded free experience.
- No fear-based backup messaging.
- No confusing core-software access with hosted-service entitlements.

Support links should be visible but unobtrusive.

## Near-term plan

### Phase 1 — project support

- Add GitHub Sponsors or an equivalent donation destination.
- Add a low-pressure support link to the README and project website.
- Publish the commitment that Curiarium remains free and self-hostable.
- Optionally include a small About or Support section in the application after the
  release-critical work is stable.

Do not make monetization a headline interaction in the v5.1 comeback release.

### Phase 2 — portable backup foundation

- Define and document a portable backup format.
- Add backup and restore APIs or tools.
- Add checksums and integrity verification.
- Introduce storage abstraction where it improves the free product.
- Evaluate S3-compatible storage based on user demand and portability needs.

### Phase 3 — managed backup or storage

The first recurring service should solve a focused operational problem:

```text
Self-hosted Curiarium
        -> encrypted off-site backup
        -> integrity verification
        -> documented restore
```

This aligns directly with the trust expected from a vault and requires less
operational scope than hosting the entire application.

### Phase 4 — managed hosting

If demand is demonstrated, offer a hosted Curiarium instance with:

- Managed upgrades.
- HTTPS and remote access.
- Storage and backups.
- Monitoring.
- Recovery assistance.

Customers pay GhostLabs to operate Curiarium for them, not to unlock Curiarium.

## Other sustainable revenue

### Donations and sponsorship

Appropriate channels may include GitHub Sponsors, Ko-fi, Open Collective, Patreon,
or a direct GhostLabs support page.

Suggested message:

> Curiarium will always be free and open source. If it saves you time or helps
> your workshop, optional support helps fund continued development and future
> GhostLabs work.

### Professional support

Schools, maker spaces, workshops, and small businesses may pay for:

- Docker and NAS deployment.
- Reverse-proxy configuration.
- Migration and recovery.
- Backup design.
- Future SSO configuration.
- Custom integrations and plugin development.
- Priority technical support.

The software remains free; organizations pay for time and expertise.

### Supporter membership

A voluntary supporter tier may offer recognition and community benefits such as:

- A supporter badge or project acknowledgement.
- Early access to beta images.
- Roadmap voting or development updates.
- Community roles.
- Credits toward optional hosted services.

These benefits should express support, not compensate for missing core features.

## Decision tests for paid features

Before introducing a paid offering, ask:

1. Does the charge reflect real infrastructure, operational work, or expertise?
2. Can a technically capable user continue self-hosting the complete product?
3. Can users export their data without payment or lock-in?
4. Does the offering improve rather than undermine trust in the open-source project?
5. Can the service be supported reliably without distracting from core product
   quality?

If the answer to any of the first four questions is no, the offering conflicts
with this policy.

## Public statement

> **Curiarium will always be free and open source.**
>
> It began as a solution to a real workshop problem and remains available to
> anyone who finds it useful. Optional donations, professional support, and hosted
> services may help fund continued development, but payment will never be required
> to run the complete Curiarium software yourself.

## Objective

Curiarium should earn revenue because people value the software and trust
GhostLabs to provide useful services—not because their workshop data or essential
features have been trapped behind payment.
