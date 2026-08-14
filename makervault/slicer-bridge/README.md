# MakerVault Bridge

The v5.1 bridge registers `makersvault-slicer://` and
`makersvault-engrave://`, redeems a short-lived file grant from a paired
MakersVault origin, and launches the selected slicing or engraving application.

The bridge no longer accepts arbitrary download URLs or administrator session
tokens. It follows no download redirects, limits each file to 512 MiB by
default, and never falls back to the operating-system default file opener.

## Install

Download the v5.1 bridge binary for your OS from the
[MakerVault releases](https://github.com/VincentCinque/MakersVault/releases/latest)
page and run it once. The installer copies the binary to a stable location and
registers both protocol handlers:

- Windows: `%LOCALAPPDATA%\MakersVault\SlicerBridge\makersvault-slicer.exe`
- Linux: `~/.local/bin/makersvault-slicer`

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
- authorizes one exact primary or prepared file;
- is valid only for slicing or engraving, never both; and
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

Manual install remains available through `slicer-bridge --install` or the
scripts in `scripts/`.

## Configuration

Config location:

- Windows: `%APPDATA%\makersvault-slicer\config.json`
- Linux: `~/.config/makersvault-slicer/config.json`

`config.example.json` documents these optional settings:

- `download_dir`: cache/download directory.
- `log_file`: bridge log path.
- `trusted_origins`: exact origins confirmed on this computer.
- `max_download_mb`: bridge-side file ceiling; default 512.
- `slicers` / `engravers`: locally trusted custom command definitions.

Environment command overrides remain supported, for example:
`MAKERVAULT_SLICER_ORCA=/path/to/orca-slicer`.

## Built-in application IDs

Slicers: `orca`, `bambu`, `prusa`, `superslicer`, `cura`, `ideamaker`,
`simplify3d`, `kisslicer`, `repetier`, `chitubox`, `lychee`, `photon`, and
`creality`.

Engravers: `lightburn` and `ezcad`.

If the selected application cannot be found, the bridge records an actionable
error in its log and does not download or open the file. Custom applications
must be explicitly configured locally.

## Logs

- Windows: `%APPDATA%\makersvault-slicer\bridge.log`
- Linux: `~/.config/makersvault-slicer/bridge.log`

Grant values are redacted from bridge logs.
