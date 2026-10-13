@echo off
title Python Weather Forecasting Project

echo Starting Python Weather Forecasting Project...

:: Start the API in a new terminal window
echo Starting the FastAPI backend...
start "Weather API" cmd /k "cd /d "%~dp0api" && if exist .venv\Scripts\activate.bat (call .venv\Scripts\activate.bat) && uvicorn app.main:app --reload"

:: Start the Next.js Web app in a new terminal window
echo Starting the Next.js frontend...
start "Weather Web" cmd /k "cd /d "%~dp0web" && npm run dev"

echo.
echo Both services have been started in separate windows!
echo Close this window to exit this launcher (the services will keep running).
pause
