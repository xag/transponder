# The repolock convention, v1

One developer, several AI agent sessions, one checkout. Git assumes the working tree has one
author; agent harnesses pretend that is still true. This convention is the missing lock: a
lockfile any agent on the machine can honor, regardless of vendor — the way `.git/index.lock`
or EditorConfig work, as a *convention*, not a service.

This document is normative. The Python package in this repository is a reference
implementation, not the definition. **MUST/SHOULD/MAY** as in RFC 2119.

## Scope: two failures, two mechanisms

1. **Two writers colliding.** Mutual exclusion, via the lockfile (§2–§5).
2. **A stale reader.** A session that only *read* a repo keeps reasoning from a picture of it;
   a concurrent rebase silently invalidates that picture without corrupting anything. Detection,
   via the commit anchor and the drift check (§6). No lock is involved.

Enforcement is out of scope, deliberately: a lock a model must *choose* to take is a
suggestion, because the offending session never chooses to. Each harness binds the convention
in its own hook mechanism (§7).

## 1. Where the lockfile lives

- Directory: `$REPOLOCK_DIR` if set, else `~/.repolock/locks/`. Implementations MUST create it.
- The directory is deliberately **outside every repo**: a lock must work for a checkout that
  is not a git repo yet, and must never appear in `git status` as an edit of its own.
- One file per working copy. The working copy's identity is its **canonical path**: absolute,
  symlinks resolved, case-normalized per platform (`realpath` + `normcase`).
- Filename: `<basename>-<key>.json`, where `key` is the first 16 hex chars of the SHA-256 of
  the canonical path (UTF-8). The basename is only for human readability of the directory;
  the hash is the identity.

## 2. The record

A single JSON object. Writers MUST write it **atomically** (write a temp file in the same
directory, fsync, rename) — a torn read is a lock held by nobody.

| field           | type            | meaning                                             |
|-----------------|-----------------|-----------------------------------------------------|
| `repo`          | string          | canonical working-copy path (§1)                    |
| `session`       | string          | opaque id of the holder (harness session id)        |
| `pid`           | int             | holder's process id, or `0` when none exists (§4)   |
| `intent`        | string          | free text: what the holder is doing                 |
| `acquired_at`   | float, epoch s  | when the lock was first taken                       |
| `renewed_at`    | float, epoch s  | last activity (§3)                                  |
| `expires_at`    | float, epoch s  | end of the current lease                            |
| `lease_seconds` | float           | the declared lease length                           |
| `base_commit`   | string \| null  | HEAD when the lock was taken — the handoff anchor   |
| `idle_since`    | float \| null   | set when the holder went idle with a dirty tree (§5)|
| `dirty_at_idle` | list of string  | `git status --porcelain` lines at that moment       |

Readers MUST treat an unparsable record as **no lock** (garbage to be overwritten), and MUST
ignore unknown fields.

## 3. Leases, renewed by activity

- A lock is **short-lived**, taken immediately before a write. The acquirer declares its lease
  (reference default 900 s; hooks use 600 s; implementations MUST cap at 4 h).
- The lease is renewed **by activity**: a harness hook renews on every tool call. A tool call
  IS the activity — there is no daemon to supervise, and an idle session lets go on its own
  because nothing renews for it.
- Acquire is **reentrant**: the holder acquiring again is a renewal, so a session never
  deadlocks against itself.

## 4. Liveness: who still holds a lock

A lock **binds** while its lease is unexpired **AND** its holder still exists:

- lease alone would let a crashed session block others until it ran out;
- PID liveness alone would let an idle session hold the repo for hours;
- each covers the other's blind spot.

`pid <= 0` means "no PID was recorded" and MUST read as *cannot disprove liveness*: locks taken
by a hook have no usable PID (the hook process exits immediately), and treating them as dead
would get every hook-taken lock stolen on sight. A PID-less lock therefore degrades to
**lease-only** liveness — which is why leases are short.

An acquire against a **binding** lock MUST be refused (verdict `held`). An acquire against a
lapsed or dead lock MUST succeed as a **takeover, with a handoff** (§6). Lock operations MUST
return verdicts, never raise: an exception in a hook is a session that cannot edit anything.

## 5. Release, and the idle boundary

- Release MUST be refused while the working tree is dirty (verdict `dirty`), unless forced.
  "Commit fast" as a rule, not an aspiration: handing over a tree with someone's half-finished
  edits is strictly worse than making the next session wait.
- Release MUST be idempotent: releasing an unheld lock is success, so hooks, tools and
  crash-recovery can all release without coordinating.
- Only the holder releases; anyone else's release MUST be refused (`denied`) unless forced.
  Force is the human's deliberate override, never the routine path.
- When the holder goes **idle** (hands control back to its human):
  - clean tree → release; holding would be pure obstruction;
  - dirty tree → do NOT release; record `idle_since` and `dirty_at_idle` and let the lease
    lapse on its own schedule. The takeover handoff then says exactly what was left behind.

## 6. The anchor, the handoff, and the drift check

- Every lock taken in a git checkout MUST record `base_commit` = HEAD at acquisition.
- A takeover (§4) MUST hand the next writer: the previous session and intent, why its claim
  ended, the base commit, current HEAD, the commits between them, whether **history was
  rewritten** (the base commit no longer exists in the object graph), and any uncommitted files.
- The **drift check** is read-side and lock-free: given the HEAD a session last saw, report
  `current`, `moved` (with the commits between), or `rewritten` (the seen commit no longer
  exists — everything the session remembers about this repo is suspect). Harnesses SHOULD run
  it at session start and on each return of control, remembering HEAD per (session, repo).

## 7. Adapter obligations

A harness adapter MUST:

1. gate every **write** (file edits, and git commands that mutate the tree or history —
   including the read-write ones: `checkout`, `pull`, `stash`) behind acquire-or-renew;
2. block the write and surface the holder, lease, and intent when the verdict is `held`;
3. surface the handoff verbatim on takeover;
4. release-or-go-idle when the session returns control to the human;
5. run the drift check when a session starts or resumes;
6. **fail open, loudly**: a crashing adapter must never wedge the machine — an unguarded write
   is bad, a laptop where nobody can edit anything is worse, and silent is worst.

Over-inclusive write detection is correct: a false positive costs a lock you'd have taken
anyway; a false negative is an unguarded write, which is the bug.

## Non-goals

- **Not a network lock.** One machine, one filesystem. Advisory across NFS is out of scope.
- **Not sandboxing.** A process that ignores the convention can still write; the convention is
  for cooperating harnesses, and enforcement strength comes from their hooks.
- **Not a replacement for worktree isolation.** Where a harness can give each session its own
  worktree, that is the better answer; this convention covers what worktrees don't reach —
  interactive sessions deliberately pointed at the same checkout, mixed-vendor fleets, and the
  stale-reader drift check.
