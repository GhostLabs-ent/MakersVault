# Bambu saved-user machine projection — MP-1b-6

Internal Windows/Linux format support, **not production activation or native app
qualification**. The existing `discover`/`select` operations now feed direct JSON
files from the explicitly chosen `user/<account>/machine` directory to
`Catalog.AddLocalUserMachine`. Generic `Add`, `AddIndexed`, `LoadBambu` and private
`project` keep the original explicit-machine contract. A source-kind label, filename,
document marker or new wire field cannot enable saved-user parsing by itself.

## Source basis and conservative mapping

At Bambu revision `926a7192574bcb9b3a732e1ec59a46d79cb45466`, the
[writer](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Config.cpp)
emits name/from/version plus configuration values, without guaranteeing system-style
type/instantiation headers. The [user-folder dispatcher](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/PresetBundle.cpp)
loads printer and filament/process subdirectories separately. The
[preset save/load code](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp)
writes `from=User`, supports inherited differences and makes explicit false
instantiation hidden. Its broader loader also consults sidecars, filename-based
identities, defaults, substitutions and nested base profiles. MakersVault does not
copy those additional behaviors or assume its read-only projection is slicer parity.

The dedicated local-user path requires:

- A bounded actual document name, with no control/surrounding whitespace or recognized
  script-template identity; no filename-stem or alias fallback.
- A `from` string equal to user (ASCII case-insensitive). Missing, project/system,
  default or malformed values fail. Explicit `type` must be `machine`; only its
  absence is supplied by the selected machine-directory context.
- A string file-version header with three or four decimal components, each 1–5
  ASCII digits. This deliberately bounded grammar is not full SemVer support or
  application-version qualification. Suffixes, absent/null/malformed versions fail
  with `unsupported_user_version`; no inherited version fills a missing header.
- Missing instantiation permits local selection under this source contract;
  explicit false remains hidden, explicit true remains selectable, other values
  fail. Selectability is separate internal state: no missing raw header is invented
  and a hidden parent's instantiation does not suppress its saved-user child.

File version is discarded after local validation. It is never retained in the
catalog, inherited into children, hashed as a normalized layout field, promoted
to installed-app version or substituted for the selected system bundle version.
Current location scans still return empty/unobserved application version.

## Preserved boundaries and remaining limits

Parser version `bambu-projection-3` records this change; system/generic acceptance
rules, geometry normalization and public/private request schemas are unchanged.
All existing shared file/byte/time limits, held-file checks, exact namespace/parent
resolution, duplicate/cycle/depth rejection, include exclusion, redacted failures
and worker timeout/reaping remain. Missing geometry stays explicitly incomplete;
no standalone printer defaults or script/credential fields are imported.

Only direct machine JSON bodies are read. Sidecars, other accounts, general config,
filament/process folders and nested custom `machine/base` documents are not read.
If a required parent exists only in such a nested folder, the scan fails as missing
instead of supplying defaults. Nested custom-root and prerelease-version support
need separate bounded conformance evidence, not recursive fallback. A successful
scan is not a complete mirror of everything the slicer could load.

The tests are authored synthetic profiles, not copied vendor/private source bytes.
The same new public-API test fails on old `535a0a1` with the missing machine-identity
error and passes on the new implementation. Linux tests exercise real private
worker round trips; Windows/macOS cross-builds do not prove native behavior.
Real installed profiles/version evidence, native Windows/lifecycle, local choice
and consented integration are still required. Mac-local import stays owner-deferred.

Next MP-1b-7: bounded local account-choice enumeration and native location hints,
keeping all names local, no automatic account selection and no production dispatch.
Actual picker/consent and independent version observation remain explicit checkpoints.
