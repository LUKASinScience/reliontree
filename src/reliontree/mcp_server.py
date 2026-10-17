"""`reliontree mcp [project]`: a READ-ONLY Model Context Protocol server (stdio) over one RELION project.

It lets an AI assistant ask "which job produced this map?", "what changed between these two jobs?", "write me a methods
paragraph" from the project's own files. It never writes, never runs RELION and never leaves the project directory:
the project is fixed when the server starts, job ids are validated, answers are plain JSON/text built by the same
functions as the reliontree commands. Standard library only (a small JSON-RPC 2.0 loop, newline-delimited as MCP's stdio
transport defines it); no MCP SDK needed.

Configure a client with e.g. {"command": "reliontree", "args": ["mcp", "/path/to/project"]}.
"""
import json
import re
import sys
from pathlib import Path

from . import __version__
from .relion_diff import diff_many_options, diff_options, job_context
from .relion_maps import list_job_maps
from .relion_methods import draft_methods_paragraph
from .relion_treebuild import build_tree, ordered_jobs

PROTOCOL_VERSION = "2024-11-05"
_JOB_ID = re.compile(r"[A-Za-z0-9_]+/job\d+")
MAX_REPLY_CHARS = 60000

TOOLS = [
    {"name": "list_jobs", "description": "All jobs of the RELION project in order, with type, alias, state, resolution (Angstrom), "
     "particle count, parents and whether a job is on the main path / the latest / the best-resolution one.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "job_info", "description": "Details of one job: state, alias, notes, parents, statistics, ALL recorded options "
     "(job.star), notes written by other tools, and the map files the job holds.",
     "inputSchema": {"type": "object", "properties": {"job": {"type": "string", "description": "e.g. Refine3D/job012"}},
                     "required": ["job"], "additionalProperties": False}},
    {"name": "lineage", "description": "The upstream chain of one job: every job it descends from, with each job's parents. "
     "Use it to answer 'which jobs led to this map?'.",
     "inputSchema": {"type": "object", "properties": {"job": {"type": "string"}, "max_hops": {"type": "integer", "minimum": 1}},
                     "required": ["job"], "additionalProperties": False}},
    {"name": "why", "description": "Why does a job exist: its parent(s), sibling jobs, and which options changed compared with its parent.",
     "inputSchema": {"type": "object", "properties": {"job": {"type": "string"}}, "required": ["job"], "additionalProperties": False}},
    {"name": "diff", "description": "Compare the recorded options of two or more jobs: what changed (two jobs) or varies (three or more).",
     "inputSchema": {"type": "object", "properties": {"jobs": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 12}},
                     "required": ["jobs"], "additionalProperties": False}},
    {"name": "methods", "description": "A draft methods-section paragraph, one line per job, for the whole project or for the upstream chain "
     "of one job. A starting point to check and edit, not a finished text.",
     "inputSchema": {"type": "object", "properties": {"job": {"type": "string"}}, "additionalProperties": False}},
]


class ToolError(Exception):
    """A problem with the request (bad job id, unknown job): reported to the assistant as a tool result with isError."""


class Project:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not (self.path / "default_pipeline.star").is_file():
            raise ValueError("not a RELION project (no default_pipeline.star): %s" % self.path)

    def tree(self, selected=None, max_hops=None):
        try:
            return build_tree(self.path, selected=selected, max_hops=max_hops)
        except ValueError as exc:
            raise ToolError(str(exc))

    def check_job(self, job, tree=None):
        if not isinstance(job, str) or not _JOB_ID.fullmatch(job):
            raise ToolError("job must look like Class3D/job012, got %r" % (job,))
        tree = tree or self.tree()
        if job not in tree["parents"]:
            raise ToolError("job %s is not in this project's pipeline" % job)
        return tree


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in (sorted(value) if isinstance(value, (set, frozenset)) else value)]
    if isinstance(value, Path):
        return value.name                                   # never hand out absolute paths
    return value if isinstance(value, (str, int, float, bool, type(None))) else str(value)


