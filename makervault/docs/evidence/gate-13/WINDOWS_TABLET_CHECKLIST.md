# Gate 13C — Dell tablet manual checkpoint

Prepared 2026-09-12. **Not executed.** Owner reports Windows, Bambu slicer and a
YubiKey; Windows Hello is not used. See the
[local results and open defects](PLATFORM_OPERATOR_RESULTS.md).

## 1. Read-only inventory — safe to collect now

Record these without sharing account passwords, key PINs, serial numbers, session
cookies, passkey credential IDs, bridge grant URLs or private keys:

- Windows edition/version/build and **Settings → System → About → System type**
  (x64 or ARM64; do not infer it from “Dell tablet”).
- Browser name/version; use an already installed browser for the first check.
- Bambu Studio version and whether it opens normally by itself.
- YubiKey model if known, connection available on the tablet, and whether the
  browser offers it as a security key. Do not reset the key or guess its PIN.
- Existing MakersVault bridge/version, if any. Do not overwrite existing handlers
  or trust settings before the test/restore plan is agreed.

No Windows Hello enrollment is required. MakersVault requires authenticator user
verification. A security-key PIN prompt is separate from the Windows sign-in PIN;
if the key/browser cannot satisfy the requirement, record the error and stop.

## 2. Preconditions — agree before installing or enrolling

The maintainer must supply/record all of the following first:

- Private test URL with a stable DNS hostname and trusted HTTPS certificate,
  reachable from the tablet; no certificate-warning bypass or plain-HTTP fallback.
- Exact API/web image IDs, application revision, passkey RP ID/origin and schema.
  Use disposable vault contents, not a live library; keep the admin policy Optional.
- Matched private bridge executable, version/revision, architecture and SHA-256.
  Do not use `releases/latest` as a substitute for the local development build.
  Cross-built binaries from the local diagnostic run were discarded, not supplied.
- Owner approval for device installation and an explicit backup/restore plan if an
  existing bridge or protocol registration would be replaced. Use the compiled
  installer, not the currently incomplete manual wrapper scripts.
- A disposable Member test account and a separate working Administrator recovery
  path. First passkey enrollment enables password-plus-passkey MFA on that account.
  Do not test first enrollment on the only working Administrator.
- A small known-good STL and a simple prepared 3MF fixture, identified by name and
  expected content. No printing, slicing service or manual thumbnail upload needed.

**Stop if any prerequisite is missing.** A Windows security/reputation warning is
an observation to record, not a reason to disable protections or bypass signing
checks. Signing and distribution remain separate release decisions.

## 3. Real-device checks — record expected and actual independently

Use the exact same HTTPS origin throughout. For each row record date/operator,
OS/browser/build versions, steps, actual result and a redacted screenshot or error
when useful. Do not mark a row passed from the automated Linux results.

| ID | Action | Expected | Actual |
|---|---|---|---|
| W01 | Sign in to the disposable account; navigate the library by touch | Library opens, selected folder/path is clear, menus can be opened/dismissed, no accidental move/delete | NOT TESTED |
| W02 | After agreed installation, run bridge `--version`, `list`, `doctor`, `trust list` locally | Recorded build matches; `bambu` is detected; config is valid; no unintended origin is trusted | NOT TESTED |
| W03 | Choose Bambu Studio and Open in Slicer for the small STL; cancel first origin confirmation | Browser/OS offers the intended handler; cancellation does not pair, download or open the fixture | NOT TESTED |
| W04 | Request again, confirm only the exact private HTTPS origin, and observe Bambu | Correct fixture opens in Bambu; no print starts. If the 90-second grant expired during pairing, request a fresh handoff | NOT TESTED |
| W05 | Repeat for simple prepared 3MF | Correct project/plate opens; prepared summary is consistent with the fixture; no raw G-code browser-file workflow or image-upload requirement | NOT TESTED |
| W06 | In Accounts & Access, start Add passkey on the disposable account, choose security key and cancel | Cancellation is reported; no credential is added; ordinary password sign-in remains available before successful enrollment | NOT TESTED |
| W07 | Retry enrollment with YubiKey, completing any key verification privately | Named credential appears; the account reports MFA enabled. Record failure instead if hardware/browser is incompatible | NOT TESTED |
| W08 | Log out, enter password, cancel the key prompt; then retry and complete it | Cancellation grants no authenticated access; successful password-plus-key verification signs in | NOT TESTED |
| W09 | If Firefox is already available, repeat a sign-in using the enrolled key on the same origin | Browser-specific physical-key ceremony succeeds, or exact limitation is retained | NOT TESTED / browser unknown |

Inspect downloads and logs locally; report only sanitized errors and fixture
names. Do not paste full protocol/confirmation URLs. For a failed handoff, keep
the MakersVault result, bridge error and Bambu outcome separate: “button clicked”
is not proof that the model opened.

## 4. Closeout

Keep results marked NOT TESTED, FAILED or PASSED per row. Unknown YubiKey capability
is a prerequisite gap, not a MakersVault regression or a successful key test.
After agreed cleanup, revoke only the test origin and remove only the disposable
MakersVault credential/account and test downloads. Do not reset the YubiKey,
uninstall Bambu, clear unrelated trust or remove another service's credentials.
Do not assume bridge `--uninstall` works on Windows; it currently supports macOS only.

This qualifies only the recorded device/browser/build combination. It does not
qualify Windows Hello, other YubiKeys, macOS/WebKit, signing/notarization, real Linux
desktop launch, or full touch/accessibility coverage. Owner acceptance and any
release support limit are separate recorded decisions.
