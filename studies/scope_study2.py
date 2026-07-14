"""The fair version of the study: give v2 EVERY benefit of the doubt and see if it still wins.

Study 1 declared a scope from the session's FIRST written path. That is a strawman — a real agent
declares from its TASK ("fix the MCP hole" -> repolock/**, tests/**, SPEC.md, ledger/**), not from
wherever it happened to land first. It also compared only writer-vs-writer, while v1 refuses READERS
too (a shell that reads takes the lock for its call).

So this one asks the question that cannot be dismissed:

    ORACLE SCOPE. Give every session PERFECT FORESIGHT — declare exactly the set of top-level
    directories it will turn out to touch, no more. That is the best any agent could ever do, and no
    real one will do better. Now: do sessions that were alive at the same time still conflict?

If they conflict even with perfect foresight, v2 cannot buy concurrency — not because agents guess
badly, but because their work genuinely overlaps, and no protocol fixes that. That is a fact about
the work, and it kills the idea cleanly rather than sending us off to build a better guesser.
"""
from __future__ import annotations

import collections
import statistics

from scope_study import committed_paths, load, top


def main():
    obs = load()

    # Every session on a real repo, writers AND readers: v1 gates both.
    sessions = {}
    for (session, repo), seq in obs.items():
        inherited = seq[0]["dirty"]
        touched = set()
        for o in seq:
            touched |= o["dirty"] - inherited
        heads = [h for o in seq for h in o["heads"]]
        if heads and heads[0] != heads[-1]:
            touched |= committed_paths(repo, heads[0], heads[-1])
        sessions[(session, repo)] = {
            "touched": touched, "repo": repo, "wrote": bool(touched),
            "start": seq[0]["t"], "end": seq[-1]["t"], "calls": len(seq),
            "scope": {top(p) for p in touched},          # the ORACLE scope: perfect foresight
        }

    writers = [s for s in sessions.values() if s["wrote"]]
    readers = [s for s in sessions.values() if not s["wrote"]]
    print(f"SESSIONS ON REAL REPOS: {len(sessions)}   writers: {len(writers)}   "
          f"read-only: {len(readers)}")
    if writers:
        sizes = [len(s["touched"]) for s in writers]
        scopes = [len(s["scope"]) for s in writers]
        print(f"  paths written per writing session : median {statistics.median(sizes):.0f}, "
              f"max {max(sizes)}")
        print(f"  top-level dirs it had to reserve  : median {statistics.median(scopes):.0f}, "
              f"max {max(scopes)}")

    # --- the upper bound: perfect foresight, do they STILL collide? ---------------------------
    by_repo = collections.defaultdict(list)
    for (sid, _), s in sessions.items():
        by_repo[s["repo"]].append((sid, s))

    pairs = clash_path = clash_scope = free = 0
    for items in by_repo.values():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ai, a), (bi, b) = items[i], items[j]
                if ai == bi or a["start"] > b["end"] or b["start"] > a["end"]:
                    continue
                pairs += 1
                if a["touched"] & b["touched"]:
                    clash_path += 1                       # same FILE: irreducible, serialise
                elif a["scope"] & b["scope"]:
                    clash_scope += 1                      # same top-level dir: v2 refuses anyway
                else:
                    free += 1                             # v1 refuses these; v2 would run them

    print(f"\nPAIRS OF SESSIONS ALIVE AT THE SAME TIME ON ONE REPO: {pairs}")
    if not pairs:
        print("  NONE. In the whole recorded history there is not one moment where two sessions")
        print("  were alive on the same checkout at once — so the contention v2 exists to relieve")
        print("  does not appear in the evidence at all.")
        return
    print(f"  same FILE (irreducible; serialise under any design) : {clash_path:3} "
          f"({100*clash_path/pairs:.0f}%)")
    print(f"  same top-level dir, with PERFECT FORESIGHT          : {clash_scope:3} "
          f"({100*clash_scope/pairs:.0f}%)")
    print(f"  genuinely disjoint -> v1 REFUSES, v2 would RUN      : {free:3} "
          f"({100*free/pairs:.0f}%)   <- v2's entire winnings")


if __name__ == "__main__":
    main()
