# repolock

One developer, several AI agent sessions, one checkout.

Git assumes the working tree has one author. Run two agent sessions against the same clone and
that assumption silently fails: sessions overwrite each other's edits, and — subtler — a session
goes on *reasoning* about commits that a concurrent rebase has already destroyed. Nothing is
corrupted, so nothing complains.

repolock is **a protocol plus a reference implementation, not a service**:

- **[SPEC.md](SPEC.md)** — a lockfile convention (think `.git/index.lock`, or EditorConfig):
  where the lockfile lives, its JSON schema, and its semantics — short leases renewed by
  activity, commit-anchored handoff, release refused on a dirty tree, idle-clean releases,
  idle-dirty lapses, and the read-side drift check.
- **`repolock/`** — the reference library. Pure stdlib, zero dependencies:
  `acquire` / `renew` / `release` / `go_idle` / `status` / `drift`.
- **`repolock/hooks/claude_code.py`** — adapter #1: a Claude Code PreToolUse/Stop/SessionStart
  hook that makes the lock *binding*. Enforcement cannot be an MCP tool — a tool is something
  the model chooses to call, and the offending session never chooses to.
- **`repolock/server.py`** *(extra `mcp`)* — a read-mostly stdio MCP server for visibility and
  the deliberate human override: `lock_status`, `lock_drift`, `lock_debug`, `force_unlock`.

The point is cross-tool: every agent on the machine — Claude Code, Cursor, Codex CLI, whatever
comes next — honoring the same lockfile. A mixed fleet is exactly the scenario the lock guards.

## Install (Claude Code)

```bash
git clone https://github.com/xag/repolock && cd repolock
uv sync            # or: pip install .
```

Wire the hook at **user scope** (`~/.claude/settings.json`), so every repo on the machine is
guarded — use an absolute path to a python that can import `repolock`:

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash",
      "hooks": [{"type": "command", "timeout": 20,
                 "command": "\"<python>\" \"<checkout>/repolock/hooks/claude_code.py\""}]
    }],
    "Stop":         [{"hooks": [{"type": "command", "timeout": 20, "command": "<same>"}]}],
    "SessionStart": [{"hooks": [{"type": "command", "timeout": 20, "command": "<same>"}]}]
  }
}
```

Optionally register the MCP server for visibility (`uv run python -m repolock.server`).

## What it feels like

A session that tries to write into a checkout another live session is mid-change on gets the
tool call blocked, with the holder, its intent, and when the lease frees. A session that stops
to ask its human something releases on a clean tree, or holds until its lease lapses on a dirty
one — and the next writer inherits a **handoff**: what landed while the previous holder was
away, what it left uncommitted, and whether history was rewritten under everyone's feet.

## Recording (optional)

A lock bug is a heisenbug — a clock, a PID, and an interleaving you cannot re-stage. With the
`flight` extra, every lock operation can be recorded at its nondeterminism boundary and
replayed deterministically, and `repolock/invariants.py` holds the claims (two live sessions
never hold the same copy; a dirty tree is never handed over; …) that condemn a bad trajectory
on any tape. Recording is off unless `REPOLOCK_FLIGHT` is set, and **off means zero imports** —
the core never pays for it.

## Honest niche

Claude Code ships worktree isolation for background sessions — the vendor's answer to the same
problem, by not sharing the checkout at all. Where worktrees fit, use them. repolock's durable
niche is what they don't reach:

- **interactive sessions deliberately pointed at the same checkout** (one clone, one venv, one
  dev server);
- **cross-tool fleets** — no vendor's isolation covers another vendor's agent;
- **the stale-reader drift check** — a worktree doesn't stop another session rewriting the
  branch you're reasoning about.

Success looks like planned obsolescence: harnesses absorb the convention, and this repo remains
as the reference.

## Environment

| variable              | meaning                                              |
|-----------------------|------------------------------------------------------|
| `REPOLOCK_DIR`        | lockfile directory (default `~/.repolock/locks`)     |
| `REPOLOCK_FLIGHT`     | set to record lock operations (needs extra `flight`) |
| `REPOLOCK_FLIGHT_DIR` | where recordings land (default `flight/locks`)       |
