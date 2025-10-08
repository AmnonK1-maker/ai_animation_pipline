# 📦 Distribution Guide for Administrators

This guide explains how to distribute the AI Media Workflow Dashboard to team members.

---

## ⚠️ Important: Virtual Environments Are NOT Portable

**You CANNOT simply ZIP the folder and send it!**

Virtual environments (`venv` folder) contain hard-coded paths specific to YOUR machine. They will NOT work on other machines.

---

## ✅ Recommended Approach: Guided Setup

### For Administrator (You):

#### Step 1: Prepare the .env File
1. Create a master `.env` file with all your API keys
2. Keep this file secure (it contains sensitive information)

```bash
# Example .env
LEONARDO_API_KEY=actual_key_here
REPLICATE_API_KEY=actual_key_here
OPENAI_API_KEY=actual_key_here
OPENAI_ORG_ID=actual_org_here
```

#### Step 2: Share Repository Access
Send team members:
- **GitHub repository link**: https://github.com/AmnonK1-maker/ai_animation_pipline
- **The `.env` file** (via secure method - email, Slack, encrypted file)
- **The `TEAM_SETUP.md` guide**

---

### For Team Members:

**Mac Users:**
```bash
# 1. Clone repository
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline

# 2. Copy .env file that administrator sent into this folder

# 3. Run automatic setup (installs Python, ffmpeg, everything)
./setup_auto.sh

# 4. Start application
./start_app.sh
```

**Windows Users:**
```cmd
REM 1. Clone repository  
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline

REM 2. Copy .env file that administrator sent into this folder

REM 3. Run automatic setup (guides Python/ffmpeg install)
setup_auto.bat

REM 4. Start application
start_app.bat
```

---

## 🪟 Windows ffmpeg Installation

Windows users have 3 options for ffmpeg:

### Option 1: Chocolatey (Recommended if they have it)
```cmd
choco install ffmpeg
```

### Option 2: Winget (Windows 10+)
```cmd
winget install ffmpeg
```

### Option 3: Manual Install
1. Download from: https://www.gyan.dev/ffmpeg/builds/
2. Extract to `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to System PATH:
   - Search "Environment Variables" in Start Menu
   - Edit "Path" under System Variables
   - Add new entry: `C:\ffmpeg\bin`
   - Click OK
   - Restart Command Prompt

The `setup_auto.bat` script will detect if ffmpeg is missing and provide these instructions.

---

## 🔄 Updating Team Members

When you update the code:

```bash
# Team members run:
git pull origin main    # Get latest code
./start_app.sh         # Restart (no need to re-run setup)
```

If you update dependencies in `requirements.txt`:

```bash
source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt
./start_app.sh
```

---

## 🚀 Future: Standalone Executable (Optional)

For a true "one-click" experience (no Python or ffmpeg needed), you can create standalone executables using PyInstaller:

**Mac:**
```bash
pip install pyinstaller
pyinstaller --onefile --add-data "templates:templates" --add-data "static:static" app.py
```

**Windows:**
```cmd
pip install pyinstaller
pyinstaller --onefile --add-data "templates;templates" --add-data "static;static" app.py
```

**Note:** This is advanced and requires:
- Bundling Python runtime
- Bundling ffmpeg binary
- Handling file paths correctly
- ~200-300 MB executable size

Not recommended unless you have 10+ non-technical users.

---

## 📝 Summary: What Actually Works

| Method | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **Send GitHub + .env** | ✅ Easy for you<br>✅ Always up-to-date | ❌ Team runs setup | ⭐ **Best for small teams** |
| **Send ZIP package** | ✅ No git needed | ❌ Still need Python/ffmpeg<br>❌ Gets outdated | ⚠️ Not recommended |
| **Standalone .exe/.app** | ✅ True one-click | ❌ Large files<br>❌ Complex to build | 💡 For 10+ users |
| **Docker container** | ✅ Fully contained | ❌ Very technical | 🔬 For DevOps teams |

---

## 🎯 Recommended Workflow

1. **You (Admin)**: 
   - Keep the GitHub repo updated
   - Share the `.env` file securely
   - Send team members the `TEAM_SETUP.md` guide

2. **Team Members**:
   - Clone the repo ONCE
   - Run `setup_auto.sh` or `setup_auto.bat` ONCE
   - After that, just use `start_app.sh` / `start_app.bat` daily

3. **Updates**:
   - Team runs `git pull` to get new features
   - Restart the app

This is the most maintainable approach for a small-to-medium team!
