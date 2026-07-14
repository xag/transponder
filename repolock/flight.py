"""The flight-recorder boundary declaration and wiring (extra `flight`).

The nondeterminism boundary is exactly repolock/env.py: the clock (claim leases), the claim files
on disk, and git. repolock/scope.py and repolock/witness.py are pure logic over this membrane.

**The tape IS the trial's evidence.** The question the whole design bets on — do agents contain
their work once containment is visible? — is answered by reading declares, conflicts and witnessed
violations off recordings, not by asking the agents how they think they did. So recording is ON by
default (REPOLOCK_FLIGHT=0 to disable), a default that was bought the hard way: the recorder used
to be opt-in, and when the old gate starved a two-session fleet (#4) there was no tape.

Sessions land in REPOLOCK_FLIGHT_DIR, default `~/.repolock/flight` — absolute, and outside every
repo, so the recorder never dirties the tree it is watching.

flight-recorder is an OPTIONAL dependency, and this module is the only place outside the invariants
that imports it — callers import repolock.flight lazily, so an install without the extra still runs
a pure-stdlib courier. A missing recorder costs the tape, never the notes.
"""

from __future__ import annotations

import inspect
import os

import flight_recorder as fr

from repolock import env, scope, witness

# `recording()` and `flight_dir()` live in env.py, NOT here: a caller has to be able to ask "is
# recording on?" WITHOUT importing this module, because importing this module is what pulls in
# flight_recorder. Asking the question must not be the thing that answers it.

BOUNDARY = fr.Boundary(
    effects=[
        (env, [
            "now",                 # claim leases: the clock is the decay of information
            "lock_dir", "canonical",
            # the claims map — every effect a declare/conflict verdict rests on has to be on tape,
            # or "did agents contain themselves?" is answered by asking them
            "claims_dir", "claim_path", "read_claims", "write_claim", "remove_claim",
            # the witness — what actually happened to the working copy
            "git_head", "git_dirty", "file_stat",
            "git_paths_between",   # the commit that swept another agent's work
            "git_tracked_dirs",    # what is free, for the conflict answer
            "git_log_between", "git_commit_exists",   # the drift check
        ]),
    ],
    constants=[(scope, "LEASE_SECONDS")],
)


def install() -> None:
    """On by default; REPOLOCK_FLIGHT=0 turns it off."""
    fr.install(BOUNDARY, scope,
               directory=env.flight_dir(),
               enabled=env.recording(),
               tool_skip_params=())
    _also_record(witness)


def _also_record(module) -> None:
    """Record a SECOND tools module — operations live in two (scope: the map; witness: the facts),
    and `fr.install` wraps exactly one and is idempotent (xag/flight-recorder#28). The recorder's
    OWN wrapper is reused rather than a hand-rolled one: an uninstrumented fake is relocated
    guessing, and that rule bites hardest when the thing being faked is the instrument."""
    from flight_recorder import record as _rec

    if _rec.hook.mode != "record":
        return                        # recording is off, or the install rolled back: wrap nothing
    for name, fn in list(vars(module).items()):
        if (callable(fn) and not name.startswith("_") and not inspect.isclass(fn)
                and getattr(fn, "__module__", "") == module.__name__):
            _rec._patch(module, name, _rec._wrap_tool(fn, ()))


class Adapter(fr.ReplayAdapter):
    boundary = BOUNDARY
    trace_root = os.path.dirname(os.path.abspath(__file__))
    skip_files = frozenset({"flight.py", "replay.py"})

    def resolve(self, fn_name: str, feed: fr.Feed):
        module = scope if hasattr(scope, fn_name) else witness   # two tool modules, one tape
        fn = getattr(module, fn_name)
        return getattr(fn, "__flight_wrapped__", fn)
