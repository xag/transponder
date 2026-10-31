"""The MCP verbs as a command, for a session that cannot see the transponder's tools.

A Claude Code session loads its MCP servers once, at startup: a session that was already running
when the transponder was registered never gets `declare_work` and the rest, however long it runs.
Its hooks do reach it, because the harness watches the settings file — so the courier can tell it
what to do, and this is the something it can do with nothing but its shell:

    python -m transponder.cli declare_work --repo C:/work/app --session_id <id> \\
        --paths src/api/ --doing 'replacing the auth middleware' --minutes 30

Each verb is the server's own function, called with the same arguments under the same names, so
the two faces cannot drift: the flags are read off the function's signature and the help off its
docstring. The run needs the `mcp` extra, which the server's venv already has.
"""

from __future__ import annotations

import argparse
import inspect
import sys
import typing

from transponder import server

VERBS = ("channel", "declare_work", "extend_work", "finish_work", "send_message",
         "lock_drift", "lock_disable", "lock_enable", "lock_switch")


def _flag(p: argparse.ArgumentParser, param: inspect.Parameter, hint) -> None:
    name, required = f"--{param.name}", param.default is inspect.Parameter.empty
    default = None if required else param.default
    if hint is bool:
        p.add_argument(name, action=argparse.BooleanOptionalAction, default=default, required=required)
    elif any(typing.get_origin(h) is list for h in (hint, *typing.get_args(hint))):  # list[str], or | None
        p.add_argument(name, nargs="+", default=default, required=required, metavar="PATH")
    else:
        p.add_argument(name, type=hint if hint in (int, float) else str, default=default, required=required)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m transponder.cli", description=__doc__.split("\n")[0])
    verbs = ap.add_subparsers(dest="verb", required=True, metavar="VERB")
    for verb in VERBS:
        fn = getattr(server, verb)
        doc = inspect.cleandoc(fn.__doc__ or "")
        p = verbs.add_parser(verb, help=doc.split("\n")[0].replace("**", ""), description=doc,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
        hints = typing.get_type_hints(fn)
        for param in inspect.signature(fn).parameters.values():
            _flag(p, param, hints.get(param.name, str))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = vars(parser().parse_args(argv))
    print(getattr(server, args.pop("verb"))(**args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
