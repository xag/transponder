"""The membrane: every effect the channel depends on, and nothing else.

`repolock/scope.py` (the claims map) and `repolock/witness.py` (what actually happened) are pure
logic over this module. Everything nondeterministic lives here — the clock, the claim files on
disk, and git — so that the boundary is one import away and any trajectory can be recorded and
replayed (see repolock/flight.py).

Keep this module dumb. No policy, no decisions: read the world, write the world, and let the other
side judge. A function that branches on what it read belongs on the other side.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time


def now() -> float:
    """Epoch seconds. The only clock — claim leases are how stale information decays, so this is
    the decay function of the whole map."""
    return time.time()


def lock_dir() -> str:
    """The state directory's anchor (the name predates the rename — claims, memos and the switch
    all live beside it). Deliberately outside every repo: state about a checkout must never show
    up in `git status` as an edit of its own."""
    d = os.getenv("REPOLOCK_DIR") or os.path.join(os.path.expanduser("~"), ".repolock", "locks")
    os.makedirs(d, exist_ok=True)
    return d


def disabled_path() -> str:
    """The panic file itself. Its PRESENCE is the switch; its contents are a note to whoever finds
    it — who turned the lock off, when, and why. A zero-byte file is a mystery in a fortnight."""
    return os.path.join(os.path.dirname(lock_dir()), "DISABLED")


def disabled() -> bool:
    """The panic switch: `~/.repolock/DISABLED` (or REPOLOCK_DISABLED=1) and every adapter becomes
    a no-op that blocks nothing.

    A file rather than only an env var, and checked on every hook call rather than at install time,
    because the sessions you most need to free are the ones already running: a harness snapshots
    its hooks at session start, so editing settings.json cannot reach them and neither can an env
    var they were launched without. Touching a file can. Uninstalling should never require a
    machine-wide restart of the work it is holding up.
    """
    value = os.getenv("REPOLOCK_DISABLED")
    if value is not None:                 # an explicit setting wins, in BOTH directions: a test (or
        return value.strip().lower() in ("1", "true", "on", "yes")   # a session) must be able to
                                          # turn the lock back on without deleting the machine's
                                          # panic file out from under everyone else.
    return os.path.exists(disabled_path())


def recording() -> bool:
    """Is flight recording on? ON by default — `REPOLOCK_FLIGHT=0` (or `false`/`off`/`no`) is the
    only way to switch it off.

    It lives here, in the stdlib-only module, so that a caller can ask the question without
    importing repolock.flight — importing that module is what pulls in flight_recorder, so asking
    must not be the thing that answers.
    """
    value = os.getenv("REPOLOCK_FLIGHT")
    if value is None:
        return True                       # unset is the default, and the default is ON
    return value.strip().lower() not in ("0", "false", "off", "no", "")


def flight_dir() -> str:
    """Where recordings land: absolute, and outside every repo, for the same reason lock_dir is.
    The hook runs with cwd set to the session's own checkout, so a relative default would drop a
    recording directory into every repo on the machine and dirty the tree it is watching."""
    return os.getenv("REPOLOCK_FLIGHT_DIR") or os.path.join(
        os.path.expanduser("~"), ".repolock", "flight")


def canonical(path: str) -> str:
    """The one true spelling of a path — so `C:\\x` and `c:/x/.` are one resource, and two agents
    cannot hold one file under two names. The claims namespace rests on this function."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


# --- the claim store (SPEC §2) ---------------------------------------------------------------
#
# MACHINE-GLOBAL, not per-repo, because the namespace a claim is written in is the local filesystem
# itself: every scope entry is a canonical absolute path, so the store needs no second notion of
# where a claim "belongs" — the paths already say. The repo is only the anchor that resolved the
# relative spellings, and keying the store on it would re-introduce exactly the ambiguity (#8's
# whole family) that canonical paths abolish.
#
# One file per agent, never one shared list. That is not tidiness, it is the only way this is safe
# without a mutex of its own: a list would be read-modify-write, so two agents declaring at the same
# instant would clobber each other — and a claim store that loses a claim under contention loses it
# exactly when it is needed. Each agent writes only its OWN file; reading the directory enumerates
# the claims.

