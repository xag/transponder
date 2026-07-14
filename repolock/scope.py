"""Negotiated scopes — SPEC. Pure logic over `env`; every effect is on the boundary and on tape.

**This is a TRIAL (SPEC §8).** The claim it tests is not about code, it is about behaviour:
*agents will contain their work once containment is visible and rewarded.* It cannot be settled by
argument, and it cannot be settled from v1's tapes either — those record agents who were never
offered the deal, and reasoning from them is the Lucas critique. So it is run, with the recorder on,
and §11b's falsifiers decide.

**The namespace is the local filesystem.** Every resource in a scope is a canonical absolute path —
realpath + normcase, the same canonicalisation the lockfile has always used for repos — either one
file or a subtree (`.../**`). One namespace, one overlap relation (the prefix), and the conflict
answer can always name the exact INTERSECTION, so "come back narrower" is computed rather than
guessed. There are no other namespaces, and that is the point:

  - `git:index` was never anything but a file. It is `<repo>/.git/index` — reserve it like any
    path before you commit, release it after. `git:HEAD` is `<repo>/.git/HEAD`. The resources
    §1a made special collapse into ordinary paths, with no second overlap relation to get wrong.
  - aliasing is dead on arrival: two spellings of one file (case, symlinks, junctions, `..`)
    canonicalise to one string, so "whom do we inform?" is always answerable and never broadcast —
    the claim store is the routing table, and overlap computes the addressees.
  - what does not fit a filesystem (a port, a service) is not reservable, deliberately. A name
    without a witness is a contract nobody can check; it can earn its way in later.

**Nothing here refuses anything.** A conflicting `declare` is not recorded — the registry will
not double-book a region — but no tool call is ever blocked on account of it: the agent is told who
holds what, down to the exact intersection, and decides for itself. The registry is a shared map,
the leases are how stale information decays, and the witness (witness.py) is how the map is checked
against what actually happened. That is the whole enforcement model.
"""

from __future__ import annotations

import json
import os

from repolock import env

LEASE_SECONDS = 900


# --- resources: canonical paths, and nothing else (SPEC §1) -----------------------------------

def canon(path: str) -> str:
    """One true spelling: absolute, symlinks resolved, case-normalised, forward slashes."""
    return env.canonical(path).replace("\\", "/")


def resolve(resource: str, anchor: str) -> str | None:
    """A resource as the agent spelt it -> its canonical form, or None if it is not expressible.

    `anchor` (the checkout the agent is talking about) resolves relative spellings, so the tools
    keep their ergonomics — an agent says `api/**` and means `<anchor>/api/**`. `**` alone is the
    whole checkout: the degenerate case, spelt out.

    Everything else is refused rather than guessed at. A general glob has no decidable overlap, and
    a named resource (`git:index`, `port:3000`) is either secretly a file — then say the file — or
    it is a contract without a witness, which this trial does not sell.
    """
    r = (resource or "").strip().replace("\\", "/")
    if not r:
        return None
    if r == "**":
        return canon(anchor) + "/**"

    subtree = r.endswith("/**")
    base = r[:-3] if subtree else r
    base = base.rstrip("/")
    if not base or any(ch in base for ch in "*?[") or ":" in base.replace(":/", "", 1)[2:]:
        return None
    if not os.path.isabs(base.replace("/", os.sep)) and ":" not in base[:2]:
        base = os.path.join(anchor, base)
    return canon(base) + ("/**" if subtree else "")


def why_bad(resource: str) -> str:
    return (f"{resource!r}: a resource is a filesystem path — one file, or a subtree spelt "
            f"`dir/**`, or `**` for the whole checkout. A glob has no decidable overlap, and a "
            f"named resource is either secretly a file (git's index is `<repo>/.git/index` — "
            f"reserve that) or a contract no witness can check.")


def _prefix(resource: str) -> str | None:
    """The directory a subtree covers, or None for a single file."""
    return resource[:-2] if resource.endswith("/**") else None


def overlaps(a: str, b: str) -> bool:
    """Do two canonical resources touch? The whole protocol rests on this being right."""
    if a == b:
        return True
    pa, pb = _prefix(a), _prefix(b)
    if pa and pb:
        return pa.startswith(pb) or pb.startswith(pa)
    if pa:
        return b.startswith(pa)
    if pb:
        return a.startswith(pb)
    return False


