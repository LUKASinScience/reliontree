# Scripts and AI assistants

reliontree is built to be driven by a person, a script or an AI assistant with the same commands.

## Machine-readable output

`tree`, `diff`, `why`, `overlap`, `compare` and `maps` take `--format json`. Exit codes: `0` ok, `1` no RELION project found,
`2` parse or job-lookup error.

## MCP server (read-only)

```bash
reliontree mcp /path/to/project
```

A [Model Context Protocol](https://modelcontextprotocol.io) server over stdio (protocol 2024-11-05, tools only). Configure
a client with `{"command": "reliontree", "args": ["mcp", "/path/to/project"]}`. Tools: `list_jobs`, `job_info`,
`lineage`, `why`, `diff`, `methods`.

What it can do is deliberately small: it reads one project directory, job ids are validated, answers contain file names
rather than absolute paths and are capped at 60 000 characters. It never writes, never runs RELION and never starts
ChimeraX. Check a new client with a harmless question first; it has been exercised with a test client, not yet with every
assistant.

## ChimeraX from a script

`contrib/chx_run.py` runs a short list of whitelisted commands (`open` of a local file, `chopchop`, `instantmap`,
`figurestyle`) in a throw-away headless ChimeraX and prints one JSON object, so no ChimeraX REST port is needed:

```bash
python3 contrib/chx_run.py --allow-dir /data "open /data/model.cif" "chopchop disulfides #1"
```

Every absolute path must lie inside an allowed directory; `;`, newlines, `runscript` and similar are refused; commands
that use the network need `--allow-network`. Rendering commands do not work headless (no OpenGL).

## What not to expect

- No write access through MCP: `reliontree plan --apply` (registering new jobs) is a human decision.
- The methods paragraph is a draft built from recorded parameters, not text to paste into a paper.
