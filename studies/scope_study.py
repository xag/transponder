"""SPEC-v2 §10.1, answered from the tapes rather than from taste.

The question that decides whether negotiated scopes work: DO AGENTS KNOW WHERE THEY WILL WRITE?
If a session's declared scope is routinely wrong, the violation alarm fires constantly, an alarm
that always fires is one nobody reads, and v2 dies of false positives.

This is answerable without building anything, because the fingerprint already records
`git status --porcelain` on every hook call. So for every real session on this machine we know the
paths it had dirty, in order. From that:

  touched   the paths a session made dirty (minus what was ALREADY dirty when it arrived — that is
            someone else's work, not this session's)
  + commits recovered from the repo itself: a file created AND committed inside one tool call never
            appears dirty on any tape, so HEAD movement is chased into `git log --name-only`.
            Without this the study would silently miss exactly the sessions that commit, which are
            the ones that matter most for `git:index`.

Then the two numbers that decide it:

  PREDICTABILITY  declare a scope from where you FIRST write; how much of what you write later
                  falls outside it? That is the alarm rate.
  CONCURRENCY     do sessions that overlap in TIME also overlap in PATHS? If they always do, scopes
                  buy nothing: they would conflict and serialise anyway.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import subprocess
from datetime import datetime

FLIGHT = os.path.expanduser("~/.transponder/flight")


def porcelain_paths(lines):
    """Paths out of `git status --porcelain` lines. Renames name two paths; both were touched."""
    out = set()
    for ln in lines or []:
        if not ln or len(ln) < 4:
            continue
        rest = ln[3:].strip()
        for part in rest.split(" -> "):
            p = part.strip().strip('"')
            if p:
                out.add(p.replace("\\", "/"))
    return out


def load():
    """(session, repo) -> ordered observations. One flight file == one hook process == one tool
    call of one session, which is what lets an un-sessioned `fingerprint` call be attributed."""
    obs = collections.defaultdict(list)
    for path in glob.glob(os.path.join(FLIGHT, "*.jsonl")):
        started, session, repo, dirty, heads = None, None, None, set(), []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    if r.get("ev") == "session":
                        started = r.get("started")
                        continue
                    if r.get("ev") != "call":
                        continue
                    kw = r.get("kwargs") or {}
                    repo = repo or kw.get("repo")
                    session = session or kw.get("session")
                    for e in r.get("events") or []:
                        if e.get("fn") == "transponder.env.git_dirty":
                            dirty |= porcelain_paths(e.get("res"))
                        elif e.get("fn") == "transponder.env.git_head" and e.get("res"):
                            heads.append(e["res"].strip())
        except (OSError, json.JSONDecodeError, ValueError):
            continue

        if not (session and repo and started):
            continue
        norm = repo.lower().replace("\\", "/")
        if "/projects/" not in norm or "pytest" in norm or "temp" in norm:
            continue                       # the suite's own temp repos are not sessions
        obs[(session, norm)].append({"t": datetime.fromisoformat(started),
                                     "dirty": dirty, "heads": heads})
    for k in obs:
        obs[k].sort(key=lambda o: o["t"])
    return obs


def committed_paths(repo, base, head):
    """The paths in base..head. Recovers the writes that never appear dirty on any tape, because
    the session created and committed them inside a single tool call."""
    real = repo.replace("/", os.sep)
    if not os.path.isdir(real):
        return set()
    try:
        r = subprocess.run(["git", "log", "--name-only", "--pretty=format:", f"{base}..{head}"],
                           cwd=real, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    if r.returncode != 0:
        return set()
    return {ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()}


def top(p):
    return p.split("/")[0]


def main():
    obs = load()
    sessions = {}

    for (session, repo), seq in obs.items():
        inherited = seq[0]["dirty"]                     # dirty on arrival == not this session's
        touched, ordered = set(), []
        for o in seq:
            for p in sorted(o["dirty"] - inherited - touched):
                ordered.append(p)                       # first time WE saw this path go dirty
            touched |= o["dirty"] - inherited

        heads = [h for o in seq for h in o["heads"]]
        moved = bool(heads) and heads[0] != heads[-1]
        if moved:                                       # chase the commits we never saw dirty
            for p in sorted(committed_paths(repo, heads[0], heads[-1])):
                if p not in touched:
                    ordered.append(p)
                    touched.add(p)

        if not touched:
            continue                                    # a read-only session: nothing to scope
        sessions[(session, repo)] = {
            "touched": touched, "ordered": ordered, "committed": moved,
            "start": seq[0]["t"], "end": seq[-1]["t"], "repo": repo,
        }

    print(f"WRITING SESSIONS: {len(sessions)}   "
          f"repos: {len({s['repo'] for s in sessions.values()})}   "
          f"(read-only sessions have no scope to declare and are excluded)\n")

    # --- 1. can a scope even be narrow? ------------------------------------------------------
    tops = collections.Counter(len({top(p) for p in s["touched"]}) for s in sessions.values())
    n = len(sessions)
    print("HOW WIDE IS A SESSION, in top-level dirs of the repo it wrote:")
    for k in sorted(tops):
        print(f"  {k:2} dir(s): {tops[k]:4}  {100*tops[k]/n:5.1f}%  {'#' * (40*tops[k]//n)}")
    one = sum(v for k, v in tops.items() if k == 1)
    print(f"  -> {100*one/n:.0f}% of writing sessions stayed inside ONE top-level directory\n")

    # --- 2. THE NUMBER: declare from your first write; how often are you wrong? ---------------
    print("PREDICTABILITY — scope declared from the FIRST path written, then how much of the rest "
          "lands outside it.\nThis is the alarm rate. An alarm that always fires is one nobody reads.")
    for label, keyfn in (("top-level dir  (app/**)", top),
                         ("directory      (app/api/**)", lambda p: os.path.dirname(p) or ".")):
        clean = viol = late = 0
        for s in sessions.values():
            if len(s["ordered"]) < 2:
                clean += 1                              # one path: the declaration cannot be wrong
                continue
            scope = {keyfn(s["ordered"][0])}
            out = [p for p in s["ordered"][1:] if keyfn(p) not in scope]
            late += len(out)
            if out:
                viol += 1
            else:
                clean += 1
        print(f"\n  scope = {label}")
        print(f"    sessions that never left it : {clean:4}  ({100*clean/n:.0f}%)")
        print(f"    sessions that wrote outside : {viol:4}  ({100*viol/n:.0f}%)  <- alarm fires")
        print(f"    out-of-scope writes, total  : {late}")

    # --- 3. would scopes buy any concurrency? ------------------------------------------------
    by_repo = collections.defaultdict(list)
    for k, s in sessions.items():
        by_repo[s["repo"]].append((k[0], s))
    conc = disjoint = clash = 0
    for repo, items in by_repo.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i][1], items[j][1]
                if items[i][0] == items[j][0]:
                    continue
                if a["start"] > b["end"] or b["start"] > a["end"]:
                    continue                            # never alive at the same time
                conc += 1
                if a["touched"] & b["touched"]:
                    clash += 1
                else:
                    disjoint += 1
    print(f"\n\nCONCURRENCY — pairs of DIFFERENT sessions alive at the same time on the same repo:")
    print(f"  overlapping in time      : {conc}")
    if conc:
        print(f"  ...and in PATHS (clash)  : {clash:4}  ({100*clash/conc:.0f}%)  "
              f"— these serialise under v2 too, as they must")
        print(f"  ...disjoint paths        : {disjoint:4}  ({100*disjoint/conc:.0f}%)  "
              f"— these are refused by v1 and WOULD RUN CONCURRENTLY under v2")

    # --- 4. git:index ------------------------------------------------------------------------
    committed = sum(1 for s in sessions.values() if s["committed"])
    print(f"\n\ngit:index — sessions that moved HEAD (and so must reserve the index, serialising "
          f"with every other committer):\n  {committed} / {n}  ({100*committed/n:.0f}%)")


if __name__ == "__main__":
    main()
