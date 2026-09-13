# MS-1 — supported macOS reader feasibility: NO-GO

**2026-09-13. Owner authorization:** “MS-1 Approved.”
**Reviewed entry:** `b748079fd58f9f33cdc086d48ee28178cf83165c`.
**Unchanged reader/native-test source:** `907cddd`; application schema 17.

## Decision

**MS-1 assessment completed: NO-GO for the proposed App Sandbox / embedded XPC
reader under the current safety contract.** Do not open MS-2, enable the experiment
or change packaging on the strength of this assessment.

The reviewed public interfaces establish resource scoping and process separation,
but no supported mechanism was identified that satisfies the two decisive pre-open
requirements: reject special-file opens before endpoint/driver effects, and prevent
unwanted mount/automount/recall activity throughout source resolution and reading.
XPC lifecycle equivalence to the current supervisor is also not established.

This is a **candidate acceptance decision based on missing required guarantees**,
not a newly executed App Sandbox exploit and not proof that safe macOS access is
impossible. The earlier FIFO counterexamples exercised the experimental reader's
approaches, not this unbuilt XPC candidate. The result is NO-GO rather than BLOCKED
on a missing SDK: a build machine would not supply the absent safety mapping.

The [approved assessment scope](../../MAKE_PLATE_MACOS_SAFETY_PROPOSAL.md) explicitly
requires stopping when the necessary supported pre-open rule cannot be identified.
One candidate was assessed. No private-policy, privileged-service or alternate
syscall experiment was started; no further investigation is assumed authorized.

## Requirement-to-mechanism assessment

“Documented” below means a public architecture/API capability exists, **not** that
MakersVault has implemented or natively qualified it. Source references follow.

| Requirement | Candidate mechanism and actual scope | Assessment |
|---|---|---|
| Confinement active before source access | App Sandbox entitlement on a separately signed service target; root/picker/bookmark acquisition must remain inside the reviewed access boundary | Documented capability, but startup and broker behavior unqualified [S1, S2] |
| Local consent and read-only selected-root access | User-selected read-only entitlement and scoped URL/bookmark transfer; selected-folder access includes descendants | Documented access grant, not an object-type/identity certificate [S3] |
| No FIFO/socket/device open effects, including replacement races | No regular-file-only pre-open rule identified in reviewed supported entitlement/access interfaces; existing pre/post checks cannot discharge it | **Decisive NO-GO: no supported enforcement mapping** [S1, S3, native evidence] |
| No unwanted mount/automount/recall from initial lookup through data read | `withoutMounting` covers bookmark resolution; network entitlements govern socket access, not a documented global restriction on filesystem work by OS brokers | **Decisive NO-GO: coverage does not span the required operation** [S4, S5] |
| Symlink/traversal/source-change defenses | Held handles, native no-follow/directory flags and identity checks remain useful defense in depth | Preserve; not a substitute for the two missing properties [S6, native evidence] |
| Narrow local IPC and caller/request identity | Embedded XPC transport with a strict operation envelope; identity, exact component version and replay binding still need design and native checks | Architecturally plausible, not qualified [S2] |
| Bounded work, cancellation and no accumulating stuck tasks | Existing Go budgets can be retained, but XPC-managed lifecycle is not the current direct-child kill/reap mechanism | Unresolved; connection invalidation alone is insufficient evidence [S2, S7, local supervisor] |
| No source mutation or unintended reader capabilities | Read-only source grant; omit unnecessary entitlements and inherited handles; separately inventory runtime/container/IPC rights | Partial mapping only; App Sandbox is not a literal zero-write/zero-IPC environment [S1, S3] |
| Preserve one user-installed bridge and existing file-open flows | One bundle with an embedded service and a native interface to the existing Go projection | Plausible packaging shape, but new build/signing/update work; not today's distribution [S2, local builder/installer] |

### Primary sources and limits

