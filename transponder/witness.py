"""The witness: what actually happened to a working copy. Pure logic over `env`, all on tape.

This module is what survived of the lock. v1's mutex, leases, takeovers, tickets and waiters are
gone — the project no longer refuses anyone anything — but the two observations underneath them
were always the sound core, and they carry the whole of v2:

  drift                        the stale reader. Nothing corrupted, nothing blocked — a session
                               reasoning about commits a concurrent rebase already destroyed. The
                               check that caught the founding incident, and the one part of this
                               library that was never wrong.

snapshot/written_between stood here and are deleted. They reported the paths a tool call "actually
wrote", and that was the one thing they could not do: a fingerprint proves the TREE MOVED, and with
two agents running it cannot tell an author from a bystander. What is left is the check that was
never wrong, and it asks about the reader rather than about anyone else's writes.
"""

from __future__ import annotations

import os

from transponder import env


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
