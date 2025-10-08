@echo off
REM AI Media Workflow Dashboard - ONE-CLICK Startup Script (Windows)
REM This script starts BOTH Flask web server AND background worker automatically

title AI Media Workflow Dashboard

echo ==========================================
echo 🎬 Starting AI Media Workflow Dashboard
echo ==========================================
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo ❌ Virtual environment not found!
    echo Please run setup first: setup_auto.bat ^(or setup.bat^)
    pause
    exit /b 1
)

REM Check if .env file exists
if not exist ".env" (
    echo ❌ .env file not found!
    echo.
    echo Please create .env file with API keys.
    echo If you're a team member, ask your administrator for the .env file.
    echo.
    echo Required format:
    echo LEONARDO_API_KEY=your_key_here
    echo REPLICATE_API_KEY=your_token_here
    echo OPENAI_API_KEY=your_key_here
    echo OPENAI_ORG_ID=your_org_id_here
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
call venv\Scripts\activate.bat
echo ✅ Virtual environment activated

REM Kill any existing Flask processes on port 5001
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5001" ^| find "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

REM Kill any existing worker processes
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *worker.py*" >nul 2>&1

echo.
echo 🚀 Starting Flask web server on http://localhost:5001...

REM Start Flask in a new hidden window
start /B "" cmd /c "flask run --host=0.0.0.0 --port=5001 > nul 2>&1"

REM Wait for Flask to start
timeout /t 3 /nobreak >nul

REM Start background worker in a new hidden window
echo ⚙️  Starting background worker...
start /B "" cmd /c "python worker.py > worker_current.log 2>&1"

REM Wait for worker to start
timeout /t 2 /nobreak >nul

echo ✅ Flask web server started
echo ✅ Background worker started
echo.
echo ==========================================
echo ✅ AI Media Workflow Dashboard is running!
echo ==========================================
echo.
echo 🌐 Open your browser to: http://localhost:5001
echo.
echo 📊 Both processes are running in the background
echo 📝 Worker logs: worker_current.log
echo.
echo ⚠️  To stop the application, close this window
echo     or run: stop_app.bat
echo ==========================================
echo.

REM Open browser automatically
start http://localhost:5001

REM Keep window open
echo Press any key to stop all processes and exit...
pause >nul

REM Cleanup on exit
echo.
echo 🛑 Shutting down...

REM Kill Flask
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5001" ^| find "LISTENING"') do (
    echo    Stopping Flask server...
    taskkill /F /PID %%a >nul 2>&1
)

REM Kill worker
echo    Stopping background worker...
taskkill /F /FI "WINDOWTITLE eq *worker.py*" >nul 2>&1

echo ✅ Shutdown complete
timeout /t 2 /nobreak >nul