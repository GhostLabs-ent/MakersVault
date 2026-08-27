# MakerVault Bridge

The bridge registers `makersvault-slicer://`, `makersvault-engrave://`, and
`makersvault-open://`, redeems a short-lived exact-file grant from a paired
MakersVault origin, and launches the selected local application.

The bridge no longer accepts arbitrary download URLs or administrator session
tokens. It follows no download redirects, limits each file to 512 MiB by
default, and never falls back to the operating-system default file opener.

## Install

Download the v5.1 bridge binary for your OS from the
[MakerVault releases](https://github.com/VincentCinque/MakersVault/releases/latest)
page and run it once. The installer copies the binary to a stable location and
registers all protocol handlers:

- Windows: `%LOCALAPPDATA%\MakersVault\SlicerBridge\makersvault-slicer.exe`
- Linux: `~/.local/bin/makersvault-slicer`
- macOS: `~/Applications/MakerVault Bridge.app`

If a Linux file manager blocks execution, mark the binary executable and run it
once.

## First handoff from an origin

The first Open in Slicer or Open in Engraving Software request from a
MakersVault API origin opens a local confirmation page in your browser. Confirm
only the exact MakersVault address you intended to use. The bridge stores that
origin in its local config; later handoffs from it remain one click.

An HTTP origin is labeled as unencrypted and should be trusted only on a network
you control. Remote MakersVault deployments should use HTTPS.

Each handoff grant:

- expires after 90 seconds;
- authorizes one exact current primary, historical primary, supporting, or
  prepared file;
- is bound to the requested legacy tool or to one adapter and content role; and
- cannot sign in to MakersVault or authorize another API route.

If confirmation takes long enough for the first grant to expire, the origin is
still paired; click Open in Slicer/Engraving again to receive a fresh grant.

## Build

Go 1.26 or newer is required.

Windows:

```powershell
cd makervault\slicer-bridge
go build -o dist\slicer-bridge.exe .\cmd\slicer-bridge
```

Linux:

```bash
cd makervault/slicer-bridge
go build -o dist/slicer-bridge ./cmd/slicer-bridge
```

macOS (Apple silicon shown; use `GOARCH=amd64` for Intel):

```bash
cd makervault/slicer-bridge
GOOS=darwin GOARCH=arm64 go build -o dist/slicer-bridge-darwin-arm64 ./cmd/slicer-bridge
```

Manual install remains available through `slicer-bridge --install` or the
scripts in `scripts/`.

The macOS bundle is user-local and can be unregistered and removed with
`slicer-bridge --uninstall`. No administrator privileges are required.

## Configuration

Config location:

- Windows: `%APPDATA%\makersvault-slicer\config.json`
- Linux: `~/.config/makersvault-slicer/config.json`
- macOS: `~/Library/Application Support/makersvault-slicer/config.json`

`config.example.json` documents these optional settings:

- `version`: adapter configuration contract; current value `1`. Omitted means the
  compatible v5.1 shape.
- `download_dir`: cache/download directory.
- `log_file`: bridge log path.
- `trusted_origins`: exact origins confirmed on this computer.
- `max_download_mb`: bridge-side file ceiling; default 512.
- `slicers` / `engravers`: locally trusted custom command definitions.
- `adapters`: versioned advanced local adapters. Each uses an absolute executable,
  fixed literal arguments with exactly one standalone `{file}` argument, bounded
  content roles/extensions, and an explicit `enabled` value. Invalid or future
  configuration fails closed without running a command.

Environment command overrides remain supported, for example:
`MAKERVAULT_SLICER_ORCA=/path/to/orca-slicer`.

## Built-in application IDs

Slicers: `orca`, `bambu`, `prusa`, `superslicer`, `cura`, `ideamaker`,
`simplify3d`, `kisslicer`, `repetier`, `chitubox`, `lychee`, `photon`, and
`creality`.

Engravers: `lightburn` and `ezcad`.

General Gate 8 catalog entries: `freecad` and `inkscape`. The legacy protocols do
not invoke these entries. The `makersvault-open://` flow binds the selected
adapter and content role through browser URL, grant, redemption headers, extension
check, and local launch.

If the selected application cannot be found, the bridge records an actionable
error in its log and does not download or open the file. Custom applications
must be explicitly configured locally.

## Logs

- Windows: `%APPDATA%\makersvault-slicer\bridge.log`
- Linux: `~/.config/makersvault-slicer/bridge.log`
- macOS: `~/Library/Application Support/makersvault-slicer/bridge.log`

Grant values are redacted from bridge logs.

## Local diagnostics and trust revocation

The bridge exposes local-only diagnostics; none contacts MakersVault or reveals a
configured command path/argument:

```text
makersvault-slicer list
makersvault-slicer doctor
makersvault-slicer trust list
makersvault-slicer trust revoke https://vault.example
```

`list` reports embedded catalog version, adapter identity, source, and
installed/unavailable status. `doctor` validates the catalog, local adapter shape,
and trusted origins. Revoking an exact origin takes effect for the next request and
does not delete MakersVault data or already downloaded files.
