# PyInstaller entry point for the desktop app's sidecar (cli.py uses relative imports, so it cannot be the script itself).
from reliontree.cli import main

main()
