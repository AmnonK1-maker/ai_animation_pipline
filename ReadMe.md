# 🎬 AI Media Workflow Dashboard

A comprehensive Flask-based application for AI-powered image generation, animation creation, and video processing with advanced chroma keying capabilities. **Now featuring a completely redesigned modern UI with streamlined workflows!**

## ✨ Key Features

### 🎨 **Multi-Model Image Generation**
- **Leonardo AI**: Multiple models with style preset dropdown (Diffusion XL, Vision XL, etc.)
- **OpenAI**: DALL-E integration with automatic transparent background
- **ByteDance Seedream**: Advanced AI image generation
- **Intelligent Style Analysis**: Art Style Forensics analyzer with optimized prompts (under 900 characters)
- **Smart Prompting**: AI suggestions for animation ideas based on uploaded images
- **Reference Image Display**: Style and palette images show directly in upload boxes with dynamic sizing

### 🎭 **Advanced Animation Workflow** 
- **Multiple Models**: Kling v2.1, Seedance-1-Pro
- **Loop Creator Tool**: Dedicated interface for creating perfect A→B→A boomerang loops with extracted frame preview
- **Frame Extraction**: Video scrubbing with precise frame-by-frame control, frames A & B display in tool
- **Automatic ABA Generation**: Creates two animations and stitches them seamlessly
- **Manual Stitching**: Select any two animations to stitch together
- **Background Management**: Smart background detection (green/blue screen, as-is, or uploaded)
- **Image Preview**: Selected start frame displays in animation tool before generation

### 🎞️ **Professional Video Processing**
- **Auto-Key Feature**: One-click automatic chroma keying for all videos (animations, stitched, uploaded)
- **Manual Keyer Tool**: Advanced HSV controls with real-time preview and click-to-sample color picker
- **Advanced Sticker Effects**: Complete post-processing pipeline for keyed videos
  - **Displacement Mapping**: Animated texture warping with intensity control
  - **Blend Mode Textures**: Multiply (darken) and Add (brighten) with opacity control
  - **Surface Bevel & Emboss**: 3D relief effects using Sobel gradients
  - **Alpha Bevel**: Edge lighting effects with customizable depth, blur, angle, and intensity
  - **Drop Shadow**: Dimensional shadows with blur, offset, and opacity controls
  - **Clipping Mask Technology**: Textures only apply to non-transparent areas
- **Posterize Time**: Stop-motion effect (12fps or 8fps) while maintaining playback speed
- **Zoom & Pan Controls**: Zoom in/out (0.5x-4x), reset zoom, constrained panning within frame boundaries
- **Grid Overlay**: Customizable grid size and color for precise alignment
- **Color Sampler**: Click anywhere on video to automatically set HSV keying values
- **Fixed Scale Conversion**: Proper OpenCV (0-180) to standard HSV (0-360) conversion
- **Visual Color Preview**: Live preview of target keying color with HSV values
- **Re-Key Functionality**: Process original videos with new settings anytime
- **Priority Processing**: Keying jobs automatically jump to top of queue
- **Transparent Display**: Checkerboard background for keyed videos in thumbnails and modal viewer
- **Download Options**: Separate buttons for original and keyed versions
- **Background Removal**: 851-labs AI-powered transparent image generation

### 🎯 **Modern UI & Workflow**
- **Tool Switching System**: Clean top toolbar for accessing different tools
- **Inline Job Actions**: Edit, Regenerate, Animate, Key, Stitch - all visible in job cards
- **Smart Polling System**: Adaptive refresh rates (2s/5s/10s) based on activity
- **Floating Delete Bar**: Batch operations with "Select All", "Invert Selection", and "Delete All"
- **Full-Screen Media Viewer**: Navigate through images and videos with arrow keys, transparency grid for keyed content
- **Background Jobs**: Style/color analysis runs invisibly, results auto-merge into prompts
- **Instant Multi-Image Creation**: Multiple image jobs appear immediately in queue
- **One-Click Regeneration**: Regenerate with new seed or edit parameters
- **Processing Animation**: Visual spinner overlay on thumbnails for jobs in progress
- **Reference Image Previews**: Style and palette images display with dynamic aspect ratio in upload boxes

