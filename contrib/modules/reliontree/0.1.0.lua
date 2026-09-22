help([[
reliontree — standalone RELION job-lineage viewer.
Adds the `reliontree` command to PATH (job cards, live watch view,
tree/table/methods export). No ChimeraX, no third-party server framework.
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
