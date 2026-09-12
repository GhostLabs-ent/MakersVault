# Gate 13C — local platform/operator qualification

Date: 2026-09-12. Entry commit: `8a7fa35`. Application/image source remains
`6306ccff289d475530a6cacf4cb2e28db456ce08`, schema 17. This is a bounded diagnostic
and documentation slice, not Gate 13C acceptance or a release candidate.

## Fresh results

| Check | Actual result | Boundary |
|---|---|---|
| Exact-image production HTTPS | Passed: web shell, protected route, Secure/HttpOnly host-only session, wrong-CSRF/origin rejection, logout revocation, schema 17 | Disposable loopback-only TLS stack; not the owner's tablet deployment |
| Persistence and privileges | Primary bytes and generated JPEG survive API/web restart; API, Nginx master and 16 workers have empty capability sets and no-new-privileges | Generated fixture only; no new full recovery drill or real power-loss test |
| Operator setup | Two independently generated credentials, 40-character password/64-character hex secret, mode 0600, two unchanged-file overwrite refusals | Password output captured and discarded, not placed in evidence; real `.env` untouched |
| Compose preflight | Development, canonical deploy and historical alias parse; production rejects missing secrets | `config -q` only; setup preflight starts no services |
| Python harness | 25 tests pass, including recovery assertions, certificate hostname checks and privilege controls | Focused harness rerun, not the complete API/web gate |
| Go bridge | 25 top-level tests / 34 inclusive pass events with race detection; no skipped/failed events | Linux/amd64 container, Go 1.26.6; mocked browser opener is not an OS-launch test |
| Cross-build | Linux, Windows and macOS, each amd64/arm64, compile successfully | Six builds, not six native runtime passes; generated executables discarded with container |
| Linux bridge CLI/install | Version/help, list/doctor, empty trust list, missing-origin revoke refusal, copied executable and all-three-scheme desktop descriptor pass | Disposable container home only; no host handler, desktop session, real app or browser launch |

API image:
`sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`.
Web image:
`sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67`.
Both label themselves `development-gate13b` at the application revision above.
The Go container was pinned to
`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`,
with network disabled and source mounts read-only. No image was rebuilt or pulled.

## Newly found gaps — not fixed or waived

**P01 — manual installer parity.** Both
[Linux](../../../slicer-bridge/scripts/install-linux.sh) and
[Windows](../../../slicer-bridge/scripts/install-windows.ps1) wrapper scripts
register only `makersvault-slicer` and `makersvault-engrave`. They omit
`makersvault-open`, needed for the general local-tool adapter flow. The compiled
installers include all three. This is a source-confirmed discrepancy, not a
Windows runtime observation. The existing Go installer tests do not read those
manual scripts.

**P02 — macOS first-use pairing.**
[openBrowserURL](../../../slicer-bridge/cmd/slicer-bridge/pairing.go) handles only
Windows and Linux; macOS reaches `unsupported OS for pairing: darwin`. There is no
production override elsewhere. The pairing tests replace `browserOpener`, so they
can pass without exercising that branch. A macOS compile and `.app` registration
do not establish working first-use origin confirmation. Pre-populating trusted
origins is not an acceptable workaround for qualification.

**P03 — bridge documentation drift.** The
[bridge README](../../../slicer-bridge/README.md) directs users to a current v5.1
binary on `releases/latest` and says trusted-network HTTP is acceptable. That does
not establish availability of the current local artifact, and production UI
sessions require HTTPS even on LAN/VPN. Use the current
[secure deployment guide](../../SECURE_DEPLOYMENT.md), not HTTP or an unmatched
public bridge. The local loopback confirmation page is a separate transport from
the production MakersVault origin.

The secure-deployment handoff description is corrected in this documentation slice
to include exact adapter/content-role authorization; the bridge source/README
corrections below remain proposed. No source is changed merely to make the
unchanged-baseline evidence checker pass.

## Proposed next bounded implementation

Request owner approval for one bridge compatibility slice:

1. Register all three existing schemes in both manual installers; add parity
   regression tests that fail on the current scripts.
2. Add an explicit macOS pairing browser command and test platform command
   selection, literal argument handling and unsupported-platform failure. Preserve
   loopback confirmation, explicit origin consent, 90-second grants, role binding,
   no redirects and no default model-file opener.
3. Correct the README's current-development/matched-binary and production-HTTPS
   boundaries; include the general local-tool flow in installation messages.
4. Re-run bridge contracts/cross-builds and verify the changed source boundary.
   Preserve historical image evidence rather than rewriting old approvals. Assess
   applicable C6 re-review triggers explicitly; a fresh bridge or candidate is not
   automatically covered by the current exact-image native decisions.

This does not authorize a signing/notarization service, a public distribution,
new platform promise, security waiver, printer control or server-side slicing.
Real macOS launch remains unverified even after a code/test fix until a device
run or an explicit owner-approved release support limit is recorded.

## Owner device and manual checkpoint

The owner reports a **Windows Dell tablet**, **Bambu slicer installed**, no use of
Windows Hello, and an available **YubiKey**. No OS version, CPU architecture,
browser/version, slicer version, key model or user-verification capability has
been observed. Hardware availability is not a passed test.

The [Windows tablet checklist](WINDOWS_TABLET_CHECKLIST.md) separates read-only
inventory from later private test deployment/bridge installation and real checks.
It covers Bambu handoff, physical-key enrollment/login/cancellation and a small
touch-navigation sample. It requires a matched private build, trusted stable HTTPS
origin and disposable account first. The loopback smoke stack is already removed
and is not a tablet-accessible test URL.

Firefox passkey checks remain separate if that browser is available. Windows
testing cannot qualify macOS/WebKit prompts, native Linux desktop launch,
Windows Hello, all security keys or broad touch/accessibility support. Missing
hardware never silently moves C03 release blockers into Gate 12's desktop deferral.

## Evidence and reproducibility

[Machine-readable record](platform-qualification.json) includes exact commands,
start/end revision and source status, image IDs, reviewed-source/driver hashes,
and all four private run manifests. Raw logs are retained with private permissions
under `~/.local/state/makersvault/verification/containment-platform-{https,bridge,operator,harness}`.
All four commands exited zero; the bridge's expected missing-origin refusal is
retained on stderr. Eight raw-log hashes and four result-manifest hashes bind the
observations. These are local durable captures, not publicly available artifacts.

The [bridge driver](platform-bridge-check.sh) must run only inside the disposable
container described by the recorded command; never execute it in a user's home.
The [operator driver](platform-operator-check.py) uses generated temporary `.env`
files and never invokes `up`, backup or restore against an existing project.
The pre-existing exact-image smoke cleans up only its uniquely named disposable
Compose project and generated volumes. No user data was removed.

Revalidate retained evidence (does not rerun Docker checks):

```bash
node makervault/docs/evidence/gate-13/platform-qualification-check.cjs --self-test
node makervault/docs/evidence/gate-13/security-remaining-approval-check.cjs --self-test
```

The first checker includes four negative controls against invented device/launch
passes, image substitution and relabeling the macOS defect as fixed. It deliberately
rejects changed application/source observations; subsequent fixes need a new
qualification record, not an edited historical pass.

Native87 remains **E4/R57/F26/H0**, under unchanged C1–C7 and the October 12
00:00 America/New_York-or-earlier deadline. No new advisory fetch/scan or full
API/web/browser/lifecycle suite occurred. S04/G13-04, C03, Gate 13C/13D and matched
release qualification stay open. Performance G13-01 and Gate 12 deferrals remain
unchanged. The frozen Gate 5 candidate is untouched; no push, tag, publication,
real deployment or release approval is implied.
