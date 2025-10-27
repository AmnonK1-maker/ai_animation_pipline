# 🎨 Realistic Sticker Effect Feature

## Overview
The Sticker Effect is a post-keying video processing feature that applies realistic texture, depth, and lighting effects to transparent animations, giving them a physical "sticker-like" appearance.

## ✨ Features

### 1. **Animated Perlin Noise Textures**
- **Displacement Texture** (0-50px intensity)
  - Warps the image to create realistic wrinkles and creases
  - Uses OpenCV remapping for smooth distortion
  - Applied with Multiply blend mode for shadow depth

- **Screen Texture** (0-100% opacity)
  - Adds dynamic highlights and shine
  - Uses Add (Linear Dodge) blend mode for bright highlights
  - Creates animated shimmer effect

### 2. **Surface Bevel & Emboss**
- Creates 3D relief effect on the image surface
- Uses Sobel edge detection to generate a relief map
- Overlay blend mode for subtle depth
- Adjustable:
  - Depth (1-10px)
  - Highlight intensity (0-100%)
  - Shadow intensity (0-100%)

### 3. **Alpha Bevel (Edge Effect)**
- Applies lighting to the alpha channel boundaries
- Mimics After Effects' alpha bevel with light angle
- Uses gradient normals and light direction comparison
- Adjustable:
  - Size/Depth (1-30px)
  - Blur/Soften (0-30px)
  - Light Angle (0-360°)
  - Highlight intensity (0-100%)
  - Shadow intensity (0-100%)

### 4. **Drop Shadow**
- Post-processing shadow effect
- Adjustable:
  - Blur (0-50px)
  - Offset X/Y (-50 to +50px)
  - Opacity (0-100%)

## 🔧 Technical Implementation

### Key Fix: Single-Encoding Pipeline
**Problem**: Double-encoding was corrupting the alpha channel:
- Old: Key → Encode WebM → Extract → Apply Effects → Encode WebM (❌ alpha lost)

**Solution**: Single-encoding with PNG intermediates:
- New: Key → PNG frames → Apply Effects → Encode WebM once (✅ alpha preserved)

### Critical Components

#### 1. **PNG Alpha Preservation** (`video_processor.py`)
```python
# Use PIL to save PNGs with alpha (OpenCV can corrupt alpha)
b, g, r, a = cv2.split(bgra_frame)
rgba_frame = cv2.merge([r, g, b, a])
pil_image = Image.fromarray(rgba_frame, 'RGBA')
pil_image.save(frame_filename, 'PNG')
```

#### 2. **FFmpeg Alpha Encoding**
```bash
ffmpeg -y \
  -framerate 30 \
  -f image2 \
  -i frames/frame_%05d.png \
  -vf 'format=yuva420p' \  # CRITICAL: Force alpha-aware format
  -c:v libvpx-vp9 \
  -pix_fmt yuva420p \
  -auto-alt-ref 0 \        # Required for transparent WebM
  -b:v 8M \
  -crf 15 \
  output.webm
```

The `-vf format=yuva420p` filter is **critical** - it tells FFmpeg to treat PNG inputs as having alpha.

#### 3. **Photoshop-Style Clipping Masks**
Textures are "clipped" by the base image's alpha before blending:

```python
# In blend_multiply() and blend_add()
alpha_mask_3d = base_alpha[:, :, np.newaxis] / 255.0
overlay_rgb_clipped = overlay_rgb * alpha_mask_3d  # Clip texture
result_rgb = (base_rgb * overlay_rgb_clipped).clip(0, 255)
result_rgb = (result_rgb * alpha_mask_3d).astype(np.uint8)  # Zero transparent areas
```

This ensures textures only appear where the image has content, maintaining perfect transparency.

## 📁 File Structure

```
static/
  textures/
    displacement/    # PNG sequence for displacement + multiply blend
      frame_0000.png
      frame_0001.png
      ...
    screen/          # PNG sequence for add blend (highlights)
      frame_0000.png
      frame_0001.png
      ...
```

**Texture Requirements**:
- PNG format
- Any resolution (auto-resized to match video)
- Grayscale recommended for displacement
- High-contrast for best effect
- 100+ frames for smooth animation loop

## 🎛️ Default Settings

These values provide a balanced "realistic sticker" look:

```python
displacement_intensity = 50      # Maximum warp
darker_opacity = 1.0             # Full multiply blend
screen_opacity = 0.7             # 70% highlights
alpha_bevel_size = 15            # 15px edge depth
alpha_bevel_blur = 2             # Subtle softening
alpha_bevel_angle = 70           # Top-right lighting
shadow_blur = 0                  # Sharp shadow
shadow_x = 1                     # 1px right
shadow_y = 1                     # 1px down
shadow_opacity = 1.0             # Fully opaque
```

## 🚀 Usage

### In the Video Keyer Tool:

1. Generate and key an animation
2. Check **"🎨 Enable Sticker Effect"**
3. Adjust sliders:
   - Displacement: How much texture warps the image
   - Multiply/Add Opacity: Blend intensity
   - Enable surface/alpha bevels as needed
   - Add drop shadow if desired
4. Click **"Process Keying"**

### Processing Flow:

```
1. User uploads/generates animation with green screen
2. Keying: Extract frames → Chroma key → Save as PNG with alpha
3. Sticker Effects (if enabled):
   - Load animated textures
   - For each frame:
     a. Apply displacement (warp)
     b. Apply multiply blend (shadows)
     c. Apply add blend (highlights)
     d. Apply surface bevel (relief)
     e. Apply alpha bevel (edge lighting)
     f. Apply drop shadow
   - Save processed PNG
4. Encode: All PNGs → Single WebM with transparency
5. Upload to S3 / Return to user
```

## 🐛 Troubleshooting

### Black Background Instead of Transparency
- **Cause**: Missing `-vf format=yuva420p` in FFmpeg command
- **Fix**: Ensure this filter is present in all WebM encoding commands

### Textures Bleeding into Transparent Areas
- **Cause**: Blend modes not using alpha clipping masks
- **Fix**: Ensure `blend_multiply()` and `blend_add()` multiply textures by `alpha_mask_3d`

### Low Quality / Compression Artifacts
- **Cause**: FFmpeg bitrate too low
- **Fix**: Use `-b:v 8M -crf 15 -quality good -cpu-used 2`

## 📊 Performance

- **Processing Time**: ~2-5 seconds per frame (depends on effects enabled)
- **Memory**: ~200MB for 90-frame animation
- **Recommended**: Render.com Standard plan (2GB RAM) or higher for production

## 🎓 Credits

Inspired by After Effects' alpha bevel, Photoshop's blend modes, and real-world printed sticker aesthetics.

---

**Last Updated**: October 26, 2025
**Version**: 1.0.0


