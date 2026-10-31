"""The fourth answer to NOT CLEAR: keep the work, do it in a worktree of your own, land it later.

Driven through a real subprocess, as an agent will launch it — the waiter's test says why: an
escape hatch that was tested in-process and had never once run is worse than none.
"""

import os
import subprocess
import sys

from transponder import branch, scope

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*args):
    return subprocess.run([sys.executable, "-m", "transponder.branch", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def commit(cwd, name, text, msg):
    with open(os.path.join(cwd, name), "w") as f:
        f.write(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-qm", msg)


def test_a_blocked_agent_branches_works_and_lands_once_the_region_frees(repo):
    assert scope.declare(repo, "A", ["a.txt"], "rewriting a")["status"] == "granted"
    assert scope.declare(repo, "B", ["a.txt"], "also a")["status"] == "conflict"

    opened = run("open", "--repo", repo, "--session", "B")
    assert opened.returncode == 0, opened.stdout + opened.stderr
    path, name = branch.names(scope.canon(repo).replace("/", os.sep), "B")
    assert os.path.isdir(path) and path in opened.stdout, "open must make the worktree and name it"
    assert not path.startswith(os.path.normcase(os.path.realpath(repo)) + os.sep), (
        "the worktree sits inside the checkout, so a claim on the checkout's ** covers it")

    # nobody is in the worktree, so the region B wanted is green THERE
    assert scope.declare(path, "B", ["a.txt"], "also a")["status"] == "granted"
    commit(path, "a.txt", "B's a", "B rewrites a")
    commit(repo, "b.txt", "A's b", "A adds b")            # the original moves on meanwhile

    early = run("land", "--repo", repo, "--session", "B")
    assert early.returncode == 1, early.stdout + early.stderr
    assert "NOT YET" in early.stdout and "agent A" in early.stdout, (
        "landing before the region frees must say who holds it, not write into it")
    assert open(os.path.join(repo, "a.txt")).read() == "one", "a refused landing wrote anyway"

    scope.release("A")
    assert scope.declare(repo, "B", ["a.txt", ".git/index"], "landing")["status"] == "granted"
    landed = run("land", "--repo", repo, "--session", "B")
    assert landed.returncode == 0, landed.stdout + landed.stderr
    assert "LANDED" in landed.stdout
    assert open(os.path.join(repo, "a.txt")).read() == "B's a"
    assert open(os.path.join(repo, "b.txt")).read() == "A's b", "the landing lost A's commit"
    assert git(repo, "log", "--format=%s").split("\n")[:2] == ["B rewrites a", "A adds b"], (
        "landing is a rebase and a fast-forward: history stays a line")
    assert not os.path.exists(path), "the worktree outlived its landing"
    assert name not in git(repo, "branch", "--list"), "the branch outlived its landing"


def test_the_command_not_clear_prints_runs_through_a_shell(repo):
    """The answer hands the agent one string to run. The waiter's string once died in bash before
    Python saw it, so this one is run exactly as printed."""
    import pytest
    server = pytest.importorskip("transponder.server")

    assert scope.declare(repo, "A", ["a.txt"], "rewriting a")["status"] == "granted"
    answer = server.declare_work(repo, "B", ["a.txt"], "also a")
    line = next(ln.strip() for ln in answer.splitlines() if "transponder.branch open" in ln)
    ran = subprocess.run(line.replace("python", f'"{sys.executable}"', 1), shell=True, cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert ran.returncode == 0 and "BRANCHED" in ran.stdout, ran.stdout + ran.stderr


def test_a_conflict_with_the_holder_stops_in_the_worktree_and_keeps_the_work(repo):
    path, name = branch.names(scope.canon(repo).replace("/", os.sep), "B")
    assert run("open", "--repo", repo, "--session", "B").returncode == 0
    commit(path, "a.txt", "B's a", "B rewrites a")
    commit(repo, "a.txt", "A's a", "A rewrites a")

    stopped = run("land", "--repo", repo, "--session", "B")
    assert stopped.returncode == 2, stopped.stdout + stopped.stderr
    assert path in stopped.stdout, "the conflict must be resolved in the worktree, and say where"
    assert open(os.path.join(repo, "a.txt")).read() == "A's a", "a stopped landing touched the original"
    assert name in git(repo, "branch", "--list"), "a stopped landing deleted the work"
