@echo off
cd /d "%~dp0"

echo Starting Infinity Outreach Agent...

set PYTHONPATH=%~dp0src

REM open browser after 2-second delay (server needs a moment to boot)
start "" /b cmd /c "timeout /t 2 >nul && start http://127.0.0.1:8000"

REM launch the web panel (this window stays open — close it to stop the server)
.venv\Scripts\python.exe -m infinity_outreach.cli web

pause