- **S1 — [Configuring the macOS App Sandbox](https://developer.apple.com/documentation/xcode/configuring-the-macos-app-sandbox).**
  Apple describes kernel-enforced entitlement restrictions, per-resource permissions
  and managed file access. The listed controls do not provide the required
  regular-file-only or complete no-mount/no-recall contract. This is the boundary of
  the reviewed interface, not a claim to have enumerated every macOS facility.
- **S2 — [Creating XPC Services](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingXPCServices.html)**
  and **[Enabling App Sandbox](https://developer.apple.com/library/archive/documentation/Miscellaneous/Reference/EntitlementKeyReference/Chapters/EnablingAppSandbox.html).**
  Apple's archived guidance supports independently configured service targets,
  signed entitlements and bundles under `Contents/XPCServices`. Service lifetime is
  managed by launchd; connections are not one-to-one certificates of a running
  process. This architecture reference is not current native-runtime qualification.
- **S3 — [Accessing files from the macOS App Sandbox](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)**
  and **[user-selected read-only entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.files.user-selected.read-only).**
  Folder grants are recursive. Bookmarks extend access; the documented read-only
  permission does not state that a replaced selected entry can never have FIFO or
  device-open effects. No grant makes an arbitrary selected folder immutable.
- **S4 — [Bookmark resolution withoutMounting](https://developer.apple.com/documentation/foundation/nsurl/bookmarkresolutionoptions/withoutmounting).**
  Its stated scope is bookmark resolution. **Inference:** applying it there does
  not establish a guarantee over later `openat`, directory listing, data reads or
  file-provider activity. No broader guarantee was found in the reviewed surfaces.
- **S5 — [Network client entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.network.client).**
  Apple's TCP rules concern connection initiation; they are not a filesystem-broker
  policy specification. **Inference:** denying worker sockets alone cannot be used
  as proof that the entire source access caused no external mount/recall activity.
- **S6 — [Pinned XNU fcntl definitions](https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-11417.101.15/bsd/sys/fcntl.h).**
  Reviewed `O_NOFOLLOW_ANY`, `O_DIRECTORY`, `O_EVTONLY` and the presence of
  `O_RESOLVE_BENEATH`. Their presence does not establish the missing regular-file
  pre-open guarantee or full mount/recall prevention. This is the prior experiment's
  source pin, not a claim to match the owner's exact kernel or every current SDK.
- **S7 — [NSXPCConnection.invalidate()](https://developer.apple.com/documentation/foundation/nsxpcconnection/invalidate()).**
  The documented effect is on the connection and pending handlers. It does not
  promise completion of remote kernel I/O or an equivalent of waiting for an owned
  child to be reaped. Losing a connection is not sufficient to release a stuck-work
  admission slot under our contract.
- **S8 — [Apple DTS on custom sandbox support](https://developer.apple.com/forums/thread/661939).**
  Apple staff's 2020/2021 explanation distinguishes supported entitlement-based
  App Sandbox from SBPL undocumented for third-party use. The review found no
  supported replacement custom-policy contract that would justify pivoting to it.
  Other developers' comments about products using SBPL are not Apple guarantees.

These are dated primary-source observations, not newly captured native results.
Some developer pages serve a JavaScript shell to direct opens; their indexed Apple
documentation text was available in search results. Archived pages are explicitly
labeled above. No unsupported claim is inferred from a search returning no match,
and no raw copy or immutable hash of these web pages is asserted by this report.

## Packaging, parser reuse and prerequisite findings

The minimum plausible architecture would use a private embedded service, its own
signed App Sandbox policy, and a supported Apple SDK interface to XPC. Apple's C
XPC API is in libSystem; Foundation/AppKit would be needed if choosing their URL/
selection interfaces. A thin native bridge to the existing Go projection core is
the candidate implementation shape—not a second preset parser or a copied Apple
implementation. Exact integration/toolchain/deployment versions are **not selected**
because the safety gate failed first. [S2](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingXPCServices.html)

Local source review confirms:

- [Current supervisor](../../../slicer-bridge/internal/presetworker/supervisor.go)
  owns an `exec.Cmd` child and releases its single slot after process reap and
  pipe cleanup. Replacing that with XPC requires a new lifecycle/admission design;
  adding an argument to self-reexec does not create a separate entitlement policy.
- [Release builder](../../../scripts/build-release.sh) produces six Go binaries
  with `CGO_ENABLED=0` in Linux containers. It does not build/sign the candidate's
  embedded service. The current workspace was observed to be Linux.
- [Mac installer](../../../slicer-bridge/cmd/slicer-bridge/install_darwin.go) copies
  one executable and writes bundle metadata. It does not establish independently
  signed service installation/update/removal. Any redesign must preserve existing
  protocol handling and require separate acceptance, not an incidental SDK change.

**Prerequisites not confirmed:** an authorized Apple SDK/native build environment,
development/distribution signing setup, Apple Silicon test asset and a disposable
rig for device/mount/provider negative controls. The owner-provided Intel Mac is
known from earlier tests, not re-inventoried here. No Mac SDK absence is asserted.
Because the decisive enforcement mapping failed, the approved early-stop rule was
used before requesting build access, inspecting signing identities or reconnecting
to the Mac. No installation, paid CI, certificate acquisition or device test ran.

## Validation and owner decision

Read-only rechecks at the unchanged runtime source:

```sh
node makervault/docs/evidence/gate-13/mac-reader-verify.cjs
python3 makervault/scripts/verify-release-contract.py
```

Both pass: 21 retained native-evidence hashes match and v5.1.0 release safeguards
remain intact. These checks do **not** repeat the earlier Mac tests, qualify XPC,
rebuild images or transfer old waivers. Only documentation changed; the owner's
ROADMAP edit and desktop architecture document were left untouched. No runtime,
API, schema, installer, build, policy or release-note support promise changed.

**Recommended owner decision, not yet accepted:** defer *new macOS preset import*
for v5.1 and continue the remaining approved Make Plate work. Keep existing Mac
file-open support unchanged; this recommendation does not qualify its outstanding
real-app/signing checks or add a manual-preset workflow. Existing/saved-preset
planning still needs its planned implementation and evidence; nothing here delivers
that feature. If Mac import must ship now, separately authorize a revised scope
and research budget instead of treating MS-2 as the automatic next gate.

No deferral has been applied. MS-1's assessment is finished; owner disposition,
MP-1b/MP-1 and Gates 13C/13D remain open. No new authority is inferred for private
sandbox policy, privileged helpers, further Mac experiments, push or publication.
