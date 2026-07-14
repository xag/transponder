"""The trajectory invariants — claims that hold on EVERY recorded channel call (extra `flight`).

Recordings answer "same?"; invariants answer "right?". The lock's invariants (exclusion, no theft
from the living, never release a dirty tree) died with the lock — there is no exclusion left to
assert. What remains is the one property the whole channel stands on, and it is the one whose
failure is SILENT: a wrong overlap answer does not crash, it double-books a region on the map and
tells two agents they are each alone. Both then work with confidence, which is worse than either
being blocked, and nobody finds out until the diff.

RULE, learned the hard way in the lock era and kept: an invariant judges from what the BOUNDARY
said, never from what the code concluded. An oracle that asks the code under test whether it just
misbehaved is an echo, not a judge — so the overlap relation is REIMPLEMENTED below, and the claim
records are read off the tape as the local `records` that env.read_claims bound.
"""

from __future__ import annotations

import json

import flight_recorder as fr


def _clock(t: fr.Trajectory) -> float | None:
    """`now` is bound by env.now — the lease clock, as the boundary served it."""
    seen = t.trace.values("now")
    return float(seen[0].value) if seen else None


def _touches(a: str, b: str) -> bool:
    """Do two resources overlap? **Deliberately a SECOND implementation, and not scope.overlaps.**

    `scope.overlaps` IS the thing most likely to be wrong, and it fails silently. Twenty lines of
    duplication, and they are the twenty that would catch it.
    """
    a, b = a.strip().replace("\\", "/"), b.strip().replace("\\", "/")
    if a == b:
        return True

    def pre(r):
        # a subtree claim `dir/**` covers everything under `dir/` — canonical paths, one namespace
        return r[:-2] if r.endswith("/**") else None

    pa, pb = pre(a), pre(b)
    if pa and pb:
        return pa.startswith(pb) or pb.startswith(pa)
    if pa:
        return b.startswith(pa)
    if pb:
        return a.startswith(pb)
    return False


@fr.invariant("a channel call never raises — every outcome is a verdict", judges_raise=True)
def channel_calls_return_verdicts(t: fr.Trajectory) -> None:
    # Harness hooks and the MCP server call straight into these. An exception in a hook is a
    # session whose courier goes quiet; an exception in declare is a map in an unknown state.
    if t.fn in ("declare", "extend", "release"):
        assert not t.raised, f"raised {t.error}"
        assert isinstance(t.result, dict) and t.result.get("status"), "no status in the verdict"


@fr.invariant("the map never double-books — a granted scope was free at the moment it was granted")
def scopes_never_overlap(t: fr.Trajectory) -> None:
    """THE claim. The map's entire value is that a region on it belongs to exactly one agent; a
    double-booked map is worse than no map, because it is believed.

    Judged from the boundary: the claim files that were actually on disk at the moment of the
    grant, and an overlap test of its own (`_touches`) that shares no line with the code it judges.
    """
    if t.fn != "declare" or t.raised:
        return
    if (t.result or {}).get("status") != "granted":
        return

    granted = ((t.result or {}).get("claim") or {}).get("scope") or []
    mine = (t.kwargs or {}).get("session")
    now = _clock(t)

    seen = t.trace.values("records")
    for text in (seen[0].value if seen else []) or []:
        try:
            other = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue                            # a torn claim is no claim (SPEC §2)
        if other.get("session") == mine or not other.get("scope"):
            continue
        if now is not None and other.get("expires_at", 0) <= now:
            continue                            # lapsed: it binds nobody

        clash = [(m, o) for m in granted for o in other["scope"] if _touches(m, o)]
        assert not clash, (
            f"granted {granted} to {mine!r} while {other['session']!r} held {other['scope']} "
            f"— overlapping at {clash}. Two agents have just been told they own the same region.")
