// The window that never opens. uv's venv launchers are console-subsystem even for gui-scripts,
// so no exe uv generates can be double-clicked without dragging a console onto the screen — and
// a console over the tray's process tree is a kill switch (closing it is how the icon died
// once). This stub is the piece uv cannot provide: a real /target:winexe binary, compiled with
// the csc.exe every Windows ships (no SDK to install), that runs `pythonw -m
// transponder.relaunch` with the console it would still try to make explicitly suppressed.
//
// Build, from the repo root:
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:winexe
//       /out:transponder-relaunch.exe transponder\relaunch_stub.cs
//
// The exe lives at the repo root and finds .venv beside itself, same convention as tray.vbs.
// All behaviour stays in transponder/relaunch.py — this file only decides that nothing is shown.

using System.Diagnostics;
using System.IO;
using System.Reflection;

static class RelaunchStub
{
    static int Main()
    {
        string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        var psi = new ProcessStartInfo
        {
            FileName = Path.Combine(root, @".venv\Scripts\pythonw.exe"),
            Arguments = "-m transponder.relaunch",
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        Process.Start(psi);
        return 0;
    }
}
