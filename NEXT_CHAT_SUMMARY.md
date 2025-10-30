# 🚀 Quick Context for Next Chat Session

## Project: AI Animation Pipeline
**Flask-based web app for AI media generation, animation creation, and video processing**

---

## 📁 Essential Files to Attach

**For full context, attach these files:**
1. `project_context.prp` - Complete project overview
2. `ReadMe.md` - User documentation
3. `OCTOBER_30_HANDOFF.md` - Latest session details
4. `app.py` - Flask backend
5. `worker.py` - Background processor
6. `templates/index_v2.html` - Frontend UI

**Or just paste this file + specific files related to your issue.**

---

## 🎯 Current State (October 30, 2025)

### Latest Features (All Working ✅):
- **GIF Export**: Export keyed videos as animated GIFs with palette optimization
- **PNG ZIP Export**: Export frame sequences for external compositing
- **Video Trimming Tool**: Edit animations with in/out points and frame navigation
- **Pingpong Loops**: Forward-then-backward seamless loops with high-quality encoding
- **Direct Downloads**: Files download directly (no new tabs)
- **Alpha Transparency**: WebM videos properly preserve transparency externally

### Core Features:
- Multi-model image generation (Leonardo, OpenAI, Seedream)
- Animation creation (Kling v2.1, Seedance-1-Pro)
- Boomerang automation (A→B→A loops)
- Advanced chroma keying (auto-key + manual)
- Sticker effects (displacement, bevel, shadows, posterize)
- Video stitching
- S3/local storage

---

## 🏗️ Architecture

```
Flask App (app.py, port 5001)
    ↕
SQLite DB (jobs.db)
    ↕
Background Worker (worker.py)
    ↕
External APIs (Leonardo, Replicate, OpenAI)
```

**Two-process system**: Flask handles UI/API, Worker processes jobs

---

## 🔧 Tech Stack

- **Backend**: Flask, SQLite, OpenCV, FFmpeg, PIL/Pillow
- **Frontend**: Vanilla JS, HTML/CSS, Jinja2 templates
- **APIs**: Leonardo AI, Replicate (Kling, Seedance), OpenAI, BRIA
- **Video**: FFmpeg for encoding/processing
- **Storage**: Local files OR AWS S3 (optional)
- **Python**: 3.11 (macOS)

---

## 🎨 Recent Session Focus (October 30, 2025)

### Problems Solved:
1. **Export Formats**: Added GIF and PNG ZIP export options
2. **Video Trimming**: Built complete trim tool with UI
3. **Pingpong Loops**: Fixed FFmpeg filter_complex for proper looping
4. **Download Behavior**: Fixed downloads opening in new tabs
5. **Alpha Transparency**: Fixed WebM encoding losing transparency
6. **App Freezing**: Cleaned up database (263 jobs → 30 jobs limit)

### Key Code Changes:
- **`worker.py`**: Added GIF/ZIP export in `handle_keying()`, fixed alpha in WebM encoding
- **`video_processor.py`**: Updated FFmpeg command with `-vf 'format=yuva420p'` and `-start_number 0`
- **`app.py`**: Added `/api/trim-video` endpoint with pingpong support
- **`index_v2.html`**: Added trim tool UI, export checkboxes, download modal

---

## 📝 Critical Code Snippets

### Alpha Preservation (Fixed):
```python
ffmpeg_cmd = [
    'ffmpeg', '-y',
    '-framerate', str(fps),
    '-f', 'image2',
    '-start_number', '0',  # CRITICAL: Start from frame 0
    '-i', os.path.join(frames_dir, 'frame_%05d.png'),
    '-vf', 'format=yuva420p',  # CRITICAL: Force alpha format
    '-c:v', 'libvpx-vp9',
    '-pix_fmt', 'yuva420p',
    '-auto-alt-ref', '0',
    '-metadata:s:v:0', 'alpha_mode=1',  # Signal alpha channel
    '-b:v', '0',
    '-crf', '15',
    output_path
]
```

### Pingpong Loop (Fixed):
```python
# Use trim filter INSIDE filter_complex (not -t flag)
'-filter_complex',
f'[0:v]trim=duration={duration},setpts=PTS-STARTPTS,split[main][copy]; '
f'[copy]reverse[rev]; [main][rev]concat=n=2:v=1:a=0[out]',
```

---

## 🐛 Known Issues & Solutions

| Issue | Solution |
|-------|----------|
| Worker not picking up changes | Restart: `pkill -f "python.*worker.py"` then `python worker.py` |
| App frozen/slow | Clean database: Keep only recent 30 jobs |
| Transparency lost | Use FFmpeg flags: `-vf 'format=yuva420p'` + `-start_number 0` |
| Downloads open new tab | Use `forceDownload()` with HTML5 download attribute |

---

## 🚀 How to Run

```bash
# Terminal 1: Flask
cd /Users/amnonk/Documents/kling_app
source venv/bin/activate
flask run --host=0.0.0.0 --port=5001

# Terminal 2: Worker
cd /Users/amnonk/Documents/kling_app
source venv/bin/activate
python worker.py
```

**Access**: http://127.0.0.1:5001

---

## 📋 Database Schema (Key Columns)

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT,  -- image_generation, animation, boomerang_automation, etc.
    status TEXT,    -- queued, processing, completed, failed, pending_process
    prompt TEXT,
    input_data TEXT,  -- JSON metadata
    result_data TEXT,  -- URL or file path
    keyed_result_data TEXT,  -- JSON with webm, gif, png_zip URLs
    parent_job_id INTEGER,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

## 🎯 Typical User Workflow

1. Generate image (Leonardo/OpenAI/Seedream)
2. Create animation from image (Kling/Seedance)
3. Auto-key or manually key (chroma keying)
4. Apply sticker effects (optional)
5. Trim video (optional) with pingpong loop (optional)
6. Download (WebM/GIF/PNG ZIP)

---

## 💡 Quick Debugging Tips

**Check worker is running:**
```bash
ps aux | grep python | grep worker
```

**Check Flask port:**
```bash
lsof -i :5001
```

**View logs:**
```bash
tail -f worker.log
tail -f flask.log
```

**Restart everything:**
```bash
pkill -f "flask run"
pkill -f "python.*worker.py"
source venv/bin/activate
flask run --host=0.0.0.0 --port=5001 &
python worker.py &
```

---

## 🎨 Paste This Into New Chat

```
I'm continuing work on the AI Animation Pipeline app.

Project: Flask-based web app for AI media generation + video processing
Architecture: Flask (port 5001) + Background Worker + SQLite
Latest work: GIF/ZIP export, video trimming tool, pingpong loops, alpha transparency fixes

All features currently working. Ready for next task.

[Then describe your specific issue or new feature request]
```

---

**For detailed technical info, see:**
- `project_context.prp` - Full project overview
- `OCTOBER_30_HANDOFF.md` - Latest session details
- `ReadMe.md` - User documentation

