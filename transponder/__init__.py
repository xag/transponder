"""transponder — one developer, several AI agent sessions, one machine of shared checkouts.

Not a lock any more, despite the name (a rename is coming): an INFORMATION layer. Agents declare
where they will write (`transponder.scope`, the claims map), a witness reports what actually happened
(`transponder.witness`), and harness hooks carry both into every agent's context. Nothing is ever
refused; the map, the notes and the loud violation report are the whole enforcement model.

The core is pure stdlib: `scope` and `witness` decide, `env` touches the world. Optional layers —
the MCP channel (`transponder.server`, extra `mcp`) and flight recording (`transponder.flight`, extra
`flight`) — are imported only when actually used.
"""

from transponder.scope import (  # noqa: F401
    LEASE_SECONDS,
    canon,
    conflicts,
    covers,
    declare,
    declared,
    extend,
    intersection,
    live,
    overlaps,
    release,
    scope_of,
    touching,
)
from transponder.witness import drift  # noqa: F401
