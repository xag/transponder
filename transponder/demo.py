"""Prove the transponder works, on this machine, with two real sessions — `python -m transponder.demo`.

This exists because the library's central claim cannot be checked from inside one session. An agent
cannot see another agent; that is the whole premise. So every internal signal can look healthy while
the thing does nothing — which is exactly what happened: for the whole life of v2 the courier wrote
its notes to a debug log, the map was accurate, the witness was watching, the tapes were faithful,
and no agent was ever told anything. It took two sessions deliberately colliding to notice.

So this is a two-party test, and it needs a human for thirty seconds:

    this process   holds a region of a throwaway checkout, writes to it, and posts to the
                   checkout's channel saying what it is doing — as a considerate agent would
    you            drive ANOTHER session at the same file, and ask it to read the channel
    the transponder  should introduce the checkout, name the violation after the write, tell the
                   HOLDER it was written into, and hand over anything the other agent said

It never touches a real repo: the checkout is a fresh temp directory unless you pass --repo.

THE GOTCHA, and it will cost you the run if you miss it: a harness snapshots WHICH hooks and events
are wired when the session starts (it re-reads the script itself on every call). So a session older
than the last `python -m transponder.toggle on` can be missing whole events — which is not a
hypothetical: UserPromptSubmit was routed in the adapter and never wired for the whole life of v2,
so it never fired once.

The number worth watching at the end is how many agents READ the channel message. Pull-only means a
channel nobody asks for is a channel that does not exist, whatever the tests say.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
import time

from transponder import env, messages, scope
from transponder.hooks import common

TICK_SECONDS = 10
HEADER = "shared.txt — held by the transponder demo\n"


def _git(repo: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def make_checkout(path: str) -> str:
    """A real git repo, because the witness reads `git status --porcelain` and a directory that is
    not a checkout is invisible to it — the demo would 'pass' by saying nothing at all."""
    os.makedirs(path, exist_ok=True)
    _git(path, "init", "-q")
    with open(os.path.join(path, "shared.txt"), "w", encoding="utf-8") as f:
        f.write(HEADER)
    _git(path, "add", "-A")
    _git(path, "-c", "user.email=demo@demo", "-c", "user.name=demo", "commit", "-qm", "demo")
    return path


def preflight() -> list[str]:
    """Say what is off BEFORE the human goes and opens a session for nothing."""
    from transponder import toggle

    out = []
    st = toggle.state()
    if env.disabled():
        out.append("transponder is switched OFF — `python -m transponder.toggle on` first.")
    if not st.get("wired"):
        out.append("the hooks are NOT wired into settings.json — `python -m transponder.toggle on`.")
    return out


def report(path: str, mine: list[str], mail: list[str], chatter: list[str]) -> None:
    """What this side saw. The point of the demo is to compare it with what the other session was
    TOLD: a violation the witness recorded but nobody delivered is the exact failure this library
    shipped with, and only two accounts of one event can catch it.

    The FILE alone is not enough evidence, and the first run of this demo proved it: the other
    session wrote, was told, and politely reverted — so the file came back clean and this report
    announced that nothing had happened. A collision that was witnessed twice, reported to both
    parties, and recorded on the tape, summarised as silence. So the mail is the primary evidence
    now and the file is corroboration: mail survives an undo, because being written into is a fact
    about the past and the file only ever shows the present.
    """
    try:
        with open(path, encoding="utf-8") as f:
            now = f.readlines()
    except OSError as e:
        print(f"\n  could not re-read the file: {e}")
        now = []

    left = collections.Counter(now) - collections.Counter(mine)
    lost = collections.Counter(mine) - collections.Counter(now)

    print("\n" + "=" * 72)
    if mail:
        print(f"  THE TRANSPONDER TOLD ME — {len(mail)} note(s) addressed to this agent:\n")
        for note in mail:
            for line in note.splitlines():
                print(f"    {line}")
            print()
        print("  That is the victim's half of the protocol, and it is the half that was missing:")
        print("  the agent whose region was written is now told, on its own next call.")
        if not left:
            print("\n  Note the file itself is clean — the write was undone. Without this note the")
            print("  demo would be reporting that nothing happened.")
    if chatter:
        print(f"  SOMEBODY TALKED TO THE ROOM — {len(chatter)} channel message(s) I had to ASK for:\n")
        for note in chatter:
            for line in note.splitlines():
                print(f"    {line}")
            print()
        print("  Nothing pushed these to me; I pulled them, which is the whole line between a")
        print("  courier and a feed. An agent saying what it is doing is the information the map")
        print("  cannot carry — it only ever knew WHERE I was writing, never what was coming.")
    if left:
        print(f"  ANOTHER AGENT WROTE IN MY REGION — {sum(left.values())} line(s) I did not write:")
        for line in list(left)[:8]:
            print(f"    {line.rstrip()}")
        print("\n  That session should have been told, on its own screen, in this order:")
        print("    1. THIS CHECKOUT IS SHARED …  (before it wrote — once per session)")
        print("    2. SCOPE VIOLATION — you just wrote inside another agent's reserved region")
        print("       (after the write landed, with the three-step remedy)")
        print("\n  If it saw NEITHER, the courier is not reaching agents — which is the failure")
        print("  this demo exists to catch, and it looks identical to everything working.")
    elif not mail and not chatter:
        print("  Nothing reached me: no mail, no channel traffic, and no lines in the file that I")
        print("  did not write.")
        print("  Either no other session tried, or it was pointed at a different path — or the")
        print("  courier is silent again. Those look the same from here, which is the point:")
        print("  check the tape (python -m transponder.replay) before concluding anything.")
    if lost:
        print(f"\n  {sum(lost.values())} line(s) of MINE are gone — the other write destroyed them.")
        print("  Worth sitting with: the report is not a recovery. Uncommitted bytes do not come")
        print("  back, which is why the map matters more than the alarm.")
    print("=" * 72)


def was_heard(message_id: str) -> int:
    """How many agents have marked our channel message read.

    Deliberately NOT a library function. A read-receipt in the hands of an agent invites waiting for
    acknowledgement, and there is no wake-up here — a protocol that waits for a reply is a protocol
    that hangs (a-channel-they-can-repurpose). The demo is a test instrument rather than a
    participant, and this is the only way to tell "nobody was listening" from "the channel is
    broken", which are the two outcomes that look identical from the sender's chair.
    """
    seen_dir = os.path.join(os.path.dirname(env.lock_dir()), "mail", "seen")
    readers = 0
    try:
        names = os.listdir(seen_dir)
    except OSError:
        return 0
    for name in names:
        try:
            with open(os.path.join(seen_dir, name), encoding="utf-8") as f:
                if message_id in set(json.load(f)):
                    readers += 1
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return readers


def _utf8() -> None:
    """Same reason the hook does it (#10's tape): Python on Windows writes the ANSI code page, and
    an em-dash arriving as U+FFFD is a message half-delivered. A demo is read by a human or it is
    nothing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8()
    ap = argparse.ArgumentParser(prog="python -m transponder.demo", description=__doc__.split("\n")[0])
    ap.add_argument("--minutes", type=float, default=5.0, help="how long to hold the file (default 5)")
    ap.add_argument("--repo", default=None, help="use this checkout instead of a temp one")
    args = ap.parse_args(argv)

    for problem in preflight():
        print(f"WARNING: {problem}")

    repo = make_checkout(args.repo or tempfile.mkdtemp(prefix="transponder-demo-"))
    path = os.path.join(repo, "shared.txt")
    session = f"demo-holder-{os.getpid()}"
    intent = "the demo: appending a tick every 10s, testing whether the other session is told"

    v = scope.declare(repo, session, [path], intent)
    if v["status"] != "granted":
        print(f"could not take the region: {v}")
        return 1

    # Say what we are doing, the way an agent is asked to. The map can only carry "shared.txt" and
    # one line of intent; this is the part that would change what somebody else writes.
    posted = messages.send(
        sender=session, kind="channel", repo=repo,
        body=("I am appending a tick to shared.txt every 10s for the next few minutes, and I hold "
              "that file. If you need it, say so and I will release it early — I am a demo, so "
              "there is nothing precious in my half."))

    ticks = max(1, int(args.minutes * 60 / TICK_SECONDS))
    print("=" * 72)
    print("  EDIT THIS FILE FROM ANOTHER SESSION:\n")
    print(f"    {path}\n")
    print(f"  I hold it as agent {session} for the next {args.minutes:g} minute(s), and I have")
    print("  posted to this checkout's channel saying what I am doing.")
    print("\n  Use a session started AFTER the last `toggle on` (a harness snapshots which hooks")
    print("  and events are wired when it starts; the script itself it re-reads every call).")
    print("\n  TWO THINGS WORTH TRYING, and the second is the new one:")
    print("    1. Edit the file. Your write will NOT be blocked — nothing here ever blocks —")
    print("       and watch what that session is told, before and after.")
    print(f"    2. Ask it to call  messages(repo, session_id)  and reply with send_message(...).")
    print("       That is the channel: pulled, never pushed. I will print anything it says here,")
    print("       live, and tell you at the end whether anyone actually read mine.")
    print("=" * 72 + "\n")

    mine, mail, chatter = [HEADER], [], []
    try:
        for i in range(1, ticks + 1):
            line = f"tick {i:03d}  {time.strftime('%H:%M:%S')}\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
            mine.append(line)
            scope.renew(session)          # no hook fires for this process; the claim would lapse
            # Drain our own inbox, exactly as an agent's hook does on its next tool call — and then
            # the channel too, which a hook never delivers, because that is what an agent has to ASK
            # for. The demo is a participant rather than a prop: it is the victim, so it receives
            # what a victim receives, live, while you are watching.
            got_mail = common.collect(session, repo)
            got_chat = [messages.render(m) for m in
                        messages.unread(session, repo, kinds=("channel", messages.BROADCAST))]
            if fresh := got_mail + got_chat:
                mail += got_mail
                chatter += got_chat
                print(" " * 30, end="\r")
                for note in fresh:
                    print("\n  >>> " + note.splitlines()[0])
                print(f"  >>> ({len(fresh)} — full text at the end)\n")
            print(f"  held {i:3d}/{ticks}", end="\r", flush=True)
            if i < ticks:
                time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\n  stopped early.")
    finally:
        scope.release(session, anchor=repo)
        report(path, mine, mail, chatter)
        heard = was_heard(posted.get("id", "")) if posted.get("status") == "sent" else 0
        print(f"\n  MY CHANNEL MESSAGE was read by {heard} other agent(s).")
        if not heard:
            print("  Nobody pulled it. That is not a failure of the channel — it is pull-only by")
            print("  design — but it is the number to watch: a channel nobody asks for is a")
            print("  channel that does not exist, whatever the tests say.")
        print(f"\n  released. the checkout is still there if you want to look: {repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
