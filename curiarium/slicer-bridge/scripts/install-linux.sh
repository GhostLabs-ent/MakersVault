#!/usr/bin/env sh
set -e

BIN_SOURCE="${1:-}"
if [ -z "$BIN_SOURCE" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  BIN_SOURCE="$SCRIPT_DIR/../dist/slicer-bridge"
fi

if [ ! -f "$BIN_SOURCE" ]; then
  echo "Binary not found: $BIN_SOURCE"
  exit 1
fi

INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"
BIN_TARGET="$INSTALL_DIR/curiarium-slicer"
install -m 755 "$BIN_SOURCE" "$BIN_TARGET"

DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"
DESKTOP_FILE="$DESKTOP_DIR/curiarium-slicer.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Curiarium Bridge
Exec=$BIN_TARGET %u
Type=Application
Terminal=false
MimeType=x-scheme-handler/curiarium-slicer;x-scheme-handler/curiarium-engrave;
EOF

xdg-mime default curiarium-slicer.desktop x-scheme-handler/curiarium-slicer >/dev/null 2>&1 || true
xdg-mime default curiarium-slicer.desktop x-scheme-handler/curiarium-engrave >/dev/null 2>&1 || true

echo "Installed protocol handler at $BIN_TARGET"