### 📚 **Enhanced Job Management**
- **Compact Job Cards**: All information visible at a glance
- **Action Buttons**: Context-aware buttons based on job type and status
- **Job Selection**: Click to select, batch delete, stitch, or invert selection
- **Status Indicators**: Visual feedback for queued, processing, completed, and failed jobs
- **Failed Job Recovery**: Retry button to requeue failed jobs, delete option, inline error messages
- **Thumbnail Previews**: Auto-playing video thumbnails with hover controls and cache-busting
- **Priority Queue**: Keying jobs automatically jump to top of queue for immediate processing
- **Edit Job Loading**: Reference images automatically load when editing previous jobs

## 🏗️ Technical Architecture

### Two-Process Design
- **Flask Web Server** (`app.py`): Handles UI, API endpoints, job creation
- **Background Worker** (`worker.py`): Processes AI jobs, handles external APIs
- **SQLite Database** (`jobs.db`): Job queue and status management

### Key Components
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Browser   │◄──►│   Flask App     │◄──►│   SQLite DB     │
│   (Frontend)    │    │   (app.py)      │    │   (jobs.db)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                ▲                        ▲
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │ Static Assets   │    │ Background      │
                       │ (Generated)     │    │ Worker          │
                       └─────────────────┘    │ (worker.py)     │
                                              └─────────────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │ External APIs   │
                                              │ (Leonardo, etc.)│
                                              └─────────────────┘
```

## 🚀 Setup Instructions

### 🎯 Choose Your Deployment Method

**Option A: Local Setup** (for small teams, 1-5 users)  
**Option B: Cloud Deployment** (for growing teams, remote access, 5+ users)

---

### 💻 **Option A: Local Setup** (Recommended for Getting Started)

**For New Team Members**: See [TEAM_SETUP.md](TEAM_SETUP.md) for detailed setup guide.

#### **Option 1: FULLY AUTOMATIC Setup** ⚡ (Installs Python + ffmpeg automatically)

**macOS/Linux:**
```bash
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline
./setup_auto.sh     # Automatically installs Python 3.8+, ffmpeg, and all dependencies
# Edit .env with your API keys
./start_app.sh      # Starts the application
```

**Windows:**
```cmd
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline
setup_auto.bat      # Guides you through installing Python and ffmpeg, installs all dependencies
REM Edit .env with your API keys
start_app.bat       # Starts the application
```

#### **Option 2: Standard Setup** (Requires Python 3.8+ and ffmpeg pre-installed)

**macOS/Linux:**
```bash
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline
./setup.sh          # Installs Python dependencies only
# Edit .env with your API keys
./start_app.sh      # Starts the application
```

**Windows:**
```cmd
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline
setup.bat           # Installs Python dependencies only
REM Edit .env with your API keys
start_app.bat       # Starts the application
```

Open http://localhost:5001 in your browser. Done! 🎉

---

### ☁️ **Option B: Cloud Deployment** (Railway.app + AWS S3)

**Perfect for:**
- Remote teams working from different locations
- 5+ concurrent users
- 24/7 access from any device
- No local installation needed

**What you get:**
- ✅ Web-based access from anywhere
- ✅ Centralized storage (AWS S3)
- ✅ Always up-to-date (update once, everyone benefits)
- ✅ Professional URLs like `https://your-studio.up.railway.app`

**Cost:** ~$15/month (Railway $10 + S3 $2-5)

**Setup time:** 30-40 minutes

📖 **Full Guide**: See [CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md) for complete step-by-step instructions.

**Quick Overview:**
1. Create AWS S3 bucket for media storage
2. Deploy to Railway.app from GitHub
3. Add environment variables (API keys + S3 config)
4. Start worker service
5. Share URL with team! 🚀

---

### 📋 Prerequisites (Local Setup)

**If using `setup_auto.sh`/`setup_auto.bat`**: No prerequisites! The script installs everything automatically.

