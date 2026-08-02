"""The reset, within reach: one exe that takes every transponder process down and puts the tray back.

Two kinds of process answer to the name. The MCP server (`transponder.server`) is stdio, spawned
per agent session — killing it is the whole restart: the session that owned it reconnects (or a
new session spawns fresh) and gets the current code. Nothing here relaunches a server, because a
stdio server with no session on the other end is a process with nobody to talk to. The tray
(`transponder-tray`) is the opposite — one per machine, owned by no session — so after the sweep
it is started again, windowless, from its stable path beside this exe.

The kill matches command lines, not process names: the server runs as python.exe (twice over,
venv and uv-managed) and as a uv wrapper, and none of those names says transponder. The patterns
`transponder.server` and `transponder[-.]tray` catch all of them — the exe trampoline and the
`pythonw -m transponder.tray` form alike — and cannot catch this process, whose own command
line says `transponder-relaunch`.

Not an entry point, and that is the lesson this file carries: uv's venv launchers are
console-subsystem even under `[project.gui-scripts]` (same finding as tray.vbs, against uv
0.11.26), so a Scripts exe for this module opens a console — and a console over a process tree
is a kill switch handed to whoever closes it. The double-clickable face is
`transponder-relaunch.exe` at the repo root, a real Windows-subsystem stub compiled from
`relaunch_stub.cs`, which runs this module through pythonw with every window suppressed.

The tray is relaunched as `pythonw -m transponder.tray`, never as Scripts/transponder-tray.exe:
uv's script trampoline dies under CREATE_NO_WINDOW ("warning: Failed to wait for input from
window", exit 0xC000013A) — it needs the window it was told not to have. And CREATE_NO_WINDOW
comes *alone* — never with DETACHED_PROCESS, the two are mutually exclusive, and the pair
silently left the tray attached to the launcher's console, which is how closing that console
once took the icon down with it.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

KILL = (
    "Get-CimInstance Win32_Process |"
    " Where-Object { $_.CommandLine -match 'transponder\\.server|transponder[-.]tray' } |"
    " ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
)


def main() -> int:
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", KILL],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(0.5)  # let the tray's named mutex die with its process before the successor claims it
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen(
        [str(pythonw), "-m", "transponder.tray"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
