# Video Trimming Feature

## Overview
Users can now trim animations to keep only the good parts by selecting in/out points with frame-accurate precision.

## Features

### ✂️ Trim Tool
- **Frame-accurate selection**: Navigate frame by frame to find exact in/out points
- **Visual timeline**: See current time, in point, out point, and resulting duration
- **Set points**: Click "Set Current Time" to mark in/out points while playing
- **Go to points**: Jump to in/out points for review
- **Live duration display**: Shows the duration of the trimmed segment

### User Interface

#### Access
- Click the **"✂️ Trim"** button on any video job (animations, boomerang, stitched videos)
- Opens the **Trim Animation** tool with the video loaded

#### Controls
1. **In Point (Start)**: 
   - Number input field
   - "Set Current Time" button (sets to video's current playback position)
   - "Go To" button (jumps to this time)

2. **Out Point (End)**:
   - Number input field  
   - "Set Current Time" button
   - "Go To" button

3. **Navigation**:
   - ◄ Prev Frame / Next Frame ► buttons
   - Video player controls (play/pause/scrub)

4. **Duration Display**: Shows calculated duration of trimmed segment

5. **Trim & Save Button**: Processes the trim and updates the job

## Workflow

1. **User clicks "✂️ Trim" on a video job**
2. **Tool loads** with video and default points (0s to end)
3. **User navigates** to desired start point → clicks "Set Current Time" for In Point
4. **User navigates** to desired end point → clicks "Set Current Time" for Out Point
5. **User reviews** by jumping to points or scrubbing
6. **User clicks "✂️ Trim & Save"**
7. **Backend trims** video using ffmpeg
8. **Job updates** with trimmed video and updated prompt showing trim range

## Technical Implementation

### Frontend (index_v2.html)
- New tool section: `#tool-trim-video`
- JavaScript functions:
  - `editAnimation(jobId)` - Loads video into trim tool
  - `setTrimInPoint()`, `setTrimOutPoint()` - Mark points at current time
  - `goToTrimInPoint()`, `goToTrimOutPoint()` - Jump to marked points
  - `updateTrimDuration()` - Calculate and display duration
  - `prevFrameTrim()`, `nextFrameTrim()` - Frame-by-frame navigation
  - `trimVideo()` - Submit trim request to backend

### Backend (app.py)
- New endpoint: `/api/trim-video` (POST)
- Process:
  1. Get job and video URL
  2. Download from S3 if needed
  3. Use ffmpeg to trim: `-ss <start> -t <duration> -c copy`
  4. Upload trimmed video to S3
  5. Update job's `result_data` with new URL
  6. Update prompt to show trim range

### FFmpeg Command
```bash
ffmpeg -y -i input.webm -ss <in_point> -t <duration> -c copy output.webm
```
- `-ss`: Start time (seek to in point)
- `-t`: Duration (out point - in point)
- `-c copy`: Stream copy (no re-encoding, fast!)

## Benefits

### For Users
- **Save time**: Keep only the best parts of animations
- **Perfect timing**: Frame-accurate trimming
- **Non-destructive**: Original video unchanged (creates new trimmed version)
- **Fast processing**: Uses stream copy (no re-encoding)

### Use Cases
- Remove slow start/end of animations
- Extract perfect loops from longer clips  
- Remove glitches or artifacts
- Create shorter clips for specific needs

## Job Types Supported
- ✅ Animation jobs
- ✅ Boomerang automation
- ✅ Video stitching
- ✅ Works with both keyed and original videos

## Notes
- Trimming updates the job's `result_data` with the new trimmed video
- Prompt is updated to show trim range: `[Trimmed 2.5s-7.3s]`
- Fast trimming uses codec copy (no quality loss, instant)
- For keyed videos, automatically extracts the WebM URL from JSON format
- Frame navigation assumes 30 FPS by default

