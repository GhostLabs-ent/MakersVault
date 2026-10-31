# Documentation images

Screenshots, diagrams and other figures that documentation embeds. One tree, organised by
topic, so that a figure used by two documents lives once and every image is reviewed in one
place.

Brand artwork is **not** here — it is generated into `docs/brand/` by `docs/brand/build.py`,
and the app's own icons come from `curiarium/web/public/`. Do not hand-edit either.

## Layout

```
docs/images/
  ui/            screenshots of the app itself (grid, settings, dialogs)
  snapshots/     snapshot browse, restore and retention behaviour
  storage/       storage capabilities, mounts, trash
  auth/          sign-in, SSO consent, sessions, MFA
  diagrams/      architecture and flow figures (SVG preferred)
```

Create the topic directory you need. Adding a new top-level topic is fine when an existing
one does not fit; use a single word, lowercase.

## Naming

`<subject>-<what-it-shows>.<ext>` — lowercase, kebab-case, no spaces, no dates, no
`-final`, no `-v2`. `library-grid-empty-state.png`, not `Screenshot 2026-10-31 at
10.42.11.png`. Names are cited by documents, so they outlive the screenshot's content: if a
figure is replaced, keep the name.

## Format and size

| Use | Format | Notes |
|---|---|---|
| App screenshots | PNG | Crop to the relevant widget, not the whole desktop |
| Same, over 400 KB | WebP | Keep the PNG only if lossless text matters |
| Diagrams and flows | SVG | Text stays selectable and the diff is readable |
| Animated demos | WebP or MP4 | Under 2 MB; do not commit long recordings |

Maximum width 1600 px. Downscale before committing — this repository is public and image
history is permanent.

## Redaction — this repository is public

Never include any of the following, in the image or in an embedded file name:

- real usernames, e-mail addresses or account IDs from anyone's deployment
- hostnames, domains, IP addresses, ports or internal network names
- the contents of a real library (file names, project names, notes, model titles)
- tokens, signed URLs, session IDs, API keys, secret names, or a filled-in password field

Screenshot a throwaway instance with fixture data, or rename and blur as needed. Crop out
browser chrome that carries a URL, and remember that a "redacted" bar over text can still
leak through selection or OCR of an unscaled original — redact before resizing.

## Referencing an image

Paths are relative to the document that embeds it, so count the directories:

| Document location | Reference |
|---|---|
| `README.md` (repo root) | `docs/images/ui/library-grid.png` |
| `docs/PERMISSIONS.md` | `images/ui/library-grid.png` |
| `curiarium/docs/ARCHITECTURE_RUNBOOK.md` | `../../docs/images/snapshots/browse-restore.png` |
| `curiarium/docs/adr/0006-*.md` | `../../../docs/images/auth/sso-consent.png` |

Always write alt text that says what the figure shows, not "screenshot":

```markdown
![The library grid, filtered to an empty folder, showing the no-results message](../images/ui/library-grid-empty-state.png)
```

Reference a figure from the text too ("see the restore dialog below") so a reader who cannot
load it knows what they are missing, and so a stale image is noticed when the prose drifts.

## Removing an image

Delete the file and every reference to it in the same commit. An orphaned figure is worse
than a missing one: nobody can tell whether it documents current behaviour.
