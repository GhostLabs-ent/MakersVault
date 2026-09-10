# Gate 13C — approved S01/S02 security hardening

**Date:** 2026-09-10. **Implementation:** `ac4a051302d49838ef676c760cdfd95ab2127408`.

The owner approved the bounded patch scope in [the closeout review](SECURITY_CLOSEOUT.md).
S01 test-tool maintenance and S02 outbound hostname hardening are implemented
locally and verified. Full verification and both audit phases completed; the
development-tool findings are gone, while the runtime image inventory remains
181 API / 3 web matches. **S04 residual acceptance and Gate 13C remain open.**

## Changes and compatibility boundary

- Vitest and its seven installed `@vitest/*` packages: **4.1.10 → 4.1.11**.
  Only that dependency family and its integrity/peer metadata changed in npm's
  lock. Production JS dependencies and application UI are unchanged.
  [Vendor advisory](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9).
- Development HTTPX2 and httpcore2: **2.9.0 → 2.12.0**. An initial dry run with
  httpcore2 2.10.0 was rejected because HTTPX2 2.12.0 requires **exactly 2.12.0**;
  the matching pair installs and `pip check` passes. No unrelated Python pins
  changed. Python locks retain their existing exact-version freeze format.
  [HTTPX2 release](https://github.com/pydantic/httpx2/releases/tag/v2.12.0).
- `idna==3.18`, already in both runtime/development locks, is now a direct runtime
  requirement. Its installed version did not change. No Python major, base image,
  installer lock, bridge, Compose, schema, or release pin changed.
- Outbound authority validation uses **strict IDNA2008**, with UTS #46 disabled
  and no Unicode case/compatibility mapping. Only ASCII letters are lowercased;
  valid Unicode/NFC names and validated punycode names yield one canonical ASCII
  hostname. The raw authority is examined before `urlsplit().hostname` could
  lowercase Unicode. [IDNA documentation](https://github.com/kjd/idna#usage).
- DNS, automatic HTTP Host, TLS SNI and redirect-origin comparison use that same
  canonical identity. Literal public IPv4/IPv6 addresses retain numeric resolution
  and private/mixed/special-use answers remain blocked. Every redirect resolves
  and checks again; HTTPS downgrade and cross-origin credential forwarding remain
  forbidden. Raw string URLs are validated before `Request` can strip controls.

This deliberately rejects previously accepted malformed/ambiguous authorities:
multiple trailing dots, empty labels, invalid A-labels, non-NFC names, Unicode
characters needing case/compatibility mapping, escaped hostnames, IPv6 zone IDs,
and malformed bracket/port suffixes. Ordinary ASCII names and one trailing DNS
root dot remain supported. `faß.example` now resolves as `xn--fa-hia.example`,
not `fass.example`. A canonical Unicode name and its equivalent punycode spelling
share an outbound origin; redirects between those spellings preserve credentials
only when scheme and effective port also match. Distinct names/ports still strip
credentials. No stored URL, user model, file payload or metadata is rewritten.

Configured inbound Host, browser Origin, CSRF and passkey policies are unchanged
and have regression/full-gate checks. Internationalized import names may need a
verified canonical lowercase/NFC or ASCII punycode spelling; see
[operator guidance](../../SECURE_DEPLOYMENT.md#remote-import-network-boundary).
This is mitigation of the reviewed outbound CVE-2026-17084 path, **not a patched
CPython interpreter or clearance of every stdlib caller**.

## Verification and failed attempts retained

The [capture helper](security-hardening-run.cjs) writes private command logs,
start/end source status, revision, exit code, duration and log hashes. Preliminary
builds/tests ran on explicitly dirty development inputs. The implementation was
then committed locally before `make verify`; its source revision stayed
`ac4a051`, with clean verification source paths throughout that run and both
audit phases. Documentation-only evidence work is separate from application input.
The [verification record](security-hardening-verification.json) retains every
captured attempt, identities, log hashes, lifecycle and runtime observations.

| Check | Result / exact scope |
|---|---|
| First focused attempt | **2 failed / 135 passed**: repeated root-dot rejection needed strengthening; fake TLS context lacked verification attributes. Both corrected before commit; neither failure erased |
| Corrected focused attempt | **138 passed / 13.56 s**, network-disabled disposable test image; hostname, safe transport, lock consistency, login security, passkey foundation and archive guard suites |
| New hostname regression coverage | **68 cases**: Unicode/punycode, malformed authorities before DNS, IPs, mixed DNS, redirect credentials/closure, actual stdlib HTTP Host generation through fake sockets, TLS failure and unchanged inbound policy |
| Old-image negative control | **1 expected assertion failure / 67 deselected**: old code maps the sharp-s hostname to `fass.example`. This demonstrates the regression detects the old behavior, not a successful exploit |
| Web preflight | Clean `npm ci`, type check, **58 tests across 16 files**, and production build pass. Full `make verify` reuses that same-source cached web test layer; it is not a second execution of those tests |
| Complete API suite | **422 passed / 153.55 s**, including all 68 new cases |
| Full `make verify` | **Exit 0 / 277.756 s**: API, web, bridge tests/build, Compose/security checks, fresh non-root/schema-17 smoke, virtual passkeys, static release contract, **19 Python / 28 Node harness tests**, joined production-HTTPS lifecycle |
| Exact-image policy/runtime probes | Pass without network, capabilities, application startup or vault mounts; read-only filesystem, no-new-privileges, UID/GID 65534, 256 MiB / one CPU. `idna` 3.18 present; HTTPX2/httpcore2/pytest absent in production |

The lifecycle proves schema **4 → 17** upgrade, raw recovery **contract 6** with
pre-start revocation and startup audit, exact stopped schema-4 rollback, portable
**17 → 12 → 17** clean-identity startup, 18 compared portable members, preserved
external-source bytes, and nonempty/corrupt-archive refusal paths. It does not prove
hostile raw SQLite/GNU tar safety; S04's trusted raw snapshot boundary still applies.
The passkey ceremony uses Chromium's virtual authenticator, not physical hardware.
No browser performance benchmark was rerun or accepted; G13-01 remains deferred.

The negative control used old test image
`sha256:4704c6196a007886663402c78668d93160a302cf836e6a65424d48388e3ae3e4`
with only the new test module mounted read-only. Corrected focused tests used
`sha256:21eb2d155aae034d4685157fe4ffe9f130f388def364c68626ff6845b23eb76b`.
Named development runtime images from the successful lifecycle:

| Image | Immutable local ID |
|---|---|
| API | `sha256:4ba3ee6147ed94fb0dd8f1502dba16d257ce98da0aa9595898e5b44ff3bdc5cc` |
| Web | `sha256:164a7f830ff2868bda6b8a0012a8ab421fe070c64f8f669a986896cd1f8a73fa` |

These are labelled `development-gate13b` / `ac4a051`, not a release candidate.

## Fresh advisory evidence

Language scans started **21:42:48Z**; image scans started **21:46:21Z** on the same
revision and lock hashes. They are two explicit phases, not an invented single
simultaneous scan. Image arguments were unused placeholders in the language phase;
the image phase explicitly names the two immutable IDs above.

| Scan | Result |
|---|---|
| npm full web / production / organization / preview | **0 / 0 / 0 / 0** |
| Python runtime / development / installer | **0 / 0 / 0** advisories across **35 / 43 / 2** dependencies, none skipped |
| Go symbol-level source | **0** findings, govulncheck 1.7.0 / Go 1.26.6 |
| Exact API / web images | **181 / 3** matches, **96 / 1** unique CVEs; complete reduced-match equality to the closeout inventory |

Grype 0.118.0 used a valid schema-6.1.9 database built September 10 at 06:30:24Z.
API severities remain 7 critical, 61 high, 51 medium, 9 low, 45 negligible and
8 unknown; all three web matches are medium. The
[combined audit record](security-hardening-audit.json) retains the separate phase
timestamps/locks, scanner metadata and raw-report hashes. Equality covers advisory,
package/version/type, severity, source/namespace, locations, match types and fix
metadata—not every raw scanner field. All original matches remain recoverable from
the referenced [closeout inventory](security-closeout-inventory.json); no counts
were subtracted for mitigations or vendor exclusions.

The [reducer](security-hardening-analysis.cjs) checks raw hashes, phase/source/image
agreement, unchanged runtime/build/harness/Go locks, and that npm changes are only
the eight Vitest-family package entries. Repeated component inspection confirms
the same x86_64/64-bit Perl, absent/present module boundaries, Python 3.11.16,
Expat 2.8.3, SQLite 3.46.1 (FTS5/SESSION enabled) and zlib 1.3.1. S04's dated vendor
review remains the earlier September 10 snapshot, not a claimed new vendor survey.
The sole application-disposition change is CVE-2026-17084's reviewed outbound
path: it is now mitigated with strict IDNA2008, while CPython remains matched and
unpatched. Inbound policy and other possible stdlib consumers are not declared fixed.

[Consistency checks](security-hardening-check.cjs) pass for 64 retained lock/log/
report hashes, local documentation links and 11 unchanged inbound-policy/schema/
base-image/Compose boundary files. Node syntax checks, `git diff --check` and the
static release-contract check pass. These checks validate evidence and scope;
they do not replace application tests, vendor review or release qualification.

Current production/test language scopes are clean within these dated scans; this
does not make the runtime OS/interpreter inventory clean. The native residual
review remains [S04](SECURITY_CLOSEOUT.md#s04--native-image-residuals-and-recovery-boundary).
No suppressed CVE, global package exemption or owner risk acceptance was added.

## Next checkpoint

Accept the verified S01/S02 implementation, then explicitly disposition remaining
S04 risks against these exact images and architecture before candidate qualification.
The earlier [review](SECURITY_CLOSEOUT.md) still supplies its dated vendor sources
and conditions: runtime preconditions, trusted raw backups, deployment containment,
named owner/reason and a review deadline. Missing vendor information and unproven
native reachability are not automatic exclusions.

Physical/native-platform qualification and owner-selected matched release evidence
remain separate obligations. Gate 13C/13D is not automatically accepted; Gate 12
remains desktop-deferred, the frozen Gate 5 candidate stays `f6ff55b`, and no push,
tag, publication or live deployment is authorized or performed.
