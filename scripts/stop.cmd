@echo off
rem ai-taskboard: stop the server that is LISTENING on the port (default 8765).
rem   Finds the single PID bound to the port and ends it with "taskkill /PID <pid> /F" - never by
rem   image name, so other Python processes are untouched. uvicorn gets no graceful shutdown; the DB
rem   is SQLite in WAL mode and survives that by design (SPEC 6-4). The uv / cmd / wscript parents
rem   exit on their own once the server process is gone.
rem   Usage: stop.cmd [--port N]     Environment: TASKBOARD_PORT, TASKBOARD_NOPAUSE
rem   Before killing it drops %TEMP%\ai-taskboard-stop-<port>.flag; serve.cmd consumes the flag and
rem   exits 0, so a scheduled task does not count the stop as a failure and restart the server.
rem   Exit code: 0 stopped or nothing was listening / 1 still in use or refused
setlocal
set "RC=0"
set "PORT=%TASKBOARD_PORT%"
if not defined PORT set "PORT=8765"
if /i "%~1"=="--port" if not "%~2"=="" set "PORT=%~2"

set "PID="
for /f "tokens=5" %%p in ('netstat -ano -p tcp ^| findstr /r /c:":%PORT% .*LISTENING"') do if not defined PID set "PID=%%p"
if not defined PID (
  echo [ai-taskboard] nothing is listening on port %PORT% - nothing to stop.
  goto :end
)
if %PID% LEQ 4 (
  echo [ai-taskboard] port %PORT% is held by system PID %PID% - refusing to touch it.
  set "RC=1"
  goto :end
)
echo [ai-taskboard] port %PORT% is held by PID %PID%:
tasklist /fi "PID eq %PID%" /fo table /nh
echo stop>"%TEMP%\ai-taskboard-stop-%PORT%.flag"
echo [ai-taskboard] stopping PID %PID% ...
taskkill /PID %PID% /F
ping -n 2 127.0.0.1 >nul
netstat -ano -p tcp | findstr /r /c:":%PORT% .*LISTENING" >nul
if errorlevel 1 (
  echo [ai-taskboard] stopped.
) else (
  echo [ai-taskboard] port %PORT% is still in use. Check Task Manager.
  set "RC=1"
)

:end
if not defined TASKBOARD_NOPAUSE pause
exit /b %RC%
