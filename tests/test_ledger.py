"""The design ledger is checkable, and checked.

Skips where `bom` (private) is not installed — CI and outside contributors lose nothing but
this audit; machines with the substrate run it.
"""

import os
import sys

import pytest

pytest.importorskip("bom")


def test_every_ledger_rule_holds():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ledger"))
    from bom.tree import run_rules

    from ledger import LEDGER

    results = run_rules(LEDGER)
    failures = [r for r in results if not r.ok]
    assert results, "the ledger declares rules but none ran"
    assert not failures, "\n".join(f"{r.rule} @ {r.node}: {r.detail}" for r in failures)
