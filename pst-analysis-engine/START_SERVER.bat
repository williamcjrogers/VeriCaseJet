@echo off
echo Starting VeriCase API Server on port 8010...
echo.
cd /d "%~dp0"
set PYTHONPATH=%cd%;%cd%\src;%PYTHONPATH%
.venv\Scripts\python src\api_server.py
pause