**If using standard `setup.sh`/`setup.bat`**:
- **Python 3.8+** - [Download](https://www.python.org/downloads/)
- **ffmpeg** (for video processing) - `brew install ffmpeg` (macOS) or see instructions below
- **API Keys** (get at least one):
  - [Leonardo AI](https://app.leonardo.ai/settings) - Image generation
  - [Replicate](https://replicate.com/account/api-tokens) - Animations
  - [OpenAI](https://platform.openai.com/api-keys) - Style analysis & DALL-E

### 🔧 Manual Installation

1. **Clone and Setup Environment**
   ```bash
   git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
   cd ai_animation_pipline
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure API Keys**
   Create `.env` file in project root:
   ```env
   LEONARDO_API_KEY="your_leonardo_key"
   REPLICATE_API_KEY="r8_your_replicate_key"
   OPENAI_API_KEY="sk-your_openai_key"
   OPENAI_ORG_ID="org-your_openai_org_id"
   ```

3. **Run the Application**
   
   **Easy Way - One Command:**
   ```bash
   ./start_app.sh
   ```
   
   **Manual Way - Two Terminals:**
   ```bash
   # Terminal 1 - Web Server
   source venv/bin/activate
   flask run --host=0.0.0.0 --port=5001
   
   # Terminal 2 - Background Worker
   source venv/bin/activate
   python3 worker.py
   ```

4. **Access Dashboard**
   Open http://localhost:5001 in your browser

## 🎮 Usage Guide

### Basic Workflow
1. **Generate Images**: Use the image generation tool with various AI models
2. **Create Animations**: Convert images to videos using animation models
3. **Extract Frames**: Use video scrubber to extract specific frames
4. **Process Backgrounds**: Remove backgrounds or apply chroma keying
5. **Create Boomerangs**: Automatic A→B→A loop generation
6. **Fine-tune Videos**: Advanced chroma keying with real-time preview

### Boomerang Automation
1. Select start and end frames
2. Enable "Boomerang Automation"
3. System automatically:
   - Preprocesses frames with consistent backgrounds
   - Creates A→B animation
   - Creates B→A animation  
   - Stitches into seamless A→B→A loop

### Video Processing & Keying Workflow

**Quick Auto-Key (Recommended for standard green/blue screens):**
1. Create animation with "Green Screen" or "Blue Screen" background option
2. Click "🔮 Auto Key" button on completed animation
3. Job gets purple ⏸ icon (pending_process status)
4. Click "Process Pending Jobs" to batch process all pending keying jobs
5. View original and keyed videos side-by-side in expanded job details

**Manual Fine-Tuning (For custom adjustments):**
1. Click "⚙️ Fine-Tune Key" on any animation or stitched video
2. Use built-in color sampler to click and sample exact HSV values
3. Adjust sliders for perfect keying (two-column layout for easy comparison)
4. Preview frame-by-frame with navigation buttons
5. Click "💾 Save Settings" (marks as pending_process)
6. Process when ready with "Process Pending Jobs" or "Process Selected Keys"

**Additional Features:**
- **Extract Frames**: Click "Extract Frame" on any video, scrub to desired position
- **Remove Background**: Use BRIA AI for transparent image generation
- **Stitch Videos**: Combine multiple animations into seamless loops
- **Download Options**: Separate buttons for original and keyed versions

## 🔧 Troubleshooting

### Common Issues

**Port 5000 in use (macOS)**
```bash
# Kill AirPlay service or use different port
sudo lsof -ti:5000 | xargs kill -9
```

**Worker not processing jobs**
```bash
# Check if worker is running
ps aux | grep python | grep worker

# Restart worker
source venv/bin/activate && python3 worker.py &
```

**Template not updating**
- Flask template caching is disabled for development
- Hard refresh browser (Cmd+Shift+R / Ctrl+Shift+R)

**Job stuck in processing**
```bash
# Check for stuck ffmpeg processes
ps aux | grep ffmpeg

# Kill if needed
sudo killall ffmpeg

# Restart worker
```

### File Structure
```
kling_app/
├── app.py                 # Flask web server
├── worker.py              # Background job processor  
├── video_processor.py     # Video processing utilities
├── jobs.db               # SQLite database
├── requirements.txt      # Python dependencies
├── .env                  # API keys (create this)
├── templates/            # HTML templates
│   ├── index.html       # Main dashboard
│   ├── animation_step.html
│   └── fine_tune.html   # Chroma keying interface
└── static/              # Generated assets
    ├── animations/      # Generated videos
    ├── library/         # Images and processed content
    └── uploads/         # User uploads
```

## 🎯 Advanced Features

### Job Types
- `image_generation`: AI image creation
- `animation`: Video generation from images
- `boomerang_automation`: A→B→A loop creation
- `video_stitching`: Combine multiple videos
- `frame_extraction`: Extract frames from videos
- `background_removal`: Create transparent images
- `keying_*`: Chroma key processing stages

### API Endpoints
- `/api/jobs`: Job status and history (all job types)
- `/api/extract-frame`: Video frame extraction with time scrubbing
- `/api/batch-delete-items`: Bulk delete operations
- `/api/reset-job`: Reset job status for retry/re-processing
- `/process-all-pending`: Process pending animations/keying (supports video_stitching)
- `/stitch-videos`: Video stitching operations (can stitch any two videos)

## 🔄 Development

### Recent Major Updates (September 2025)
- ✅ **A-B-A Loop Fixes**: Consistent background preprocessing for both start and end frames
- ✅ **Performance Optimization**: Changed stitching from veryslow to fast preset to prevent hanging
- ✅ **Enhanced Job Management**: Re-stitch, re-key, retry failed jobs with comprehensive UI
- ✅ **Universal Job Selection**: All jobs (except actively processing) now have checkboxes
- ✅ **Video Stitching Improvements**: Aspect ratio preservation, timeout protection, can stitch any two videos
- ✅ **Worker Logic Fixes**: Keying status now takes precedence over job type for proper routing
- ✅ **API Enhancements**: Added /api/reset-job endpoint for job management
- ✅ **Automation Reliability**: Fixed race conditions in boomerang automation, no more duplicate stitching jobs
- ✅ **Keying Workflow Fixes**: Complete fix for process pending keys functionality and status routing
- ✅ **Video Stitching Keying**: Resolved worker routing bug - stitched videos now properly create keyed .webm files
- ✅ **UI Library Support**: Added video_stitching job support to library gallery with keyed/original view options
- ✅ **Process Management**: Added automatic ffmpeg cleanup to prevent stuck processes
- ✅ **Style Analyzer Fix**: Fixed unlock checkbox functionality - textarea now properly enables/disables for editing
- ✅ **Startup Automation**: Added start_app.sh script with environment validation and automatic port handling
- ✅ **Debug Enhancements**: Added job count logging and console feedback for better troubleshooting

### Latest Stability & UX Fixes (October 1, 2025)
- ✅ **Animation Image Selection**: Fixed error when selecting images from multi-image generation jobs for animation
- ✅ **Replicate GPT-4o Integration**: Switched animation idea generation from OpenAI to Replicate's GPT-4o model
- ✅ **Enhanced Animation Ideas**: Now uses professional Image-to-Animation Director prompt with detailed analysis
- ✅ **UI Improvements**: Fixed "Get Idea" button positioning, added end frame upload option, improved seamless loop layout
- ✅ **Path Handling**: Fixed image path construction and URL normalization for better reliability
- ✅ **API Response Handling**: Enhanced JavaScript to handle both array and object response formats from /api/jobs
- ✅ **Worker Process Management**: Improved worker restart and code update handling

### Advanced Sticker Effects & Video Processing (October 20-27, 2025)
- ✅ **Complete Sticker Effect Pipeline**: Displacement mapping, blend mode textures, surface bevel, alpha bevel, drop shadow
- ✅ **Clipping Mask Technology**: Textures apply only to non-transparent pixels, preserving alpha channel throughout
- ✅ **Posterize Time Feature**: Stop-motion effect at 12fps or 8fps while maintaining playback speed
- ✅ **Failed Job Recovery System**: Retry button, delete option, and inline error messages for failed jobs
- ✅ **Background Removal Update**: Switched to 851-labs model for improved reliability
- ✅ **Enhanced Image Generation**: Updated prompts with "isolated and centered", FLUX uses "white matte flat background"
- ✅ **Style Analyzer Improvements**: Removed character limit (now 1500 max_tokens), focus on movement/genre naming
- ✅ **Outline Thickness**: Increased max thickness from 10 to 30 pixels for animation preprocessing
- ✅ **Double-Submit Protection**: Prevents duplicate jobs with cooldown timers and button disabling
- ✅ **Alpha Preservation**: PNG-based workflow with single WebM encoding pass ensures transparency maintained
- ✅ **Quality Settings**: 8M bitrate, CRF 15, good quality preset for optimal video output

### Enhanced UI/UX & Video Keying Tools (October 13, 2025)
- ✅ **Processing Animations**: Spinner overlay on thumbnails for jobs in progress states
- ✅ **Reference Image Previews**: Style/palette images display with dynamic aspect ratio in upload boxes
- ✅ **Style Analysis Optimization**: Art Style Forensics analyzer prompt limited to 900 characters for Leonardo compatibility
- ✅ **Extracted Frames Display**: Frames A and B now visible in Loop Creator tool below video
- ✅ **Keying Job Priority**: Auto-key and manual-key jobs jump to top of queue for immediate processing
- ✅ **Universal Keying Support**: Key/Auto Key buttons added to stitched videos and uploaded videos
- ✅ **ABA Thumbnail Fix**: Cache-busting prevents frozen thumbnails after keying
- ✅ **Video Keyer Improvements**: Auto-replace video preview, zoom controls, grid customization, color sampler
- ✅ **Animation Tool Preview**: Selected start frame displays before generation
- ✅ **Batch Selection Tools**: Select All and Invert Selection added to delete functionality
- ✅ **Transparency Display**: Grid background for transparent images/videos in modal viewer
- ✅ **Edit Job Enhancement**: Reference images automatically load when editing jobs
- ✅ **Leonardo Style Presets**: Dropdown menu for Leonardo model style options
- ✅ **ChatGPT Transparency**: Automatic "on a transparent background" appended to prompts
- ✅ **Zoom Constraint Fix**: Video zoom properly constrained within frame boundaries with pan limits
- ✅ **Keying Tool UX**: Flat dark gray background, hand cursor for panning when zoomed

### Analysis Tools Enhancement (October 3, 2025)
- ✅ **Style & Palette Analyzers**: Fixed display of analysis results and thumbnails in job queue
- ✅ **GPT-4o Vision Integration**: Switched from Replicate to direct OpenAI GPT-4o Vision API for reliable analysis
- ✅ **Enhanced Result Display**: Analysis results now show in expandable job cards with side-by-side image/result layout
- ✅ **"Use This" Button**: Automatically copies style analysis to image generation prompt, appends palette analysis
- ✅ **System Prompt Display**: Shows the actual system prompt used for each analysis job
- ✅ **Smart UI Layout**: Analysis results use flexible width layout with input image (150px) and result taking remaining space
- ✅ **Enhanced Error Handling**: User-friendly error messages with debug mode toggle for development
- ✅ **Status Badge Visibility**: Improved "completed" badge readability with black text on teal background
- ✅ **Responsive Dashboard**: Adjusted default panel split to 40% tools / 60% job queue for better workflow visibility

### Auto-Keying & Enhanced Keying Workflow (October 4, 2025)
- ✅ **Auto-Key Button**: One-click automatic chroma keying that reads background color from animation metadata
- ✅ **Intelligent Background Detection**: Automatically applies correct HSV settings (hue 60 for green, 100 for blue)
- ✅ **Pending Process Status**: Jobs marked with purple pause icon (⏸) when auto-keyed but not yet processed
- ✅ **Manual Processing Control**: "Save Settings" button stores keying parameters without immediate processing
- ✅ **Batch Processing**: "Process Pending Jobs" and "Process Selected Keys" for efficient batch keying
- ✅ **Visual Status Indicators**: Green "KEYED" badge on thumbnails for completed keying jobs
- ✅ **Side-by-Side Comparison**: Expanded view shows original and keyed videos simultaneously
- ✅ **Transparent Background Display**: Checkered pattern background for keyed videos to show transparency
- ✅ **Download Options**: Separate download buttons for original and keyed versions
- ✅ **Video Playback Enhancement**: Automatic play/loop when expanding job details with cache-busting
- ✅ **Inline Keying Tool**: Video keyer integrated into left tools panel instead of separate window
- ✅ **Color Sampler**: Click-to-sample tool for precise HSV value selection from video frames
- ✅ **Compact Layout**: Two-column grid for keying sliders with proper spacing

### UX Improvements & Workflow Enhancements (October 5, 2025)
- ✅ **Streamlined Notifications**: Removed confirmation popups for background removal and keying operations
- ✅ **Enhanced Button Readability**: Clear Failed, Clear Stuck, Clear All Jobs now have black text on light background
- ✅ **Smart Status Display**: "waiting_for_children" and "stitching" statuses show friendly labels with shimmer animation
- ✅ **Improved ABA Loop Flow**: Stitched videos now update parent boomerang job directly (no separate log entry)
- ✅ **Advanced Color Sampler**: Click-to-sample now inverts saturation/value thresholds for correct keying
- ✅ **Bidirectional Erode/Dilate**: Sliders now range from -5 to 5 with 0 as default (negative values reverse the effect)
- ✅ **Enhanced Preview System**: Fixed cache-busting parameter handling in keying preview endpoint
- ✅ **Uploaded Video Support**: Auto-key and manual keying now fully support user-uploaded videos
- ✅ **Palette Analysis Enhancement**: System prompt updated to exclude chroma key background colors from subject palette
- ✅ **Image Modal Navigation**: Fixed navigation arrows to work correctly across all job types with proper image collection
- ✅ **Keying Tool UX**: Added Reset Preview, Zoom In/Out controls, and improved checkerboard background display
- ✅ **Non-Intrusive Feedback**: Replaced blocking alerts with timed notification toasts (4s for success, 6s for errors)

### Critical Bug Fixes & Stability Improvements (October 5, 2025 PM)
- ✅ **Frame Extraction Database Bug**: Fixed SQLite AUTOINCREMENT conflict by using future timestamps instead of manual ID assignment
- ✅ **Animation File Handle Leak**: Implemented try-finally blocks to ensure proper cleanup of `end_file_obj` in all error scenarios
- ✅ **Boomerang Race Condition**: Refined child job completion detection to explicitly check `status=='completed'` and `result_data`
- ✅ **Database Lock Prevention**: Added comprehensive error handling to Flask route database operations to prevent crashes
- ✅ **FFmpeg Zombie Process Fix**: Implemented explicit `process.kill()` in timeout handlers to prevent hung FFmpeg processes
- ✅ **JavaScript Syntax Errors**: Fixed 3 critical frontend bugs (misplaced braces in deleteGroup, animateGroupImages, removeBgGroup functions)
- ✅ **Worker Process Cleanup**: Eliminated 18 duplicate worker processes that were causing resource contention
- ✅ **Database Integrity**: Updated stuck boomerang automation job (status='stitching' despite completed children) to restore frontend functionality

### Git Workflow
```bash
git status                    # Check changes
git add app.py worker.py templates/  # Add core files
git commit -m "Feature: description"
```

## ✅ Current Status

### All Features Working
- ✅ **Animation Keying**: Works perfectly, creates proper transparent .webm files
- ✅ **Video Stitching Keying**: RESOLVED - stitched videos now properly create keyed .webm files with transparency
- ✅ **Keying Workflow**: Process Pending Keys button now correctly queues jobs for keying processing
- ✅ **Worker Routing**: Status-based routing ensures keying jobs go to handle_keying() function
- ✅ **UI Gallery Support**: Video stitching jobs display correctly with keyed/original view options
- ✅ **Process Management**: Automatic cleanup of stuck ffmpeg processes every 30 seconds
- ✅ **Job Management**: Cancel, clear stuck, clear failed jobs functionality
- ✅ **All Other Features**: Fully functional including boomerang automation and video stitching

## 📞 Support

For issues or questions:
1. Check logs in terminal windows
2. Verify API keys in `.env`
3. Ensure both Flask app and worker are running
4. Check browser console for JavaScript errors
5. Kill stuck FFmpeg processes: `sudo killall ffmpeg`
6. Restart worker if needed: `python3 worker.py &`

---

**Built with Flask, OpenCV, FFmpeg, and various AI APIs for professional-grade media workflow automation.**