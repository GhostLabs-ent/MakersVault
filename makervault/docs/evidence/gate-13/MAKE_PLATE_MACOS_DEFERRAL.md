# Owner decision — defer new macOS preset import for v5.1

**Date:** 2026-09-13. **Status: ACCEPTED release-scope amendment.**
**Decision entry:** `eb8f31d8327e75d0165a4efef29cace200e7a977`.
**Runtime remains:** experimental source `907cddd`, schema 17; no activation.

The owner answered **“Yes approved”** to the explicit question:
“Do you approve that limited deferral?” The immediately preceding recommendation
was to defer **only new macOS preset import**, preserving existing Mac file-open
functionality. This records that decision, not a broader platform or gate waiver.

## Exact scope

- Defer workstation-local printer-preset discovery, import and refresh through the
  macOS bridge from v5.1. This covers the new import feature's Bambu/Orca/Prusa
  adapters on macOS, not their existing model-file handoff adapters.
- Preserve existing Mac file-open/protocol functionality. Its outstanding actual
  application, platform and distribution checks remain required; this is not a
  claim that those checks passed.
- Keep Windows/Linux preset import, the planned browser use of stored presets,
  Make Plate editing/recipes and editable 3MF export in scope, including access
  from Mac browsers. These features still need their implementation and evidence;
  the decision does not deliver them or introduce manual preset entry.
- Keep the macOS reader experiment excluded from normal/release builds. Retain its
  failed safety properties, source and evidence; do not enable a weaker fallback,
  an “accept risk” switch, or unsupported sandbox policy.

The [MS-1 NO-GO](MAKE_PLATE_MACOS_MS1_RESULTS.md) remains the assessment of its
candidate, not a proof of macOS impossibility or a new image-security exception.
MS-2/MS-3 macOS import work is deferred, not passed. The Mac-import safety boundary
is no longer a v5.1 delivery prerequisite, but remains a prerequisite to ever
enabling that feature. No existing file-open safety requirement is waived.

## Release communication and future integration

The [Make Plate scope matrix](../../MAKE_PLATE_RUNBOOK.md#platform-scope-after-the-mac-import-deferral)
and release notes must distinguish this one deferred feature from Mac support as
a whole. When the future import UI/bridge contract is implemented, report that
Mac-local preset import is unavailable in v5.1. Do not infer bridge capabilities
from the browser OS alone, hide unrelated browser workflows, prompt for source or
thumbnail uploads, or fall back to an unsafe local scan. No UI change is made here.

Return to macOS import only with a separately approved scope and a reviewed safe
boundary, supported packaging/API/lifecycle design, native counterexample controls,
named OS/architecture and real-slicer evidence, matched consent and recovery
qualification. MS-1's missing SDK/signing/test prerequisites remain unconfirmed,
not silently satisfied. No delivery date or automatic desktop-release inclusion
is promised by this deferral.

## Next work and unchanged gates

Resume MP-1b on **Windows/Linux Bambu known-root/manifest discovery, explicit local
selection and version observations**, with native Windows/lifecycle qualification.
Keep production scanning inactive until the matched consented worker integration
is verified. Then MP-1c still couples scoped import with persistence/migration and
portable/raw recovery; MP-1d and MP-2–MP-4 keep their own checkpoints. The owner's
Windows Bambu `v2.8.0.6` remains reported, not a qualified installed-version fixture.

MP-1b/MP-1, Gate 13C/13D, existing Mac real-app checks and Windows/YubiKey checks
remain open. CNC/CAM, Gate 12 and performance deferrals are unchanged. No push,
publication, SDK/signing acquisition, device installation or Mac connection is
authorized or performed by recording this decision. The user's separate ROADMAP
edit and desktop architecture document are preserved.

Documentation verification reuses `mac-reader-verify.cjs` (21 retained evidence
hashes) and `verify-release-contract.py`; a successful recheck is not a new native
run, release qualification, support-wide pass or transfer of old image waivers.
