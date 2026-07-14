"""The off switch, held to the one promise that matters: it reaches sessions already running.

Nothing here refuses tool calls any more, so the switch no longer frees anyone — it SILENCES: an
information layer can still be wrong, noisy, or slow, and off must mean off, everywhere, on the
very next hook call, without a restart and without a settings.json edit (a harness snapshots its
hooks at startup and cannot see one).
"""

import json
import os
import subprocess
import sys

import pytest

from transponder import scope, toggle
from transponder.hooks import claude_code

CLAUDE = os.path.join(os.path.dirname(__file__), "..", "transponder", "hooks", "claude_code.py")


@pytest.fixture
def switchable(repo, tmp_path, monkeypatch):
    """The `repo` fixture pins TRANSPONDER_DISABLED=0 so the machine's own panic file cannot mute the
    suite. Here the panic FILE is the thing under test, so the override has to come off — otherwise
    we would be testing the env var and calling it the file."""
    monkeypatch.delenv("TRANSPONDER_DISABLED", raising=False)
    monkeypatch.setenv("TRANSPONDER_CLAUDE_SETTINGS", str(tmp_path / "settings.json"))
    return repo


def _edit(repo, session="B", path="a.txt"):
    return subprocess.run(
        [sys.executable, CLAUDE],
        input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                          "tool_input": {"file_path": os.path.join(repo, path)},
                          "cwd": repo, "session_id": session}),
        capture_output=True, text=True, timeout=60)


def test_the_switch_silences_a_session_that_is_already_running(switchable):
    """The property that makes the switch worth having: the harness snapshotted its hooks when the
    session started, so editing settings.json cannot reach it. Only a file, read on every hook
    call, can — and once it is armed, the courier goes quiet on the very next call."""
    repo = switchable
    os.makedirs(os.path.join(repo, "api"), exist_ok=True)
    scope.declare(repo, "A", ["api/**"], "working")

    noisy = _edit(repo, "B", path="api/x.py")               # B walks into A's region
    assert noisy.returncode == 0, "nothing is ever refused"
    assert "HEADS UP" in noisy.stdout or "SHARED" in noisy.stdout, "the courier should speak here"

    toggle.disable(reason="too noisy, switching off")

    quiet = _edit(repo, "B", path="api/y.py")
    assert quiet.returncode == 0
    assert not quiet.stdout.strip(), "the switch is armed and the courier is still talking"


def test_on_means_on_even_when_the_hooks_were_removed(switchable, tmp_path):
    """The dangerous middle state: switch disarmed, hooks never wired. It reports itself ON and
    guards precisely nothing — which is worse than being off, because you would rely on it. So
    `enable()` re-wires as well as disarming."""
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "Opus"}', encoding="utf-8")
    assert not claude_code.wired()

    toggle.enable()

    assert claude_code.wired(), "enable() left the hooks unwired — it would guard nothing"
    assert not toggle.state()["armed"]
    wired = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert set(wired) == set(claude_code.EVENTS), "a partial install is the DEGRADED case, not an install"


def test_uninstalling_transponder_does_not_uninstall_anyone_elses_hooks(switchable, tmp_path):
    """We remove our entries. Only ours.

    The foreign command is `echo not-transponder` on purpose, and it is not a joke: the first cut of
    `_ours()` matched the bare substring `transponder`, so this hook — which merely mentions the word —
    was identified as ours and deleted. Identity is the script we install, not a word that appears
    in a command line."""
    settings = tmp_path / "settings.json"
    foreign = {"type": "command", "command": "echo not-transponder"}
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash",
                                                              "hooks": [foreign]}]}}), encoding="utf-8")
    claude_code.install()
    claude_code.uninstall()

    left = json.loads(settings.read_text(encoding="utf-8")).get("hooks") or {}
    assert left == {"PreToolUse": [{"matcher": "Bash", "hooks": [foreign]}]}, (
        "uninstall touched a hook that was not ours")


def test_the_switch_says_who_turned_it_off_and_why(switchable):
    """A zero-byte panic file is a mystery in a fortnight. The reason travels with the switch."""
    toggle.disable(reason="the waiter never ran (#10)")
    s = toggle.state()
    assert s["armed"] and s["effective_disabled"]
    assert s["reason"] == "the waiter never ran (#10)"
    assert s["since"]
    assert "OFF" in toggle.render(s)


def test_disable_can_clear_the_map(switchable):
    """Turning it off makes the claims inert, not absent — they would greet everyone, stale, on the
    way back in. `clear` is how you leave nothing behind."""
    repo = switchable
    scope.declare(repo, "A", ["**"], "working")
    assert toggle.held_claims(), "A's claim should be on the map"

    v = toggle.disable(reason="clearing", clear=True)

    assert v["cleared"] == ["A"]
    assert not toggle.held_claims(), "the claim survived a --clear"


def test_an_env_override_is_reported_because_it_beats_the_file(switchable, monkeypatch):
    """TRANSPONDER_DISABLED wins over the panic file in BOTH directions. A session launched with
    `TRANSPONDER_DISABLED=0` will happily ignore an armed switch — so the switch has to say so out
    loud, rather than claiming an authority it does not have."""
    toggle.disable(reason="armed")
    monkeypatch.setenv("TRANSPONDER_DISABLED", "0")

    s = toggle.state()
    assert s["armed"] is True                     # the file is there...
    assert s["effective_disabled"] is False       # ...and is being ignored
    assert "OVERRIDES" in toggle.render(s)
