# repolock v2 — negotiated scopes

> **Status: PROPOSAL.** Not implemented. [SPEC.md](SPEC.md) is what ships today and remains
> normative until this replaces it. Discussion: [#14](https://github.com/xag/repolock/issues/14).
>
> This document changes what the project *is*, so it is written to be argued with rather than
> merely read. Where it takes something away that v1 promised, it says so under that heading.

## 0. The turn

v1 is a **gate**. It decides, for each tool call, whether an agent may write a checkout, and it
refuses the ones that would collide. Everything hard about it follows from that: the undecidability
of reading a command (§7a), the pessimistic hold, the tickets a refused session needs in order to
wait at all, the off switch that must live where the gate cannot reach it.

v2 is a **channel**. Agents declare what they intend to write, see what everyone else has declared,
and stay out of each other's way. Nothing needs to be guessed, because the agent *says*. Nothing
needs to be refused, because there is nothing to collide with.

The failure this library exists to prevent was never malice, and reading the incidents back it was
never even carelessness. **It was ignorance.** Every one of them is an agent that did not know
another agent was there. You do not deter ignorance. You inform it — and a channel informs where a
gate can only obstruct.

### What that does NOT mean

It does not mean trusting agents and hoping. Two things keep this honest, and both are load-bearing:

- **Silence still costs everything (§4).** An agent that declares nothing is given scope `**`, which
  conflicts with every other scope — *exactly v1's whole-checkout mutex*. Concurrency is granted only
  to agents that opted in by declaring, and those are, by construction, the cooperating ones. **The
  guarantee v2 "gives up" was only ever held over agents who would have honoured the channel anyway.**
- **The witness stays (§7).** Every write is still observed, by fingerprint, exactly as in v1 §7b. A
  contract nobody checks is a wish. The hook stops being the gate and becomes the **witness** and the
  **courier**; it does not stop existing.

## 1. Scope

A **scope** is a set of **resources** an agent reserves before it works. A resource is any name the
implementation and its agents agree on. Paths are the obvious ones and they are not the only ones:

| resource            | reserves                                                          |
|---------------------|-------------------------------------------------------------------|
| `path:app/api/**`   | those working-copy paths (glob)                                    |
| `git:index`         | the staging area — **the resource that makes this work, see §1a**  |
| `git:HEAD`          | commits, rebases, checkouts: anything that moves the branch        |
| `branch:main`       | a named branch                                                     |
| `port:3000`         | a dev server, a debugger, anything a second agent would fight over |

Resources MUST have a defined **overlap** relation. Two scopes **conflict** iff any resource in one
overlaps any resource in the other. For `path:` globs, overlap is glob intersection; for opaque
names, string equality.

Paths that **git ignores are not reservable and are never observed** — the same rule as v1's
fingerprint. Without it, `node_modules/`, `dist/` and `.pytest_cache/` make every scope conflict with
every other scope, every time, and the protocol dies of false positives in an afternoon.

### 1a. `git:index` is not a nicety, it is the reason resource scopes exist

Take path scopes alone. Agent A holds `path:api/**`, agent B holds `path:web/**`, and they edit
concurrently — which is the entire point. Then A runs `git add -A && git commit`.

It sweeps B's half-finished edits into A's commit. **That is the founding incident of this library**,
and path-only scopes hand it straight back: in v1 it is prevented only as a side effect of B never
being able to edit at all while A holds the checkout.

It cannot be prevented by inspection — knowing that a command is a whole-tree stage means reading the
command, and v1 §7a is the proof that this is not decidable.

Resource scopes dissolve it without anyone reading anything. **An agent that intends to commit MUST
reserve `git:index` and `git:HEAD`.** Commits serialise. Nobody parsed a command line to get there.

## 2. The protocol

Every step below is an MCP call. MCP is ungated by construction (v1 §7c), so **an agent can always
reach the channel, including one that is currently blocked, wedged, or being asked to give something
up.** That property is not a convenience here; it is what makes the channel a channel.

```
declare(repo, scope, intent)   -> granted | conflict(with: [{agent, scope, intent, since}])
extend(repo, add)              -> granted | conflict(...)          # widening: see §5
release(repo, drop)            -> ok                               # narrowing, or letting go
scopes(repo)                   -> who holds what, and why
```

**`declare` is all-or-nothing.** An agent states its whole scope up front and is granted all of it or
none of it. This is conservative two-phase locking, and it is the reason v2 has no deadlock: no
incremental acquisition, therefore no cycle, therefore no wait-for graph, no detection, no victim
selection, and nothing to debug at 2am on a wedged laptop. Deadlock is designed out rather than
managed.

**A conflict is an answer, not a refusal.** v1 tells a blocked agent *why* it is blocked and hands it
a way to wait. v2 tells it **who holds what**, so it can come back with a scope that fits and proceed
*immediately*:

```
CONFLICT — app/server/** is held by agent 8663de9b (adding the rate limiter, 4m).
Free right now: app/web/**, tests/**, docs/**.
Take a narrower scope and carry on, or ask them to narrow theirs (see §3).
```

Waiting becomes the fallback. In v1 it is the outcome.

## 3. The channel is duplex

An agent turn **cannot be interrupted**, and nothing can push into it. That is not a limitation of
this design; it is a fact about agent harnesses, and every delivery mechanism must be built out of
what remains. Two things remain, and between them they cover both states an agent can be in:

- **A working agent** is making tool calls, and the hook prints to stdout on every one of them. An
  inbound request rides its **next tool call**. No daemon, no push, no new machinery.
- **A parked or blocked agent** is making no tool calls, so there is nothing to ride. It launches a
  **listener** — the v1 waiter (#5, #10), generalised from *"wait until this lock frees"* to *"wait
  until something is addressed to me"*. The listener **exits** on a message, because **exiting is the
  only signal that wakes a harness**. The agent is woken, reads the message, and relaunches it.

So an agent that listens is reachable *promptly*, not merely eventually — it does not have to make a
tool call to hear you.

The listener is a shell command, and a blocked agent cannot run shells. So, exactly as in v1 §7.9,
**the channel MUST mint the listener as a one-time ticket**, allowed by byte-equality against a string
it wrote itself, one spelling per shell, with a test that runs it in a real one. Every word of
xag/repolock#10 applies here unchanged, and it will be re-learned the hard way by anyone who skips it.

### What may be pushed

```
please_narrow(repo, agent, scope, why)   # "I need web/**; you hold ** and haven't touched it"
```

The holder MAY comply, MAY counter-offer, MAY decline. **It is a request, not a preemption.** An
agent mid-edit in a region cannot be made to drop it — that would hand its half-finished tree to
someone else, which is the thing v1 §5 refuses and v2 has no reason to start doing.

## 4. Silence, and what it costs

An agent that has declared nothing holds `**` — every resource in the checkout.

That single rule is what makes v2 safe to adopt:

- an agent that has never heard of scopes behaves **exactly as it does under v1**, and is excluded
  from a checkout another agent is working, exactly as under v1;
- a legacy or third-party harness costs nothing and breaks nothing;
- **v1 is the degenerate case of v2** — the state in which every agent asks for everything.

Migration is therefore not a flag day. It is agents learning to ask for less.

## 5. Widening, which is the one genuinely hard operation

`declare` is all-or-nothing and up front. Real work is not: an agent halfway through a task discovers
it must touch one more module.

It cannot simply release and re-declare — it is holding uncommitted work, and v1 §5 (which stands)
forbids releasing a dirty tree. So `extend` **is** incremental acquisition, and incremental
acquisition is where deadlock lives.

v2 does not solve this with a wait-for graph. It solves it with the channel:

- `extend` **never blocks**. It returns `granted`, or `conflict` naming the holder.
- On `conflict` the agent MAY `please_narrow` the holder and get on with something else, or commit
  what it has and re-`declare` from a clean tree.
- An agent MUST NOT sit and spin on `extend`. Two agents each blocked in `extend` on the other's
  region is a deadlock, and it is the only shape of deadlock v2 admits — so this is the rule that
  keeps the design's central claim true, and it MUST be tested rather than asserted.

## 6. What is still enforced

Not everything becomes advisory. The hook still knows, for free and without guessing, the target of
every **declared** write:

- `Edit` / `Write` / `NotebookEdit` carry a `file_path`. A write to a path **outside the writing
  agent's own scope MUST be refused**, before it happens, with the conflict message from §2. This is
  v1 §7.1 unchanged, with the scope taking the place of the checkout.
- The refusal is *useful* now, which it never was in v1: the agent is not told to wait, it is told to
  declare the region it evidently meant to write.

## 7. The witness, and what it cannot do

For a **shell** or an **MCP call**, the target is not declared, and v1 §7a is the standing proof that
it cannot be recovered from the text. So the fingerprint (v1 §7b) stays, and its job changes: it no
longer decides who takes a lock, it **witnesses who wrote what**.

- writes inside the writer's own scope: expected, correct, silent;
- writes **outside** it, into a region another agent reserved: a **violation**. It is detected, it is
  named (culprit, victim, paths, commit), it is loud, and it is **NOT PREVENTED**.

### 7a. This is a real loss, and v1 explicitly forbids it

v1 §7b, on detection-instead-of-exclusion for shells:

> *"a known-reachable hole in a mutex is not a residual risk, it is the absence of the mutex on that
> path. It was rejected. An adapter MUST NOT implement it."*

**v2 reverses that sentence for the shell path, and must own it.** Under v1 two agents cannot run
shells against one checkout at the same instant. Under v2, two agents with disjoint scopes can — and
nothing stops one of them writing into the other's region.

The case for reversing it:

- the hole is bounded to **out-of-scope** writes, where v1's MCP hole (§7c) is *every* MCP write, so
  the unsound surface **shrinks** rather than grows;
- a violation has a culprit, a victim, an alarm and a diff, where a v1 collision had none of those;
- the exclusion being traded away was **never machine-wide**. It binds only agents whose harness runs
  the hook — the very population that would honour a channel. A human in an editor, a `cron` job, a
  harness with no adapter: all of these already write freely, and v1's own non-goals admit it
  ("*Not sandboxing… the convention is for cooperating harnesses*").

The case against, which must not be waved through: it is a **weaker guarantee than the one we have**,
and this library's entire history is of weaker guarantees being discovered in production.

### 7b. What a violation MUST do

Detection with no consequence is a log line. On observing an out-of-scope write, an implementation
MUST:

1. **tell the violator, immediately**, on its next hook call: what it wrote, whose region it landed
   in, and that it must stop;
2. **tell the victim**, through the channel — this is what the duplex channel is *for*;
3. **refuse that agent's further declared writes** until it re-declares a scope that covers what it
   is evidently doing, or reverts. It cannot unwrite the bytes; it can be stopped from continuing;
4. where the violation is a **commit** (`git:HEAD` moved with out-of-scope paths in it), say so with
   the sha — a commit is the one violation that is cleanly **recoverable**, and the message MUST say
   `git revert`/`git reset` rather than leaving the agent to work it out.

## 8. The cooperation assumption, stated plainly so it can be attacked

**v2 assumes agents cooperate.** The assumption is not "agents are good". It is:

- they are driven by **one human**, who wants all of their work to survive;
- the failure mode observed in every incident in this repository is **ignorance, not defection** — an
  agent that did not know another was there;
- **there is no adversary to model.** An agent that stomps a scope is not defecting in a repeated
  game: it has no memory across sessions, no reputation, and no future to lose. Which is exactly why
  **deterrence cannot be the mechanism** — "they risk being stomped back" is not an argument, it is a
  hope, and it MUST NOT appear in the reasoning for this design.

What replaces deterrence is **information plus a witness**: an agent that can see the other scopes has
no reason to collide, and one that collides anyway is named immediately rather than discovered a week
later in a mangled rebase.

**If this assumption is wrong, v2 is wrong** — and the honest kill condition is §7b's alarm firing
regularly in tapes, from agents that had declared a scope and wrote outside it anyway. That is
mechanical, it is cheap, and it fires long before anyone loses a day's work.

## 9. What v1 keeps

Unchanged, and not up for renegotiation: the lockfile record and its atomicity; leases renewed by
activity; liveness (lease **and** holder); the commit anchor, the takeover handoff and the drift check
(§6 — it needs no scopes and catches what no scope can); the dirty-tree release refusal and the
handback (§5, §5a); fail-open-loudly; the off switch (§7 obligation 11); **and the ungated MCP channel
(§7c), on which the whole of v2's negotiation now rides.**

## 10. Open, and not to be closed by assertion

1. **Scope granularity in practice.** Agents do not reliably know where they will write. If declared
   scopes are wrong most of the time, §7b's alarm fires constantly, and an alarm that always fires is
   an alarm nobody reads. This is the likeliest way v2 fails, and it is measurable *before* building
   it: take the existing tapes and ask what scope each recorded session would have had to declare.
2. **Who is an agent?** v1 keys on the harness session id, and subagents share their parent's
   (`hyp-subagents-share-the-session-id`). Scopes make that reentrancy sharper, not softer: two
   subagents of one session with disjoint scopes are two writers with one identity.
3. **Does the shell still take anything at all?** §7 says no. The alternative — a shell keeps taking
   the whole checkout, and only editors and MCP use scopes — preserves v1's hard exclusion and buys
   almost no concurrency, since agents run shells constantly. It should be written down as the
   rejected alternative it is, with this sentence as the reason.
4. **`please_narrow` and starvation.** A holder that always declines is a holder that starves
   everyone else, and v2 has no preemption by design (§3). Is the lease the only backstop?
