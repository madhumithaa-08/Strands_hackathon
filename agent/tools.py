"""Reflex Arc tools: a MOCKED, in-memory coding sandbox — no real filesystem, no real shell.

The coding agent (Amazon Bedrock Nova Pro) writes code against the fixed URL-shortener spec in
agent/data/spec/. Every tool here operates on an in-memory dict "filesystem" and a simulated
command runner, so nothing ever touches the real machine. A stray `rm -rf`, a write under `/prod`
or a `push --force` is flagged in the simulated return as defense-in-depth, but the BLOCKING
decision is always the reflex's (Strands Decider 2B via agent/decision.py), never a regex `if`
here.

Loading rule: the three markdown spec files are read with Path.read_text() through the cached
`read_spec(part)` helper (decider_kit.data.load only reads .json/.csv); tasks.json is a plain
JSON list.

Built with the AWS User Group Madurai Strands Decider hackathon kit.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from strands import tool

from decider_kit.config import ROOT

DATA = ROOT / "agent" / "data"
MAX_FILE = 20_000  # cap written content so the reflex state stays bounded

# The in-memory sandbox filesystem, seeded with the four empty spec modules.
_FS: dict[str, str] = {"app.py": "", "store.py": "", "validate.py": "", "config.py": ""}

# Inert safety net (defense in depth only; the reflex, not this regex, is what blocks an action).
_DANGER_HINTS = ("rm -rf", "/prod", "push --force", "mkfs", "dd if=", ":(){", "shutdown", "reboot")


@lru_cache(maxsize=None)
def read_spec(part: str) -> str:
    """Return the full text of a spec document: part is 'requirements', 'design' or 'tasks'."""
    return (DATA / "spec" / f"{part}.md").read_text()


def _flag(text: str) -> list[str]:
    low = text.lower()
    return [h for h in _DANGER_HINTS if h in low]


@tool
def read_spec_tool(part: str = "design") -> dict:
    """Read a spec document (requirements, design or tasks) so the agent can follow it."""
    try:
        return {"part": part, "text": read_spec(part)}
    except FileNotFoundError:
        return {"error": f"no spec part {part!r}; use requirements, design or tasks"}


@tool
def list_files() -> dict:
    """List the files in the sandbox workspace and their sizes."""
    return {"files": {name: len(body) for name, body in _FS.items()}}


@tool
def read_file(path: str) -> dict:
    """Read a file from the sandbox workspace by its path."""
    name = path.strip().lstrip("./")
    if name not in _FS:
        return {"error": f"no file {path!r} in the workspace"}
    return {"path": name, "content": _FS[name]}


@tool
def write_file(path: str, content: str) -> dict:
    """Write (create or overwrite) a file in the sandbox workspace with the given content."""
    name = path.strip().lstrip("./")
    if len(content) > MAX_FILE:
        return {"error": f"content is {len(content)} chars; the cap is {MAX_FILE}"}
    _FS[name] = content
    return {"written": name, "bytes": len(content), "flags": _flag(path + " " + content)}


@tool
def edit_file(path: str, patch: str) -> dict:
    """Append a patch/snippet to a file in the sandbox workspace."""
    name = path.strip().lstrip("./")
    if name not in _FS:
        return {"error": f"no file {path!r} in the workspace; write_file it first"}
    if len(_FS[name]) + len(patch) > MAX_FILE:
        return {"error": f"result would exceed the {MAX_FILE}-char cap"}
    _FS[name] += ("\n" if _FS[name] else "") + patch
    return {"edited": name, "bytes": len(_FS[name]), "flags": _flag(patch)}


@tool
def run_command(cmd: str) -> dict:
    """Run a shell command in the sandbox (SIMULATED — never actually executed)."""
    flags = _flag(cmd)
    # Simulated only. We NEVER execute. The reflex judges the command text in the state.
    return {"command": cmd, "simulated": True, "exit_code": 0,
            "stdout": f"[simulated] would run: {cmd}", "flags": flags}


@tool
def delete_path(path: str) -> dict:
    """Delete a path in the sandbox (SIMULATED — never actually executed)."""
    flags = _flag(path)
    name = path.strip().lstrip("./")
    existed = name in _FS
    # Simulated only: record the intent, never touch the real FS.
    return {"path": path, "simulated": True, "existed_in_sandbox": existed, "flags": flags}


TOOLS = [read_spec_tool, list_files, read_file, write_file, edit_file, run_command, delete_path]


def tasks() -> list[dict]:
    """The machine-readable task list (agent/data/tasks.json)."""
    return json.loads((DATA / "tasks.json").read_text())
