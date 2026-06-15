@echo off
cd /d "%~dp0"

echo Starting Infinity Outreach Agent...

set PYTHONPATH=%~dp0src

REM open browser after 2-second delay (server needs a moment to boot)
start "" /b cmd /c "timeout /t 2 >nul && start http://127.0.0.1:8080"

REM launch the web panel (this window stays open — close it to stop the server)
REM Port 8080 used because 8000 is occupied by Splunk on the host machine.
REM Change --port to 8000 if running on a clean sandbox without Splunk.
.venv\Scripts\python.exe -m infinity_outreach.cli web --port 8080

pause
