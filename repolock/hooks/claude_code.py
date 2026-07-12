"""The Claude Code hook that makes the repo lock binding instead of advisory — adapter #1.

An MCP tool alone would be a suggestion. The session that rebases `main` underneath another
session would never have called `lock_repo` — nobody had told it to. What makes a lock mean
something is a gate the model cannot forget to walk through, so the enforcement lives here, in
the harness, and the model never has to remember anything.

Three events, three jobs:

  PreToolUse   before any tool that WRITES (Edit/Write/NotebookEdit, and the git commands that
               rewrite history), acquire-or-renew the lock on the repo under `cwd`. Another live
               session holding it => exit 2, which blocks the tool and hands the reason back to
               the model. This is also where renewal happens: a tool call IS activity, so the
               lease extends exactly while the session works and stops the moment it stops — no
               daemon, nothing to supervise.

  Stop         the model is handing control back to the human. Clean tree => release (a session
               waiting on someone at lunch must not starve every other session). Dirty tree =>
               hold, mark it idle, and let the declared lease run out; releasing a checkout full
               of half-finished edits is worse than making the next session wait.

  SessionStart the read-side check. Compare the HEAD this session last saw against the HEAD that
               is there now, and say so if history moved. No lock involved — and it is the one
               thing that catches the stale reader, where nothing is corrupted and a session
               merely reasons confidently about commits that no longer exist.

Install: a `hooks` block in ~/.claude/settings.json (user scope, so every repo on the machine
is guarded, not just one) wiring PreToolUse (matcher Edit|Write|MultiEdit|NotebookEdit|Bash),
Stop, and SessionStart to run this script via a python that can import `repolock`, by absolute
path — at user scope $CLAUDE_PROJECT_DIR points at whatever project the session is in.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

try:
    from repolock import env, lock
except ImportError:                               # run straight from a checkout, uninstalled
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from repolock import env, lock

# Tools that write. Read-only tools never take a lock — locking a `Read` would be pure friction.
WRITING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# git subcommands that mutate the working copy or rewrite history. `rebase` is on this list
# because a rebase is a *sequence* of commits, and the lock must span the whole sequence.
WRITING_GIT = ("commit", "rebase", "merge", "reset", "checkout", "switch", "restore",
               "cherry-pick", "revert", "apply", "am", "stash", "push", "pull", "clean", "mv",
               "rm", "add")

LEASE_SECONDS = 600          # renewed on every tool call; must outlast the longest single call
SEEN_DIR = "seen"


def _repo_root(cwd: str) -> str | None:
    try:
        res = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.strip() or None if res.returncode == 0 else None


def _writes(tool: str, tool_input: dict) -> bool:
    if tool in WRITING_TOOLS:
        return True
    if tool != "Bash":
        return False
    cmd = (tool_input.get("command") or "").strip()
    # Cheap and deliberately over-inclusive: a false positive costs a lock we'd have taken
    # anyway; a false negative is an unguarded write, which is the bug.
    for part in cmd.split("&&"):
        toks = part.split()
        if len(toks) >= 2 and toks[0] == "git" and toks[1] in WRITING_GIT:
            return True
    return False


def _seen_path(session: str, repo: str) -> str:
    import hashlib
    d = os.path.join(os.path.dirname(env.record_path(repo)), SEEN_DIR)
    os.makedirs(d, exist_ok=True)
    key = hashlib.sha256(f"{session}:{repo}".encode()).hexdigest()[:16]
    return os.path.join(d, f"{key}.txt")


def _remember_head(session: str, repo: str, head: str | None) -> None:
    if not head:
        return
    try:
        with open(_seen_path(session, repo), "w", encoding="utf-8") as f:
            f.write(head)
    except OSError:
        pass


def _last_seen_head(session: str, repo: str) -> str | None:
    try:
        with open(_seen_path(session, repo), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _deny(reason: str) -> None:
    """Exit 2 blocks the tool call and feeds stderr back to the model as the reason."""
    print(reason, file=sys.stderr)
    sys.exit(2)


def _say(msg: str) -> None:
    print(msg)


def pre_tool_use(payload: dict) -> None:
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if not _writes(tool, tool_input):
        return

    cwd = payload.get("cwd") or os.getcwd()
    repo = _repo_root(cwd)
    if not repo:
        return                       # not a git checkout — nothing to protect, nothing to lock

    session = payload.get("session_id") or "unknown"
    # pid=0 on purpose: this process is about to exit. See env.pid_alive.
    verdict = lock.acquire(repo, session, pid=0, lease_seconds=LEASE_SECONDS,
                           intent=f"{tool}")

    if verdict["status"] == "held":
        lk = verdict["lock"]
        _deny(
            f"REPO LOCKED — another agent session is writing to this working copy.\n"
            f"  repo    : {verdict['repo']}\n"
            f"  holder  : session {lk['session']}"
            f"{' (' + lk['intent'] + ')' if lk.get('intent') else ''}\n"
            f"  frees in: ~{int(verdict['expires_in'])}s\n"
            f"  base    : {(lk.get('base_commit') or '?')[:12]}\n\n"
            f"Do not force your way in — you would be editing a tree someone else is "
            f"mid-change on.\nIf this work is blocking, wait for the lease to lapse and retry. "
            f"If it is not, file an issue with what you were about to do and move on."
        )

    if verdict["status"] == "acquired" and verdict.get("handoff"):
        h = verdict["handoff"]
        note = [f"Took over the lock on {verdict['repo']} ({h['reason']})."]
        if h.get("history_rewritten"):
            note.append(f"WARNING: history was REWRITTEN — the previous holder's base commit "
                        f"{(h.get('base_commit') or '?')[:12]} no longer exists. Re-read before "
                        f"you act on anything you remember about this repo.")
        elif h.get("commits_since"):
            note.append(f"{len(h['commits_since'])} commit(s) landed since they started:")
            note += [f"  {c}" for c in h["commits_since"][:10]]
        if h.get("uncommitted"):
            note.append(f"They left {len(h['uncommitted'])} uncommitted change(s) in the tree — "
                        f"review before writing:")
            note += [f"  {c}" for c in h["uncommitted"][:10]]
        _say("\n".join(note))

    warn = lock.needs_commit_warning(repo, session)
    if warn:
        _say(warn["message"])

    _remember_head(session, repo, env.git_head(repo))


def stop(payload: dict) -> None:
    cwd = payload.get("cwd") or os.getcwd()
    repo = _repo_root(cwd)
    if not repo:
        return
    session = payload.get("session_id") or "unknown"
    verdict = lock.go_idle(repo, session)
    if verdict["status"] == "idle_dirty":
        # Not a block — just the truth, on the way out.
        _say(verdict["message"])


def session_start(payload: dict) -> None:
    cwd = payload.get("cwd") or os.getcwd()
    repo = _repo_root(cwd)
    if not repo:
        return
    session = payload.get("session_id") or "unknown"
    seen = _last_seen_head(session, repo)
    verdict = lock.drift(repo, seen)
    if verdict["status"] in ("moved", "rewritten"):
        _say(verdict["message"])
    _remember_head(session, repo, verdict.get("head_commit"))


HANDLERS = {
    "PreToolUse": pre_tool_use,
    "Stop": stop,
    "SessionStart": session_start,
    "UserPromptSubmit": session_start,   # same read-side check, on the way back in
}


def main() -> None:
    # Recording off ⇒ zero flight-recorder imports. This hook runs before EVERY write, and a
    # heavyweight import on the hot path is a tax the session pays forever for nothing.
    if os.getenv("REPOLOCK_FLIGHT"):
        from repolock import flight
        flight.install()
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
