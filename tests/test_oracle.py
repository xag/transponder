"""The trajectory oracle: the invariants, replayed against recordings of real channel calls.

The map's catastrophic bug cannot be staged by a normal test, because it does not crash: a wrong
overlap answer silently double-books a region, two agents are each told they are alone, and both
work with confidence. So the bug is PLANTED into the code, the recording is replayed through it,
and the oracle must condemn it — an oracle that stays green here is decoration.

Needs the `flight` extra; skipped without it.
"""

import json
import os

import pytest

fr = pytest.importorskip("flight_recorder")

from transponder import flight as scope_flight, invariants, scope  # noqa: E402


@pytest.fixture
def recorded_scopes(repo, tmp_path, monkeypatch):
    """A channel lifecycle: a grant, a disjoint grant, and a conflict."""
    monkeypatch.setenv("TRANSPONDER_FLIGHT", "1")
    flightdir = tmp_path / "flight-scopes"
    monkeypatch.setenv("TRANSPONDER_FLIGHT_DIR", str(flightdir))
    scope_flight.install()
    try:
        scope.declare(repo, "A", ["api/**"], "the rate limiter")   # 0 granted
        scope.declare(repo, "B", ["web/**"], "the page")           # 1 granted — disjoint
        scope.declare(repo, "C", ["api/handlers/**"], "nope")      # 2 CONFLICT — inside A's region
    finally:
        fr.uninstall()
    name = sorted(os.listdir(flightdir))[0]
    return fr.Recording.load(flightdir / name)


def check(handle):
    return handle.check(scope_flight.Adapter(), invariants)


def test_every_claim_holds_on_every_recorded_call(recorded_scopes):
    for i, call in enumerate(recorded_scopes.calls):
        report = check(recorded_scopes.call(i))
        assert report.ok, f"call {i} ({call['fn']}):\n{fr.format_invariant_report(report)}"


def test_the_oracle_condemns_a_double_booked_map(recorded_scopes):
    """NEGATIVE CONTROL, and the most important test in the suite.

    Plant the bug no crash can reveal: an overlap test that says two regions never touch. Nothing
    raises, nothing is refused — two agents are simply both put on the map for one region, each
    certain it is alone, which is strictly worse than either being absent, because the map is
    BELIEVED.

    Built by keeping the RECORDED outcome (a grant) and lying to the call about the world instead:
    the boundary now says another agent already holds the very region being granted. The oracle
    must condemn that WITHOUT consulting `scope.overlaps`, because `scope.overlaps` is the thing
    that is broken — it recomputes the overlap itself (invariants._touches) from the claim records
    the boundary served. If this test ever goes green, the oracle has become an echo.
    """
    handle = recorded_scopes.call(1)                     # B declares web/** — recorded as GRANTED

    granted = (recorded_scopes.calls[1]["result"] or {}).get("claim", {}).get("scope") or []
    assert granted, "the fixture's second declare was not granted — the control has no subject"
    rival = json.dumps({"session": "A", "scope": granted, "intent": "the page, actually",
                        "acquired_at": 0, "renewed_at": 0, "expires_at": 9e18,
                        "lease_seconds": 900})
    handle.effect("read_claims").result = [rival]

    real = scope.overlaps
    scope.overlaps = lambda a, b: False                  # the silent bug
    try:
        report = check(handle)                           # ...so it still grants: outcome unchanged
    finally:
        scope.overlaps = real

    assert report.outcome == "violated", (
        "the oracle did not notice that two agents were handed the same region:\n"
        + fr.format_invariant_report(report))
    violated = " ".join(str(v) for v in report.violations)
    assert "never double-books" in violated
