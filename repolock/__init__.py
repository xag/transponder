"""repolock — one developer, several AI agent sessions, one checkout.

A lockfile convention (SPEC.md) plus this reference implementation. The core is pure stdlib:
`repolock.lock` decides, `repolock.env` touches the world. Optional layers — the MCP server
(`repolock.server`, extra `mcp`) and flight recording (`repolock.flight`, extra `flight`) —
are imported only when actually used, so the lock itself costs nothing to adopt.
"""

from repolock.lock import (  # noqa: F401
    DEFAULT_LEASE_SECONDS,
    MAX_LEASE_SECONDS,
    WARN_BEFORE_SECONDS,
    Lock,
    acquire,
    drift,
    go_idle,
    needs_commit_warning,
    release,
    renew,
    status,
)
