# The shared-checkout convention, v2

One developer, several AI agent sessions, one machine of shared checkouts. Git assumes a working
tree has one author; agent harnesses pretend that is still true. This convention is the missing
**information layer**: a claims map any agent on the machine can read and write, a witness that
reports what actually happened, and a courier that carries both into every agent's context —
regardless of vendor.

This document is normative. The Python package in this repository is a reference implementation,
not the definition. **MUST/SHOULD/MAY** as in RFC 2119.

> **v1 of this spec described a lock.** It refused tool calls, held a mutex through every shell,
> and took its own machine down four times (#4, #7, #10, #11) — every incident a *reader* or an
> *innocent* refused, never a collision prevented that mattered: the only two real contentions in
> its recorded history were sessions working different directories. v1 is deleted, not deprecated.
> The history lives in git and in the ledger; the lessons that survive are baked in below.

## 0. The model, in four sentences

Agents **declare** where they will write; the declarations form a map, and the map never
double-books a region. The **courier** delivers what an agent cannot see from inside its own
context: who else is here, and that the file it is about to edit is inside someone's region. The
**witness** observes every write and reports, loudly and with the remedy attached, the ones that
land in another agent's region. **Nothing is ever refused** — the failure this convention prevents
was never malice, it was an agent that did not know another agent was there, and information cures
ignorance at a fraction of the price of a mutex.

### 0a. Why cooperation is a sound foundation, not a hope

Every agent on the machine works for the same human, who wants all of their work to survive. There
is no adversary to model — and **deterrence is explicitly not the mechanism** (an agent has no
memory across sessions, no reputation, no future to lose; "they risk being stomped back" is a hope,
not an argument). The mechanism is *visibility plus a witness*: an agent that can see the other
scopes has no reason to collide, and one that collides anyway is named immediately, rather than
discovered a week later inside a mangled rebase.

If this assumption is wrong, the convention is wrong — and the kill condition is mechanical:
violation reports firing regularly, from agents that had seen the map (§8).

## 1. The namespace is the local filesystem

A **scope** is a set of **resources**; a resource is a **canonical absolute path** — `realpath` +
`normcase`, forward slashes — in exactly two forms:

| resource               | reserves   |
|------------------------|------------|
| `<canonical-path>`     | one file   |
| `<canonical-path>/**`  | a subtree  |

Agents spell paths relative to the checkout they name (`api/**` for `<repo>/api/**`; `**` alone is
the whole checkout), and the implementation canonicalises before storing. **Overlap is the prefix
relation** — decidable always — so a conflict MUST name the exact **intersection**: "come back
narrower" is computed, never guessed.

One namespace, deliberately:

- **general globs** (`src/*.py`) have no decidable overlap and MUST be rejected at declaration. A
  scope system unsure whether two regions touch hands one region to two agents and tells each it
  is alone.
- **opaque names** (`port:3000`) are contracts no witness can check, and MUST be rejected until
  one arrives *with* a witness.
- **aliasing is dead by construction**: case, symlinks, junctions, `..` all canonicalise to one
  string, so "whom do we inform?" is always answerable point-to-point from the map. Nothing is
  ever broadcast.
- paths git ignores are not reservable and are never observed — without this, `node_modules/`
  makes every scope conflict with every other, and the convention dies of false positives.

### 1a. The index is a file, and that is why commits are safe

Agent A works `api/**`, agent B works `web/**`, both mid-edit — the whole point. A runs
`git add -A && git commit` and sweeps B's half-finished work into A's commit. **That is the
founding incident of this convention**, it cannot be prevented by inspection (knowing a command
stages the whole tree means reading the command, which is undecidable — the one v1 lesson nothing
here revisits), and source-path scopes alone hand it straight back.

The filesystem namespace dissolves it without adding anything: **the staging area was never
anything but a file.** An agent that intends to commit SHOULD reserve `<repo>/.git/index` — an
ordinary path with the ordinary overlap — immediately before the commit, and release it
immediately after. Held for the life of a scope it makes every writer conflict with every other,
which is the old mutex rebuilt; taken briefly, commits serialise by consent and nobody parsed
anything. The witness backstops the agent that doesn't: a commit that swept another agent's paths
is named, sha and all, with the recovery attached (§5).

## 2. The claims map

- Claims live in one machine-global store (`$REPOLOCK_DIR`'s parent, `claims/`), **one file per
  agent**, written atomically. Never a shared list: a list is read-modify-write, and a store that
  loses a claim under contention loses it exactly when it matters.
- A claim carries: `session` (the harness session id — the same one the hooks see), `scope`
  (canonical resources), `intent` (free text, refreshed on renewal — a stale intent misleads the
  agent reading the map to decide what to do), `acquired_at` / `renewed_at` / `expires_at` /
  `lease_seconds`.
- **Leases are the decay rate of information, not a hold.** Activity renews (a tool call IS the
  activity; nothing needs a daemon); an agent that crashed or wandered off simply fades from the
  map. Readers MUST treat an unparsable claim as no claim, and MUST ignore unknown fields.
- The map MUST NOT double-book: a `declare` or `extend` whose scope overlaps a live claim is not
  recorded, and the answer names the holder, the intent, the exact intersection, and what is free.
  **This refuses a map entry, never a tool call** — the agent's work is not blocked by anything,
  anywhere.
- `declare` is all-or-nothing (a scope granted entire or not at all); `extend` widens and never
  blocks; `release` narrows or clears. Since nothing ever waits on anything, deadlock does not
  exist in this convention — there is nothing to cycle on.

## 3. The courier

An agent turn cannot be interrupted and nothing can push into it. Two delivery paths exist, and
they are the only two:

- **a working agent**: the adapter prints into its context on every tool call. This is how all
  notes below arrive;
- **a parked agent**: reachable when it next works. (A subscribe-able listener — the old waiter,
  generalised — MAY be added when negotiation between live agents needs it; nothing below depends
  on it.)

The courier MUST deliver:

1. **the introduction**, once per (session, checkout): who else is working here and where, and how
   to get on the map. Once — a note printed forever is a note nobody reads;
2. **the heads-up**, when a *declared* write (an Edit/Write tool carries its path) is about to
   land inside another agent's region — information at its most valuable moment, before the write,
   and still not a gate;
3. **the drift note** (§6), when history moved under what the session remembers.

A participant writing *unclaimed* ground SHOULD have its claim quietly extended — the map should
say what participants are actually touching.

## 4. The witness

For every tool whose effect is not declared (a shell, an MCP call), the adapter MUST take a
fingerprint of the checkout before the call (HEAD + porcelain + the stat of every dirty path — the
stat is load-bearing: an already-dirty file edited again moves no status line, but the bytes move)
and diff it after. A **moved fingerprint names the paths that were written, as a fact**. Commits
are chased into the object graph (`git log --name-only`): a file created and committed inside one
tool call is dirty at neither end, and it is precisely the file that matters (§1a).

- unmoved (almost every call): nothing is said, nothing is charged;
- moved, inside the writer's own scope: silent, lease renewed;
- moved, outside every claim: a nudge to declare it (participants only);
- moved, **inside another agent's region**: a violation (§5).

Known limits, stated rather than hidden: a backgrounded task's writes land after its hook window
and are attributed to nobody; the witness sees only what git tracks; and between one session's
Post and its next Pre, another process's writes are that process's to witness, not this one's.

## 5. Violations

A violation is not prevented — nothing is — so it MUST NOT be silent. The report goes to the agent
that wrote, immediately, and MUST carry: the paths, the victim, the victim's intent, and **the
remedy**. Where HEAD moved (their work is inside your commit), the remedy is exact — `git reset
--soft HEAD~1`, unstage their paths, stage yours **by name, never `-A`** — because a commit is the
one violation that is cleanly recoverable, and an accusation without a recovery is half a message.

## 6. The drift check

Read-side, lock-free, and the one part of v1 that was never wrong: given the HEAD a session last
saw, report `current`, `moved` (with the commits between) or `rewritten` (the seen commit no
longer exists — everything the session remembers about this repo is suspect). Adapters SHOULD run
it at session start and on each return of control.

## 7. Adapter obligations

1. **never refuse a tool call.** The one permitted exit-2 is the Stop boundary (obligation 6);
2. deliver the courier's three notes (§3) and the witness's reports (§4, §5) through the harness's
   own channel into the agent's context;
3. key claims and witness on **the repo that owns the written path**, never the session's cwd;
4. cover **every shell the harness exposes** and its MCP traffic in the witness's matchers — a
   tool the witness does not see is a write that never happened;
5. detect its own blind half: a before-picture that is never settled means the after-hook is not
   wired, and the adapter MUST say so, once, rather than let anyone believe they are covered;
6. at the Stop boundary: release the session's claims in that checkout against a clean tree; if
   the tree is dirty and the session was a participant there, it MAY block the stop **exactly
   once** to ask for commit / ignore / stash — three routes, because "commit your work" is the
   wrong instruction for an artifact and for a scrap. Asked once and declined, the claims stay on
   the map until the lease lapses: the work is still there, and the map should say so;
7. **fail open, silently for the flow, loudly for the eye**: a crashing adapter must never block
   work — losing a note is an inconvenience; blocking would be the lock's disease in the
   informer's coat;
8. offer a **kill switch** that reaches sessions already running (a file checked on every call,
   `~/.repolock/DISABLED`) and that does not need a terminal (an MCP tool). An informer cannot
   wedge the machine, but it can be wrong, noisy or slow, and off must mean off, everywhere,
   instantly. "On" must re-wire the hooks as well as disarm — reporting on while feeding nothing
   is the worst of the three states.

## 8. What kills this design

Falsifiable, off the tape, and each one cheap:

| the claim | what kills it |
|---|---|
| agents contain their work once containment is visible | violation reports firing regularly from agents that had seen the map |
| the map is used at all | checkouts shared for days with zero declarations — the notes are being ignored, and this is decoration |
| the witness sees every write that matters | a tape whose settle shows an unmoved fingerprint across a call after which `git status` differs |
| information suffices — the loss of exclusion was affordable | an out-of-scope write destroying work that `git revert` could not bring back. **One** is enough; that is the outcome the deleted mutex existed to prevent, and it would mean the trade was wrong rather than merely cheap |

## Non-goals

- **Not enforcement.** A process that ignores the convention writes freely; the convention is for
  cooperating harnesses, and §0a is the argument for why that is enough. If it is not, §8 will say
  so before anyone loses much.
- **Not a network protocol.** One machine, one filesystem.
- **Not a replacement for worktree isolation.** Where a harness can give each agent its own
  worktree, that is strictly better; this covers what worktrees don't reach — sessions
  deliberately pointed at one checkout, mixed-vendor fleets, and the drift check.
- **Not arbitration between subagents.** A subagent's tool calls carry its parent's session id
  (verified against a real run), so one session and its subagents are one participant on the map.
