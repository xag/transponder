"""What every harness adapter shares: the parts of an adapter that are not the harness.

An adapter is a thin translation — harness event in, SPEC.md obligation out. The obligations
themselves (which commands write, what a refusal must say, how a session remembers the HEAD it
last saw) are identical across harnesses, so they live here and each adapter keeps only its
vendor's wire format.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess

from repolock import env, lock

# The WRITERS are the list, and the unrecognized command is a READ.
#
# The opposite was tried, in the obvious belief that failing closed is the safe direction: a
# reader allowlist, anything unknown takes the lock. It broke a two-session fleet within the hour
# (xag/repolock#4). The reasoning was right about the asymmetry and wrong about the population.
# On Windows every command reaches the harness through a shell, so an allowlist has to enumerate
# not just the readers but every *shape* a reader comes in — and it missed `cd`, which is how
# `cd repo && cat file` becomes a write, and `gh`, which is how reading a GitHub issue mints a
# ten-minute write lease. Sessions doing nothing but reading held the repo against sessions that
# actually wanted to change it. That is not a conservative failure; it is a livelock with good
# intentions.
#
# So: a false positive is NOT free, and the earlier note in this file saying so (repeated into
# SPEC §7) was simply wrong. It costs the lease, and the lease is the whole resource. A false
# negative is one unguarded write; a false positive can stop every session on the machine.
#
# The tail this leaves open — a mutating command nobody listed — is real, and it is issue #2. It
# does not get closed by widening this list until it swallows the world. It gets closed by asking
# the right question, which is not "was this a shell command?" but "did the repo change?" (#4).
# Unchanged from v0.1, and deliberately not widened: every entry here mutates the tree or its
# history, and nothing is added "just in case". `git fetch`, `git gc` and `git submodule status`
# are absent because they do not touch the working copy — and a lock they do not need is a lock
# taken from someone who does.
WRITING_GIT = ("commit", "rebase", "merge", "reset", "checkout", "switch", "restore",
               "cherry-pick", "revert", "apply", "am", "stash", "push", "pull", "clean", "mv",
               "rm", "add")

# Non-git commands that mutate a working copy. Judged on the head of each segment, basename'd and
# lower-cased, so both shells' spellings share one set.
WRITING_SHELL = {
    # POSIX
    "rm", "rmdir", "mv", "cp", "touch", "mkdir", "tee", "dd", "truncate", "patch", "install",
    "ln", "chmod", "chown", "unzip", "gunzip",
    # PowerShell, and its aliases
    "set-content", "add-content", "out-file", "new-item", "remove-item", "copy-item",
    "move-item", "rename-item", "clear-content", "ni", "ri", "cpi", "mi", "rni", "sc", "ac",
}

# git's global options that swallow the next token, which would otherwise be read as the
# subcommand: `git -C sub commit` is a commit, not a `sub`.
_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                          "--config-env"}

# Segment separators, longest first so `||` is never read as two pipes. Every segment is judged
# on its own: `cd sub && git commit` is a commit, and keying on the first token of the whole
# command — as v0.1 did — misses it. THIS is the half of the fail-closed experiment that was
# never wrong, and it survives.
_SEPARATORS = re.compile(r"&&|\|\||;|\||\n|\r")

# A redirect into a file is a write whatever ran: `echo` is a reader until it is pointed at a
# file. The sinks that are not files are the exception: `2>&1`, `/dev/null`, PowerShell's `$null`.
_REDIRECT = re.compile(r"\d?>>?\s*([^\s;|&]+)")
_NOT_A_FILE = {"/dev/null", "$null", "nul", "null"}

LEASE_SECONDS = 600          # renewed on every tool call; must outlast the longest single call
SEEN_DIR = "seen"


def repo_root(cwd: str) -> str | None:
    try:
        res = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.strip() or None if res.returncode == 0 else None


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:                   # unbalanced quotes — unreadable, so unjudgeable
        return segment.split()


def _head(tokens: list[str]) -> str | None:
    """The command a segment actually runs: env assignments and prefixes skipped, path stripped,
    case folded. `cd` is a prefix like any other — `cd repo && git commit` runs git, and reading
    `cd` as the command is the mistake that locked a fleet out of its own repos (#4)."""
    for tok in tokens:
        if "=" in tok and not tok.startswith("-") and tok.split("=", 1)[0].isidentifier():
            continue                     # VAR=value prefix
        if tok in ("sudo", "command", "nice", "time", "env", "exec", "&"):
            continue                     # a prefix, not the command — keep looking
        return os.path.basename(tok).lower().removesuffix(".exe")
    return None


def _git_subcommand(tokens: list[str]) -> str | None:
    rest = iter(tokens[1:])
    for tok in rest:
        if tok in _GIT_GLOBAL_WITH_VALUE:
            next(rest, None)             # this flag eats its value
            continue
        if tok.startswith("-"):
            continue
        return tok.lower()
    return None                          # bare `git` — prints usage, writes nothing


def _segment_writes(segment: str) -> bool:
    if not segment.strip():
        return False
    if any(t.strip("\"'").lower() not in _NOT_A_FILE and not t.startswith("&")
           for t in _REDIRECT.findall(segment)):
        return True                      # pointed at a file: a write, whatever ran

    tokens = _tokens(segment)
    head = _head(tokens)
    if head is None:
        return False
    if head == "git":
        return _git_subcommand(tokens) in WRITING_GIT
    if head == "sed":
        return "-i" in tokens or any(t.startswith("--in-place") for t in tokens)
    return head in WRITING_SHELL


def shell_writes(command: str) -> bool:
    """Does this shell command mutate a working copy or its history?

    Deliberately NOT over-inclusive, and that is the correction #4 bought at the cost of an
    outage. The old note here — "a false positive costs a lock we'd have taken anyway" — was
    false. A false positive costs the *lease*, and the lease is the only resource there is: a
    session that merely read a file, or asked GitHub about an issue, would hold the repo for ten
    minutes against a session that actually wanted to change it. One unguarded write is a smaller
    failure than a machine where nobody can write at all.

    So: a command writes when we can point at the thing in it that writes — a mutating git verb,
    a mutating command, a redirect into a file. Everything else is a read, including everything
    we do not recognize. The remaining tail (a mutator nobody listed) is issue #2, and it does not
    get closed by widening this list; it gets closed by asking whether the REPO changed instead of
    whether a SHELL ran.

    One function for both shells: the separators and redirect forms overlap, and the mutating
    cmdlets sit in the same set as their POSIX cousins.
    """
    return any(_segment_writes(seg) for seg in _SEPARATORS.split(command or ""))


# --- the per-(session, repo) memory of the last-seen HEAD ----------------------

def _seen_path(session: str, repo: str) -> str:
    d = os.path.join(os.path.dirname(env.record_path(repo)), SEEN_DIR)
    os.makedirs(d, exist_ok=True)
    key = hashlib.sha256(f"{session}:{repo}".encode()).hexdigest()[:16]
    return os.path.join(d, f"{key}.txt")


def remember_head(session: str, repo: str, head: str | None) -> None:
    if not head:
        return
    try:
        with open(_seen_path(session, repo), "w", encoding="utf-8") as f:
            f.write(head)
    except OSError:
        pass


def last_seen_head(session: str, repo: str) -> str | None:
    try:
        with open(_seen_path(session, repo), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def drift_note(session: str, repo: str) -> str | None:
    """The read-side check, packaged: report a move/rewrite since this session last looked,
    and remember where the repo stands now. Returns None when there is nothing to say."""
    verdict = lock.drift(repo, last_seen_head(session, repo))
    remember_head(session, repo, verdict.get("head_commit"))
    if verdict["status"] in ("moved", "rewritten"):
        return verdict["message"]
    return None


# --- the words a refusal and a takeover owe the next session -------------------

def format_held(verdict: dict) -> str:
    lk = verdict["lock"]
    return (
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


def format_handoff(verdict: dict) -> str:
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
    return "\n".join(note)


def gate(repo: str, session: str, intent: str) -> tuple[str | None, list[str]]:
    """Acquire-or-renew ahead of a write: SPEC.md §7.1, harness-independent.

    Returns (denial, notes): `denial` is the refusal text when a live holder is in the way
    (the adapter turns it into its harness's block), else None; `notes` are the messages the
    session should see anyway — the takeover handoff and the commit warning.
    """
    verdict = lock.acquire(repo, session, pid=0, lease_seconds=LEASE_SECONDS, intent=intent)
    if verdict["status"] == "held":
        return format_held(verdict), []

    notes = []
    if verdict["status"] == "acquired" and verdict.get("handoff"):
        notes.append(format_handoff(verdict))
    warn = lock.needs_commit_warning(repo, session)
    if warn:
        notes.append(warn["message"])
    remember_head(session, repo, env.git_head(repo))
    return None, notes
