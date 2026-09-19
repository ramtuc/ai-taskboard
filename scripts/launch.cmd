@echo off
rem ai-taskboard: start the server if needed, wait until it answers, open it in the default browser.
rem   This is the one-double-click entry point: launch.cmd in the repo root just calls this file.
rem   If something already LISTENs on the port it does not start a second server - it only opens
rem   the browser. Otherwise it starts scripts\serve-hidden.vbs (no console; log goes to
rem   data\logs\serve.log) without waiting for it, polls http://127.0.0.1:<port>/healthz about once
rem   a second for up to 30 seconds, opens http://127.0.0.1:<port>/ and closes this window.
rem   Only on failure it prints what to look at and pauses. Stop the server with scripts\stop.cmd.
rem   Usage: launch.cmd [--port N]
rem   Environment (all optional):
rem     TASKBOARD_PORT     port to check, serve and open (default 8765; --port N wins, like serve.cmd)
rem     TASKBOARD_NOPAUSE  set to anything to skip the "pause" on failure
rem     TASKBOARD_UV / TASKBOARD_LOG / TASKBOARD_DB are inherited by serve-hidden.vbs -> serve.cmd
rem   Exit code: 0 browser opened / 1 no answer from /healthz within 30 seconds
setlocal
cd /d "%~dp0.."
set "RC=0"
set "PORT=%TASKBOARD_PORT%"
if not defined PORT set "PORT=8765"
if /i "%~1"=="--port" if not "%~2"=="" set "PORT=%~2"
set "URL=http://127.0.0.1:%PORT%/"
set "WAIT=30"

rem same check as serve.cmd / stop.cmd: a LISTENING socket on the port means "already running"
set "PID="
for /f "tokens=5" %%p in ('netstat -ano -p tcp ^| findstr /r /c:":%PORT% .*LISTENING"') do if not defined PID set "PID=%%p"
if defined PID (
  echo [ai-taskboard] already running on port %PORT% - PID %PID%
) else (
  echo [ai-taskboard] starting the server on port %PORT% ^(hidden, log: data\logs\serve.log^) ...
  start "" wscript.exe "%~dp0serve-hidden.vbs" /port:%PORT%
)

rem Wait for /healthz with ONE PowerShell 5.1 process that polls against a real clock deadline.
rem Why not "30 x (curl.exe -m 2 + 1 s sleep)" in cmd: a refused connect to 127.0.0.1 takes about
rem 2 s on Windows (the stack retries the SYN before it gives up), so counting probes silently
rem stretches 30 s into ~90 s, and cmd has no locale-safe clock arithmetic (%TIME% format varies).
rem -UseBasicParsing keeps the IE engine out of it; -TimeoutSec 2 caps each probe; the deadline is
rem checked after every probe, so the worst case is about WAIT + 2 s. Exit 0 = HTTP 200 seen.
powershell -NoProfile -NonInteractive -Command "$ProgressPreference='SilentlyContinue'; $u='%URL%healthz'; $t0=Get-Date; $dl=$t0.AddSeconds(%WAIT%); while ($true) { try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $u; if ($r.StatusCode -eq 200) { Write-Host ('[ai-taskboard] /healthz answered after {0} s' -f [int]((Get-Date)-$t0).TotalSeconds); exit 0 } } catch {}; if ((Get-Date) -ge $dl) { exit 1 }; Start-Sleep -Seconds 1 }"
if errorlevel 1 goto :timeout

echo [ai-taskboard] opening %URL%
start "" "%URL%"
goto :end

:timeout
echo [ai-taskboard] no answer from %URL%healthz after %WAIT% seconds.
if defined PID (
  echo   port %PORT% is held by PID %PID% but it does not answer like this app. Check: tasklist /fi "PID eq %PID%"
) else (
  echo   the server did not come up. uv may be missing from PATH, or the app failed at start-up.
  echo   run scripts\serve.cmd in a console to see the error, or read data\logs\serve.log
)
set "RC=1"

:end
if %RC% NEQ 0 if not defined TASKBOARD_NOPAUSE pause
exit /b %RC%
