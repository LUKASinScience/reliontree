#!/bin/bash
# One-time install of reliontree into its own venv at a shared, versioned
# path, for an HPC admin to point a module file at. reliontree has zero
# third-party runtime dependencies, so this venv only ever contains
# reliontree itself.
#
# Usage:
#   ./install.sh /shared/apps/reliontree/0.1.0
set -euo pipefail

INSTALL_DIR="${1:?Usage: install.sh /shared/apps/reliontree/<version>}"
SOURCE="${2:-git@github.com:LUKASinScience/reliontree.git}"

python3 -m venv "$INSTALL_DIR"
"$INSTALL_DIR/bin/pip" install --upgrade pip --quiet
"$INSTALL_DIR/bin/pip" install "git+${SOURCE}"

echo
echo "Installed to: $INSTALL_DIR"
echo "Point the modulefile's install_dir at this path (see contrib/modules/README.md)."
"$INSTALL_DIR/bin/reliontree" --help >/dev/null && echo "Sanity check OK: reliontree runs."
