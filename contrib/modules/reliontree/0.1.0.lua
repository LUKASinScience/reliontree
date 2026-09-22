help([[
reliontree — standalone RELION job-lineage viewer.
No ChimeraX, no third-party server framework, no GUI toolkit.

This module only adds the `reliontree` command to PATH — every subcommand
and option works exactly as documented at
https://github.com/LUKASinScience/reliontree, nothing cluster-specific.

Usage:
  cd /path/to/your/relion_project
  reliontree                          zero-config: opens the live view
  reliontree tree . --format json     machine-readable job graph
  reliontree table . --format csv     job history as a table
  reliontree watch . --port 8710      live view with explicit options

See `reliontree --help` (and `reliontree <subcommand> --help`) once loaded.
]])

whatis("Name: reliontree")
whatis("Version: 0.1.0")
whatis("Description: Standalone RELION job-lineage viewer")
whatis("URL: https://github.com/LUKASinScience/reliontree")

-- Edit this to wherever contrib/modules/install.sh installed reliontree's
-- venv on this cluster (one shared install, used by everyone loading this
-- module — not a per-user install).
local install_dir = "/path/to/shared/apps/reliontree/0.1.0" -- <-- edit for your site

prepend_path("PATH", pathJoin(install_dir, "bin"))
