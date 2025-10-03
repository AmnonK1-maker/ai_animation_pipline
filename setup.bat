@echo off
REM AI Media Workflow Dashboard - Windows Setup Script
REM This script sets up the entire application environment automatically

echo ========================================
echo AI Media Workflow Dashboard - Setup
echo ========================================
echo.

REM Check Python version
echo [INFO] Checking Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.8+ from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

python --version
echo [SUCCESS] Python found
echo.

REM Check ffmpeg
echo [INFO] Checking ffmpeg installation...
ffmpeg -version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] ffmpeg not found. Video processing features will not work.
    echo.
    echo To install ffmpeg on Windows:
    echo 1. Download from: https://ffmpeg.org/download.html
    echo 2. Or use Chocolatey: choco install ffmpeg
    echo 3. Or use Scoop: scoop install ffmpeg
    echo.
    set /p CONTINUE="Continue without ffmpeg? (y/n): "
    if /i not "%CONTINUE%"=="y" exit /b 1
) else (
    echo [SUCCESS] ffmpeg found
)
echo.

REM Create virtual environment
echo [INFO] Setting up Python virtual environment...
if not exist "venv" (
    python -m venv venv
    echo [SUCCESS] Virtual environment created
) else (
    echo [WARNING] Virtual environment already exists, skipping creation
)
echo.

REM Activate virtual environment and install dependencies
echo [INFO] Installing Python dependencies (this may take a few minutes)...
call venv\Scripts\activate.bat

REM Upgrade pip
python -m pip install --upgrade pip >nul 2>&1

REM Install requirements
if exist "requirements.txt" (
    pip install -r requirements.txt
    echo [SUCCESS] All Python packages installed successfully
) else (
    echo [ERROR] requirements.txt not found!
    pause
    exit /b 1
)
echo.

REM Setup .env file
echo [INFO] Configuring environment variables...
if not exist ".env" (
    echo [WARNING] .env file not found. Creating template...
    (
        echo # API Keys - Please fill in your actual keys
        echo LEONARDO_API_KEY="your_leonardo_api_key_here"
        echo REPLICATE_API_KEY="your_replicate_api_key_here"
        echo OPENAI_API_KEY="your_openai_api_key_here"
        echo OPENAI_ORG_ID="your_openai_org_id_here"
    ) > .env
    echo [SUCCESS] .env template created
    echo.
    echo [WARNING] IMPORTANT: You need to edit .env with your actual API keys!
    echo.
    echo API Key Sources:
    echo   - Leonardo AI: https://app.leonardo.ai/settings
    echo   - Replicate: https://replicate.com/account/api-tokens
    echo   - OpenAI: https://platform.openai.com/api-keys
    echo.
    pause
) else (
    echo [SUCCESS] .env file already exists
)
echo.

REM Check database
echo [INFO] Checking database...
if not exist "jobs.db" (
    echo [INFO] Database not found. It will be created automatically on first run.
) else (
    echo [SUCCESS] Database exists
)
echo.

REM Create necessary directories
echo [INFO] Creating necessary directories...
if not exist "static\animations\generated" mkdir static\animations\generated
if not exist "static\animations\approved\_processed" mkdir static\animations\approved\_processed
if not exist "static\animations\rendered" mkdir static\animations\rendered
if not exist "static\library\transparent_videos" mkdir static\library\transparent_videos
if not exist "static\uploads" mkdir static\uploads
echo [SUCCESS] Directory structure created
echo.

REM Setup complete
echo ========================================
echo [SUCCESS] Setup Complete!
echo ========================================
echo.
echo Next Steps:
echo.
echo 1. Verify your API keys in .env file:
echo    notepad .env
echo.
echo 2. Start the application:
echo    start_app.bat
echo.
echo 3. Open your browser to:
echo    http://localhost:5001
echo.
echo For troubleshooting, see ReadMe.md
echo.
pause

