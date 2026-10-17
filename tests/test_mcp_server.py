"""The read-only MCP server: protocol handshake, every tool on a small fake project, refusals, and a real stdio session."""
import io
import json
import subprocess
import sys

import pytest

from reliontree import mcp_server

PIPELINE = """data_pipeline_processes

loop_
_rlnPipeLineProcessName #1
_rlnPipeLineProcessAlias #2
_rlnPipeLineProcessTypeLabel #3
_rlnPipeLineProcessStatusLabel #4
Class3D/job001/ first_class relion.class3d Succeeded
Select/job002/ None relion.select.onvalue Succeeded
Refine3D/job003/ None relion.refine3d Succeeded

data_pipeline_nodes

loop_
_rlnPipeLineNodeName #1
_rlnPipeLineNodeTypeLabel #2
Class3D/job001/run_it025_data.star ParticlesData.star.relion
Select/job002/particles.star ParticlesData.star.relion
Refine3D/job003/run_data.star ParticlesData.star.relion

data_pipeline_input_edges

loop_
_rlnPipeLineEdgeFromNode #1
_rlnPipeLineEdgeProcess #2
Class3D/job001/run_it025_data.star Select/job002/
Select/job002/particles.star Refine3D/job003/

data_pipeline_output_edges

loop_
_rlnPipeLineEdgeProcess #1
_rlnPipeLineEdgeToNode #2
Class3D/job001/ Class3D/job001/run_it025_data.star
Select/job002/ Select/job002/particles.star
Refine3D/job003/ Refine3D/job003/run_data.star
"""


def _job_star(**opts):
    rows = "\n".join("%s  %s" % (k, v) for k, v in opts.items())
    return "data_job\n\n_rlnJobTypeLabel             relion.x\n\ndata_joboptions_values\n\nloop_\n_rlnJobOptionVariable #1\n_rlnJobOptionValue #2\n" + \
           "\n".join("%s %s" % (k, v) for k, v in opts.items()) + "\n"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "default_pipeline.star").write_text(PIPELINE)
    for job, opts in (("Class3D/job001", dict(nr_classes=4, tau_fudge=4)), ("Select/job002", dict(select_value=3)),
                      ("Refine3D/job003", dict(nr_classes=1, particle_diameter=200))):
        d = tmp_path / job
        d.mkdir(parents=True)
        (d / "job.star").write_text(_job_star(**opts))
    (tmp_path / "Refine3D" / "job003" / "run_class001.mrc").write_bytes(b"x")
    return mcp_server.Project(tmp_path)


def ask(project, method, params=None, mid=1):
    return mcp_server.handle(project, {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})


def call(project, name, **args):
    r = ask(project, "tools/call", {"name": name, "arguments": args})["result"]
    return json.loads(r["content"][0]["text"]) if not r["isError"] else r["content"][0]["text"], r["isError"]


def test_handshake_and_tool_list(project):
    init = ask(project, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
    assert init["result"]["serverInfo"]["name"] == "reliontree" and init["result"]["capabilities"] == {"tools": {}}
    assert mcp_server.handle(project, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert ask(project, "ping")["result"] == {}
    names = [t["name"] for t in ask(project, "tools/list")["result"]["tools"]]
    assert sorted(names) == sorted(mcp_server.HANDLERS) and len(names) == 6
    assert "error" in ask(project, "resources/list")
    assert mcp_server.handle(project, ["not", "a", "request"])["error"]["code"] == -32600


def test_list_jobs_and_info(project):
    data, err = call(project, "list_jobs")
    assert not err and [j["job"] for j in data["jobs"]][-1] == "Refine3D/job003"
    first = data["jobs"][0]
    assert first["alias"] == "first_class" and first["type"] == "Class3D"
    info, err = call(project, "job_info", job="Refine3D/job003")
    assert not err and info["parents"] == ["Select/job002"] and info["options"]["particle_diameter"] == "200"
    assert [m["label"] for m in info["maps"]] == ["Final map"] and "/" not in info["maps"][0]["files"][0]   # names only


def test_lineage_why_diff_methods(project):
    data, _ = call(project, "lineage", job="Refine3D/job003")
    assert [u["job"] for u in data["upstream"]] == ["Class3D/job001", "Select/job002", "Refine3D/job003"] or \
        {u["job"] for u in data["upstream"]} == {"Class3D/job001", "Select/job002", "Refine3D/job003"}
    assert {u["job"] for u in call(project, "lineage", job="Refine3D/job003", max_hops=1)[0]["upstream"]} == {"Select/job002", "Refine3D/job003"}
    ctx, err = call(project, "why", job="Refine3D/job003")
    assert not err and ctx["parents"] == ["Select/job002"]
    d, err = call(project, "diff", jobs=["Class3D/job001", "Refine3D/job003"])
    assert not err and "changed" in d
    many, err = call(project, "diff", jobs=["Class3D/job001", "Select/job002", "Refine3D/job003"])
    assert not err and "varying" in many
    text, err = call(project, "methods")
    assert not err and "methods_draft" in text
    assert not call(project, "methods", job="Select/job002")[1]


@pytest.mark.parametrize("name,args", [
    ("job_info", {"job": "../../etc/passwd"}), ("job_info", {"job": "Class3D/job999"}), ("job_info", {"job": 5}),
    ("why", {}), ("lineage", {"job": "Class3D/job001", "max_hops": 0}), ("diff", {"jobs": ["Class3D/job001"]}),
    ("diff", {"jobs": ["Class3D/job001", "Class3D/job404"]}), ("methods", {"job": "nope"}), ("no_such_tool", {})])
def test_bad_requests_are_tool_errors_not_crashes(project, name, args):
    text, err = call(project, name, **args)
    assert err is True and isinstance(text, str) and text


def test_it_is_read_only(project, tmp_path):
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    for name, args in (("list_jobs", {}), ("job_info", {"job": "Class3D/job001"}), ("lineage", {"job": "Refine3D/job003"}),
                       ("why", {"job": "Refine3D/job003"}), ("methods", {})):
        call(project, name, **args)
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before


def test_not_a_project_is_refused(tmp_path):
    with pytest.raises(ValueError, match="default_pipeline.star"):
        mcp_server.Project(tmp_path)


def test_serve_loop_handles_garbage_and_keeps_going(project):
    lines = ["", "not json", json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"})]
    out = io.StringIO()
    mcp_server.serve(project.path, stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out)
    replies = [json.loads(l) for l in out.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700 and replies[1] == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_real_stdio_session(project):
    """Start `reliontree mcp` as a subprocess, speak newline-delimited JSON-RPC to it, close stdin: it exits cleanly."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_jobs", "arguments": {}}}]
    done = subprocess.run([sys.executable, "-c", "import sys; from reliontree.cli import main; main(sys.argv[1:])", "mcp", str(project.path)],
                          input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    replies = [json.loads(l) for l in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2] and not replies[1]["result"]["isError"]
    assert "Refine3D/job003" in replies[1]["result"]["content"][0]["text"]
