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


DIFF_PIPELINE_STAR = """
data_pipeline_general

data_pipeline_processes

loop_
_rlnPipeLineProcessName #1
_rlnPipeLineProcessAlias #2
_rlnPipeLineProcessTypeLabel #3
_rlnPipeLineProcessStatusLabel #4
Import/job001/ None relion.import.movies Scheduled
Class3D/job002/ None relion.class3d Scheduled
Class3D/job003/ None relion.class3d Scheduled

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
Import/job001/movies.star Class3D/job003/

data_pipeline_output_edges

loop_
_rlnPipeLineEdgeProcess #1
_rlnPipeLineEdgeToNode #2
Import/job001/ Import/job001/movies.star
"""

JOB_STAR_TEMPLATE = """
data_joboptions_values

loop_
_rlnJobOptionVariable #1
_rlnJobOptionValue #2
tau_fudge {tau_fudge}
sym_name {sym_name}
"""


def _make_diff_project(tmp_path: Path) -> Path:
    """Two sibling Class3D jobs (same type, same parent) with different
    job.star options — enough to exercise `diff`/`why` meaningfully."""
    project = tmp_path / "relion_project"
    project.mkdir()
    (project / "default_pipeline.star").write_text(DIFF_PIPELINE_STAR, encoding="utf-8")
    for job in ("Import/job001", "Class3D/job002", "Class3D/job003"):
        (project / job).mkdir(parents=True)
        (project / job / "RELION_JOB_EXIT_SUCCESS").write_text("", encoding="utf-8")
    (project / "Class3D/job002/job.star").write_text(
        JOB_STAR_TEMPLATE.format(tau_fudge=4, sym_name="C1"), encoding="utf-8")
    (project / "Class3D/job003/job.star").write_text(
        JOB_STAR_TEMPLATE.format(tau_fudge=2, sym_name="C1"), encoding="utf-8")
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


