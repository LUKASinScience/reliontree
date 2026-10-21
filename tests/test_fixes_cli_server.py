"""Aliases, --job spelling, --max-hops, 'missing' jobs, HTTP errors and MCP argument checks (found on two real projects)."""
import http.client
import json
import socket

import pytest

from reliontree import start_background
from reliontree.cli import main
from reliontree import mcp_server

PIPE = """data_pipeline_processes

loop_
_rlnPipeLineProcessName #1
_rlnPipeLineProcessAlias #2
_rlnPipeLineProcessTypeLabel #3
_rlnPipeLineProcessStatusLabel #4
Import/job001/ Import/first_import/ relion.import.movies Succeeded
Class3D/job002/ Class3D/junk_out/ relion.class3d Succeeded
Class3D/job003/ None relion.class3d Succeeded

data_pipeline_input_edges

loop_
_rlnPipeLineEdgeFromNode #1
_rlnPipeLineEdgeProcess #2
Import/job001/movies.star Class3D/job002/
Class3D/job002/run_it001_data.star Class3D/job003/

data_pipeline_output_edges

loop_
_rlnPipeLineEdgeProcess #1
_rlnPipeLineEdgeToNode #2
Import/job001/ Import/job001/movies.star
Class3D/job002/ Class3D/job002/run_it001_data.star
Class3D/job003/ Class3D/job003/run_it001_data.star
"""
JOBSTAR = "data_job\n\nloop_\n_rlnJobOptionVariable #1\n_rlnJobOptionValue #2\nnr_classes %s\n"


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "default_pipeline.star").write_text(PIPE)
    for j, n in (("Import/job001", 1), ("Class3D/job002", 3)):          # job003 stays missing on disk
        (tmp_path / j).mkdir(parents=True)
        (tmp_path / j / "RELION_JOB_EXIT_SUCCESS").write_text("")
        (tmp_path / j / "job.star").write_text(JOBSTAR % n)
    return tmp_path


def run(capsys, *argv):
    try:
        main(list(argv))
        code = 0
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_aliases_everywhere_and_job_spelling(proj, capsys):
    p = str(proj)
    assert "(junk_out)" in run(capsys, "tree", p)[1]
    tj = json.loads(run(capsys, "tree", p, "--format", "json")[1])
    assert tj["alias"]["Class3D/job002"] == "junk_out"
    assert tj["artifacts"]["Class3D/job002"]["state_from_marker"] is True       # bool, not "True"
    assert "junk_out" in run(capsys, "table", p)[1]
    assert "[junk_out]" in run(capsys, "methods", p)[1]
    for spelling in ("junk_out", "Class3D/junk_out", "Class3D/job002/"):
        code, out, _ = run(capsys, "why", p, "--job", spelling, "--format", "json")
        assert code == 0 and json.loads(out)["alias"] == "junk_out"
    assert "(junk_out)" in run(capsys, "why", p, "--job", "junk_out")[1]
    code, out, _ = run(capsys, "diff", p, "--job", "first_import/", "--job", "junk_out", "--format", "json")
    assert code == 0 and json.loads(out)["alias"] == {"Import/job001": "first_import", "Class3D/job002": "junk_out"}
    assert "junk_out" in run(capsys, "diff", p, "--job", "Import/job001", "--job", "junk_out")[1]
    cj = json.loads(run(capsys, "compare", p, "--job", "Import/job001", "--job", "junk_out", "--format", "json")[1])
    assert [j["alias"] for j in cj["jobs"]] == ["first_import", "junk_out"]
    assert run(capsys, "tree", p, "--job", "junk_out")[0] == 0


def test_missing_job_is_one_clear_error_everywhere(proj, capsys):
    p = str(proj)
    for argv in (("why", p, "--job", "Class3D/job003"), ("maps", p, "--job", "Class3D/job003"),
                 ("diff", p, "--job", "Class3D/job002", "--job", "Class3D/job003"),
                 ("compare", p, "--job", "Class3D/job002", "--job", "Class3D/job003"),
                 ("overlap", p, "Class3D/job002", "Class3D/job003")):
        code, out, err = run(capsys, *argv)
        assert code == 2 and "job missing" in err and "job003" in err and "None" not in out, argv
    code, _, err = run(capsys, "overlap", p, "Class3D/job002", "Class3D/job999")
    assert code == 2 and "job not found" in err and "run_data.star" not in err


def test_max_hops_zero_or_negative_is_an_error(proj, capsys):
    for bad in ("0", "-2", "x"):
        code, _, err = run(capsys, "tree", str(proj), "--job", "Class3D/job003", "--max-hops", bad)
        assert code == 2 and "positive integer" in err
    assert run(capsys, "tree", str(proj), "--job", "Class3D/job003", "--max-hops", "1")[0] == 0


def get(srv, path):
    port = int(srv.url.rsplit(":", 1)[1].strip("/"))
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", path)
    r = c.getresponse()
    return r.status, r.read().decode()


def test_server_errors(proj):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = start_background(proj, port=port)
    try:
        assert get(srv, "/")[0] == 200
        for q in ("abc", "0", "-1"):
            status, body = get(srv, "/?max_hops=" + q)
            assert status == 400 and "max_hops" in body
        assert get(srv, "/?max_hops=2")[0] == 200
        assert get(srv, "/nope")[0] == 404
        status, body = get(srv, "/class-thumbs?job=Class3D/job002")
        assert status == 400 and "'it'" in body
    finally:
        srv.stop()


def test_mcp_rejects_unknown_arguments_and_missing_jobs(proj):
    p = mcp_server.Project(proj)
    text, err = mcp_server.call_tool(p, "list_jobs", {"bogus": 1})
    assert err and "unknown argument" in text
    assert not mcp_server.call_tool(p, "list_jobs", {})[1]
    text, err = mcp_server.call_tool(p, "why", {"job": "Class3D/job003"})
    assert err and "job missing" in text
