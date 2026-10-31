"""The shell face of the verbs, for a session that started before the transponder was registered.

Such a session never loads the MCP server, and its hooks reach it anyway. So what matters is not
that `transponder.cli` exists but that the command a note hands an agent, run as printed, puts the
agent on the map — the effect, observed from outside (renewal-was-never-wired).
"""

import inspect
import shlex
import subprocess

from test_adapters import CLAUDE, claude_edit, run_hook

from transponder import cli, scope, server


def claude_prompt(repo, session):
    return run_hook(CLAUDE, {"hook_event_name": "UserPromptSubmit", "cwd": repo, "session_id": session,
                             "prompt": "do the thing"})


def commands(note: str, verb: str) -> list[str]:
    return [line.strip() for line in note.splitlines() if f"-m transponder.cli {verb} " in line]


def run(command: str) -> subprocess.CompletedProcess:
    """As a POSIX shell would run it: its own quoting, split by the shell's rules."""
    return subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=60)


def test_every_tool_is_a_verb_and_every_argument_a_flag():
    tools = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert set(cli.VERBS) == tools, "a tool with no shell form is out of reach of an older session"
    verbs = cli.parser()._subparsers._group_actions[0].choices
    for verb in cli.VERBS:
        flags = {a.dest for a in verbs[verb]._actions if a.dest != "help"}
        assert flags == set(inspect.signature(getattr(server, verb)).parameters), verb


def test_the_command_in_the_undeclared_note_declares(repo):
    claude_prompt(repo, "A")                                  # spend the intro
    claude_edit(repo, "A", "a.txt")
    note = claude_prompt(repo, "A").stdout
    [command] = commands(note, "declare_work")
    res = run(command)
    assert res.returncode == 0 and "GREEN LIGHT" in res.stdout, res.stdout + res.stderr
    assert scope.declared("A"), "the command ran and the agent is still not on the map"
    claude_edit(repo, "A", "a.txt")
    assert "DECLARED NOTHING" not in claude_prompt(repo, "A").stdout


def test_the_intro_says_how_to_ask_from_a_shell(repo):
    note = claude_prompt(repo, "A").stdout
    [ask] = commands(note, "channel")
    res = run(ask)
    assert res.returncode == 0 and "nobody has declared anything" in res.stdout, res.stdout + res.stderr
    assert commands(note, "declare_work"), "told how to ask, not how to declare"
