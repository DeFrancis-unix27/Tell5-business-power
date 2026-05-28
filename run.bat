@echo off
REM Setup and run Tell5 locally on Windows

setlocal enabledelayedexpansion

echo ==================================
echo Tell5 Setup ^& Run Script
echo ==================================

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo [OK] Found: %PYTHON_VERSION%

REM Create venv if not exists
if not exist "venv" (
    echo.
    echo Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created
)

REM Activate venv
echo.
echo Activating virtual environment...
call venv\Scripts\activate.bat
echo [OK] Virtual environment activated

REM Install requirements
echo.
echo Installing dependencies...
pip install -q -r requirements.txt
echo [OK] Dependencies installed

REM Check .env exists
echo.
if not exist ".env" (
    echo Creating .env from template...
    copy .env.example .env >nul
    echo.
    echo [WARNING] Edit .env with your Twilio credentials!
    echo.
    echo Steps:
    echo 1. Go to https://console.twilio.com
    echo 2. Find your Account SID and Auth Token
    echo 3. Edit .env file
    echo 4. Run this script again
    exit /b 0
) else (
    echo [OK] .env file exists
)

REM Check database
echo.
echo Database Configuration:
echo Check your DATABASE_URL in .env
echo Make sure PostgreSQL is running

REM Run app
echo.
echo ==================================
echo Starting Tell5...
echo ==================================
echo.
echo Dashboard: http://localhost:8000/dashboard
echo API Docs: http://localhost:8000/docs
echo Press Ctrl+C to stop
echo.

uvicorn main:app --reload --host 0.0.0.0 --port 8000

pause
