@echo off
rem ai-taskboard: start the Web UI in this console window (double-click friendly).
rem   Close the window or press Ctrl+C to stop. Extra arguments go to "taskboard serve"
rem   (e.g.  serve.cmd --port 8766). If something already listens on the port, it only tells you.
rem   Environment (all optional; serve-hidden.vbs sets them):
rem     TASKBOARD_PORT     port to check and serve (default 8765)
rem     TASKBOARD_UV       absolute path of uv.exe (default: "uv" found on PATH)
rem     TASKBOARD_LOG      append uvicorn output and these messages to this file
rem     TASKBOARD_NOPAUSE  set to anything to skip the final "pause"
rem   Exit code: 0 stopped by stop.cmd or already running / 2 uv missing / else uv's exit code
setlocal
cd /d "%~dp0.."
set "RC=0"
set "PORT=%TASKBOARD_PORT%"
if not defined PORT set "PORT=8765"
if /i "%~1"=="--port" if not "%~2"=="" set "PORT=%~2"
set "UV=uv"
if defined TASKBOARD_UV set "UV=%TASKBOARD_UV%"
rem stop.cmd drops this flag before killing the server so an intentional stop exits 0
rem (a scheduled task with "restart on failure" would otherwise bring the server back)
set "STOPFLAG=%TEMP%\ai-taskboard-stop-%PORT%.flag"
if defined TASKBOARD_LOG for %%d in ("%TASKBOARD_LOG%") do if not exist "%%~dpd" mkdir "%%~dpd"

if defined TASKBOARD_UV (
  if not exist "%TASKBOARD_UV%" (
    call :say [ai-taskboard] uv not found: %TASKBOARD_UV%
    set "RC=2"
    goto :end
  )
) else (
  where uv >nul 2>nul
  if errorlevel 1 (
    call :say [ai-taskboard] uv is not on PATH. Install: https://docs.astral.sh/uv/getting-started/installation/
    set "RC=2"
    goto :end
  )
)

for /f "tokens=5" %%p in ('netstat -ano -p tcp ^| findstr /r /c:":%PORT% .*LISTENING"') do (
  call :say [ai-taskboard] already running on port %PORT% - PID %%p - http://127.0.0.1:%PORT%/  stop: scripts\stop.cmd
  goto :end
)

if exist "%STOPFLAG%" del "%STOPFLAG%" >nul 2>nul
call :say [ai-taskboard] %DATE% %TIME% starting http://127.0.0.1:%PORT%/  - Ctrl+C or close the window to stop
if defined TASKBOARD_LOG (
  "%UV%" run taskboard serve %* >> "%TASKBOARD_LOG%" 2>&1
) else (
  "%UV%" run taskboard serve %*
)
set "RC=%ERRORLEVEL%"
if exist "%STOPFLAG%" (
  del "%STOPFLAG%" >nul 2>nul
  set "RC=0"
)
call :say [ai-taskboard] %DATE% %TIME% server exited with code %RC%

:end
if not defined TASKBOARD_NOPAUSE pause
exit /b %RC%

:say
echo %*
if defined TASKBOARD_LOG >>"%TASKBOARD_LOG%" echo %*
goto :eof