def claims_dir() -> str:
    """Beside the lockfiles, and outside every repo, for the reasons lock_dir() gives."""
    d = os.path.join(os.path.dirname(lock_dir()), "claims")
    os.makedirs(d, exist_ok=True)
    return d


def claim_path(session: str) -> str:
    return os.path.join(claims_dir(), f"{hashlib.sha256(session.encode()).hexdigest()[:16]}.json")


def read_claims() -> list[str]:
    """The raw text of every claim on the machine. Unparsable ones are the caller's problem — the
    SPEC says a torn record reads as no claim, and that judgement is policy, so it is not made here."""
    out = []
    try:
        names = sorted(os.listdir(claims_dir()))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(claims_dir(), name), encoding="utf-8") as f:
                out.append(f.read())
        except OSError:
            continue
    return out


def write_claim(session: str, text: str) -> str:
    """Atomic, for the same reason write_record is: a torn claim is a region nobody owns."""
    path = claim_path(session)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def remove_claim(session: str) -> bool:
    try:
        os.remove(claim_path(session))
        return True
    except OSError:
        return False


def _run(args: list[str], cwd: str | None) -> str | None:
    try:
        res = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def git_head(repo: str) -> str | None:
    """The commit the working copy is on. None when it isn't a git repo — the lock still works,
    it just can't offer a handoff base."""
    out = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    return out.strip() if out else None


def git_dirty(repo: str) -> list[str]:
    """Porcelain lines for the working tree. Empty means clean, which is what release demands."""
    out = _run(["git", "status", "--porcelain"], cwd=repo)
    return [ln for ln in (out or "").splitlines() if ln.strip()]


def file_stat(path: str) -> tuple[int, int] | None:
    """(size, mtime_ns) for one path, or None if it is gone.

    The reason the porcelain alone is not enough: a file that is already ` M` stays ` M` when it is
    edited again, so the status line is identical across a write and the write goes unseen. The
    stat moves every time the bytes do.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def git_log_between(repo: str, base: str, head: str) -> list[str]:
    """One line per commit in base..head — the "what changed while I was away" of a handoff.

    Returns [] when base is unreachable (the usual reason: the predecessor rebased it out of
    existence, which is precisely the interesting case), so callers must treat [] as "can't
    say", not as "nothing changed" — see lock.py, which cross-checks base != head.
    """
    if not base or not head or base == head:
        return []
    out = _run(["git", "log", "--oneline", "--no-decorate", f"{base}..{head}"], cwd=repo)
    return [ln for ln in (out or "").splitlines() if ln.strip()]


def git_paths_between(repo: str, base: str, head: str) -> list[str]:
    """The paths touched by the commits in base..head.

    The witness cannot see a file that was created and committed inside a single tool call — it is
    never dirty, so it is in no porcelain. This is how those are recovered, and they are the ones
    that matter: a `git add -A` that swept up another agent's work shows up here and nowhere else.
    """
    if not base or not head or base == head:
        return []
    out = _run(["git", "log", "--name-only", "--pretty=format:", f"{base}..{head}"], cwd=repo)
    return sorted({ln.strip().replace("\\", "/") for ln in (out or "").splitlines() if ln.strip()})


def git_tracked_dirs(repo: str) -> list[str]:
    """Top-level directories git tracks. Only used to tell a refused agent WHERE IT MAY GO instead —
    a conflict has to be an answer, not a wall (SPEC §2)."""
    out = _run(["git", "ls-tree", "-d", "--name-only", "HEAD"], cwd=repo)
    return [ln.strip().replace("\\", "/") for ln in (out or "").splitlines() if ln.strip()]


def git_commit_exists(repo: str, sha: str) -> bool:
    """Does this commit still exist in the object graph? A `False` for a base we recorded
    ourselves means history was rewritten under us — the incident class that motivated the
    drift check."""
    if not sha:
        return False
    return _run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo) is not None