def tool_list_jobs(project, args):
    tree = project.tree()
    rows = []
    for job in ordered_jobs(tree):
        stats = tree["stats"].get(job, {})
        rows.append({"job": job, "type": job.split("/")[0], "alias": tree["alias"].get(job, ""),
                     "state": tree["artifacts"].get(job, {}).get("state", "unknown"),
                     "resolution_angstrom": stats.get("resolution_angstrom"), "n_particles": stats.get("n_particles"),
                     "parents": sorted(tree["parents"].get(job, [])), "main_path": job in tree["main"],
                     "latest": job == tree["latest"], "best_resolution": job == tree["best"]})
    return {"project": project.path.name, "jobs": rows}


def tool_job_info(project, args):
    tree = project.check_job(args.get("job"))
    job = args["job"]
    stats = tree["stats"].get(job, {})
    return _jsonable({"job": job, "state": tree["artifacts"].get(job, {}).get("state"), "alias": tree["alias"].get(job, ""),
                      "notes": tree["notes"].get(job, ""), "parents": sorted(tree["parents"].get(job, [])), "stats": stats,
                      "options": tree["options"].get(job, {}), "annotations": tree.get("annotations", {}).get(job, []),
                      "maps": [{"label": m["label"], "files": m["files"]} for m in list_job_maps(tree["job_dirs"][job])]})


def tool_lineage(project, args):
    project.check_job(args.get("job"))
    hops = args.get("max_hops")
    if hops is not None and (not isinstance(hops, int) or hops < 1):
        raise ToolError("max_hops must be a positive integer")
    tree = project.tree(selected=args["job"], max_hops=hops)
    return {"job": args["job"], "upstream": [{"job": j, "state": tree["artifacts"].get(j, {}).get("state", "unknown"),
                                              "parents": sorted(tree["parents"].get(j, []))} for j in ordered_jobs(tree)]}


def tool_why(project, args):
    tree = project.check_job(args.get("job"))
    return _jsonable(job_context(tree, args["job"]))


def tool_diff(project, args):
    jobs = args.get("jobs")
    if not isinstance(jobs, list) or not 2 <= len(jobs) <= 12:
        raise ToolError("give between 2 and 12 jobs")
    tree = project.tree()
    for j in jobs:
        project.check_job(j, tree)
    if len(jobs) == 2:
        return _jsonable(diff_options(tree["options"][jobs[0]], tree["options"][jobs[1]]))
    return _jsonable(diff_many_options({j: tree["options"][j] for j in jobs}))


def tool_methods(project, args):
    job = args.get("job")
    if job is not None:
        project.check_job(job)
    tree = project.tree(selected=job) if job else project.tree()
    return {"methods_draft": draft_methods_paragraph(ordered_jobs(tree), tree["options"], tree["stats"])}


HANDLERS = {"list_jobs": tool_list_jobs, "job_info": tool_job_info, "lineage": tool_lineage, "why": tool_why,
            "diff": tool_diff, "methods": tool_methods}


def call_tool(project, name, args):
    """-> (text, is_error)"""
    handler = HANDLERS.get(name)
    if handler is None:
        return "unknown tool %r" % name, True
    try:
        text = json.dumps(handler(project, args or {}), indent=1, ensure_ascii=False)
    except ToolError as exc:
        return str(exc), True
    except (OSError, ValueError, KeyError) as exc:
        return "could not read the project: %s" % exc, True
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS] + "\n... (cut: reply longer than %d characters)" % MAX_REPLY_CHARS
    return text, False


def handle(project, message):
    """One JSON-RPC message in, the reply dict (or None for notifications) out."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    method, mid = message.get("method"), message.get("id")
    params = message.get("params") or {}
    if mid is None:                                         # notification: nothing to answer
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "reliontree", "version": __version__}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        text, is_error = call_tool(project, params.get("name"), params.get("arguments"))
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}


def serve(project_path, stdin=None, stdout=None):
    project = Project(project_path)
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(project, json.loads(line))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
