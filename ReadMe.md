# 🎬 AI Media Workflow Dashboard

A comprehensive Flask-based application for AI-powered image generation, animation creation, and video processing with advanced chroma keying capabilities.

## ✨ Key Features

### 🎨 **Multi-Model Image Generation**
- **Leonardo AI**: Multiple models (Diffusion XL, Vision XL, etc.)
- **OpenAI**: DALL-E integration
- **Style Analysis**: AI-powered color palette and style extraction

### 🎭 **Advanced Animation Workflow** 
- **Multiple Models**: Kling v2.1, Seedance-1-Pro, Pixverse v4.5
- **Boomerang Automation**: Automatic A→B→A loop creation with consistent backgrounds
- **Frame Extraction**: Video scrubbing with precise frame selection
- **Seamless Loops**: Automatic loop detection and processing

### 🎞️ **Professional Video Processing**
- **Chroma Keying**: Advanced green/blue screen removal with real-time preview (works on animations and stitched videos)
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

### Prerequisites
- **Python 3.8+**
- **ffmpeg** (for video processing)
- **OpenCV** (automatically installed via requirements.txt)
- **API Keys**: Leonardo AI, Replicate, OpenAI

### Installation

1. **Clone and Setup Environment**
   ```bash
   git clone <repository>
   cd kling_app
   python3 -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure API Keys**
   Create `.env` file in project root:
   ```env
   LEONARDO_API_KEY="your_leonardo_key"
   REPLICATE_API_TOKEN="r8_your_replicate_key"
   OPENAI_API_KEY="sk-your_openai_key"
   OPENAI_ORG_ID="org-your_openai_org_id"
   ```

3. **Run the Application**
   
   **Easy Way (Recommended) - One Command:**
   ```bash
   ./start_app.sh
   ```
   This script automatically handles virtual environment, port conflicts, and provides clear instructions.
   
   **Manual Way - Two Terminals:**
   
   **Terminal 1 - Web Server:**
   ```bash
   source venv/bin/activate
   flask run --host=0.0.0.0 --port=5001
   ```
   
   **Terminal 2 - Background Worker (Optional):**
   ```bash
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

### Video Processing
- **Extract Frames**: Click "Extract Frame" on any video, scrub to desired position
- **Remove Background**: Use BRIA AI for transparent image generation
- **Chroma Key**: Advanced green/blue screen removal with parameter tuning
- **Stitch Videos**: Combine multiple animations into seamless loops

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