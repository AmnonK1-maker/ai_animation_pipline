# 🚀 Quick Setup Guide for Team Members

This guide will help you get the AI Media Workflow Dashboard running on your machine in minutes.

## 📋 Prerequisites

Before starting, make sure you have:

1. **Git** - [Download here](https://git-scm.com/downloads)
2. **Python 3.8+** - [Download here](https://www.python.org/downloads/)
3. **ffmpeg** (for video processing):
   - **macOS**: `brew install ffmpeg`
   - **Ubuntu/Debian**: `sudo apt-get install ffmpeg`
   - **Windows**: [Download from ffmpeg.org](https://ffmpeg.org/download.html)

4. **API Keys** (you'll need at least one):
   - [Leonardo AI](https://app.leonardo.ai/settings) - For image generation
   - [Replicate](https://replicate.com/account/api-tokens) - For animations
   - [OpenAI](https://platform.openai.com/api-keys) - For style analysis and DALL-E

---

## 🎯 One-Click Setup (Recommended)

### Step 1: Clone the Repository

```bash
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline
```

### Step 2: Run Setup Script

```bash
./setup.sh
```

This script will:
- ✅ Check Python and ffmpeg installation
- ✅ Create virtual environment
- ✅ Install all dependencies
- ✅ Create `.env` template file
- ✅ Set up directory structure
- ✅ Make startup script executable

### Step 3: Add Your API Keys

Edit the `.env` file with your actual API keys:

```bash
nano .env
# or
open .env
```

Replace the placeholder values:
```env
LEONARDO_API_KEY="your_actual_leonardo_key"
REPLICATE_API_KEY="your_actual_replicate_key"
OPENAI_API_KEY="your_actual_openai_key"
OPENAI_ORG_ID="your_actual_openai_org_id"
```

### Step 4: Start the Application

```bash
./start_app.sh
```

### Step 5: Open Browser

Navigate to: **http://localhost:5001**

---

## 🔧 Manual Setup (Alternative)

If you prefer to set up manually or the script doesn't work:

### 1. Clone Repository
```bash
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline
```

### 2. Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Create .env File
```bash
cp .env.example .env  # If example exists
# or create manually with the keys above
```

### 5. Run Application
```bash
# Terminal 1 - Web Server
flask run --host=0.0.0.0 --port=5001

# Terminal 2 - Background Worker (in a new terminal)
source venv/bin/activate
python3 worker.py
```

---

## 🎮 Using the Application

### First Time Usage

1. **Generate an Image**: 
   - Go to "Image Generation" section
   - Select a model (Leonardo, DALL-E)
   - Enter a prompt
   - Click "Generate"

2. **Analyze an Image**:
   - Upload an image in "Style Analyzer" or "Palette Analyzer"
   - View the AI analysis in the job queue
   - Click "Use This" to apply the style to image generation

3. **Create Animation**:
   - Select a generated image
   - Choose an animation model
   - Add a prompt describing the motion
   - Click "Create Animation"

4. **Process Videos**:
   - Extract frames from videos
   - Apply chroma keying (green screen removal)
   - Stitch multiple videos into loops

### Key Features

- 🎨 **Multi-Model Image Generation** (Leonardo, DALL-E)
- 🎭 **Animation Creation** (Kling, Seedance, Pixverse)
- 🎞️ **Advanced Video Processing** (Stitching, Chroma Keying)
- 🔄 **Boomerang Automation** (A→B→A loops)
- 📊 **Job Queue Management** (Real-time status updates)
- 🎯 **Style & Palette Analysis** (AI-powered with GPT-4o Vision)

---

## 🔄 Keeping Your Installation Updated

### Pull Latest Changes
```bash
git pull origin main
```

### Update Dependencies (if requirements.txt changed)
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Restart Application
```bash
./start_app.sh
```

---

## 🐛 Troubleshooting

### Application Won't Start

**Port 5001 already in use:**
```bash
# Find and kill the process
lsof -ti:5001 | xargs kill -9
```

**Worker not processing jobs:**
```bash
# Check if worker is running
ps aux | grep python | grep worker

# Start worker manually
source venv/bin/activate
python3 worker.py &
```

### Dependencies Issues

**Reinstall dependencies:**
```bash
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt --force-reinstall
```

### Template Not Updating

- Hard refresh browser: **Cmd+Shift+R** (Mac) or **Ctrl+Shift+R** (Windows/Linux)
- Clear browser cache
- Restart Flask server

### Video Processing Fails

**Check ffmpeg:**
```bash
ffmpeg -version
```

If not installed, install it:
- **macOS**: `brew install ffmpeg`
- **Ubuntu**: `sudo apt-get install ffmpeg`
- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

### Database Issues

**Reset database (WARNING: Deletes all jobs):**
```bash
python3 reset_database.py
```

---

## 📁 Project Structure

```
ai_animation_pipline/
├── setup.sh              # One-click setup script
├── start_app.sh          # One-click startup script
├── app.py                # Flask web server
├── worker.py             # Background job processor
├── video_processor.py    # Video processing utilities
├── requirements.txt      # Python dependencies
├── .env                  # API keys (create this)
├── jobs.db              # SQLite database (auto-created)
├── templates/           # HTML templates
│   ├── index.html       # Main dashboard
│   ├── animation_step.html
│   └── fine_tune.html   # Chroma keying interface
└── static/              # Generated assets
    ├── animations/      # Generated videos
    ├── library/         # Images and processed content
    └── uploads/         # User uploads
```

---

## 🔐 Security Notes for Team Sharing

### Option 1: Private Repository (Recommended)
- Keep API keys in `.env` (already in `.gitignore`)
- Share repository access via GitHub/GitLab
- Each team member adds their own API keys

### Option 2: Shared Development Keys
- Create dedicated development API keys
- Share keys securely (1Password, LastPass, encrypted file)
- Never commit `.env` to git

### Option 3: Team API Key Management
- Use environment variable management service (e.g., Doppler, Vault)
- Configure each team member's environment separately

---

## 💡 Tips for Team Collaboration

### Workflow Best Practices

1. **Pull before starting work**: `git pull origin main`
2. **Create feature branches**: `git checkout -b feature/your-feature`
3. **Test locally before pushing**
4. **Document changes in commit messages**
5. **Update ReadMe.md if you add features**

### Shared Resources

- Generated images/videos are in `static/` (consider adding to `.gitignore` for large files)
- Database `jobs.db` is local to each installation
- Each team member can work independently without conflicts

---

## 📞 Getting Help

1. Check the main [ReadMe.md](ReadMe.md) for detailed feature documentation
2. Review [project_context.prp](project_context.prp) for technical architecture
3. Check logs:
   - Flask: Terminal output or `flask.log`
   - Worker: Terminal output or `worker.log`
4. Browser console: Press F12 and check for JavaScript errors

---

## ✅ Checklist for New Team Members

- [ ] Python 3.8+ installed
- [ ] ffmpeg installed
- [ ] Repository cloned
- [ ] Setup script run successfully (`./setup.sh`)
- [ ] API keys added to `.env`
- [ ] Application started (`./start_app.sh`)
- [ ] Browser opened to http://localhost:5001
- [ ] First image generated successfully
- [ ] Worker processing jobs correctly

---

**Welcome to the team! 🎉**

If you encounter any issues not covered here, please reach out to the team or create an issue in the repository.

