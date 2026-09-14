# macOS preset-reader safety boundary — bounded proposal

**Date:** 2026-09-13. **Status: MS-1 completed NO-GO; Mac preset import deferred by owner for v5.1.**
**Entry:** `2226728`; unchanged experimental reader/test source `907cddd`, schema 17.
The owner subsequently said “MS-1 Approved” against proposal commit `b748079`.
[Assessment results](evidence/gate-13/MAKE_PLATE_MACOS_MS1_RESULTS.md) record the
supported candidate's missing pre-open guarantees and the required early stop.
MS-2 did not open. The owner then separately [approved the limited Mac-import deferral](evidence/gate-13/MAKE_PLATE_MACOS_DEFERRAL.md)
against assessment commit `eb8f31d`. Existing Mac file-open support is unchanged;
implementation, installation and publication remain unauthorized. The original
proposal below is retained as design/re-entry history, not a new execution plan.

## Original recommendation — MS-1 scope subsequently approved

Approve **MS-1 only**: one bounded feasibility pass for a supported, separately
confined macOS reader using App Sandbox. Investigate an embedded XPC service as the
candidate packaging/privilege boundary, not a new application users must install.
Do not implement a production service until the pass identifies a supported way to
prevent special-file opens and unwanted mount/recall effects **before they happen**.

App Sandbox is a candidate, **not an established fix**. It may constrain access
without satisfying these particular requirements. MS-1 must return GO, NO-GO or
BLOCKED with the precise evidence; missing guarantees are not a provisional pass.
No open-ended succession of custom sandbox or syscall experiments is authorized.

If the candidate cannot meet the contract within that pass, return for an explicit
owner choice: separately fund/re-scope the work, or defer **new macOS preset import**
while preserving existing Mac file-open functionality. Deferral is an option, not
a decision made here. Windows, Linux, saved-preset planning and remaining Make Plate
gates do not become qualified merely because Mac import is deferred.

## 1. What is known, and what is not

The [native experiment](evidence/gate-13/MAKE_PLATE_MAC_READER_RESULTS.md) at `907cddd`
read synthetic profiles on macOS 15.7.9 / 24G830 / Intel. It passed 34 default and
42 ordinary experimental unit checks. Two additional regression tests reproduced
**failed safety properties**, not security passes:

- An event-only open of a FIFO creates a reader endpoint, so `O_EVTONLY` is not
  demonstrated to be a metadata-only `O_PATH` substitute.
- A regular file can be replaced with a FIFO between metadata validation and open.
  The subsequent descriptor check detects replacement too late to undo the open.

Post-open local APFS/fSID checks also do not prove prevention of earlier mount,
automount or file-provider recall effects. No native device/mount/recall fixture,
Apple Silicon run, native race detector or real slicer profile was qualified.
These limits do not prove that safe macOS reading is impossible.

Normal Darwin builds still refuse preset reads. The experimental tag must remain
out of release builds; no fallback to direct reads is permitted. Existing
[ADR 0020](adr/0020-printer-presets-and-plate-recipes.md),
[MP-1b gates](MAKE_PLATE_RUNBOOK.md) and historical failures remain unchanged.

### Primary-source assessment, checked 2026-09-13

