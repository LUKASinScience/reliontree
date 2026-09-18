"""Smoke test: build a minimal fake RELION project on disk and drive the
real CLI entry points against it (text/json/svg/html/table/methods),
asserting each produces the expected content. No mocks — real filesystem,
real parser."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PIPELINE_STAR = """
data_pipeline_general

data_pipeline_processes

loop_
_rlnPipeLineProcessName #1
_rlnPipeLineProcessAlias #2
_rlnPipeLineProcessTypeLabel #3
_rlnPipeLineProcessStatusLabel #4
Import/job001/ None relion.import.movies Scheduled
Class3D/job002/ None relion.class3d Scheduled

data_pipeline_nodes

loop_
_rlnPipeLineNodeName #1
_rlnPipeLineNodeTypeLabel #2
Import/job001/movies.star relion.movies

data_pipeline_input_edges

loop_
_rlnPipeLineEdgeFromNode #1
_rlnPipeLineEdgeProcess #2
Import/job001/movies.star Class3D/job002/

data_pipeline_output_edges

loop_
_rlnPipeLineEdgeProcess #1
_rlnPipeLineEdgeToNode #2
Import/job001/ Import/job001/movies.star
"""


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "relion_project"
    project.mkdir()
    (project / "default_pipeline.star").write_text(PIPELINE_STAR, encoding="utf-8")
    for job in ("Import/job001", "Class3D/job002"):
        (project / job).mkdir(parents=True)
        (project / job / "RELION_JOB_EXIT_SUCCESS").write_text("", encoding="utf-8")
    return project


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "reliontree.cli", *args],
        cwd=str(Path(__file__).resolve().parent.parent / "src"),
        capture_output=True, text=True,
    )


def test_tree_text(tmp_path):
    project = _make_project(tmp_path)
    result = _run("tree", str(project), "--format", "text")
    assert result.returncode == 0, result.stderr
    assert "Import/job001" in result.stdout
    assert "Class3D/job002" in result.stdout
    assert "[succeeded]" in result.stdout


def test_tree_json(tmp_path):
    project = _make_project(tmp_path)
    result = _run("tree", str(project), "--format", "json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert set(data["jobs"]) == {"Import/job001", "Class3D/job002"}
    assert data["parents"]["Class3D/job002"] == ["Import/job001"]


def test_tree_html_writes_file(tmp_path):
    project = _make_project(tmp_path)
    out = tmp_path / "tree.html"
    result = _run("tree", str(project), "--format", "html", "-o", str(out))
    assert result.returncode == 0, result.stderr
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "Import/job001" in html


def test_table_csv(tmp_path):
    project = _make_project(tmp_path)
    result = _run("table", str(project), "--format", "csv")
    assert result.returncode == 0, result.stderr
    assert "Import/job001" in result.stdout
    assert "Class3D/job002" in result.stdout


def test_unknown_job_exits_2(tmp_path):
    project = _make_project(tmp_path)
    result = _run("tree", str(project), "--job", "Refine3D/job999")
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_zero_config_no_project_starts_picker(tmp_path):
    """With no default_pipeline.star anywhere above cwd, zero-config
    `reliontree` no longer exits with an error — it starts the watch
    server anyway with a bare directory-picker start screen, so there's
    always something to click through to a project."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "reliontree.cli"],
        cwd=str(tmp_path),
        # BROWSER=true: a no-op "browser" so webbrowser.open() returns
        # instantly instead of hanging while it hunts for a real one in
        # this headless/sandboxed test environment.
        env={"PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"), "BROWSER": "true"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        body = None
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                body = urllib.request.urlopen("http://127.0.0.1:8710/", timeout=0.5).read().decode()
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                time.sleep(0.1)
        assert body is not None, "server never came up"
        assert "no RELION project selected yet" in body
    finally:
        proc.terminate()
        proc.wait(timeout=5)
