@echo off
echo =======================================
echo Starting VeriCase Analysis (Direct Mode)
echo =======================================

cd /d "C:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"

echo.
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Starting API server...
cd api
python -m uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload

pause
