' ai-taskboard: start the Web UI with no console window.
'   Double-click this file, or let the scheduled task (install-autostart.ps1) run it at logon.
'   It runs scripts\serve.cmd hidden and waits for it, so the exit code reaches Task Scheduler
'   and "Running" in Task Scheduler means the server is up. uvicorn output and start/stop lines
'   go to data\logs\serve.log (override with TASKBOARD_LOG). Stop with scripts\stop.cmd.
'   Named arguments (all optional):
'     /uv:"C:\path\to\uv.exe"   use this uv instead of the one on PATH (install-autostart.ps1 passes it)
'     /port:8765                port to check and serve (same as TASKBOARD_PORT)
Option Explicit
Dim fso, sh, env, named, scriptDir, root, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
Set env = sh.Environment("Process")
Set named = WScript.Arguments.Named
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(scriptDir)

env("TASKBOARD_NOPAUSE") = "1"
If env("TASKBOARD_LOG") = "" Then env("TASKBOARD_LOG") = fso.BuildPath(root, "data\logs\serve.log")
If named.Exists("uv") Then env("TASKBOARD_UV") = named("uv")
If named.Exists("port") Then env("TASKBOARD_PORT") = named("port")

sh.CurrentDirectory = root
rc = sh.Run("cmd.exe /c """ & fso.BuildPath(scriptDir, "serve.cmd") & """", 0, True)
WScript.Quit rc
