# Gate 13C — S04 residual decision checkpoint

**Date:** 2026-09-10. **Status: REVIEWED; OWNER DECISIONS PENDING.**

The owner requested continuation after the verified S01/S02 patch. This authorizes
the next review, not a blanket vulnerability waiver or release. Application source
remains `ac4a051`; entry documentation is `20342e7`. This checkpoint adds no
application, dependency, startup, Compose, upload-policy or release-pin changes.

## Outcome and recommendation

S04 contains **80 unique native CVEs / 167 package matches**. The other 17 CVEs /
17 matches are interpreter findings handled in S02/S03. Together they retain the
entire **181 API / 3 web** scan inventory; exclusions and mitigations do not subtract
scanner matches.

| Proposed action | Unique CVEs | Meaning |
|---|---:|---|
| E — exact-image precondition exclusion | 11 | Prior vendor review plus repeated component inspection supports an absent required module or 32-bit precondition. Not a patched package, other-architecture exclusion or suppression |
| H — priority unresolved review | 10 | Native reachability, raw-database exposure, missing vendor detail or conflicting version evidence needs particular attention. No automatic acceptance |
| R — scoped residual decision | 59 | Installed findings still need a named, bounded disposition. This includes two critical-rated Perl CVEs; this bucket does **not** mean low severity or proven unreachable |

Every CVE has its own proposed action, matched image/package/version/severity,
review source and empty acceptance fields in the
[decision register](security-residual-decisions.json). E/H/R are review queues,
not scanner severity replacements. **All 80 owner decisions are pending; the
69 non-excluded candidates remain unwaived.**

Recommend a bounded **runtime containment implementation** next, then return with
verified deployment conditions and a residual-acceptance proposal. Do not close
security simply because the language-package audits are clean. A distribution
migration, custom native backports or utility removal is not authorized here.

## Exact evidence and limits

Both existing local images were inspected again as **linux/amd64**:

| Image | Immutable ID |
|---|---|
| API | `sha256:4ba3ee6147ed94fb0dd8f1502dba16d257ce98da0aa9595898e5b44ff3bdc5cc` |
| Web | `sha256:164a7f830ff2868bda6b8a0012a8ab421fe070c64f8f669a986896cd1f8a73fa` |

The [new observations](security-residual-observations.json) retain timestamps,
image identities, the exact benign probe command/output digest, current component
values and hashes of seven deployment/recovery boundary files. Components exactly
match the committed hardening observations: 64-bit Perl; the same absent modules;
present Perl core, Socket and File::Temp; SQLite 3.46.1 with FTS5/SESSION enabled;
zlib 1.3.1. The disposable probe had no network, vault mount or application startup.
It did not execute a malicious native payload or prove a complete native call graph.

Current application inputs are unchanged from the
[422-API/58-web-test hardening verification](SECURITY_HARDENING_RESULTS.md).
No new full-suite run or advisory scan is claimed. Inventory identity is joined
through the committed full reduced-record comparison in
[the hardening audit](security-hardening-audit.json). Targeted vendor pages below
were reread for this checkpoint; the remainder uses the dated September 10 review.

The earlier `/tmp` hardening audit/full-run directories and vendor snapshot are
no longer available in this session. Committed inventories, summaries, hashes and
prior verification results remain; a hash is not a substitute for missing bytes.
The new checker validates committed evidence and the fresh probe only, not those
historical raw logs. Any selected release needs newly retained matched raw reports
in durable private storage, rather than relying solely on temporary directories.

## Critical matches and priority cases

Seven critical-rated package matches represent six CVEs. Three CVEs have bounded
precondition evidence: CVE-2026-8376 requires 32-bit Perl; CVE-2026-42496 and
CVE-2026-57433 require Archive::Tar and Storable, respectively. This is limited to
the inspected image; installed package matches remain visible.

The other three critical-rated CVEs remain residuals:

