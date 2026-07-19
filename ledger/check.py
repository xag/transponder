"""Run the ledger's rules, print what is red, and exit non-zero if the gate is.

`nothing-unsound-passes-a-gate` counts the ungrounded params on everything the release gate admits,
so while a debt is carried and undischarged, this exits 1 — and any pipeline that runs it stops.
That is the whole difference between a caveat and a gate: prose cannot fire.

    uv run python -m ledger.check

`quern` is the substrate this is authored against. It is PRIVATE, and deliberately not a dependency of
this package — transponder is public and its adopters must not need it — so the check runs only where
someone has put it on the path (`uv pip install -e ../quern`). The test suite's structural rules
`importorskip` past its absence; this module does not, because a check that silently passes when it
could not run is worse than one that is missing.

**Nothing runs this today, and that is the honest state of it.** The docstring above used to open
with "This is the brake", and it named a `--group ledger` that has never existed in pyproject.toml
— so the command as written could not run at all. CI runs `pytest` and nothing else, and it cannot
run this: `quern` is private and a public runner cannot install it. A gate wired into no pipeline
brakes nothing. Until that is resolved, this is a thing a human runs on a machine that has the
substrate, and it should not be described as if it stops a release.

The structural rules (a decision names what it rejected, a hypothesis is falsifiable, a debt states
how it is discharged) are also checked by the test suite, which stays green while they hold. The
GATE is deliberately not a unit test: a red gate does not mean the code is broken, it means an
unsound thing is being carried and has not been paid for. Those are different facts and they should
fail in different places.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from quern.tree import run_rules
from quern.roll import audit, write

from ledger import LEDGER

_ROOT = Path(__file__).resolve().parents[1]
_ROLL = "ledger/roll.json"

# WHICH revision's roll to compare against, and it is not a detail. Locally the
# working tree holds the edit under judgement and HEAD is the last good state, so
# HEAD is right. In CI the commit under judgement IS HEAD - and carries the roll
# written beside it - so comparing against HEAD compares the tree with itself and
# passes whatever it is handed. CI names the base it is diffing from instead.
_REV = os.environ.get("LEDGER_ROLL_REV", "HEAD")


def main() -> int:
    results = run_rules(LEDGER)
    failures = [r for r in results if not r.ok]
    # A tombstone with no `was` excuses nothing - the right way round, because
    # forgetting it leaves the check red, never green.
    excused = {n.payload["was"] for _, n in LEDGER.walk("")
               if n.kind == "tombstone" and n.payload.get("was")}
    removals, looked = audit(LEDGER, _ROOT, _ROLL, _REV, excused)

    for r in failures:
        print(f"RED  {r.rule} @ {r.node}: {r.detail}")
    for line in removals:
        print(f"GONE {line}")
    if not looked:
        print(f"note: no roll at {_REV} - nothing was compared, so nothing was")
        print("      checked for removal. Honest on the first run of this check,")
        print("      and a problem on any other.")

    # The roll is written on a red run too, and for this ledger that is the whole
    # point: it ships red by design while a debt is carried, so gating the roll on
    # green would deny it removal protection permanently. A red rule is a debt; the
    # roll records what EXISTS. Only an unexplained removal makes it unsafe to
    # rewrite, because rewriting it then would launder what the check just caught.
    if not removals:
        write(LEDGER, _ROOT / _ROLL)
    if not failures and not removals:
        print(f"green - {len(results)} rules, nothing unsound in front of the "
              "gate; roll written")
        return 0

    gate_red = any(r.rule == "nothing-unsound-passes-a-gate" for r in failures)
    print()
    if failures:
        print(f"{len(failures)} rule(s) red.")
    if gate_red:
        print("The gate is RED: an unsound thing is on the write path of every")
        print("session on the machine. Discharge the debt by doing the work its")
        print("`discharge` names - never by editing the ledger.")
    if removals:
        print(f"{len(removals)} entr(y/ies) left the record without saying so.")
        print("Reversed is superseded and the node STAYS; paid is discharged and")
        print("the node STAYS; only an entry that was never valid is retracted,")
        print("with a tombstone naming it. The eight [SUPERSEDED] decisions here")
        print("are kept on purpose - that sequence IS the finding.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
