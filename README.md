# repolock

One developer, several AI agent sessions, one machine of shared checkouts.

**This is no longer a lock, despite the name** (a rename is coming). It is an **information
layer**: agents declare where they will write, a witness reports what actually happened, and a
courier carries both into every agent's context. **Nothing is ever refused.**

> ### How a lock became a channel
>
> v1 was a mutex on the write path of every agent session on the machine, and it took that machine
> down four times. Twice by misreading commands (#4 refused *readers*; #7 read `print("a -> b")` as
> a redirect); once by minting an escape hatch that could not run (#10 — the waiter's own ticket
> died in bash, and dying looked identical to succeeding); once by parking a lock on an artifact
> directory and refusing `ls` for ten minutes (#11). Each time the cure was more machinery: tickets,
> degraded modes, idle boundaries, an off switch.
>
> Then the tapes were read. In the entire recorded history of the lock, it had faced exactly **two**
> real contentions — and both were sessions working **different directories**, refused for no
> reason. Meanwhile every incident it caused had the same root: not malice, not even carelessness —
> **an agent that did not know another agent was there.** You do not build a mutex against
> ignorance. You inform it.
>
> So the mutex is deleted. What remains never says no:
>
> - **the map** — agents declare scopes (canonical filesystem paths; `.git/index` is just a file,
>   and reserving it around a commit is what keeps `git add -A` from sweeping a neighbour's
>   half-finished work into your commit). The map never double-books; a conflicting declaration
>   is answered with who, why, the exact overlap to subtract, and what is free — and nothing about
>   your *work* is blocked either way.
> - **the courier** — hooks that print into an agent's context: "this checkout is shared, agent X
>   is working `api/**`", once; "the file you are about to edit is inside X's region", before the
>   write; "history moved under you", at session start.
> - **the witness** — a fingerprint before and after every shell and MCP call. A write that lands
>   in another agent's region is named, loudly, to the agent that did it, with the recovery
>   attached. A fact off the tree, never a guess about a command — the one v1 lesson that survives
>   everything: what a command will write is not decidable from its text, so nothing here reads
>   commands.
>
> One deliberate exception: at the **Stop boundary**, a session leaving a dirty tree it was working
> is asked — once, never twice — to commit, ignore, or stash. That blocks no other agent, ever.

## Install (Claude Code)

```bash
git clone https://github.com/xag/repolock && cd repolock
uv sync            # or: pip install .
python -m repolock.toggle on        # wires the hooks at user scope; idempotent
```

Four events, all information: `PreToolUse` (the courier + the witness's before-picture; matcher
includes both shells and `mcp__.*`), `PostToolUse` (the witness settles), `Stop` (release claims on
a clean tree; the ask-once on a dirty one), `SessionStart` (the drift check). A missing
`PostToolUse` is a **blind witness** — the hook detects it and says so, once, rather than letting
anyone believe they are covered.

**Register the MCP server too:** `uv run python -m repolock.server`. It is the channel — the tools
the notes point at:

| tool | what it does |
|---|---|
| `scopes(repo)` | who is working this checkout and where — call it BEFORE you plan |
| `declare_scope(repo, scope, session_id, intent)` | put your region on the map |
| `extend_scope(repo, add, session_id)` | widen when you discover you need more |
| `release_scope(repo, session_id, drop?)` | take yourself off the map the moment a region stops being yours |
| `lock_drift(repo, seen_head)` | has history moved under you? |
| `lock_disable` / `lock_enable` / `lock_switch` | the off switch (below) |

## What it feels like

An agent walking into a checkout someone else is working:

```
THIS CHECKOUT IS SHARED — you are not alone in c:/users/x/projects/app:

  agent e85314e1 is working c:/users/x/projects/app/api/**  — the rate limiter

Nothing is blocked. But their regions are their half-finished work: stay out of them, and
SAY WHERE YOU WILL WRITE so they can stay out of yours:
    declare_scope(repo, ['src/thing/**', 'tests/thing/**'], intent='what you are doing')
```

An agent about to edit a file in someone's region gets a **HEADS UP** naming the holder and their
intent — before the write, and without blocking it. An agent whose shell *did* write into someone's
region gets the loudest thing this library says:

```
SCOPE VIOLATION — you just wrote inside another agent's reserved region.
  web/page.js
     belongs to agent e85314e1 (c:/users/x/projects/app/web/**) — the page

  ...
  3. YOU COMMITTED THEIR WORK. This is the one violation that is cleanly recoverable:
         git reset --soft HEAD~1     # un-commit, keep the tree
         git restore --staged <their paths>
     Stage YOUR paths by name, never `-A`.
```

Two agents with disjoint scopes work the same checkout **concurrently, in silence** — which is the
entire point, and the thing the old lock refused both times it ever mattered.

## Recording (on by default)

Every claim, conflict and witnessed write lands on a flight-recorder tape (`~/.repolock/flight`,
extra `flight`). The tape is the evidence for the design's own bet — *agents contain their work
once containment is visible* — and the spec's §8 lists exactly what observation kills it. An
invariant suite judges every recorded call; the crucial one condemns a **double-booked map**, and
its negative control plants a broken overlap function and requires the oracle to catch it.
`REPOLOCK_FLIGHT=0` turns recording off.

## The off switch

`lock_disable("why")` from any agent session, or `python -m repolock.toggle off` from a terminal.
Either writes `~/.repolock/DISABLED`, which every hook checks on **every call** — so sessions
already running go quiet on their next tool use, no restart needed. An information layer cannot
wedge the machine the way the lock could, but it can be wrong, noisy, or slow, and off must mean
off. `lock_enable` re-wires the hooks as well as disarming, because *on* has to mean on.

`REPOLOCK_DISABLED` (env) overrides the file in both directions and is reported by `lock_switch`
precisely because it wins.

## Honest niche

Claude Code ships worktree isolation for background sessions — the vendor's answer, by not sharing
the checkout at all. Where worktrees fit, use them. This convention covers what they don't reach:
interactive sessions deliberately pointed at one checkout, mixed-vendor fleets, and the
stale-reader drift check. Success still looks like planned obsolescence: harnesses absorb the
convention, and this repo remains the reference.

## Environment

| variable              | meaning                                               |
|-----------------------|-------------------------------------------------------|
| `REPOLOCK_DIR`        | state directory anchor (default `~/.repolock/locks`)  |
| `REPOLOCK_FLIGHT`     | recording; **on** unless set to `0`/`false`/`off`     |
| `REPOLOCK_FLIGHT_DIR` | where recordings land (default `~/.repolock/flight`)  |
| `REPOLOCK_DISABLED`   | the off switch; also `~/.repolock/DISABLED` (above)   |
