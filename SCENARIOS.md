# What actually happens, in order

Sequence diagrams for every path an agent can take through the transponder. They are here because
the protocol's hard parts are all about *timing* — when a note can be delivered, and what is known
at the moment it is sent — and prose keeps making that sound simpler than it is.

`SPEC.md` is the normative document. This one is the pictures.

---

## 1. Walking in — the introduction, once

An agent cannot see other agents from inside its own context. That is the whole premise, and the
introduction is the fact it is missing.

```mermaid
sequenceDiagram
    autonumber
    participant B as agent B
    participant H as hooks
    participant M as the map
    B->>H: any tool call
    H->>M: who is on this machine?
    M-->>H: agent A holds api/**  — "the rate limiter"
    H-->>B: YOU ARE NOT THE ONLY AGENT ON THIS MACHINE<br/>(once per session, then never again)
    B->>M: declare_scope(['web/**'], intent='the page')
    M-->>B: ON THE MAP
    Note over B,M: disjoint regions — from here on, silence
```

The intro names the machine rather than "this checkout": an agent working across a library and its
client sits in neither and needs to know about both.

---

## 2. The region is taken — a conflict is an answer, not a wall

```mermaid
sequenceDiagram
    autonumber
    participant A as agent A (holder)
    participant M as map + mail
    participant B as agent B
    B->>M: declare_scope(['api/**'])
    M-->>B: CONFLICT — A holds it<br/>overlap: api/**   free right now: web/**, docs/**
    M->>A: (direct) SOMEONE WANTS YOUR REGION — B asked, they are working around it
    B->>M: messages()
    M-->>B: A: "rebuilding index.part in place — inconsistent until the last row lands"
    B->>M: send_message(to=A) "need api/x when you are free. No reply needed."
    Note over A,B: nothing blocked · nothing written · both sides informed
```

The conflicting claim is **not registered** — the map never double-books — but no call is refused
and B keeps working somewhere else.

---

## 3. A write the witness can attribute

`Edit`/`Write` carry the path they will write. The harness *declares* it, so there is an author.

```mermaid
sequenceDiagram
    autonumber
    participant B as agent B
    participant H as hooks
    participant A as agent A (owner)
    B->>H: PreToolUse — Edit(file_path=api/server.py)
    H->>H: snapshot the checkouts on the map
    B-->>B: the write lands (nothing is ever blocked)
    B->>H: PostToolUse
    H->>H: fingerprint moved AND the tool named this path
    H-->>B: SCOPE VIOLATION — you wrote inside A's region<br/>stop · do not restore by guess · they have been told
    H->>A: (direct) SOMEONE WROTE IN YOUR REGION — look before you carry on
    Note over A: only A knows what its half-finished work was,<br/>so only A decides: keep, merge, or restore
```

---

## 4. A change the witness *cannot* attribute

A shell names nothing. The fingerprint proves the tree moved; it cannot prove who moved it — and
these two branches produce **the same picture from outside**.

```mermaid
sequenceDiagram
    autonumber
    participant B as agent B
    participant H as hooks
    participant A as agent A (owner)
    B->>H: PreToolUse — Bash("…")
    H->>H: snapshot
    par B's command runs
        B-->>B: it may have written api/server.py
    and A keeps working
        A-->>A: or A appended to its own api/server.py
    end
    B->>H: PostToolUse
    H->>H: api/server.py moved — author unknown
    H-->>B: A REGION YOU DO NOT HOLD CHANGED WHILE YOUR CALL WAS RUNNING<br/>YOU know which it was
    H--xA: nothing is sent
    Note over H,A: a false accusation to the party whose work is at stake<br/>is worse than silence
```

If it *was* B, B knows, and B has a channel to say so. That is the cooperative bet, applied to the
one fact only one agent holds.

**This is why the alarm went quiet for shells.** Reported as certainty, it fired four times at an
agent whose only crime was a read loop long enough to span a neighbour's tick.

---

## 5. Why there is no warning *before* a write

The one that surprises everybody. A hook can reach an agent before its tool runs only by refusing
the call — and this library does not refuse.

```mermaid
sequenceDiagram
    autonumber
    participant U as human
    participant M as the model
    participant H as hooks
    U->>M: a prompt
    H->>M: UserPromptSubmit context ✅ arrives BEFORE the model acts
    M->>H: PreToolUse
    H->>H: the note is produced here…
    M-->>M: the tool RUNS
    H-->>M: …and is delivered here, beside the tool result ❌
    Note over M,H: too late to prevent the write it warned about.<br/>The only earlier channel is exit 2 — which blocks.
```

So the pre-write warning was deleted rather than reworded. What genuinely arrives in time is
**pulled, not pushed**: `scopes()` and `declare_scope()` answer synchronously, in the agent's own
context, before it writes. Observed working — an agent asked, saw the holder, and declined to write.

---

## 6. Going home

```mermaid
sequenceDiagram
    autonumber
    participant A as agent A
    participant H as hooks (Stop)
    participant M as the map
    A->>H: Stop — the turn is over
    alt tree is clean
        H->>M: release A's claims in every checkout it declared
        M-->>A: off the map
    else tree is dirty and A was a participant
        H-->>A: exit 2, ONCE — commit / gitignore the artifact / stash the scrap
        Note over A,H: the one refusal in the library, and it blocks<br/>no other agent, ever
    end
```

Asked once and declined, the claims stay until the lease lapses: the work really is still there, and
the map should say so.

---

## Who is told what

| what happened | the actor is told | the region's owner is told |
|---|---|---|
| disjoint regions | nothing | nothing |
| walked into a shared machine | the introduction, once | — |
| asked for a held region | conflict + overlap + what is free | someone wants your region |
| **declared** write into another's region | SCOPE VIOLATION + remedy | someone wrote in your region |
| **shell** change in another's region | this changed while you ran | **nothing** |
| history moved underneath | drift note | — |
| said something on the channel | — | only if they call `messages()` |

The last row is the design in one line: **direct messages are pushed, the room is pulled.** Chat
traffic and the violation alarm share one delivery path, and an agent trained to skim the channel
skims the alarm with it.
