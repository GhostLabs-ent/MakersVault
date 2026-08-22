# Experimental Print-Failure Monitoring

**Status:** Experimental candidate for the first post-v5.1 release

**Decision date:** 2026-08-22

**Product boundary:** Opt-in failure detection and advisory notifications, not
printer control

## User outcome

While a print is active, MakersVault may sample an authorized printer or workshop
camera and notify the owner when several observations indicate a likely failure. A
Discord notification should identify the printer and associated MakersVault item,
show the confidence and elapsed time, include one incident snapshot, and link back
to the relevant view.

The first experiment is alert-only. It must not pause, cancel, start, schedule, or
otherwise control a printer.

## Why this is experimental

Local failure-detection models already exist, but reliable camera acquisition,
printer-state detection, false-alarm control, hardware performance, firmware
compatibility, and secret handling vary materially between installations. Native
OctoPrint and Moonraker camera interfaces are documented; Bambu camera access does
not currently have the same stable public contract and must be treated as an
experimental adapter until it is proven on supported hardware.

MakersVault will therefore validate the workflow through an optional provider
boundary rather than train or embed a new model in the core API. Initial provider
candidates include:

- [PrintGuard](https://github.com/oliverbravery/PrintGuard), as a local external
  detector with broad camera/printer and notification support;
- [Obico](https://github.com/TheSpaghettiDetective/obico-server), as a more mature
  but operationally heavier self-hosted system; and
- [OctoEverywhere's failure-detection API](https://docs.octoeverywhere.com/ai-failure-detection-apis/overview/)
  only as an explicitly selected cloud option, never a required dependency.

External projects retain their own licenses and security posture. MakersVault must
not copy GPL implementation code into its core merely to accelerate this experiment.
A separately deployed process and documented HTTP boundary are the preferred first
integration. Any bundled Compose profile requires a license and distribution review.

## Proposed boundary

```text
Authorized camera/printer adapter
          |
          | bounded snapshot sample while a print is active
          v
External inference provider
          |
          | score + observation time + optional incident image
          v
MakersVault temporal alert policy
          |
          +-- incident/health record
          `-- Discord notifier
```

- Prefer snapshots every 10–20 seconds over continuous video ingestion.
- Require multiple suspicious observations within a time window before alerting.
- Apply an incident cooldown so one failure does not create repeated messages.
- Keep the detector in an optional resource-limited process or container. Detector,
  camera, or notification failure must not impair the vault.
- Keep printer-run telemetry separate from artifact, revision, attachment, and
  prepared-file metadata. A print session may reference a MakersVault artifact or
  revision, but monitoring must also work when no reliable association exists.
- Do not record full video by default. Retain only bounded incident snapshots and
  health/error events under an explicit retention policy.
- Treat every detection as advisory. The UI and notification must communicate
  uncertainty and offer a false-alarm outcome for evaluation.

## Adapter order

1. Generic HTTP snapshot, MJPEG, or RTSP camera.
2. OctoPrint using its documented snapshot/stream settings.
3. Moonraker using its documented webcam list and printer-state APIs.
4. Native Bambu camera access only after an actual supported printer proves the
   LAN protocol, credential flow, decode path, and firmware resilience. A separate
   workshop camera remains the stable Bambu fallback.

Browser clients never receive reusable camera, printer, inference-provider, or
Discord credentials. The MakersVault backend or isolated monitor service fetches
configured endpoints, and it must reject arbitrary network targets rather than
becoming an SSRF proxy.

## Next-release experiment

This is an independently gated experimental track for the first release after
v5.1. It is not a Gate 6 acceptance requirement and cannot delay revision or Trash
correctness. It may ship only when disabled by default and clearly labelled
experimental.

Before implementation is promoted beyond a local prototype, the experiment must:

1. Run beside MakersVault for at least 20–30 representative prints.
2. Record detection latency, false alarms, missed known failures, camera dropouts,
   CPU/memory use, and notification delivery without retaining full video.
3. Prove Discord delivery with a redacted webhook secret and bounded retry/cooldown.
4. Prove that an unavailable detector or camera cannot affect core vault behavior.
5. Define and test the provider interface before any provider-specific behavior is
   exposed as a core domain contract.
6. Complete threat review for LAN endpoints, stored credentials, incident images,
   logs, and remote access.

Automatic printer actions require a separate future owner decision, threat model,
credential scope, fail-safe design, and hardware evidence. They are not implied by
successful alerting.
