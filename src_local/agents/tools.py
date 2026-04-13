"""File system tools for LIL BRO LOCAL agents.

Provides tool schemas (Ollama function-calling format) and an async
executor that runs tools against the local project directory.

Permission model:
  - Big Bro: read + write (all tools)
  - Lil Bro: read-only by default (read_file, list_directory, grep_files)
  - /bunkbed toggles Lil Bro to full read+write

Path sandboxing: every path argument is resolved relative to the
project directory. Paths that escape the sandbox are rejected.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import math
import operator
import os
import re
from pathlib import Path

logger = logging.getLogger("lilbro-local.tools")

# ---------------------------------------------------------------------------
# Permission sets
# ---------------------------------------------------------------------------

READ_TOOLS = frozenset({"read_file", "list_directory", "grep_files"})
WRITE_TOOLS = frozenset({"write_file", "edit_file", "run_command"})
BIBLE_TOOLS = frozenset({"coding_lookup", "reasoning_lookup"})
UTILITY_TOOLS = frozenset({"calculate"})
ALL_TOOLS = READ_TOOLS | WRITE_TOOLS | BIBLE_TOOLS | UTILITY_TOOLS

TOOL_DISPLAY_LABELS = {
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "list_directory": "List",
    "grep_files": "Grep",
    "run_command": "Run",
    "coding_lookup": "Asking Grandpa (Coding)",
    "reasoning_lookup": "Asking Grandpa (Reasoning)",
    "calculate": "Crunching Numbers",
}

# ---------------------------------------------------------------------------
# Tool schemas (Ollama / OpenAI function-calling format)
# ---------------------------------------------------------------------------

_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file. Returns lines with line numbers. "
                "Use offset and limit to paginate large files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the project directory",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start reading from (0-based, default 0)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of lines to return (default 200)",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and subdirectories in a directory. "
                "Shows file sizes and marks directories with a trailing /."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to the project (default: project root)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_files",
            "description": (
                "Search for a regex pattern across files in the project. "
                "Returns matching lines with file paths and line numbers. "
                "Caps at 50 matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "Subdirectory to search in (default: project root)",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File glob pattern to filter (e.g. '*.py', default: all files)",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a file with the given content. "
                "Parent directories are created automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the project directory",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full content to write to the file",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Edit a file by replacing the first occurrence of old_string "
                "with new_string. Read the file first to see its current content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the project directory",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact text to find and replace",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The replacement text",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command in the project directory. "
                "Use for git, tests, linting, or other CLI operations. "
                "30-second timeout. Output is capped at 10000 characters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "coding_lookup",
            "description": (
                "Search the coding bible for reference material — API docs, "
                "syntax patterns, stdlib usage, implementation examples. "
                "Use this BEFORE writing code to ground your answer in "
                "authoritative documentation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language query describing what you need (e.g. 'python asyncio gather error handling')",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reasoning_lookup",
            "description": (
                "Search the reasoning bible for judgment frameworks, "
                "debugging strategies, tradeoff rationale, and design "
                "decisions. Use this when explaining WHY, debugging, "
                "comparing approaches, or making design choices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language query describing what you need (e.g. 'when to use composition vs inheritance')",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a Python math expression and return the result. "
                "Use this for ANY arithmetic, binary conversion, powers, "
                "modulo, or numeric computation. Don't do math in your "
                "head — use this tool instead. Examples: '730 % 2', "
                "'bin(730)', '2**10', '3*5 - 2*3', 'sum(range(1,101))'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Python math expression to evaluate (e.g. 'bin(730)', '2**10 > 1000')",
                    },
                },
                "required": ["expression"],
            },
        },
    },
]


def get_tool_schemas(*, write_access: bool = True) -> list[dict]:
    """Return the tools array for the Ollama /api/chat payload.

    When *write_access* is False, only read + bible + utility tools are included.
    Bible and utility tools are always available to both agents.
    """
    if write_access:
        return list(_SCHEMAS)
    allowed = READ_TOOLS | BIBLE_TOOLS | UTILITY_TOOLS
    return [s for s in _SCHEMAS if s["function"]["name"] in allowed]


def get_tool_names(*, write_access: bool = True) -> set[str]:
    """Return the set of tool names available at the given permission level."""
    if write_access:
        return set(ALL_TOOLS)
    return set(READ_TOOLS | BIBLE_TOOLS | UTILITY_TOOLS)


# ---------------------------------------------------------------------------
# Path sandboxing
# ---------------------------------------------------------------------------

def _resolve_path(raw: str, project_dir: Path) -> Path | str:
    """Resolve *raw* relative to *project_dir*.

    Returns the resolved ``Path`` on success, or an error string if the
    path escapes the sandbox.
    """
    try:
        candidate = (project_dir / raw).resolve()
    except (OSError, ValueError) as exc:
        return f"Error: invalid path '{raw}': {exc}"
    # Ensure the resolved path is within the project directory.
    try:
        candidate.relative_to(project_dir.resolve())
    except ValueError:
        return f"Error: path '{raw}' is outside the project directory."
    return candidate


def _fmt_size(n: int) -> str:
    """Human-readable file size."""
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


# ---------------------------------------------------------------------------
# Tool executors (each returns a plain string, never raises)
# ---------------------------------------------------------------------------

def _exec_read_file(args: dict, project_dir: Path) -> str:
    raw_path = args.get("path", "")
    if not raw_path:
        return "Error: 'path' argument is required."
    resolved = _resolve_path(raw_path, project_dir)
    if isinstance(resolved, str):
        return resolved
    if not resolved.exists():
        return f"Error: file not found: {raw_path}"
    if resolved.is_dir():
        return f"Error: '{raw_path}' is a directory. Use list_directory instead."
    offset = max(0, int(args.get("offset", 0)))
    limit = min(2000, max(1, int(args.get("limit", 200))))
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Error reading file: {exc}"
    lines = text.splitlines(keepends=True)
    total = len(lines)
    selected = lines[offset : offset + limit]
    if not selected and total > 0:
        return f"File has {total} lines. Offset {offset} is past the end."
    out = []
    for i, line in enumerate(selected, start=offset + 1):
        out.append(f"{i:>5}\t{line.rstrip()}")
    header = f"[{raw_path}] lines {offset + 1}-{offset + len(selected)} of {total}"
    return header + "\n" + "\n".join(out)


def _exec_list_directory(args: dict, project_dir: Path) -> str:
    raw_path = args.get("path", ".")
    resolved = _resolve_path(raw_path, project_dir)
    if isinstance(resolved, str):
        return resolved
    if not resolved.exists():
        return f"Error: directory not found: {raw_path}"
    if not resolved.is_dir():
        return f"Error: '{raw_path}' is a file, not a directory."
    entries = []
    try:
        with os.scandir(resolved) as it:
            for entry in sorted(it, key=lambda e: (not e.is_dir(), e.name.lower())):
                if entry.is_dir():
                    entries.append(f"d  {entry.name}/")
                else:
                    try:
                        size = _fmt_size(entry.stat().st_size)
                    except OSError:
                        size = "?"
                    entries.append(f"f  {entry.name}  ({size})")
                if len(entries) >= 200:
                    entries.append(f"... (truncated, {raw_path} has more entries)")
                    break
    except OSError as exc:
        return f"Error listing directory: {exc}"
    if not entries:
        return f"(empty directory: {raw_path})"
    return "\n".join(entries)


def _exec_grep_files(args: dict, project_dir: Path) -> str:
    pattern = args.get("pattern", "")
    if not pattern:
        return "Error: 'pattern' argument is required."
    raw_path = args.get("path", ".")
    glob_pat = args.get("glob", "*")
    resolved = _resolve_path(raw_path, project_dir)
    if isinstance(resolved, str):
        return resolved
    if not resolved.exists():
        return f"Error: path not found: {raw_path}"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regex '{pattern}': {exc}"
    matches = []
    # Skip common non-text directories
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox"}
    for filepath in sorted(resolved.rglob(glob_pat)):
        if any(part in skip_dirs for part in filepath.parts):
            continue
        if not filepath.is_file():
            continue
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                rel = filepath.relative_to(project_dir.resolve())
                matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                if len(matches) >= 50:
                    matches.append("... (50 match limit reached)")
                    return "\n".join(matches)
    if not matches:
        return f"No matches for '{pattern}' in {raw_path}"
    return "\n".join(matches)


def _exec_write_file(args: dict, project_dir: Path) -> str:
    raw_path = args.get("path", "")
    content = args.get("content", "")
    if not raw_path:
        return "Error: 'path' argument is required."
    resolved = _resolve_path(raw_path, project_dir)
    if isinstance(resolved, str):
        return resolved
    if resolved.is_dir():
        return f"Error: '{raw_path}' is an existing directory."
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"Error writing file: {exc}"
    nbytes = len(content.encode("utf-8"))
    return f"Wrote {nbytes} bytes to {raw_path}"


def _exec_edit_file(args: dict, project_dir: Path) -> str:
    raw_path = args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    if not raw_path:
        return "Error: 'path' argument is required."
    if not old_string:
        return "Error: 'old_string' argument is required."
    resolved = _resolve_path(raw_path, project_dir)
    if isinstance(resolved, str):
        return resolved
    if not resolved.exists():
        return f"Error: file not found: {raw_path}"
    if resolved.is_dir():
        return f"Error: '{raw_path}' is a directory."
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Error reading file: {exc}"
    if old_string not in text:
        return f"Error: old_string not found in {raw_path}"
    new_text = text.replace(old_string, new_string, 1)
    try:
        resolved.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        return f"Error writing file: {exc}"
    old_lines = old_string.count("\n") + 1
    new_lines = new_string.count("\n") + 1
    return (
        f"Edited {raw_path}: replaced {old_lines} line(s) with {new_lines} line(s)"
    )


async def _exec_run_command(args: dict, project_dir: Path) -> str:
    command = args.get("command", "")
    if not command:
        return "Error: 'command' argument is required."
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Error: command timed out after 30 seconds: {command}"
    except OSError as exc:
        return f"Error running command: {exc}"
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    if len(output) > 10000:
        output = output[:10000] + "\n... (output truncated at 10000 chars)"
    exit_code = proc.returncode
    header = f"$ {command}\n(exit code: {exit_code})\n"
    return header + output if output else header + "(no output)"


# ---------------------------------------------------------------------------
# Bible tool executors
# ---------------------------------------------------------------------------

def _exec_coding_lookup(args: dict, _project_dir: Path) -> str:
    query = args.get("query", "")
    if not query:
        return "Error: 'query' argument is required."
    from src_local.bibles.store import get_bible_store
    store = get_bible_store()
    results = store.coding_lookup(query, top_k=8)
    if not results:
        return f"No coding bible results for: {query}"
    lines = [f"# Coding Bible — {len(results)} results for '{query}'\n"]
    for chunk in results:
        lines.append(chunk.to_context())
        lines.append("")
    return "\n".join(lines)


def _exec_reasoning_lookup(args: dict, _project_dir: Path) -> str:
    query = args.get("query", "")
    if not query:
        return "Error: 'query' argument is required."
    from src_local.bibles.store import get_bible_store
    store = get_bible_store()
    results = store.reasoning_lookup(query, top_k=8)
    if not results:
        return f"No reasoning bible results for: {query}"
    lines = [f"# Reasoning Bible — {len(results)} results for '{query}'\n"]
    for chunk in results:
        lines.append(chunk.to_context())
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Calculator tool (AST-based safe math evaluation)
# ---------------------------------------------------------------------------

# Supported binary operators.
_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
# Supported unary operators.
_UN_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
# Safe function whitelist.
_SAFE_FUNCS: dict[str, Any] = {
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float, "pow": pow,
    "sqrt": math.sqrt, "log": math.log, "log2": math.log2,
    "log10": math.log10, "ceil": math.ceil, "floor": math.floor,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "pi": math.pi, "e": math.e,
}

# Maximum expression length to prevent abuse.
_MAX_EXPR_LEN = 500


def _safe_eval_node(node: ast.AST) -> Any:
    """Recursively evaluate an AST node using only safe operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"unsupported constant type: {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        return op(_safe_eval_node(node.left), _safe_eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
        return op(_safe_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only simple function calls allowed (e.g. sqrt(4))")
        fn = _SAFE_FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"unknown function: {node.func.id}")
        args = [_safe_eval_node(a) for a in node.args]
        return fn(*args)
    if isinstance(node, ast.Name):
        val = _SAFE_FUNCS.get(node.id)
        if val is None:
            raise ValueError(f"unknown name: {node.id}")
        return val
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


