"""Replay a flight-recorded lock call with full internal-state tracing (extra `flight`).

    python -m repolock.replay flight/locks/<session>.jsonl              # list recorded calls
    python -m repolock.replay flight/locks/<session>.jsonl --call 0     # replay + trace
    python -m repolock.replay ... --call 0 --watch repo,session         # variable timeline
"""

import sys

import flight_recorder as fr

from repolock.flight import Adapter

if __name__ == "__main__":
    sys.exit(fr.run_cli(Adapter(), prog="python -m repolock.replay"))
