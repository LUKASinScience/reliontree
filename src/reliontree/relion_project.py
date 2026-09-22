"""Project discovery — split out of cli.py so the library API (__init__.py)
doesn't have to import cli.py itself (which would make `python -m
reliontree.cli` re-import its own already-partially-loaded module and warn
about it). Pure stdlib."""

from pathlib import Path


class ProjectNotFoundError(Exception):
    pass


def find_project(start=None):
    """Walk upward from `start` (default: cwd) looking for
    `default_pipeline.star`, the same way `git status` finds its repo."""
    p = Path(start or ".").resolve()
    for candidate in (p, *p.parents):
        if (candidate / "default_pipeline.star").is_file():
            return candidate
    raise ProjectNotFoundError(
        "no RELION project found (no default_pipeline.star in %s or any parent directory)" % p
    )
