# Bambu content discovery — MP-1b-5 / MP-1b-6

Internal Windows/Linux foundation, **inactive in the production executable**.
`DiscoverBambu` inspects one locally selected data root and optional explicit
account, binds every non-script manifest identity to its document's actual name,
and validates all loaded machine parent chains before returning sorted kind/name
choices. Names never become filenames. No alias, case-insensitive parent match,
filename stem, active account or owned/online printer is guessed.

`SelectBambu` repeats the full bounded scan and projects up to 100 unique exact
choices in requested order. Prior discovery is not a snapshot or permission to
trust changed files. Missing or unsupported geometry remains an incomplete review
candidate with reasons; discovery choices alone are not geometry-complete presets.
Any file, identity, schema, graph or selection failure returns no partial result.

## Scope and boundaries

- One held ancestry covers manifest, machine files, optional user listing and
  final directory-change checks. It never reopens child directories as new roots.
  The existing Linux mount/link/special-file policy and Windows NTFS policy remain.
- Only manifest-listed system machine documents and direct JSON children of the
  chosen user machine directory are parsed. No general settings, other accounts,
  unlisted system files, executable/version probe, URLs or script includes.
- Recognized G-code-template manifest names are **excluded before any file open**.
  Their count is reported locally; their contents/identities are deliberately not
  inspected or qualified. A layout parent that refers to an excluded template
  fails as missing. Exclusion never authorizes an include or supplies geometry.
- System inheritance stays in system scope. A user parent found in both selected
  user and system scopes is ambiguous and rejected, not assigned precedence.
  Every loaded chain, including hidden machines, is checked for missing parents,
  cycles, depth and unsupported includes. Unsupported bundles fail as a whole.
- One 15-second context and catalog cover traversal, reads, graph and projection.
  The 10,000 ceiling conservatively charges the fixed manifest, all its entries
  (including excluded templates), and all user-directory entries including ignored
  non-JSON entries. Content reads share 8 MiB/file and 128 MiB total, with the usual
  one-byte overflow detection probe. No reset between system/user/index reads.
- Private `discover`/`select` worker operations retain 4-MiB input, 2-MiB output,
  parent timeout/reaping and atomic failure controls. Direct functions remain
  cooperative; the future UI must use the supervisor, not fall back to direct I/O.
- Root/account/filenames are absent from discoveries and normalized candidates.
  Labels may contain private user-authored text and still require visible consent.
  Application version stays empty; bundle version is never an installed version.
- Change checks are not an atomic multi-file snapshot or a privileged-local-attacker
  sandbox. Selection rereads and future immutable review/digest binding remain needed.

## Format boundary and next checkpoint

The system and generic readers keep the **explicit machine-document schema**: `type` must
be `machine`, and only explicit true instantiation becomes a choice. False/missing
instantiation is counted as hidden, malformed instantiation fails. Source JSON now
rejects case-aliased headers/duplicates and non-ASCII keys (`bambu-projection-2`).
No geometry defaults or general slicer merge/substitution engine was added.

The pinned Bambu [system profile](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL/machine/Bambu%20Lab%20P1S%200.4%20nozzle.json)
has explicit machine/instantiation headers and exact inheritance. Its
[template](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL/machine/Bambu%20Lab%20A1%200.4%20nozzle%20template%20machine_start_gcode.json)
is non-instantiated and lacks a machine type. The
[vendor loader](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/PresetBundle.cpp)
distinguishes templates and combines configurations more broadly than this adapter.

Importantly, the [saved-user writer](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Config.cpp)
writes name/from/version plus config values; it does not guarantee system-style
type/instantiation headers. MP-1b-6 adds a [dedicated saved-user reader](SAVED_USER.md)
from the selected machine-directory context, requiring user/version headers and
preserving explicit hidden settings. Generic/system parsing is not relaxed; file
versions are not installed-app observations. Parser version is now `bambu-projection-3`.
Direct saved-user files are supported under that bounded contract, not nested custom
base profiles, arbitrary version suffixes or complete installed-slicer conformance.

These primary-source observations are not byte-hashed vendor fixtures or native
qualification of the owner's reported Bambu Studio v2.8.0.6. Native root hints,
account enumeration/local selector, real profile/version evidence, Windows reader/
lifecycle qualification and matched consented activation remain open. New Mac-local
import stays owner-deferred; existing Mac file-open/browser scope is unchanged.
