@echo off
REM 🎬 AI Media Workflow Dashboard - AUTOMATIC One-Click Setup Script (Windows)
REM This script automatically installs ALL dependencies including Python and ffmpeg

echo ========================================================
echo 🎬 AI Media Workflow Dashboard - AUTOMATIC Setup
echo ========================================================
echo This script will check and guide you to install:
echo   - Python 3.8+ (if needed)
echo   - ffmpeg (if needed)
echo   - All Python dependencies
echo ========================================================
echo.

REM ============================================
REM STEP 1: Check for Python
REM ============================================

echo [INFO] Checking Python installation...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo.
    echo Please install Python 3.8 or higher:
    echo   1. Download from: https://www.python.org/downloads/
    echo   2. During installation, CHECK "Add Python to PATH"
    echo   3. Run this script again after installation
    echo.
    pause
    exit /b 1
)

REM Check Python version
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [SUCCESS] Python %PYTHON_VERSION% found

REM Extract major and minor version
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set PYTHON_MAJOR=%%a
    set PYTHON_MINOR=%%b
)

if %PYTHON_MAJOR% lss 3 (
    echo [ERROR] Python 3.8+ is required. You have %PYTHON_VERSION%
    pause
    exit /b 1
)

if %PYTHON_MAJOR% equ 3 if %PYTHON_MINOR% lss 8 (
    echo [ERROR] Python 3.8+ is required. You have %PYTHON_VERSION%
    pause
    exit /b 1
)

REM ============================================
REM STEP 2: Check for ffmpeg
REM ============================================

echo [INFO] Checking ffmpeg installation...

ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] ffmpeg not found. Video features will not work.
    echo.
    echo To install ffmpeg on Windows:
    echo   1. Download from: https://www.gyan.dev/ffmpeg/builds/
    echo   2. Extract to C:\ffmpeg
    echo   3. Add C:\ffmpeg\bin to your System PATH
    echo   4. Or use Chocolatey: choco install ffmpeg
    echo   5. Or use winget: winget install ffmpeg
    echo.
    set /p CONTINUE="Continue without ffmpeg? (Y/N): "
    if /i not "%CONTINUE%"=="Y" exit /b 1
) else (
    for /f "tokens=*" %%i in ('ffmpeg -version 2^>^&1 ^| findstr /C:"ffmpeg version"') do set FFMPEG_VERSION=%%i
    echo [SUCCESS] ffmpeg found
)

REM ============================================
REM STEP 3: Create Virtual Environment
REM ============================================

echo [INFO] Setting up Python virtual environment...

if not exist "venv" (
    python -m venv venv
    echo [SUCCESS] Virtual environment created
) else (
    echo [WARNING] Virtual environment already exists, skipping creation
)

REM ============================================
REM STEP 4: Install Python Dependencies
REM ============================================

echo [INFO] Installing Python dependencies (this may take a few minutes)...

call venv\Scripts\activate.bat

REM Upgrade pip
python -m pip install --upgrade pip --quiet

REM Install requirements
if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found!
    pause
    exit /b 1
)

pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install Python dependencies!
    pause
    exit /b 1
)
echo [SUCCESS] All Python packages installed successfully

REM ============================================
REM STEP 5: Setup Environment File
REM ============================================

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
    echo ⚠️  IMPORTANT: You need to edit .env with your actual API keys!
    echo.
    echo API Key Sources:
    echo   - Leonardo AI: https://app.leonardo.ai/settings
    echo   - Replicate: https://replicate.com/account/api-tokens
    echo   - OpenAI: https://platform.openai.com/api-keys
    echo.
) else (
    echo [SUCCESS] .env file already exists
    findstr /C:"your_.*_api_key_here" .env >nul 2>&1
    if not errorlevel 1 (
        echo [WARNING] ⚠️  Your .env file contains placeholder values. Please update with real API keys!
    )
)

REM ============================================
REM STEP 6: Create Directory Structure
REM ============================================

echo [INFO] Creating necessary directories...

if not exist "static\animations\generated" mkdir "static\animations\generated"
if not exist "static\animations\approved\_processed" mkdir "static\animations\approved\_processed"
if not exist "static\animations\rendered" mkdir "static\animations\rendered"
if not exist "static\library\transparent_videos" mkdir "static\library\transparent_videos"
if not exist "static\uploads" mkdir "static\uploads"

echo [SUCCESS] Directory structure created

REM ============================================
REM SETUP COMPLETE!
REM ============================================

call venv\Scripts\deactivate.bat 2>nul

echo.
echo ==============================================
echo [SUCCESS] 🎉 AUTOMATIC SETUP COMPLETE!
echo ==============================================
echo.
echo ✅ Installed:
echo    - Python %PYTHON_VERSION% with pip
echo    - All Python dependencies
echo    - Virtual environment configured
echo.
if %errorlevel% equ 0 (
    echo ✅ ffmpeg is ready
) else (
    echo ⚠️  ffmpeg not found - install it for video features
)
echo.
echo Next Steps:
echo.
echo 1. Configure your API keys:
echo    notepad .env
echo.
echo 2. Start the application:
echo    start_app.bat
echo.
echo 3. Open your browser to:
echo    http://localhost:5001
echo.
echo For help, see ReadMe.md or SETUP.md
echo.

pause

