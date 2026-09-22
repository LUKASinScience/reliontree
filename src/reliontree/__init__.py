"""reliontree — standalone RELION job-lineage viewer.

Ported from the Qt/ChimeraX-free core of the ChimeraX-InstantMap plugin's
RELION History tab (relion_pipeline/relion_artifacts/relion_treebuild/
relion_tree_layout/relion_export/relion_methods). Pure stdlib.

Usable as a library, not just the `reliontree` CLI:

    import reliontree

    project = reliontree.find_project(".")       # or a specific path
    tree = reliontree.build_tree(project)
    html = reliontree.render_html(tree, title=str(project))

    rows = reliontree.history_rows(
        reliontree.ordered_jobs(tree), tree["artifacts"], tree["parents"], tree["stats"],
    )
    csv_text = reliontree.rows_to_csv(rows)
"""

from .relion_project import ProjectNotFoundError, find_project
from .relion_export import history_rows, rows_to_csv, rows_to_markdown
from .relion_methods import draft_methods_paragraph
from .relion_treebuild import build_tree, ordered_jobs, render_svg
from .render_html import render_html

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "find_project",
    "ProjectNotFoundError",
    "build_tree",
    "ordered_jobs",
    "render_svg",
    "render_html",
    "history_rows",
    "rows_to_csv",
    "rows_to_markdown",
    "draft_methods_paragraph",
]
