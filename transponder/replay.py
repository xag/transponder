"""Replay a flight-recorded lock call with full internal-state tracing (extra `flight`).

    python -m transponder.replay flight/locks/<session>.jsonl              # list recorded calls
    python -m transponder.replay flight/locks/<session>.jsonl --call 0     # replay + trace
    python -m transponder.replay ... --call 0 --watch repo,session         # variable timeline
"""

import sys

import flight_recorder as fr

from transponder.flight import Adapter

if __name__ == "__main__":
    sys.exit(fr.run_cli(Adapter(), prog="python -m transponder.replay"))
