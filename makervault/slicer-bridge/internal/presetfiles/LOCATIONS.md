# Bambu location planning/inspection — MP-1b-4

Internal foundation only; the production bridge does not dispatch it. No profile
is imported, no installation/account is automatically selected, and no real
workstation configuration was read to implement or test this slice.

## Pure planning versus bounded observation

`PlanBambuLocations` accepts local-only hints supplied by a future consented caller:
Windows roaming application-data directory, or Linux XDG configuration directory
(home/.config only when XDG is absent), or one expressly chosen custom data root.
It returns unobserved `BambuStudio`, `BambuStudioBeta` and `BambuStudioInternal`
directory candidates. IDs are location labels, **not** observed release channels,
installation presence, application versions or ownership. A custom root replaces
the candidate plan; invalid selected hints fail without a fallback search.

No environment, filesystem, executable, registry, Flatpak/AppImage installation,
cloud account, general configuration or version command is probed by the planner.
Packaging-specific and nonstandard roots need explicit local choice. Supplying
hints does not grant consent; JSON cannot deserialize paths into the public types.
[Native hint acquisition](ACCOUNTS.md) is now implemented separately, without
existence checks or automatic selection. Its native Windows/lifecycle qualification
and actual server/launcher integration remain open. The inactive [local selection/
consent foundation](../presetconsent/README.md) now exists; it does not activate import.

`InspectBambuLocation` takes one locally selected **data root**, not an install or
resource root. Its fixed paths are:

- `system/BBL.json`: the bounded manifest index;
- `system/BBL/machine`: verify this directory without listing/reading its profiles;
- `user/<explicit-account>/machine`: optional direct ordinary JSON filename index.

Empty account explicitly requests system-only inspection. It does not mean
`default`, the first folder found or the logged-in cloud account. A selected
missing/unreadable account fails the whole operation; no fallback or partial system
result escapes. [Account enumeration](ACCOUNTS.md) is now a separate bounded local
operation, not automatic selection; the new local selection handler is unmounted. Directory
names and roots are absent from the result; successful filenames/labels are still
potentially private and must remain local until the later explicit review contract.

All children open relative to held parents. Linux keeps `NO_XDEV` below the original
root, including same-device directory bind mounts. Windows uses existing relative
NTFS/reparse/volume checks. The original root and all opened ancestors remain held
through final change checks. No joined absolute child is promoted to a new root.
Windows behavior still requires native execution; this is not a new qualification
of its syscall/filter/placeholder or lifecycle semantics.

One 15-second context covers the whole inspection. Manifest entries plus **all**
selected user-directory entries (including ignored non-JSON files) share 10,000.
Only one bounded manifest is read (8 MiB), so this operation cannot consume the
128-MiB aggregate content budget. Profile-content discovery must extend the shared
accounting when added, not chain separately reset scans. The isolated worker retains
its 2-MiB response limit and all-or-nothing framing; direct APIs remain cooperative.
Directory change checks are not an atomic snapshot or protection against privileged
local tampering. This inspection never reads profile bodies, template includes or
URLs; listed user JSON children receive only confined metadata inspection.

The result's application version is explicitly empty/unobserved. It is not filled
from a directory label, manifest bundle version, saved config version or owner report.
[Content discovery](DISCOVERY.md) now extends this held ancestry to actual machine
identities, parent closure and [saved-user machine context](SAVED_USER.md).
Installed version observations, native qualification and matched consented activation
are still required; the inspection-only operation remains an index, not that scan.

New Mac preset discovery/import/refresh stays owner-deferred; both planning and
location inspection refuse macOS, including the old reader experiment. Existing
Mac file-open and planned browser use of saved presets remain unchanged.

## Pinned primary source review

Bambu revision `926a7192574bcb9b3a732e1ec59a46d79cb45466` supplies:

- [Application key](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/version.inc): `BambuStudio`.
- [GUI data-root logic](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/GUI_App.cpp): platform user data, Linux XDG/home fallback, explicit data-root override and compile-time Beta/Internal suffixes.
- [Directory constants](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.hpp): system/user/machine names.
- [Preset loading](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/PresetBundle.cpp): separate system/vendor and chosen user-folder loading. Its active selection uses general settings; MakersVault does not read those here.

These are reviewed format facts, not retained byte-hashed vendor fixtures or proof
about the owner's reported Windows Bambu Studio v2.8.0.6 installation.