def test_diff_two_jobs(tmp_path):
    project = _make_diff_project(tmp_path)
    result = _run("diff", str(project), "--job", "Class3D/job002", "--job", "Class3D/job003",
                  "--format", "json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["changed"]["tau_fudge"] == ["4", "2"]
    assert data["unchanged"]["sym_name"] == "C1"


def test_why_same_type_parent_diffs(tmp_path):
    project = _make_diff_project(tmp_path)
    # Class3D/job003 shares its Import parent with Class3D/job002 (a
    # different type), so job_context should report no comparable parent —
    # there's no same-type Class3D parent here to diff against.
    result = _run("why", str(project), "--job", "Class3D/job003", "--format", "json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["parents"] == ["Import/job001"]
    assert "Class3D/job002" in data["siblings"]
    assert data["diff_from_parent"] is None


def test_zero_config_no_project_starts_picker(tmp_path):
    """With no default_pipeline.star anywhere above cwd, zero-config
    `reliontree` no longer exits with an error — it starts the watch
    server anyway with a bare directory-picker start screen, so there's
    always something to click through to a project."""
    import socket
    with socket.socket() as sock:  # a free port, so a `watch` already running on 8710 can't break the test
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "reliontree.cli"],
        cwd=str(tmp_path),
        # BROWSER=true: a no-op "browser" so webbrowser.open() returns
        # instantly instead of hanging while it hunts for a real one in
        # this headless/sandboxed test environment.
        env={"PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"), "BROWSER": "true", "RELIONTREE_PORT": str(port)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        body = None
        deadline = time.time() + 90        # a loaded CI runner needs far longer than a laptop to start Python
        while time.time() < deadline and proc.poll() is None:
            try:
                body = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=2).read().decode()
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                time.sleep(0.2)
        if body is None:
            proc.terminate()
            _out, err = proc.communicate(timeout=10)
            raise AssertionError("server never came up (exit %s): %s" % (proc.returncode, err[-1500:]))
        assert "no RELION project selected yet" in body
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_compare_json_and_text(tmp_path):
    project = _make_diff_project(tmp_path)
    for n in ("run_it010_class001.mrc", "run_it010_class002.mrc"):
        (project / "Class3D/job002" / n).write_bytes(b"x")
    r = _run("compare", str(project), "--job", "Class3D/job002", "--job", "Class3D/job003", "--format", "json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert [j["job"] for j in d["jobs"]] == ["Class3D/job002", "Class3D/job003"]
    assert d["options"]["changed"]["tau_fudge"] == ["4", "2"]
    assert d["jobs"][0]["maps"][0]["label"].startswith("All 2 classes") and d["jobs"][1]["maps"] == []
    t = _run("compare", str(project), "--job", "Class3D/job002", "--job", "Class3D/job003")
    assert t.returncode == 0 and "tau_fudge" in t.stdout and "Changed options" in t.stdout
    assert _run("compare", str(project), "--job", "Class3D/job002", "--job", "Nope/job9").returncode == 2


def test_maps_and_open_refuse_bad_input(tmp_path):
    project = _make_diff_project(tmp_path)
    (project / "Class3D/job002" / "run_class001.mrc").write_bytes(b"x")
    m = _run("maps", str(project), "--job", "Class3D/job002", "--format", "json")
    assert m.returncode == 0 and json.loads(m.stdout)["maps"][0]["files"] == ["run_class001.mrc"]
    assert _run("maps", str(project), "--job", "../../etc").returncode == 2
    assert _run("open", str(project), "--job", "Class3D/job003").returncode == 2           # no maps in that job
    assert _run("open", str(project), "--job", "Class3D/job002", "--map", "zzz").returncode == 2


def test_open_queues_with_template(tmp_path, monkeypatch):
    from reliontree import chimerax_bridge, cli
    project = _make_diff_project(tmp_path)
    for n in ("run_class001.mrc", "mask.mrc"):
        (project / "Class3D/job002" / n).write_bytes(b"x")
    seen = {}
    monkeypatch.setattr(chimerax_bridge, "open_files", lambda paths, tile=False, style=None: seen.update(
        files=[p.name for p in paths], tile=tile, style=style) or "queued")
    cli.main(["open", str(project), "--job", "Class3D/job002", "--map", "mask", "--template", "Mask overlay"])
    assert seen == {"files": ["mask.mrc"], "tile": False, "style": "Mask overlay"}


def test_settings_command_roundtrip(tmp_path, monkeypatch, capsys):
    from reliontree import chimerax_bridge, cli
    monkeypatch.setattr(chimerax_bridge, "HOME_DIR", tmp_path)
    monkeypatch.setattr(chimerax_bridge, "SETTINGS_FILE", tmp_path / "settings.json")
    cli.main(["settings", "--chimerax", "cx", "--run-first", "module load chimerax", "--template", "Mask overlay"])
    out = json.loads(capsys.readouterr().out)
    assert out["settings"] == {"chimerax_cmd": "cx", "prelaunch": "module load chimerax", "figure_template": "Mask overlay"}


def _run_cli(*argv, **kw):
    import subprocess, sys
    return subprocess.run([sys.executable, "-c", "import sys; from reliontree.cli import main; main(sys.argv[1:])", *argv],
                          capture_output=True, text=True, timeout=60, **kw)


def test_missing_or_broken_project_is_an_error_but_empty_project_is_fine(tmp_path):
    for sub in ("tree", "table", "methods"):
        r = _run_cli(sub, str(tmp_path))                                  # no default_pipeline.star
        assert r.returncode == 1 and "no RELION project found" in r.stderr and not r.stdout.strip()
    star = tmp_path / "default_pipeline.star"
    for content in ("", "data_pipeline_general\n_rlnPipeLineJobCounter 1", "\x00\xff garbage"):     # empty, cut off mid-line, not a STAR file
        star.write_text(content)
        r = _run_cli("tree", str(tmp_path))
        assert r.returncode == 2 and "reliontree:" in r.stderr, content
    star.write_text("data_pipeline_general\n_rlnPipeLineJobCounter 1\n")    # valid, just no jobs yet: empty output is correct
    assert _run_cli("tree", str(tmp_path)).returncode == 0


def test_real_relion_pipeline_file_layout_is_accepted(tmp_path):
    # Real files (RELION 3/4/5) start with a blank line + "# version NNNNN" and end with a space, not a newline
    star = "\n# version 50001\n\ndata_pipeline_general\n\n_rlnPipeLineJobCounter                       1\n \n"[:-1]
    assert not star.startswith("data_") and not star.endswith("\n")
    (tmp_path / "default_pipeline.star").write_text(star)
    r = _run_cli("tree", str(tmp_path))
    assert r.returncode == 0 and not r.stderr.strip(), r.stderr


def test_maps_unknown_job_exits_2(tmp_path):
    (tmp_path / "default_pipeline.star").write_text("data_pipeline_general\n_rlnPipeLineJobCounter 1\n")
    r = _run_cli("maps", str(tmp_path), "--job", "nosuch/job9")
    assert r.returncode == 2 and "not found" in r.stderr


def test_watch_ctrl_c_exits_cleanly(tmp_path):
    import signal, socket, subprocess, sys, time
    (tmp_path / "default_pipeline.star").write_text("data_pipeline_general\n_rlnPipeLineJobCounter 1\n")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    p = subprocess.Popen([sys.executable, "-c", "import sys; from reliontree.cli import main; main(sys.argv[1:])", "watch", str(tmp_path),
                          "--port", str(port), "--no-open"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 60
    while True:                                                           # wait until the server listens
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            assert p.poll() is None and time.time() < deadline
            time.sleep(0.2)
    p.send_signal(signal.SIGINT)
    _, err = p.communicate(timeout=30)
    assert p.returncode == 0 and "Traceback" not in err
