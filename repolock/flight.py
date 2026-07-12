"""The repo lock's flight-recorder boundary declaration and wiring.

The nondeterminism boundary of a lock operation is exactly repolock/env.py: the clock (leases
are the design, so `now` is the hottest effect here), process liveness (`pid_alive` — the
crashed-holder case), the lockfile on disk, and git. There is nothing else: repolock/lock.py is
pure logic over this membrane.

flight-recorder is an OPTIONAL dependency (extra `flight`), and this module is the only place
outside the invariants that imports it — callers must import repolock.flight lazily, only when
recording is actually on (see repolock/hooks/claude_code.py and repolock/server.py). Recording
off means zero imports: the lock stays pure stdlib.

Recording is on when REPOLOCK_FLIGHT is set; sessions land in REPOLOCK_FLIGHT_DIR
(default `flight/locks`). Replay: `python -m repolock.replay <session>`.

Why it matters here more than usual: a lock bug is a heisenbug. "Two sessions held it at once"
and "it wouldn't let go after a crash" are both unreproducible by construction — they depend on
a clock, a PID, and an interleaving you cannot re-stage by hand. Recording the boundary is the
only way to ever debug one by reading a variable instead of re-deriving what must have happened.
"""

from __future__ import annotations

import os

import flight_recorder as fr

from repolock import env, lock

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
    """No-op unless REPOLOCK_FLIGHT is set."""
    fr.install(BOUNDARY, lock,
               directory=os.getenv("REPOLOCK_FLIGHT_DIR", os.path.join("flight", "locks")),
               enabled=bool(os.getenv("REPOLOCK_FLIGHT")),
               tool_skip_params=())


class Adapter(fr.ReplayAdapter):
    boundary = BOUNDARY
    trace_root = os.path.dirname(os.path.abspath(__file__))
    skip_files = frozenset({"flight.py", "replay.py"})

    def resolve(self, fn_name: str, feed: fr.Feed):
        fn = getattr(lock, fn_name)
        return getattr(fn, "__flight_wrapped__", fn)
