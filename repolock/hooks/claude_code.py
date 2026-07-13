"""The Claude Code hook that makes the repo lock binding instead of advisory — adapter #1.

An MCP tool alone would be a suggestion. The session that rebases `main` underneath another
session would never have called `lock_repo` — nobody had told it to. What makes a lock mean
something is a gate the model cannot forget to walk through, so the enforcement lives here, in
the harness, and the model never has to remember anything.

Three events, three jobs:

  PreToolUse   before any tool that WRITES (Edit/Write/NotebookEdit, and any shell command that
               is not recognizably a read — see common.shell_writes), acquire-or-renew the lock on
               the repo under `cwd`. Another live session holding it => exit 2, which blocks the
               tool and hands the reason back to the model. This is also where renewal happens: a
               tool call IS activity, so the lease extends exactly while the session works and
               stops the moment it stops — no daemon, nothing to supervise.

  Stop         the model is handing control back to the human. Clean tree => release (a session
               waiting on someone at lunch must not starve every other session). Dirty tree =>
               hold, mark it idle, and let the declared lease run out; releasing a checkout full
               of half-finished edits is worse than making the next session wait.

  SessionStart the read-side check. Compare the HEAD this session last saw against the HEAD that
               is there now, and say so if history moved. No lock involved — and it is the one
               thing that catches the stale reader, where nothing is corrupted and a session
               merely reasons confidently about commits that no longer exist.

Install: a `hooks` block in ~/.claude/settings.json (user scope, so every repo on the machine is
guarded, not just one) wiring PreToolUse (matcher Edit|Write|MultiEdit|NotebookEdit|Bash|
PowerShell — the shells BOTH have to be there, and on Windows PowerShell is the one that gets
used), Stop, and SessionStart to run this script via a python that can import `repolock`, by
absolute path — at user scope $CLAUDE_PROJECT_DIR points at whatever project the session is in.
"""

from __future__ import annotations

import json
import os
import sys

try:
    from repolock import env, lock
    from repolock.hooks import common
except ImportError:                               # run straight from a checkout, uninstalled
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from repolock import env, lock
    from repolock.hooks import common

# Tools that write a file directly. Read-only tools never take a lock — locking a `Read` would be
# pure friction.
WRITING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _writes(tool: str, tool_input: dict) -> bool:
    if tool in WRITING_TOOLS:
        return True
    # Any tool carrying a `command` is a shell — `Bash`, `PowerShell` on Windows, and whatever
    # the next one is called. Keyed on the payload's shape rather than on a list of names, so a
    # shell we have never heard of is gated on arrival instead of writing unguarded until someone
    # notices. Only the settings.json matcher then has to learn the name.
    command = tool_input.get("command")
    if isinstance(command, str):
        return common.shell_writes(command)
    return False


def _deny(reason: str) -> None:
    """Exit 2 blocks the tool call and feeds stderr back to the model as the reason."""
    print(reason, file=sys.stderr)
    sys.exit(2)


def _say(msg: str) -> None:
    print(msg)


def _record() -> None:
    """Arm the recorder, immediately before the first call into `lock`.

    Not at the top of main(): the boundary being recorded IS the lock, and a hook call that takes
    no lock performs no boundary effect and has nothing to record. Installing eagerly bought a
    ~110ms flight-recorder import for every read the session ran — the recorder taxing exactly
    the calls it has nothing to say about. Called from each handler that actually touches lock.
    """
    if env.recording():
        from repolock import flight
        flight.install()


def pre_tool_use(payload: dict) -> None:
    tool = payload.get("tool_name") or ""
    if not _writes(tool, payload.get("tool_input") or {}):
        return

    cwd = payload.get("cwd") or os.getcwd()
    repo = common.repo_root(cwd)
    if not repo:
        return                       # not a git checkout — nothing to protect, nothing to lock

    _record()
    session = payload.get("session_id") or "unknown"
    denial, notes = common.gate(repo, session, intent=f"{tool}")
    if denial:
        _deny(denial)
    for note in notes:
        _say(note)


def stop(payload: dict) -> None:
    cwd = payload.get("cwd") or os.getcwd()
    repo = common.repo_root(cwd)
    if not repo:
        return
    _record()
    session = payload.get("session_id") or "unknown"
    verdict = lock.go_idle(repo, session)
    if verdict["status"] == "idle_dirty":
        # Not a block — just the truth, on the way out.
        _say(verdict["message"])


def session_start(payload: dict) -> None:
    cwd = payload.get("cwd") or os.getcwd()
    repo = common.repo_root(cwd)
    if not repo:
        return
    _record()
    session = payload.get("session_id") or "unknown"
    note = common.drift_note(session, repo)
    if note:
        _say(note)


HANDLERS = {
    "PreToolUse": pre_tool_use,
    "Stop": stop,
    "SessionStart": session_start,
    "UserPromptSubmit": session_start,   # same read-side check, on the way back in
}


def main() -> None:
    # No recorder here — see _record(). Recording is ON by default (REPOLOCK_FLIGHT=0 disables),
    # but it is armed inside the handlers that call `lock`, so a read never pays the import.
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)                       # a hook that cannot parse its input must not block work

    handler = HANDLERS.get(payload.get("hook_event_name") or "")
    if not handler:
        sys.exit(0)

    try:
        handler(payload)
    except SystemExit:
        raise
    except Exception as e:                # noqa: BLE001
        # A crashing hook must never wedge the session. Fail OPEN, loudly: an unguarded write is
        # bad, but a laptop where nobody can edit anything is worse — and silent is worst.
        print(f"repo-lock hook error ({type(e).__name__}: {e}) — proceeding unguarded",
              file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
