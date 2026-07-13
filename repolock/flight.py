"""The repo lock's flight-recorder boundary declaration and wiring.

The nondeterminism boundary of a lock operation is exactly repolock/env.py: the clock (leases
are the design, so `now` is the hottest effect here), process liveness (`pid_alive` — the
crashed-holder case), the lockfile on disk, and git. There is nothing else: repolock/lock.py is
pure logic over this membrane.

flight-recorder is an OPTIONAL dependency (extra `flight`), and this module is the only place
outside the invariants that imports it — callers must import repolock.flight lazily (see
repolock/hooks/claude_code.py and repolock/server.py), so an install without the extra still runs
a pure-stdlib lock.

**Recording is ON by default**, and switching it on was paid for the hard way. It used to be
opt-in behind REPOLOCK_FLIGHT, on the reasoning that the import is a per-write tax nobody should
pay for nothing. Then the gate starved a two-session fleet (xag/repolock#4) and there was no tape
— the incident had to be reconstructed from the harness's own transcripts, which happened to
exist and were never designed to answer this. An opt-in recorder is off precisely when you need
it, because you do not know in advance which hour is the interesting one. Set REPOLOCK_FLIGHT=0
to turn it off.

Sessions land in REPOLOCK_FLIGHT_DIR, default `~/.repolock/flight` — **absolute, and outside
every repo**, for the same reason the lockfile is (SPEC.md §1): the hook runs with cwd set to the
session's own checkout, so the old relative default (`flight/locks`) would have dropped a
recording directory inside every repo on the machine and shown up in `git status` as an edit of
its own. A recorder that dirties the tree it is watching is not an option.

Why it matters here more than usual: a lock bug is a heisenbug. "Two sessions held it at once"
and "it wouldn't let go after a crash" are both unreproducible by construction — they depend on
a clock, a PID, and an interleaving you cannot re-stage by hand. Recording the boundary is the
only way to ever debug one by reading a variable instead of re-deriving what must have happened.
"""

from __future__ import annotations

import os

import flight_recorder as fr

from repolock import env, lock


# `recording()` and `flight_dir()` live in env.py, NOT here: a caller has to be able to ask "is
# recording on?" WITHOUT importing this module, because importing this module is what pulls in
# flight_recorder. Asking the question must not be the thing that answers it.

BOUNDARY = fr.Boundary(
    effects=[
        (env, [
            "now",                 # leases: the clock is not incidental here, it is the design
            "pid_alive",           # crashed holder
            "lock_dir", "canonical", "record_path",
            "read_record", "write_record", "remove_record",
            "git_head", "git_dirty", "git_log_between", "git_commit_exists",
        ]),
    ],
    constants=[(lock, "DEFAULT_LEASE_SECONDS"),
               (lock, "MAX_LEASE_SECONDS"),
               (lock, "WARN_BEFORE_SECONDS")],
)


def install() -> None:
    """On by default; REPOLOCK_FLIGHT=0 turns it off."""
    fr.install(BOUNDARY, lock,
               directory=env.flight_dir(),
               enabled=env.recording(),
               tool_skip_params=())


class Adapter(fr.ReplayAdapter):
    boundary = BOUNDARY
    trace_root = os.path.dirname(os.path.abspath(__file__))
    skip_files = frozenset({"flight.py", "replay.py"})

    def resolve(self, fn_name: str, feed: fr.Feed):
        fn = getattr(lock, fn_name)
        return getattr(fn, "__flight_wrapped__", fn)
