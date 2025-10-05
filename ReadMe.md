# 🎬 AI Media Workflow Dashboard

A comprehensive Flask-based application for AI-powered image generation, animation creation, and video processing with advanced chroma keying capabilities.

## ✨ Key Features

### 🎨 **Multi-Model Image Generation**
- **Leonardo AI**: Multiple models (Diffusion XL, Vision XL, etc.)
- **OpenAI**: DALL-E integration
- **ByteDance Seedream**: Advanced AI image generation
- **Style Analysis**: AI-powered color palette and style extraction

### 🎭 **Advanced Animation Workflow** 
- **Multiple Models**: Kling v2.1, Seedance-1-Pro
- **Boomerang Automation**: Automatic A→B→A loop creation with consistent backgrounds
- **Frame Extraction**: Video scrubbing with precise frame selection
- **Seamless Loops**: Automatic loop detection and processing

### 🎞️ **Professional Video Processing**
- **Auto-Key Feature**: One-click automatic chroma keying based on animation background (green/blue screen)
- **Manual Chroma Keying**: Advanced fine-tuning with real-time preview and color sampler tool
- **Smart Keying Workflow**: Save settings to `pending_process`, batch process when ready
- **Side-by-Side Comparison**: View original and keyed videos simultaneously with download options
- **Video Stitching**: Optimized A-B-A loop stitching with aspect ratio preservation and timeout protection
- **Background Removal**: BRIA AI-powered transparent image generation
- **Performance Optimized**: Fast preset, CRF 18 encoding with 5-minute timeout for reliability

### 🎯 **Intelligent Workflow Management**
- **Job Queue System**: Background processing with real-time status updates
- **Auto-Pause Refresh**: Smart UI that pauses when viewing job details
- **Enhanced Batch Operations**: Multi-select delete, video stitching (any two videos)
- **Job Management Tools**: Re-stitch, re-key, retry failed jobs with one click
- **Universal Selectability**: All jobs (except actively processing) have checkboxes
- **Model Name Mapping**: Human-readable model names instead of IDs

### 📚 **Media Library & Management**
- **Visual Job Log**: Thumbnails, previews, and action buttons for each job
- **Search & Filter**: Find content by prompts, models, or job types
- **Library Gallery**: Organized view of all generated assets

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

### 🎯 Quick Start (Recommended)

**For New Team Members**: See [SETUP.md](SETUP.md) for detailed setup guide.

**One-Click Setup:**

**macOS/Linux:**
```bash
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline
./setup.sh          # Installs everything
# Edit .env with your API keys
./start_app.sh      # Starts the application
```

**Windows:**
```cmd
git clone https://github.com/AmnonK1-maker/ai_animation_pipline.git
cd ai_animation_pipline
setup.bat           # Installs everything
REM Edit .env with your API keys
start_app.bat       # Starts the application
```

Open http://localhost:5001 in your browser. Done! 🎉

### 📋 Prerequisites
- **Python 3.8+** - [Download](https://www.python.org/downloads/)
- **ffmpeg** (for video processing) - `brew install ffmpeg` (macOS)
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