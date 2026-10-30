# Curiarium Bridge

This helper registers the custom protocols `curiarium-slicer://` and
`curiarium-engrave://`, launching slicing or engraving software with the
downloaded file. It is required for the "Open in Slicer" and "Open in Engraving
Software" buttons to work across Windows and Linux clients.

Protocol formats:
`curiarium-slicer://open?url=<download-url>&slicer=<id>&filename=<name>`
`curiarium-engrave://open?url=<download-url>&engraver=<id>&filename=<name>`

The `url` parameter should be a direct HTTP(s) download link. Curiarium
already includes the auth token in that URL.

## Quick install (no shell commands)

Download the latest Bridge binary for your OS from the
[Curiarium releases](https://github.com/VincentCinque/MakersVault/releases/latest)
page and run it once. The installer registers the `curiarium-slicer://` and
`curiarium-engrave://` protocol handlers and copies the binary into a stable location:

- Windows: `%LOCALAPPDATA%\Curiarium\SlicerBridge\curiarium-slicer.exe`
- Linux: `~/.local/bin/curiarium-slicer`

If your Linux file manager blocks execution, mark the file as executable and run it once.

## Build

You need Go installed (1.21+ recommended).

Windows (PowerShell):
```powershell
cd curiarium\slicer-bridge
go build -o dist\slicer-bridge.exe .\cmd\slicer-bridge
```

Linux (bash):
```bash
cd curiarium/slicer-bridge
go build -o dist/slicer-bridge ./cmd/slicer-bridge
```

## Install (manual)

Windows (PowerShell):
```powershell
cd curiarium\slicer-bridge\scripts
.\install-windows.ps1 -BridgePath "..\dist\slicer-bridge.exe"
```

Linux (bash):
```bash
cd curiarium/slicer-bridge/scripts
./install-linux.sh ../dist/slicer-bridge
```

You can also run the binary directly:
`slicer-bridge --install`

If your shell blocks scripts, set the execution policy for the current user:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Config

Create a config file if you want custom slicer or engraver paths or arguments:

Windows: `%APPDATA%\curiarium-slicer\config.json`
Linux: `~/.config/curiarium-slicer/config.json`

Use `config.example.json` as a template.

Environment override (per slicer):
`CURIARIUM_SLICER_ORCA=C:\Path\To\OrcaSlicer.exe`

Environment override (per engraver):
`CURIARIUM_ENGRAVER_LIGHTBURN=C:\Path\To\LightBurn.exe`

## Slicer IDs

- orca
- bambu
- prusa
- superslicer
- cura
- ideamaker
- simplify3d
- kisslicer
- repetier
- chitubox
- lychee
- photon
- creality
- other (opens with OS default)

## Engraver IDs

- lightburn
- ezcad
- other (opens with OS default)

## Testing

After install, paste this into your browser (replace URL):
`curiarium-slicer://open?url=https://example.com/model.stl&slicer=orca&filename=model.stl`
`curiarium-engrave://open?url=https://example.com/design.svg&engraver=lightburn&filename=design.svg`

## Logs

Log file location:
Windows: `%APPDATA%\curiarium-slicer\bridge.log`
Linux: `~/.config/curiarium-slicer/bridge.log`

## Notes

- The bridge downloads files into the user cache directory unless configured.
- If an app is not found, the file opens with the OS default app.
