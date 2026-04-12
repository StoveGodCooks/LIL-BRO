"""Single source of truth for slash-command metadata.

Every slash command the user can type has one entry here. Both the help
modal (`help_screen.py`) and the inline command palette
(`command_palette.py`) read from this list so there is exactly one
place to add, remove, or rename a command.

Each entry is a tuple of:
  (command_name, target_hint, description)

- `command_name` includes the leading slash and any fixed aliases
  separated by two spaces (e.g. ``"/cwd  /pwd"``). The palette will use
  the first token (before any space) as the canonical trigger for
  autocomplete.
- `target_hint` is a short label describing which agent the command
  affects (or "--" for generic commands). Used to color-code the palette.
- `description` is a one-line beginner-friendly explanation.
"""

from __future__ import annotations


# NOTE: list order is the order commands appear in both the palette and
# the help screen. Keep the most common ones near the top.
COMMANDS: list[tuple[str, str, str]] = [
    ("/help",                   "?",           "Show the full help screen"),
    ("/settings",               "--",          "Open the settings modal (models, theme, logs, config)"),
    ("/explain <topic>",        "-> Lil Bro",  "Structured 6-section teaching breakdown"),
    ("/plan <task>",            "-> Big Bro",  "Outline Goal/Steps/Files/Risks before coding"),
    ("/focus <task>",           "--",          "Pin a goal in the status bar + journal"),
    ("/focus",                  "--",          "Clear the current focus"),
    ("/save [name]",            "--",          "Save the session journal (optional slug)"),
    ("/load",                   "--",          "List the 10 most recent journals"),
    ("/load <substring>",       "--",          "Find a journal by filename substring"),
    ("/journal",                "--",          "Show the current journal file path"),
    ("/cwd  /pwd",              "--",          "Show the project directory both agents see"),
    ("/model",                  "--",          "Show the current model for both agents"),
    ("/model big <name>",       "Big Bro",     "Switch Big Bro's model (restarts agent)"),
    ("/model lil <name>",       "Lil Bro",     "Switch Lil Bro's model (restarts agent)"),
    ("/model <tag>",            "--",          "Switch both agents to a different model"),
    ("/models",                 "--",          "List models available in Ollama"),
    ("/review",                 "-> Lil Bro",  "Structured 4-section code review of Big Bro's last reply"),
    ("/review-file <path>",     "-> Lil Bro",  "Lil Bro reads and reviews a specific file (5 sections)"),
    ("/compare <a> | <b>",      "-> Lil Bro",  "Structured compare/contrast teaching ('vs' also works)"),
    ("/explain-diff",           "-> Lil Bro",  "Teach through Big Bro's last reply (4 sections)"),
    ("/trace <symbol>",         "-> Lil Bro",  "Lil Bro walks the call graph of a function/class"),
    ("/find <query>",           "--",          "Grep across saved journals for a substring"),
    ("/debug-dump",             "--",          "Bundle debug.log + SESSION.md + journal + /state into a zip"),
    ("/debug <error>",          "-> Lil Bro",  "Structured debug walkthrough for an error or stack trace"),
    ("/reset",                  "Lil Bro",     "Clear Lil Bro's thread -- fresh conversation, same process"),
    ("/session",                "--",          "Show the live SESSION.md log (last 80 lines)  /  also F2"),
    ("/state",                  "--",          "Dump diagnostics (python, pids, models, paths)"),
    ("/status",                 "--",          "Show Ollama connection status and model info"),
    ("/restart [a|b|both]",     "--",          "Force-restart an agent (bypasses cooldown)"),
    ("/wrap",                   "--",          "Toggle soft word-wrap on the active panel"),
    ("/clear",                  "--",          "Wipe the active panel's scrollback"),
    ("/history clear",          "--",          "Clear conversation history (keep system prompt)"),
    ("/session-save <name>",    "--",          "Bookmark the current project dir as a named session"),
    ("/session-open <name>",    "--",          "Show info for a saved session (use /sessions to list)"),
    ("/sessions",               "--",          "List all saved sessions"),
    ("/skills",                 "--",          "List installed skill plugins in ~/.lilbro-local/skills/"),
    ("/player",                 "--",          "Show your RPG card -- level, skills, badges, perks"),
    ("/export-html",            "--",          "Export the current journal to a styled HTML file"),
    ("/bunkbed",                "Lil Bro",     "Toggle Lil Bro's write access (default: read-only)"),
    ("/quit  /exit",            "--",          "Shut down THE BROS"),
]


def canonical_trigger(entry_name: str) -> str:
    """Return the first slash-token from an entry name (drops args, aliases).

    ``"/explain <topic>"``   -> ``"/explain"``
    ``"/cwd  /pwd"``         -> ``"/cwd"``
    ``"/model a <name>"``    -> ``"/model"``
    """
    return entry_name.split()[0] if entry_name else ""


def all_triggers() -> list[str]:
    """Every canonical trigger token, deduplicated, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for name, _, _ in COMMANDS:
        trig = canonical_trigger(name)
        if trig and trig not in seen:
            seen.add(trig)
            out.append(trig)
        # Also expose any secondary aliases on the same entry
        # (e.g. "/cwd  /pwd" -> "/pwd").
        parts = name.split()
        for part in parts[1:]:
            if part.startswith("/") and part not in seen:
                seen.add(part)
                out.append(part)
    return out


def filter_commands(query: str) -> list[tuple[str, str, str]]:
    """Return all COMMANDS whose canonical trigger starts with `query`.

    `query` should include the leading slash (e.g. ``"/pl"``). Empty or
    bare ``"/"`` returns the full list. Matching is case-insensitive and
    prefix-based.
    """
    if not query or query == "/":
        return list(COMMANDS)
    q = query.lower()
    out: list[tuple[str, str, str]] = []
    for entry in COMMANDS:
        trig = canonical_trigger(entry[0]).lower()
        if trig.startswith(q):
            out.append(entry)
    return out
