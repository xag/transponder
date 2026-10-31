"""Work on a branch in a checkout of your own instead of waiting — `python -m transponder.branch`

An agent told NOT CLEAR can take different work, ask its human, wait, or — this — keep the work it
wanted and do it somewhere nobody else is:

    python -m transponder.branch open --repo R --session S
        makes a git worktree beside R, on a local branch, from R's HEAD. Declare there (nobody else
        is in it, so the light is green), work, commit.

    python -m transponder.branch land --repo R --session S
        when the region frees: rebases the branch onto R's branch IN THE WORKTREE, so any conflict
        with the holder's work is resolved where only you are working; then, once you hold the
        paths it changed plus `.git/index` in R, fast-forwards R, removes the worktree and deletes
        the branch. The branch is never pushed, and does not outlive its landing.

Both take the ORIGINAL checkout as --repo; the worktree and branch names are derived from it and
the session, so the two commands need the same arguments and nothing else to remember.

It does not declare on your behalf. Landing writes into R, and a write into R is agreed BEFORE it
happens, by the agent making it, with declare_work — the same as every other write. `land` checks
that you hold what it is about to touch, and says exactly what to declare when you do not.

Exit 0 = done. Exit 1 = not yet (a dirty worktree, or the paths are not yours in R): it says why
and what to do. Exit 2 = git stopped (a rebase conflict, a fast-forward refused): git's own words
follow, and the work is still on the branch, untouched.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from transponder import env, scope


def _top(repo: str) -> str | None:
    ok, out = env.git(repo, "rev-parse", "--show-toplevel")
    return env.canonical(out.splitlines()[-1]) if ok and out else None


def names(top: str, session: str) -> tuple[str, str]:
    """(worktree path, branch) for this checkout and session. A SIBLING of the checkout, never
    inside it: a claim on the original's `**` would otherwise cover the worktree, and the one thing
    the worktree is for is a region that overlaps nobody."""
    tag = re.sub(r"[^A-Za-z0-9-]", "", session)[:8] or "session"
    return (os.path.join(os.path.dirname(top), f"{os.path.basename(top)}.{tag}"),
            f"transponder/{tag}")


def open_(repo: str, session: str) -> int:
    if bad := scope.why_not_a_checkout(repo):
        print(bad)
        return 1
    top = _top(repo)
    path, branch = names(top, session)
    if not os.path.isdir(path):
        ok, out = env.git(top, "worktree", "add", "-b", branch, path, "HEAD")
        if not ok:
            print(f"git would not make the worktree:\n{out}")
            return 2
    print(f"BRANCHED — your own checkout is {path}, on {branch}, from {top}'s HEAD.\n"
          f"It holds what is COMMITTED in {top}: nobody's uncommitted work, and none of the ignored\n"
          f"files (a venv, node_modules, .env) — set those up there if you need them.\n\n"
          f"  1. declare_work(repo=\"{path}\", ...) — nobody else is in it, so it is green.\n"
          f"  2. work, and commit there.\n"
          f"  3. when the region you wanted frees, land it (it tells you what to declare in {top}):\n"
          f"        python -m transponder.branch land --repo \"{top}\" --session \"{session}\"")
    return 0


def land(repo: str, session: str) -> int:
    if bad := scope.why_not_a_checkout(repo):
        print(bad)
        return 1
    top = _top(repo)
    path, branch = names(top, session)
    if not os.path.isdir(path):
        print(f"Nothing to land: there is no worktree at {path}.")
        return 1
    if dirty := env.git_dirty(path):
        print(f"NOT YET — {path} is not clean. Commit, ignore or stash, then land again:\n  "
              + "\n  ".join(dirty))
        return 1
    ok, target = env.git(top, "symbolic-ref", "--short", "HEAD")
    if not ok:
        print(f"{top} is not on a branch (detached HEAD), so there is nothing to land onto.")
        return 1

    ok, out = env.git(path, "rebase", target)
    if not ok:
        print(f"The rebase onto {target} stopped. Resolve it in {path} — that checkout is yours —\n"
              f"`git rebase --continue`, then land again. git said:\n{out}")
        return 2

    changed = env.git_paths_between(path, target, branch)
    need = [p for p in [*changed, ".git/index"] if p]
    held = (scope.mine(session) or {}).get("scope", [])
    missing = [p for p in need if not scope.covers(held, scope.resolve(p, top))]
    if changed and missing:
        others = [c for c in scope.live() if c["session"] != session
                  and any(scope.overlaps(scope.resolve(p, top), r) for p in need for r in c["scope"])]
        listed = ", ".join(f'"{p}"' for p in need)
        print(f"NOT YET — landing writes these in {top}, and you do not hold them all:\n  "
              + "\n  ".join(missing)
              + f"\n\ndeclare_work(repo=\"{top}\", paths=[{listed}], doing=\"landing {branch}\"),"
                f" then land again.")
        for c in others:
            print(f"  agent {c['session']} still holds {', '.join(c['scope'])}"
                  + (f" — {c['intent']}" if c.get("intent") else ""))
        if others:
            print("Wait for them in the background, then declare:\n"
                  f"    python -m transponder.wait --repo \"{top}\" --paths "
                  + " ".join(f'"{p}"' for p in need[:4]) + f" --session \"{session}\"")
        return 1

    if changed:
        ok, out = env.git(top, "merge", "--ff-only", branch)
        if not ok:
            print(f"{top} would not fast-forward to {branch}. The work is still on the branch.\n"
                  f"git said:\n{out}")
            return 2
    for args in (("worktree", "remove", path), ("branch", "-d", branch)):
        ok, out = env.git(top, *args)
        if not ok:
            print(f"Landed, but `git {' '.join(args)}` failed — clean it up by hand:\n{out}")
            return 2
    print(f"LANDED — {len(changed)} path(s) onto {target} in {top}; the worktree and {branch} are gone."
          if changed else f"Nothing had changed on {branch}; the worktree and the branch are gone.")
    print("finish_work() now — somebody may be waiting on exactly this.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m transponder.branch",
        description="Work on a local branch in a worktree of your own, and land it when the "
                    "region frees.")
    ap.add_argument("action", choices=["open", "land"])
    ap.add_argument("--repo", required=True, help="the ORIGINAL checkout, for both actions")
    ap.add_argument("--session", required=True, help="your session id")
    args = ap.parse_args(argv)
    return (open_ if args.action == "open" else land)(args.repo, args.session)


if __name__ == "__main__":
    sys.exit(main())
