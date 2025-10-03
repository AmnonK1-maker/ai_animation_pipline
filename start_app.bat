@echo off
REM AI Media Workflow Dashboard - Windows Startup Script
REM This script starts both the Flask web server and the background worker

echo ========================================
echo AI Media Workflow Dashboard - Starting
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run setup.bat first
    pause
    exit /b 1
)

REM Check if .env exists
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Please create .env with your API keys
    echo You can copy .env.example or run setup.bat
    pause
    exit /b 1
)

REM Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

REM Check if port 5001 is in use
echo [INFO] Checking if port 5001 is available...
netstat -ano | findstr :5001 >nul
if %ERRORLEVEL% EQU 0 (
    echo [WARNING] Port 5001 is already in use!
    echo.
    set /p KILL="Do you want to kill the process and restart? (y/n): "
    if /i "%KILL%"=="y" (
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5001') do (
            taskkill /F /PID %%a >nul 2>&1
        )
        echo [INFO] Killed existing process on port 5001
        timeout /t 2 /nobreak >nul
    ) else (
        echo [INFO] Exiting. Please stop the existing process manually.
        pause
        exit /b 1
    )
)

REM Start Flask in a new window
echo [INFO] Starting Flask web server on http://localhost:5001
start "Flask Web Server" cmd /k "venv\Scripts\activate.bat && flask run --host=0.0.0.0 --port=5001"

REM Wait a moment for Flask to start
timeout /t 3 /nobreak >nul

REM Start Worker in a new window
echo [INFO] Starting background worker...
start "Background Worker" cmd /k "venv\Scripts\activate.bat && python worker.py"

echo.
echo ========================================
echo [SUCCESS] Application Started!
echo ========================================
echo.
echo Flask Web Server: Running in separate window
echo Background Worker: Running in separate window
echo.
echo Access the dashboard at:
echo   http://localhost:5001
echo.
echo To stop the application:
echo   - Close both terminal windows
echo   - Or press Ctrl+C in each window
echo.
echo Logs are visible in the separate windows
echo.
pause

