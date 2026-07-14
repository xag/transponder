"""The witness: what actually happened to a working copy. Pure logic over `env`, all on tape.

This module is what survived of the lock. v1's mutex, leases, takeovers, tickets and waiters are
gone — the project no longer refuses anyone anything — but the two observations underneath them
were always the sound core, and they carry the whole of v2:

  snapshot / written_between   the paths a tool call ACTUALLY wrote. A fact, not a guess about a
                               command: v1 §7a proved that guessing is undecidable, and observation
                               is the answer that never had to be retracted.

  drift                        the stale reader. Nothing corrupted, nothing blocked — a session
                               reasoning about commits a concurrent rebase already destroyed. The
                               check that caught the founding incident, and the one part of this
                               library that was never wrong.

A contract nobody checks is a wish. The claims registry (scope.py) says who INTENDS to write where;
this module says who DID — and the difference between those two answers, delivered loudly to the
agent that caused it, is the entire enforcement model now.
"""

from __future__ import annotations

import os

from transponder import env


def snapshot(repo: str) -> dict:
    """The working copy, itemised: path -> (porcelain status, stat), plus HEAD.

    The stat is load-bearing: a file that is already ` M` stays ` M` when it is edited again — the
    status line does not move, but the bytes do. Files git ignores are deliberately not seen; the
    witness reports on what git tracks.
    """
    repo = env.canonical(repo)
    out = {"HEAD": env.git_head(repo) or "-"}
    for line in env.git_dirty(repo):
        path = line[3:].strip().strip('"').split(" -> ")[-1]
        out[path] = f"{line[:2]}|{env.file_stat(os.path.join(repo, path))}"
    return out


def written_between(repo: str, before: dict, after: dict) -> list[str]:
    """The paths a tool call actually wrote. A fact, not a guess about a command.

    A commit is chased into the object graph rather than inferred: a file created AND committed
    inside one tool call is never dirty at either end, so it appears in NEITHER porcelain — and it
    is precisely the case that matters, because `git add -A` sweeping another agent's half-finished
    work into your commit is the founding incident of this library (SPEC §1a).
    """
    paths = {p for p in set(before) | set(after)
             if p != "HEAD" and before.get(p) != after.get(p)}
    b, a = before.get("HEAD"), after.get("HEAD")
    if b and a and b != a and b != "-" and a != "-":
        paths |= set(env.git_paths_between(env.canonical(repo), b, a))
    return sorted(paths)


def drift(repo: str, seen_head: str | None) -> dict:
    """The read-side check, and the cheapest thing in this library.

    A session that only *read* a repo still holds a picture of it, and that picture goes stale the
    moment another session rebases — which is exactly the damage in the founding incident: not a
    corrupted file, but a session confidently reasoning about commits that no longer existed.
    Compare the HEAD a session last saw against the HEAD that is there now.
    """
    repo = env.canonical(repo)
    head = env.git_head(repo)
    if not seen_head or not head or seen_head == head:
        return {"status": "current", "repo": repo, "head_commit": head}

    gone = not env.git_commit_exists(repo, seen_head)
    return {
        "status": "rewritten" if gone else "moved",
        "repo": repo,
        "seen_head": seen_head,
        "head_commit": head,
        "commits_since": [] if gone else env.git_log_between(repo, seen_head, head),
        "message": (
            f"History was REWRITTEN under you: the commit you last saw ({seen_head[:7]}) no "
            f"longer exists; HEAD is now {head[:7]}. Anything you remember about this repo's "
            "commits is suspect — re-read before acting."
            if gone else
            f"{repo} moved from {seen_head[:7]} to {head[:7]} since you last looked."),
    }
