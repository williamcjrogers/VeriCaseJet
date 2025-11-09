@echo off
echo ================================================
echo VeriCase Workflow Test
echo ================================================
echo.
echo This will test the complete workflow:
echo 1. Start API server
echo 2. Open the wizard page
echo 3. Create a project/case
echo 4. Upload a PST file
echo 5. View correspondence
echo.
echo Starting API server on port 8010...
echo.
echo Press any key to open the wizard in your browser...
pause > nul

start http://localhost:8010/ui/wizard.html

echo.
echo Follow these steps to test:
echo 1. Click "Set up a Project" or "Set up a Case"
echo 2. Fill out the form (all tabs)
echo 3. Submit to create your profile
echo 4. On dashboard, click "Upload Evidence"
echo 5. Upload a PST file
echo 6. Click "View Correspondence" to see emails
echo.
echo Keep this window open to see server logs...
echo.
cd /d "%~dp0"
set PYTHONPATH=%cd%;%cd%\src;%PYTHONPATH%
.venv\Scripts\python src\api_server.py
