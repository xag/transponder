"""Per-harness adapters. The lock's enforcement half cannot be an MCP tool — a tool is
something the model chooses to call, and the offending session never chooses to. Binding
enforcement lives in each harness's hook mechanism, which is vendor-specific; each module here
is one harness's adapter onto the same lockfile convention (SPEC.md)."""