Apple documents App Sandbox resource restrictions and entitlement-based
configuration. It also documents unrestricted access to an app's own container:
“sandboxed” does not mean literally unable to write anywhere. Required baseline
system/container access must be enumerated rather than hidden behind a deny-all
claim. [Apple: protecting user data](https://developer.apple.com/documentation/security/protecting-user-data-with-app-sandbox)

User-selected read-only access is supported; a chosen directory grants access to
its contents recursively. Security-scoped bookmarks are access capabilities, not
regular-file or stable-inode certificates. **Inference:** neither a directory picker
nor a read-only entitlement, by itself, establishes the missing special-file and
mount/recall protections. The reviewed documentation does not specify those
guarantees. [Apple: file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)

Apple's archived XPC guidance describes separately sandboxed embedded services and
their signing requirements. It also describes launchd-managed restart/lifetime
behavior. This supports investigating privilege separation, not assuming that XPC
preserves the current kill/reap/one-worker contract. Current SDK and native lifecycle
behavior need qualification. [Apple: creating XPC services](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingXPCServices.html)

Ordinary embedded child tools inherit their containing sandbox; adding an internal
argument does not establish a distinct entitlement policy. **Design implication:**
do not apply one restrictive policy to the entire existing bridge and assume its
networking/slicer launch will remain intact, or assume self-reexec makes the reader
more confined. [Apple: embedded-tool configuration](https://developer.apple.com/documentation/security/protecting-user-data-with-app-sandbox)

Apple DTS explains that custom SBPL policy is not documented for third-party use
and connects that limitation to `sandbox-exec` deprecation (2020/2021 guidance).
No replacement public custom-policy contract was established in this review.
Therefore a handcrafted Seatbelt policy is **not the proposed shipping dependency**;
its presence on a Mac or use by another project would not resolve supportability.
[Apple DTS: custom sandbox support](https://developer.apple.com/forums/thread/661939)

Bookmark resolution offers `withoutMounting`, but its documented scope is resolution
of the bookmark. Do not generalize it to all subsequent path lookups, file opens or
provider recalls. Similarly, omitting network entitlements must not be presented as
proof that filesystem-triggered work by other OS services cannot occur.
[Apple: withoutMounting](https://developer.apple.com/documentation/foundation/nsurl/bookmarkresolutionoptions/withoutmounting),
[Apple: network entitlement scope](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.network.client)

## 2. Options and release impact

| Option | Assessment | Proposed disposition |
|---|---|---|
| Enable current pre/post-check reader | Known FIFO opening gap; mount/recall remains unproved | Reject; no warning checkbox or weaker fallback |
| Supported App Sandbox with separately confined embedded reader | Plausible privilege separation, but exact pre-open controls and lifecycle fit unknown; new native packaging work | **MS-1 candidate only**, not a promise to ship |
| Custom SBPL / `sandbox-exec` / private sandbox APIs | Could warrant separate research, but unsupported policy surface adds maintenance and OS-version risk | Not the release solution proposed here; no automatic pivot |
| Privileged daemon, Endpoint Security, kernel extension or VM | Materially different deployment/authority/cost; does not remove the need to safely access host source files | Out of this slice; no installation or entitlement requests |
| Defer new Mac preset import | Avoids enabling this unsafe reader, but changes accepted feature/platform scope | Owner decision only; preserve old Mac file-open support and saved presets |

For context, Apple DTS's Endpoint Security guidance requires Full Disk Access for
the ES client. That is not an acceptable additional end-user requirement for this
bounded optional profile reader. No ES implementation is proposed or tested.
[Apple DTS: Endpoint Security permissions](https://developer.apple.com/forums/thread/791996)

## 3. Candidate boundary and non-negotiable rules

The candidate would change the **internal Mac worker packaging/transport**, not the
public import API, parser semantics or existing file-open protocols. It would need
a follow-up accepted architecture decision before replacing today's supervisor.
One user-installed bridge bundle may contain internal components; no additional
mandatory helper installation, background daemon or broad filesystem service.

```text
Existing bridge: local consent and request ownership; no source-file opens
    -> bounded local selection + operation, no server-supplied paths/secrets
Separately confined reader: acquire safe root -> read -> existing Go projection
    -> bounded typed candidates or one redacted failure, never raw profiles
Existing bridge: validate -> visible review -> separately scoped future submission
```

This is a proposed trust split, not implemented code. The root-opening step is part
of the safety boundary: moving it into the parent, a picker, a copy operation or a
bookmark broker does not discharge the missing proof. No component may first open
an unsafe source and then pass its handle to a sandbox as a supposed remedy.

Required properties:

1. **Confine before source access.** OS-enforced policy must be active before the
   first source-path lookup/metadata operation. Identify the enforcement point for
   each forbidden effect, including any OS broker. No self-reported “sandbox ready”
   flag is sufficient proof, and no fallback runs when policy setup fails.
2. **Keep authority local.** Only adapter-owned roots or a locally selected root;
   no browser/server path, glob, command, policy text or arbitrary file API. Prefer
   one root confirmation per import where needed, not selecting every profile or
   uploading files/images. Access tokens/bookmarks remain ephemeral and local for
   the first proof; persistence would require a separate reviewed lifecycle.
3. **Open only allowed objects.** Prove denial of FIFO/socket/device opens before
   endpoint/driver effects; directories permit only necessary traversal/listing.
   Keep no-follow, traversal, hard-link, filesystem, dataless and mutation controls.
   A final `fstat`, inode comparison, nonblocking flag or timeout is insufficient.
4. **No source mutation or extra capabilities.** No profile writes, credential
   access, cloud login, network request, printing, app launch or arbitrary process
   execution by the reader. Inventory essential runtime/container/IPC exceptions;
   verify them with negative controls. Read-only profile access does not establish
   that the whole process has zero write capabilities.
5. **Narrow IPC.** The proposed embedded endpoint is private, not a LAN or general
   Mach service. Establish caller/child identity, exact build/protocol match,
   connection/request binding and one-shot operation behavior using supported
   mechanisms. Do not treat a PID, claimed path or nonce alone as authenticated
   process identity. Old/mismatched/replayed messages return no candidates.
6. **Preserve bounds and semantics.** Retain 10,000 entries, 8 MiB/file, 128 MiB/read,
   depth 16, 100 selected presets and the 15-second scan budget; the user-consent
   wait precedes the scan. Retain 4 MiB private request / 2 MiB response ceilings
   and diagnostic suppression. Failed or cancelled work publishes no partial
   catalog. User labels still require visible review before external submission.
7. **Prove lifecycle, do not inherit claims.** XPC invalidation is not proof of task
   death. Demonstrate cancellation, crash/restart, stale replies, admission limits
   and no accumulating stuck workers before using any replacement supervisor.
   Preserve honest limits on uninterruptible kernel I/O and host scheduling; no
   hard-real-time termination or parent-crash cleanup claim without evidence.

Threats in scope include malformed profiles and concurrently replaced files within
a selected writable root, including changes by another process of the same user.
Do not discard those cases as trusted merely because the user selected the folder.
A compromised kernel or privileged administrator defeating OS policy is not a
newly solved threat. Unprivileged mounts/providers must still be considered.

## 4. Packaging and prerequisites — not a flag-only change

Today's [supervisor](../slicer-bridge/internal/presetworker/supervisor.go) reexecutes
the same binary through private pipes. The [release builder](../scripts/build-release.sh)
cross-builds six `CGO_ENABLED=0` binaries in Linux containers; the
[Mac installer](../slicer-bridge/cmd/slicer-bridge/install_darwin.go) copies one
executable and writes the bundle metadata. None establishes the proposed independently
sandboxed, signed component. Do not silently replace these distribution assumptions.

MS-1 must identify the minimal supported SDK/native interface, a compatible way to
reuse the Go projection core, component signing/entitlements and the bundle/update/
uninstall implications. Prefer public SDK/library interfaces over the experiment's
raw Darwin syscall ABI. Do not introduce a second independent preset parser.

No Apple SDK/build environment or signing identity is confirmed available for this
work. The previous Mac runs used cross-built test binaries and installed nothing;
absence of Go on PATH is not evidence that Xcode/SDKs are absent or present.
Inventory a specifically authorized build environment before proposing native builds.
If it lacks a suitable SDK, report that prerequisite—do not install toolchains on
the OpenClaw Mac, fetch unofficial SDKs, start paid CI or acquire certificates.
No signing secret is requested in chat or stored in evidence.

A disposable development-signed proof would not establish Developer ID distribution,
notarization, Gatekeeper behavior, upgrade parity or support for all Intel/Apple
Silicon OS versions. Later release qualification must record exact artifacts,
entitlements, SDK/deployment target and both native architectures. Do not publish
development proof bundles or change the public release workflow during feasibility.

## 5. Gates, decisive tests and stop conditions

| Checkpoint | Deliverable / required exit | Current state |
|---|---|---|
| MS-0 — proposal | Owner reviews options, unchanged safety requirements and bounded MS-1 scope | Owner approves MS-1 only on 2026-09-13; no implementation/support decision |
| MS-1 — feasibility only | Map each pre-open requirement to a supported enforcement mechanism; identify packaging/lifecycle and authorized SDK/test prerequisites; return GO / NO-GO / BLOCKED | COMPLETED NO-GO — [results](evidence/gate-13/MAKE_PLATE_MACOS_MS1_RESULTS.md); supported pre-open mapping not established, early stop applied |
| MS-2 — disposable native proof | Only after a renewed assessment returns GO and owner approval, prove the table below with synthetic fixtures and retained red controls; no production dispatch | DEFERRED with Mac preset import for v5.1; not opened or passed |
| MS-3 — integration/release qualification | Separately accepted packaging/transport decision, matched local consent/discovery, native targets, install/update/uninstall and release evidence; rejoin MP-1b/MP-1 | DEFERRED for Mac preset import only; existing Mac file-open qualification is not deferred |

MS-1 ends after **one candidate assessment**. Stop early if the necessary supported
pre-open rule cannot be identified, independent policy needs unapproved packaging,
the SDK/device prerequisites are unavailable, or termination/admission semantics
would weaken the current contract. Return the specific gap rather than trying
private APIs, adding permissions or implementing adjacent discovery/API work.
No schedule estimate is treated as evidence that the candidate is feasible.

Minimum MS-2 evidence, if separately authorized:

| Control | Required observation |
|---|---|
| Confinement off / invalid / missing / wrong entitlement | Operation refuses before source access; instrumented forbidden-access canary detects a disabled-policy control |
| FIFO static and deterministic replacement; event-only counterexample | Unconfined controls reproduce the existing endpoint effect; confined opens produce **no endpoint effect**, not just no returned bytes. An independent observer and synchronization make the test non-vacuous |
| Symlink/ancestor, hard link, directory/socket/device substitution | Refusal at the appropriate boundary, no outside bytes or forbidden open effects; devices only on a separately authorized disposable rig |
| Mount, automount, remote/provider and dataless/recall | No forbidden lookup/mount/hydration activity, including root resolution and brokers; denial of a direct socket alone is insufficient. Missing instrumentation/fixtures means NOT TESTED |
| Ordinary reads, rename, concurrent mutation, permissions | Exact synthetic projection/source-byte preservation; changed/ambiguous sources fail with no partial result |
| IPC/resource/lifecycle | Wrong caller/build/frame, stale response, oversized input/output, diagnostic leakage, timeout, cancellation and crash/restart fail closed without accumulating workers |
| Distribution/native parity | Exact signed bytes/policy on named OS/Intel and Apple Silicon; malformed bundle and mismatched component refused; old file-open workflows remain separately tested |

Use only owned synthetic fixtures and least-privileged tests. Do not exercise device,
mount, provider-account or privileged controls on the shared OpenClaw asset without
separate explicit scope. Hostile-case observations must be independent of a reader
claiming success. Keep every failed attempt, command/source/binary/policy digest,
OS/architecture, timing, omitted check and cleanup result. A skipped critical test
does not close the gate; obtaining a dedicated rig may be a prerequisite.

## 6. Owner checkpoint and handoff

**Current checkpoint:** the owner [accepted the Mac-import-only deferral](evidence/gate-13/MAKE_PLATE_MACOS_DEFERRAL.md).
Resume the remaining Windows/Linux MP-1b work; existing Mac file-open support and
planned browser Make Plate workflows remain in scope. Further Mac reader research
or a revised architecture needs separate direction.

**Original recommended approval (now granted):** MS-1 only, with no native installation, production code
activation, support reduction or publication. Report back once the candidate is
mapped to the required guarantees or rejected. Any MS-2 execution needs the concrete
build/device plan and separate approval; MS-3 needs its own architecture acceptance.

If the owner instead chooses a release-scope deferral, record it explicitly in the
Make Plate runbook, traceability/support matrix and release notes. Explain the
unavailable import action; retain existing Mac file-open support and future access
to already-saved valid presets. Do not imply manual preset entry exists unless it
has actually been implemented. CNC/CAM, Gate 12 and performance deferrals stay as
previously decided; Gates 13C/13D and the other Make Plate requirements remain open.

This preparation changes documentation only. Rechecking the existing 21 evidence
hashes and release-contract verifier does not repeat native tests, certify a sandbox,
close MP-1b or transfer historical image waivers. No connection to the owner's Mac,
code/policy installation, SDK acquisition or public action is part of this proposal.