- **CVE-2026-5450** (libc6/libc-bin, two matches): allocating `scanf` conversion;
  native reachability has not been exhaustively excluded. Debian still marks the
  installed Trixie source version vulnerable; a fix in another Debian release is
  not an installed fix here. [Debian record](https://security-tracker.debian.org/tracker/CVE-2026-5450).
- **CVE-2026-13221**: particular large Perl regex tries can produce incorrect
  matches. No application-controlled Perl invocation was identified, but Perl core
  is present and Trixie remains affected. [Debian record](https://security-tracker.debian.org/tracker/CVE-2026-13221).
- **CVE-2026-12087**: the Perl Socket helper can read beyond a short argument.
  Socket is loadable; no matching application caller was identified. Trixie remains
  affected. [Debian record](https://security-tracker.debian.org/tracker/CVE-2026-12087).

H explicitly tracks CVE-2026-5450 plus these nine additional cases:

- **CVE-2026-19499 / 19542 / 77117 / 80489**: earlier CNA retrieval failed.
  Debian pages remain affected for installed Trixie; some descriptions are absent.
  The 19542 page identifies a `tdelete` stack-access issue. Missing detail is not
  evidence of safety. This turn did not retry the CNA endpoint or assert new 404s.
  [19499](https://security-tracker.debian.org/tracker/CVE-2026-19499),
  [19542](https://security-tracker.debian.org/tracker/CVE-2026-19542),
  [77117](https://security-tracker.debian.org/tracker/CVE-2026-77117),
  [80489](https://security-tracker.debian.org/tracker/CVE-2026-80489).
- **CVE-2026-11822 / 11824 / 39113 / 50812**: retain the prior SQLite raw-input /
  component/version uncertainty. The reread 11822 record describes malformed FTS5
  data used by a MATCH query and still marks Trixie vulnerable. No application FTS
  MATCH caller was identified, but accepting raw database bytes is not a native
  sandbox. [11822 record](https://security-tracker.debian.org/tracker/CVE-2026-11822);
  other three dispositions retain the [prior review](SECURITY_CLOSEOUT.md#s04--native-image-residuals-and-recovery-boundary).
- **CVE-2026-85091**: the upstream affected range in the description and Debian's
  Trixie mapping still differ. Do not clear installed zlib 1.3.1 by a headline
  version comparison; Debian also still marks its newer branch vulnerable.
  [Debian record](https://security-tracker.debian.org/tracker/CVE-2026-85091).

Web's three matches remain the same BusyBox-wget CVE-2025-60876, not an identified
Nginx request-parsing defect. Alpine still lists potentially affected packages.
The absent application URL-to-wget path is bounded source evidence, not a package
fix. [Alpine record](https://security.alpinelinux.org/vuln/CVE-2025-60876).

## Deployment truth — probe flags are not product defaults

Source inspection of the canonical Compose manifests finds **no explicit**
`security_opt`, capability-drop/add policy, read-only root filesystem, or container
memory/CPU/PID limits. This is not a claim that Docker has no default isolation.
The API's startup runs account setup and ownership changes before `setpriv` drops
to PUID/PGID. Normal application UID evidence is not proof of an explicitly emptied
capability bounding set or `NoNewPrivs=1`.

The probe's `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, 256 MiB and
one-CPU settings were inspection safety controls. They must **not** be reused as
claims about shipped production protection. See
[Docker runtime capability guidance](https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities).

Raw restore separately uses GNU tar and recursive chown, and opens supplied SQLite
bytes. Require trusted operator-controlled snapshots, protected provenance and
private staging; checksums and read-only SQLite do not authenticate the author or
sandbox native parsers. Portable `.mvault` remains the logical-content path, not
permission to treat raw snapshots as public model-sharing files. Existing guidance
is in [secure deployment](../../SECURE_DEPLOYMENT.md); no new admin setting or
end-user step was installed by this review.

## Proposed next slice — containment before acceptance

**Authorization requested; not implemented.**

1. Add explicit no-new-privileges and capability policy to canonical development /
   production Compose and synchronize aliases. Web should need no Linux capabilities;
   determine and test the API's minimal startup set instead of guessing it.
2. Preserve PUID/PGID account setup and existing volume ownership behavior; after
   initialization, explicitly drop unnecessary capability sets for the API process.
   Verify effective/permitted/inheritable/ambient/bounding sets and `NoNewPrivs`
   from the running application, not only container configuration.
3. Test fresh volumes, existing populated volumes, custom PUID/PGID, read-only
   mounted imports, upload/preview work, restart, and raw/portable recovery. Retain
   trusted-operator restore behavior; do not imply this sandboxes hostile snapshots.
4. Run the complete gate and joined production-HTTPS lifecycle, then scan the actual
   resulting images and update each affected decision. Preserve durable private raw
   evidence and publish only sanitized summaries locally in the repository.

No new container memory/CPU/PID cap, upload/library quota, port/topology restriction,
read-only-root conversion, Python/distribution migration, native package stripping,
schema migration, or release-pin change belongs to this slice. Such changes need
their own compatibility decision. Existing file/preview budgets remain unchanged.
Capability controls reduce privilege exposure; they do **not** repair libc/SQLite,
prevent every denial of service, protect all vault bytes from a compromised API,
or turn 181/3 scanner matches into zero.

## Owner checkpoint

Approve the bounded containment slice above first, or explicitly choose to review
exceptions against today's unchanged deployment instead. Approval to implement
containment is **not** acceptance of E/H/R entries.

Any later acceptance must identify the named maintainer, exact images/architecture,
individual CVEs, rationale, actual deployment conditions and date. Proposed expiry
is before candidate freeze/13D and within 30 days of acceptance, whichever is first;
reopen immediately for a relevant vendor fix, new caller, different image/platform,
or weaker deployment/raw-backup trust boundary. These conditions are proposed,
not evidence that the owner has accepted them.

G13-04 / Gate 13C remain open. Platform/passkey/operator/release qualification stays
separate; G13-01 performance and Gate 12 desktop work retain their deferrals. No
push, tag, publication, deployment, risk waiver or automatic gate acceptance occurred.

Reproduce the offline register checks with
`node makervault/docs/evidence/gate-13/security-residual-review.cjs` from the repo root.
They validate all 80 entries, 167 native matches, linked input/boundary hashes and
zero acceptances. The offline check passes, including 198 local document links;
Node syntax, static release-contract and `git diff --check` checks also pass.
`--capture` and `--write` deliberately refuse existing outputs.