def intersection(a: str, b: str) -> str | None:
    """The exact region two resources share — what a conflict NAMES, so the refused agent can
    subtract it and come back with the rest instead of guessing at a spelling that might fit."""
    if not overlaps(a, b):
        return None
    pa, pb = _prefix(a), _prefix(b)
    if pa and pb:
        return a if pa.startswith(pb) else b     # the deeper subtree
    return b if pa else a                        # a file inside a subtree: the file


def conflicts(mine: list[str], theirs: list[str]) -> list[tuple[str, str, str]]:
    """(mine, theirs, the intersection), for every touching pair."""
    return [(m, t, intersection(m, t)) for m in mine for t in theirs if overlaps(m, t)]


def covers(scope: list[str], path: str) -> bool:
    """Is this canonical path inside this scope? What the witness and the heads-up check ask."""
    return any(overlaps(r, path) for r in scope)


# --- the claims ---------------------------------------------------------------------------------

def _live(now: float) -> list[dict]:
    # `records` is bound to a local ON PURPOSE, and it is not a style choice. The oracle judges from
    # the boundary's own answer, and it reads that answer off the tape as a LOCAL BINDING
    # (invariants.scopes_never_overlap, via t.trace.values). Inline this into the `for` and the
    # claims that were actually on disk never reach the tape — and the invariant that is supposed to
    # catch two agents being handed the same region goes vacuously green, which is the single most
    # dangerous state this library can be in.
    records = env.read_claims()
    out = []
    for text in records:
        try:
            claim = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue                           # a torn claim is no claim (SPEC §2)
        if claim.get("expires_at", 0) > now and claim.get("scope"):
            out.append(claim)
    return out


def live() -> list[dict]:
    """Every claim that still binds, machine-wide. A lapsed claim is nobody's: leases are the
    backstop here for the same reason as in v1 — a crashed agent must not hold a region for ever."""
    return _live(env.now())


def touching(root: str) -> list[dict]:
    """The live claims that reach into one checkout — what `scopes(repo)` shows, and what the
    courier tells a session that walks into a shared repo."""
    tree = canon(root) + "/**"
    return [c for c in live() if any(overlaps(tree, r) for r in c["scope"])]


def mine(session: str) -> dict | None:
    return next((c for c in live() if c["session"] == session), None)


def declared(session: str) -> bool:
    """Has this agent opted into the trial? Machine-global, like the claims themselves: an agent
    that has declared ANYWHERE is working by reservation, and its writes elsewhere are judged
    against its scope (and auto-extend over unclaimed ground) rather than by the v1 mutex."""
    return mine(session) is not None


def scope_of(session: str) -> list[str]:
    claim = mine(session)
    return claim["scope"] if claim else []


def _write(session: str, scope: list[str], intent: str, now: float,
           acquired_at: float | None = None) -> dict:
    claim = {
        "session": session, "scope": sorted(set(scope)), "intent": intent,
        "acquired_at": acquired_at or now, "renewed_at": now,
        "expires_at": now + LEASE_SECONDS, "lease_seconds": LEASE_SECONDS,
    }
    env.write_claim(session, json.dumps(claim, indent=2, sort_keys=True))
    return claim


def declare(anchor: str, session: str, resources: list[str], intent: str = "") -> dict:
    """Reserve a scope. **All-or-nothing** — granted entire, or not at all (§3).

    Not a preference: it is conservative two-phase locking, and it is what keeps the HAPPY path free
    of deadlock. Grant it piecemeal and you have incremental acquisition, which is where the cycle
    lives. `extend` is the one place incremental acquisition survives, and it never blocks — §5.

    A conflict is an ANSWER (§2): who holds what, the exact intersection, and what is free — so the
    refused agent takes something narrower and works NOW, instead of waiting or guessing.
    """
    now = env.now()

    scope = []
    for r in resources:
        c = resolve(r, anchor)
        if not c:
            return {"status": "rejected", "reason": why_bad(r)}
        scope.append(c)

    others = [c for c in _live(now) if c["session"] != session]
    clash = [(c, conflicts(scope, c["scope"])) for c in others]
    clash = [(c, hits) for c, hits in clash if hits]
    if clash:
        return {"status": "conflict", "scope": scope,
                "conflicts": [{"session": c["session"], "scope": c["scope"],
                               "intent": c.get("intent") or "",
                               "held_for": int(now - c.get("acquired_at", now)),
                               "intersection": sorted({hit[2] for hit in hits})}
                              for c, hits in clash],
                "free_hint": _free_hint(anchor, others)}

    was = mine(session)
    claim = _write(session, scope, intent, now, acquired_at=was["acquired_at"] if was else None)
    return {"status": "granted", "claim": claim}


