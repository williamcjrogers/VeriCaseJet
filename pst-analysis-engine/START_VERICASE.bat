@echo off
echo =======================================
echo Starting VeriCase Analysis System
echo =======================================

cd /d "C:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"

echo.
echo Starting Docker services...
docker-compose up -d

echo.
echo Waiting for services to start...
timeout /t 5 /nobreak > nul

echo.
echo Checking service status...
docker ps

echo.
echo =======================================
echo VeriCase should be available at:
echo   http://localhost:8010
echo.
echo To stop services, run:
echo   docker-compose down
echo =======================================

echo.
echo Opening browser...
start http://localhost:8010

pause