def _exec_calculate(args: dict, _project_dir: Path) -> str:
    expr = args.get("expression", "")
    if not expr:
        return "Error: 'expression' argument is required."
    if len(expr) > _MAX_EXPR_LEN:
        return f"Error: expression too long ({len(expr)} chars, max {_MAX_EXPR_LEN})."
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        return f"Error: invalid expression: {exc}"
    try:
        result = _safe_eval_node(tree)
        return f"{expr} = {result}"
    except Exception as exc:  # noqa: BLE001
        return f"Error evaluating '{expr}': {exc}"


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

_EXECUTORS = {
    "read_file": _exec_read_file,
    "list_directory": _exec_list_directory,
    "grep_files": _exec_grep_files,
    "write_file": _exec_write_file,
    "edit_file": _exec_edit_file,
    "coding_lookup": _exec_coding_lookup,
    "reasoning_lookup": _exec_reasoning_lookup,
    "calculate": _exec_calculate,
    # run_command is async, handled separately
}


async def execute_tool(
    name: str,
    arguments: dict,
    *,
    project_dir: Path,
    write_access: bool = True,
) -> str:
    """Execute a tool call and return the result as a string.

    Never raises — errors become ``"Error: ..."`` strings so the model
    can read them and self-correct.
    """
    if name not in ALL_TOOLS:
        return f"Error: unknown tool '{name}'"
    if not write_access and name in WRITE_TOOLS:
        return (
            f"Error: '{name}' requires write access. "
            "You are in read-only mode. Ask the user to enable /bunkbed."
        )
    try:
        if name == "run_command":
            return await _exec_run_command(arguments, project_dir)
        executor = _EXECUTORS.get(name)
        if executor is None:
            return f"Error: no executor for '{name}'"
        return executor(arguments, project_dir)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool %s crashed", name)
        return f"Error: tool '{name}' crashed: {exc}"
