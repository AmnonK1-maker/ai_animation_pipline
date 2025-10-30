# GIF and PNG Sequence Export Features

## Overview
The app can now export GIF files and PNG sequence ZIP archives from the processed keyed frames, in addition to the standard WebM output.

## Features Added

### 1. GIF Export
- Creates an animated GIF with transparency support
- Uses ffmpeg's palette generation for high-quality output
- Maintains the same frame rate as the processed video
- Checkbox option: "Export as GIF"

### 2. PNG Sequence ZIP Export
- Exports all processed frames as individual PNG files
- Packaged in a ZIP archive for easy download
- All frames maintain full alpha channel transparency
- Checkbox option: "Export PNG Sequence (ZIP)"

## User Interface

### Location
The export options are in the **Video Keyer** tool, in a new "Export Options" section:
- Located after the Posterize Time section
- Before the "Save & Process" button
- Two checkboxes for GIF and PNG ZIP export

### Usage
1. Upload and process a video with chroma keying
2. Check "Export as GIF" and/or "Export PNG Sequence (ZIP)" before processing
3. Click "Save & Process"
4. After processing completes, click "Download Keyed" button
5. If multiple formats available, a menu will appear to choose which format to download

## Technical Implementation

### Backend (worker.py)
- Exports are generated **before** encoding to WebM
- GIF export uses two-pass ffmpeg with palette generation for quality
- PNG ZIP uses Python's zipfile module with compression level 6
- All exports use the same processed frames (after keying, sticker effects, posterize)

### Data Format
The `keyed_result_data` field now stores JSON:
```json
{
  "webm": "url_to_webm_file",
  "gif": "url_to_gif_file_or_null",
  "png_zip": "url_to_zip_file_or_null"
}
```

### Backward Compatibility
- Old jobs with string URLs still work (auto-detected)
- Display code handles both old (string) and new (JSON) formats
- Downloads work for both formats

## Export Workflow

1. **Keying** → Frames extracted and keyed
2. **Sticker Effects** (if enabled) → Applied to frames
3. **Posterize Time** (if enabled) → Frame reduction
4. **GIF Export** (if requested) → Generate palette and create GIF
5. **PNG ZIP Export** (if requested) → Compress frames to ZIP
6. **WebM Encoding** → Final video encoding
7. **Cleanup** → Temporary frames deleted

## File Locations
- WebM: `static/library/transparent_videos/keyed_*.webm`
- GIF: `static/library/transparent_videos/keyed_*.gif`
- ZIP: `static/library/transparent_videos/keyed_*.zip`

## Notes
- All exports maintain full transparency (alpha channel)
- GIF export quality is optimized with palette generation
- ZIP compression provides good balance between size and speed
- Exports are optional - WebM is always generated