def extend(anchor: str, session: str, add: list[str], intent: str = "") -> dict:
    """Widen a scope you already hold — **the genuinely hard operation** (§5).

    An agent discovers mid-task that it must touch one more module. It cannot release and re-declare
    — it is holding uncommitted work, and releasing a dirty tree is refused (v1 §5). So this IS
    incremental acquisition, and incremental acquisition is where deadlock lives.

    v2 does not answer that with a wait-for graph. It answers it by **never blocking**: this returns
    `granted` or `conflict`, immediately, and the agent negotiates or commits and re-declares from a
    clean tree. An agent that SPINS here, waiting for the other to yield while holding what the
    other wants, is the one shape of deadlock v2 admits — so it must not.
    """
    claim = mine(session)
    if not claim:
        return declare(anchor, session, add, intent)
    return declare(anchor, session, list(claim["scope"]) + list(add),
                   intent or claim.get("intent", ""))


def release(session: str, drop: list[str] | None = None, anchor: str = "") -> dict:
    """Let go — of everything, or of the entries named in `drop` (narrowing, which is what a
    please-narrow asks for). Dropping the last entry removes the claim and the agent falls back to
    working under v1."""
    claim = mine(session)
    if not claim:
        return {"status": "ok", "scope": []}

    if drop:
        gone = {resolve(d, anchor or os.getcwd()) for d in drop}
        keep = [r for r in claim["scope"] if r not in gone]
    else:
        keep = []
    if not keep:
        env.remove_claim(session)
        return {"status": "ok", "scope": []}
    return {"status": "ok",
            "scope": _write(session, keep, claim.get("intent", ""), env.now(),
                            claim["acquired_at"])["scope"]}


def release_under(session: str, root: str) -> None:
    """Give back everything inside one checkout — the Stop boundary, when its tree is clean."""
    claim = mine(session)
    if not claim:
        return
    tree = canon(root) + "/**"
    keep = [r for r in claim["scope"] if not overlaps(tree, r)]
    if keep:
        _write(session, keep, claim.get("intent", ""), env.now(), claim["acquired_at"])
    else:
        env.remove_claim(session)


def renew(session: str) -> None:
    """Activity renews the lease, exactly as in v1 §3 — a tool call IS the activity, and an agent
    that has gone home stops renewing and lets go on its own."""
    claim = mine(session)
    if claim:
        _write(session, claim["scope"], claim.get("intent", ""), env.now(),
               claim["acquired_at"])


def _free_hint(anchor: str, others: list[dict]) -> list[str]:
    """Top-level directories of the anchor checkout nobody has claimed. A conflict must be an
    ANSWER, not a refusal (§2): 'that region is taken' leaves an agent stuck; 'that region is
    taken, these are free' does not."""
    taken = [r for c in others for r in c["scope"]]
    root = canon(anchor)
    # A subtree at or above the checkout root covers the whole checkout: nothing here is free.
    if any(p and (root + "/").startswith(p) for p in map(_prefix, taken)):
        return []
    free = []
    for entry in sorted(env.git_tracked_dirs(anchor)):
        if not any(overlaps(f"{root}/{entry}/**", t) for t in taken):
            free.append(f"{entry}/**")
    return free[:12]


# --- the witness (SPEC §4) -------------------------------------------------------------------

def violations(session: str, written: list[str]) -> list[dict]:
    """Canonical paths this agent wrote OUTSIDE its own scope, and whose region another agent had
    reserved.

    This is what a shell or an MCP call gets instead of a gate: the target of those is not declared
    and v1 §7a is the standing proof it cannot be recovered from the text, so the write is WITNESSED
    rather than prevented. §7a is explicit that this is a real loss, and it is the trade the trial
    is testing.

    A write outside your scope that lands in NOBODY's region is untidy, not dangerous — it is
    reported to you (you evidently meant to declare it) but it is not a violation against anyone.
    """
    my_scope = scope_of(session)
    others = [c for c in live() if c["session"] != session]

    out = []
    for path in written:
        if covers(my_scope, path):
            continue
        for c in others:
            if covers(c["scope"], path):
                out.append({"path": path, "victim": c["session"], "scope": c["scope"],
                            "intent": c.get("intent") or ""})
                break
    return out


def stray(session: str, written: list[str]) -> list[str]:
    """Wrote outside your own scope, into nobody's region. Not a violation — a missing declaration."""
    my_scope = scope_of(session)
    others = [c for c in live() if c["session"] != session]
    return [p for p in written
            if not covers(my_scope, p) and not any(covers(c["scope"], p) for c in others)]
