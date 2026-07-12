"""The trajectory oracle: the invariants, replayed against recordings of real lock calls.

A lock's two catastrophic bugs (two live holders; a lock nobody can reclaim) cannot be staged
by hand: they depend on a clock, a PID and an interleaving you don't control. So we plant each
bug INTO the code, replay the recording through it, and assert the oracle condemns it. A suite
that only ever runs correct code proves the code runs — not that it is right.

Needs the `flight` extra; skipped without it.
"""

import os

import pytest

fr = pytest.importorskip("flight_recorder")

from repolock import flight as lock_flight, invariants as lock_invariants, lock  # noqa: E402

DEAD_PID = 999_999
LIVE_PID = os.getpid()


@pytest.fixture
def recorded(repo, tmp_path, monkeypatch):
    """Record a lifecycle: a grant, a refusal, a release, a crashed holder, a takeover."""
    monkeypatch.setenv("REPOLOCK_FLIGHT", "1")
    flightdir = tmp_path / "flight"
    monkeypatch.setenv("REPOLOCK_FLIGHT_DIR", str(flightdir))
    lock_flight.install()
    try:
        lock.acquire(repo, "A", LIVE_PID, 600, "work")          # 0 acquired
        lock.acquire(repo, "B", LIVE_PID, 600, "work")          # 1 held
        lock.release(repo, "A")                                 # 2 released
        lock.acquire(repo, "CRASHED", DEAD_PID, 3600, "crash")  # 3 acquired
        lock.acquire(repo, "B", LIVE_PID, 600, "takeover")      # 4 takeover
    finally:
        fr.uninstall()
    name = sorted(os.listdir(flightdir))[0]
    return fr.Recording.load(flightdir / name)


def check(handle):
    return handle.check(lock_flight.Adapter(), lock_invariants)


def test_every_claim_holds_on_every_recorded_call(recorded):
    for i, call in enumerate(recorded.calls):
        report = check(recorded.call(i))
        assert report.ok, f"call {i} ({call['fn']}):\n{fr.format_invariant_report(report)}"


def test_the_oracle_condemns_a_stolen_live_lease(recorded):
    """NEGATIVE CONTROL. Plant the classic lock bug — a lease comparison the wrong way round, so
    every holder looks lapsed — and tell the boundary the holder is alive after all. The code
    then grants a lock over a living session. If the oracle stays green here, it is decoration.

    Note it must catch this WITHOUT trusting `prior_live`: that local is exactly what the bug
    corrupts. It recomputes liveness from the record, the clock and the PID answer instead.
    """
    real = lock._lapsed
    lock._lapsed = lambda lk, now: True
    try:
        handle = recorded.call(4)
        handle.effect("pid_alive").result = True
        report = check(handle)
    finally:
        lock._lapsed = real

    assert report.outcome == "violated"
    violated = " ".join(str(v) for v in report.violations)
    assert "two live sessions never hold the same working copy" in violated
    assert "never stolen" in violated


def test_the_oracle_condemns_a_released_dirty_tree(recorded):
    """NEGATIVE CONTROL. Stop enforcing "commit fast" and hand back a checkout with uncommitted
    work in it — the next session would walk straight into someone else's half-finished edits."""
    real = lock._may_release
    lock._may_release = lambda dirty_, force: True
    try:
        handle = recorded.call(2)
        handle.effect("git_dirty").result = [" M scratch.txt"]
        report = check(handle)
    finally:
        lock._may_release = real

    assert report.outcome == "violated"
    assert "dirty working tree is never handed" in " ".join(str(v) for v in report.violations)
