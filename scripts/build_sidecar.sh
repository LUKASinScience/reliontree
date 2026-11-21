#!/usr/bin/env bash
# Freeze reliontree into ONE executable for the desktop app's local mode (Tauri externalBin):
#   desktop/src-tauri/binaries/reliontree-cli-<target-triple>[.exe]
# macOS, Linux, and Windows under Git Bash (GitHub's windows runners have it). Needs Python 3.9+ with
# PyInstaller (pip install pyinstaller) and rustc (for the target triple). Set PYTHON to pick the interpreter.
#
# --onefile, not --onedir: externalBin ships exactly one file per target and Tauri places it next to the app's own
# binary; a onedir folder (exe + _internal/) does not fit that. Cost: the bootloader unpacks to a temp folder on
# every start (about a second) and runs Python as a child process, so the app stops it with SIGTERM (forwarded by
# the bootloader) on macOS/Linux and `taskkill /T` (whole tree) on Windows, never a bare kill.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
EXT=""
case "$TRIPLE" in *windows*) EXT=".exe" ;; esac

mkdir -p build/sidecar desktop/src-tauri/binaries
# run from build/sidecar so the .spec and every relative path below agree (no absolute paths: Git Bash vs Windows)
(cd build/sidecar && "$PY" -m PyInstaller --onefile --noconfirm --clean --name reliontree-cli \
    --paths ../../src \
    --add-data "../../src/reliontree/chimerax_listener.py:reliontree" \
    --distpath dist --workpath work \
    ../../scripts/sidecar_entry.py)
cp "build/sidecar/dist/reliontree-cli$EXT" "desktop/src-tauri/binaries/reliontree-cli-$TRIPLE$EXT"
"desktop/src-tauri/binaries/reliontree-cli-$TRIPLE$EXT" --version
ls -l "desktop/src-tauri/binaries/reliontree-cli-$TRIPLE$EXT"
