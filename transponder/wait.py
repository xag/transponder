"""Wait for a region to come free, without spinning — `python -m transponder.wait --repo R --paths p`

An agent told NOT CLEAR has three honest moves: take different work, ask its human, or wait. This
is how it waits. Launched as a BACKGROUND task, it polls the map and exits the moment nothing
overlaps the paths any more — and a harness that notices a background task exiting is the only
thing in existence that can wake an agent, so exiting IS the notification.

Exit 0 = the region is free, go and declare it. Exit 1 = gave up after --max-minutes; the holder is
still there, and that is worth telling your human about rather than waiting again.

It reads the map and nothing else. No lock, no ticket, no permission: this process is a convenience
for the agent that launched it, and if it never runs, the agent has lost nothing but the notification
— it can call `channel()` again on its next turn and find out the same thing.
"""

from __future__ import annotations

import argparse
import sys
import time

from transponder import scope


def free(repo: str, paths: list[str], session: str = "") -> list[dict]:
    """The live claims that still overlap what we are waiting for. Empty means go."""
    blocking = []
    for p in paths:
        target = scope.resolve(p, repo)
        if not target:
            continue
        for c in scope.live():
            if c["session"] == session or c in blocking:
                continue
            if any(scope.overlaps(target, r) for r in c["scope"]):
                blocking.append(c)
    return blocking


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m transponder.wait",
        description="Exit 0 when nobody holds the given paths any more.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--paths", nargs="+", required=True)
    ap.add_argument("--session", default="", help="your own session id, so your own claim is ignored")
    ap.add_argument("--every", type=float, default=20.0, help="seconds between checks (default 20)")
    ap.add_argument("--max-minutes", type=float, default=60.0, help="give up after this (default 60)")
    args = ap.parse_args(argv)

    deadline = time.time() + args.max_minutes * 60
    while True:
        blocking = free(args.repo, args.paths, args.session)
        if not blocking:
            print("FREE — nobody holds those paths now. declare_work() and go.")
            return 0
        if time.time() >= deadline:
            who = ", ".join(sorted({c["session"] for c in blocking}))
            print(f"STILL HELD after {args.max_minutes:g} min, by: {who}. "
                  "Tell your human rather than waiting again.")
            return 1
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
