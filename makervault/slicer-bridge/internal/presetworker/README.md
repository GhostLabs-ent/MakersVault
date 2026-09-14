# Single-use profile worker — MP-1b-2 through MP-1b-7

Internal foundation, **not dispatched by the production bridge main**. Only the
test executable currently handles `--internal-preset-worker-v1`. Do not call `Run`
from a UI/protocol path until consent, discovery and matched early main dispatch
are implemented. No new public/hidden CLI action, listener, network request,
installation, storage or import authority is enabled by this package.

`Run(ctx, request)` reexecutes the current executable with that one constant
argument, not a caller-specified command or shell. Locally constructed roots and
exact basenames travel only in a private anonymous stdin pipe. Public `Request`
and file-reader `Input` do not accept/emit JSON authority; the distinct private
wire shape is not an API schema or an authentication mechanism. A future caller
must obtain local consent and must never translate browser/server paths into it.
Do not mutate request slices concurrently with Run.

The child implements only `list` (direct JSON basenames, local-only), `manifest`
(fixed BBL.json local index), `location` (one selected Bambu data root/account;
system manifest plus optional user filename index) or `project`
(load selected Bambu documents, resolve up to 100 exact kind/name picks). It neither
launches descendants nor reads general slicer configuration. A later failed pick
discards earlier candidates. Labels in successful candidates can still contain
private user-authored text and require the eventual visible import review.

MP-1b-5 also adds private `discover` (bound machine identities and exact parent
closure) and `select` (rescan one chosen location, project up to 100 exact choices).
Both share the held ancestry and manifest/profile budgets described in
[content discovery](../presetfiles/DISCOVERY.md). Account is allowed only for
location/discover/select. Discoveries cannot appear on another operation or beside
partial candidates/errors; selections cannot claim an observed application version.
MP-1b-6 adds [saved-user machine projection](../presetfiles/SAVED_USER.md) inside
the same operations, not a new wire mode or relaxed generic `project` reader.
Invalid selected user files fail atomically; their versions never become observed
app versions. API wire validation and real installed-profile qualification remain separate.

MP-1b-7 adds private `accounts`: direct bounded local account-folder choices,
never account contents, selected presets or an active/default account assertion.
These names stay exclusively in local picker data, not a candidate/import payload.
Account/inputs/picks are forbidden on this operation, and account results cannot
appear in other operation responses or alongside errors/partial results. Missing
`user` is an error; an empty existing folder is an empty list. The [account/hint
contract](../presetfiles/ACCOUNTS.md) records the metadata-only boundary and limits.
Native hint acquisition is separate and inactive: it is not a worker operation,
does not expand the child's environment, and still needs bounded-lifecycle/native
qualification before matched local consent/UI integration.

The manifest operation retains the profile-bundle version separately, without
guessing an application version. Its entries include templates and are local-only;
the later adapter must bind actual document identities, resolve parents, exclude
non-instantiated documents and obtain explicit review. The parent validates the
index version/path/name/collision bounds and rejects mixed or partial responses.
No manifest URL or listed file is followed by this operation. Oversized indexes
fail at the response ceiling rather than silently dropping entries.

The [location operation](../presetfiles/LOCATIONS.md) traverses fixed children from
held parents, never treats a joined child as a new root, and shares the deadline
and entry budget across the manifest/user listing. Account is a bounded local-only
private request field for location/discover/select only; it and the root are absent
from the result. Empty account means system-only, not automatic/default selection.
The parent checks account-presence agreement, combined index bounds and deliberately
unknown app version. No local selector, installed-version probe or profile parsing
is implied. New Mac location inspection is refused, even in the old experiment.

## Resource and output controls

- 15-second parent context budget, or the caller's earlier deadline/cancellation.
  Scan work is in the child, not a goroutine that can leave the parent blocked on
  the same disk read. Cancellation/timeout kills the worker and closes owned pipes;
  the parent does not synchronously wait for a killed child to finish kernel I/O.
- One active or unreaped worker per parent process. The slot is released only after
  actual process reap and pipe-copy cleanup. A delayed/uninterruptible kernel wait
  leaves it occupied (`worker_busy`), preventing repeated hidden child accumulation.
  This is not a cross-process lock or a guarantee that SIGKILL/TerminateProcess
  immediately removes every stalled kernel task.
- 4 MiB private request, 2 MiB response, 64 KiB stderr drain ceiling. Overflow kills
  the child; stderr is never returned or logged, and even short diagnostic output
  makes the operation fail. No partial stdout is published after failure.
- Strict single JSON frame, ASCII schema keys, no duplicate (including case aliases)
  or unknown fields, depth 16, 250,000 value tokens, 64 keys/object. Reader budgets
  remain 10,000 files/entries, 8 MiB/file, 128 MiB total. These are **preset** limits,
  not changes to ordinary model uploads.
- Response version, selected kind/name count/order and parser/digest shape are
  checked. This is NOT independent geometry/digest authentication: MP-1c still
  needs strict API validation and shared canonical wire fixtures. Incomplete
  candidates are valid review output, not valid planning or print-ready claims.
- Only a fixed set of error codes crosses the pipe. Environment inheritance is
  limited to the Go race-runtime exit setting and Windows SystemRoot where needed;
  parent credentials, cloud tokens, loader overrides and application environment
  settings are not deliberately forwarded. No paths/preset names appear in argv.

## Limits of this evidence

Linux tests execute real subprocess round trips and simulate hung work, blocked
stdin, output floods, diagnostic leakage, cancellation and concurrent attempts.
They do not create an actual uninterruptible kernel I/O task. Ordinary test workers
are reaped and the slot becomes reusable. Windows process/pipe/file behavior still
needs native execution; a cross-build is not that evidence.

This is not a hard real-time OS guarantee: process creation, process termination
and pipe-close system calls themselves depend on the host OS. There is no OS memory/
CPU sandbox, parent-crash job-object guarantee or defense against local privileged
process/binary tampering. The supported child never spawns descendants; do not reuse
this supervisor as a general command runner. Native qualification and matched main
integration must resolve/report remaining lifecycle and startup constraints before
activation. Existing direct `presetfiles` APIs are still cooperative if bypassing
this supervisor; the eventual UI must not use them as a fallback.
