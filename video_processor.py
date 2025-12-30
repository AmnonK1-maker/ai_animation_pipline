import cv2
import numpy as np
import os
import shutil
import subprocess
import tempfile
import time
import traceback
from colorsys import rgb_to_hsv, hsv_to_rgb
from pathlib import Path
from PIL import Image

def process_single_frame(frame, lower_green, upper_green, erode_amount, dilate_amount, blur_amount, spill_amount):
    """
    Applies chroma keying and returns a single, transparent 4-channel BGRA frame.
    """
    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv_frame, np.array(lower_green), np.array(upper_green))
    
    # Handle erode/choke (positive = choke alpha inward, negative = grow alpha outward)
    # NOTE: We work on the green MASK (white = remove), so operations are INVERTED
    # To CHOKE alpha (shrink visible area), we DILATE the mask (expand green removal)
    if erode_amount > 0:
        dilate_kernel = np.ones((erode_amount, erode_amount), np.uint8)
        mask = cv2.dilate(mask, dilate_kernel, iterations=1)  # Expand mask = choke alpha
    elif erode_amount < 0:
        # Negative erode means grow alpha outward
        erode_kernel = np.ones((abs(erode_amount), abs(erode_amount)), np.uint8)
        mask = cv2.erode(mask, erode_kernel, iterations=1)  # Shrink mask = grow alpha
        
    # Handle dilate/soften (positive = grow alpha outward, negative = shrink alpha inward)
    # To GROW alpha (expand visible area), we ERODE the mask (shrink green removal)
    if dilate_amount > 0:
        erode_kernel = np.ones((dilate_amount, dilate_amount), np.uint8)
        mask = cv2.erode(mask, erode_kernel, iterations=1)  # Shrink mask = grow alpha
    elif dilate_amount < 0:
        # Negative dilate means shrink alpha
        dilate_kernel = np.ones((abs(dilate_amount), abs(dilate_amount)), np.uint8)
        mask = cv2.dilate(mask, dilate_kernel, iterations=1)  # Expand mask = shrink alpha

    if blur_amount > 0:
        blur_amount = blur_amount if blur_amount % 2 != 0 else blur_amount + 1
        mask = cv2.GaussianBlur(mask, (blur_amount, blur_amount), 0)
        
    inverted_mask = cv2.bitwise_not(mask)
    
    # GREEN SPILL SUPPRESSION: Remove green color cast from edges
    # Create spill map by dilating the keying mask to find edge areas
    spill_iterations = max(1, int(spill_amount * 3))  # Convert 0-1 float to 1-3 iterations
    spill_map = cv2.dilate(mask, np.ones((5,5), np.uint8), iterations=spill_iterations)
    spill_map = cv2.GaussianBlur(spill_map, (7,7), 0)
    spill_map_normalized = (spill_map / 255.0) * spill_amount
    
    # Split frame into B, G, R channels
    b, g, r = cv2.split(frame)
    
    # Reduce GREEN channel in spill areas (suppress green color cast)
    # Use the average of blue and red as replacement for green
    green_replacement = ((b.astype(np.float32) + r.astype(np.float32)) / 2.0).astype(np.uint8)
    g_despilled = (g * (1 - spill_map_normalized) + green_replacement * spill_map_normalized).astype(np.uint8)
    
    # Merge back with despilled green channel
    frame_despilled = cv2.merge([b, g_despilled, r])
    
    bgra_frame = cv2.merge([b, g_despilled, r, inverted_mask])
    
    return bgra_frame

def apply_motion_blur_to_frame(current_frame, previous_frame, blur_strength=1.0):
    """
    Apply motion blur based on optical flow analysis (RSMB-style).
    Analyzes motion between frames and applies directional blur.
    
    Args:
        current_frame: BGRA frame with alpha channel
        previous_frame: Previous BGRA frame (None for first frame)
        blur_strength: Blur intensity multiplier (0.5-2.0, default 1.0)
    
    Returns:
        BGRA frame with motion blur applied
    """
    if previous_frame is None or blur_strength <= 0:
        return current_frame
    
    # Extract BGR channels for optical flow (ignoring alpha)
    curr_bgr = current_frame[:, :, :3]
    prev_bgr = previous_frame[:, :, :3]
    alpha = current_frame[:, :, 3]
    
    # Convert to grayscale for optical flow calculation
    curr_gray = cv2.cvtColor(curr_bgr, cv2.COLOR_BGR2GRAY)
    prev_gray = cv2.cvtColor(prev_bgr, cv2.COLOR_BGR2GRAY)
    
    # Calculate dense optical flow (Farneback method)
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray, curr_gray,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0
    )
    
    # Get motion magnitude
    mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    
    # Apply blur based on motion magnitude
    # Higher motion = more blur
    max_mag = np.max(mag)
    if max_mag < 0.5:  # Minimal motion, skip blur
        return current_frame
    
    # Create motion blur by blending current and previous frames
    # Weight based on motion magnitude
    mag_norm = np.clip(mag / max_mag * blur_strength, 0, 1)
    mag_3d = np.stack([mag_norm] * 3, axis=-1)
    
    # Blend frames: more motion = more previous frame blended in
    blurred_bgr = (curr_bgr * (1 - mag_3d * 0.5) + prev_bgr * (mag_3d * 0.5)).astype(np.uint8)
    
    # Recombine with alpha
    result = np.dstack([blurred_bgr, alpha])
    return result

def apply_light_wrap_to_frame(frame_with_alpha, intensity=0.3, thickness=5):
    """
    Apply light wrap effect to transparent frame edges.
    Simulates white background light wrapping around object.
    
    Args:
        frame_with_alpha: BGRA frame with alpha channel
        intensity: Wrap strength (0.0-1.0, typically 0.2-0.5)
        thickness: Wrap radius in pixels (typically 3-8)
    
    Returns:
        BGRA frame with light wrap applied
    """
    if intensity <= 0 or thickness <= 0:
        return frame_with_alpha
    
    bgr = frame_with_alpha[:, :, :3].astype(np.float32)
    alpha = frame_with_alpha[:, :, 3].astype(np.float32)
    
    # Create smooth edge mask from alpha channel
    # Invert alpha (0 = solid, 255 = transparent) for edge detection
    alpha_inv = 255 - alpha
    
    # Dilate to find edge region
    dilate_kernel = np.ones((thickness, thickness), np.uint8)
    edge_region = cv2.dilate(alpha_inv.astype(np.uint8), dilate_kernel, iterations=1).astype(np.float32)
    
    # CRITICAL: Blur the edge mask for smooth falloff (not hard edges!)
    blur_size = thickness * 2 + 1
    edge_mask_smooth = cv2.GaussianBlur(edge_region, (blur_size, blur_size), thickness / 2.0)
    
    # Normalize and apply intensity
    edge_mask_smooth = edge_mask_smooth / 255.0 * intensity
    
    # Create white glow (255, 255, 255)
    white = np.array([255.0, 255.0, 255.0], dtype=np.float32)
    
    # Apply screen blend mode at edges
    # Screen formula: 1 - (1 - A) * (1 - B)
    edge_mask_3d = np.stack([edge_mask_smooth] * 3, axis=-1)
    
    # Blend white glow into edges
    wrapped = bgr + (white - bgr) * edge_mask_3d
    wrapped = np.clip(wrapped, 0, 255).astype(np.uint8)
    
    # Recombine with original alpha
    result = np.dstack([wrapped, alpha.astype(np.uint8)])
    return result

def process_single_frame_with_effects(frame, lower_green, upper_green, erode_amount, 
                                     dilate_amount, blur_amount, spill_amount,
                                     motion_blur=False, motion_blur_strength=1.0,
                                     light_wrap=False, light_wrap_intensity=0.3, 
                                     light_wrap_thickness=5,
                                     previous_keyed_frame=None):
    """
    Process frame with chroma keying AND optional post-effects.
    
    This combines the keying with optional motion blur and light wrap
    for preview purposes.
    
    Note: Motion blur requires previous_keyed_frame for optical flow calculation.
    For preview (single frame), motion blur will be skipped.
    """
    # First, apply standard keying
    bgra_frame = process_single_frame(frame, lower_green, upper_green, 
                                     erode_amount, dilate_amount, blur_amount, spill_amount)
    
    # Apply optional post-keying effects
    if motion_blur and motion_blur_strength > 0 and previous_keyed_frame is not None:
        bgra_frame = apply_motion_blur_to_frame(bgra_frame, previous_keyed_frame, motion_blur_strength)
    
    if light_wrap and light_wrap_intensity > 0 and light_wrap_thickness > 0:
        bgra_frame = apply_light_wrap_to_frame(bgra_frame, light_wrap_intensity, light_wrap_thickness)
    
    return bgra_frame

def reverse_green_adjustment(image_path):
    """
    TEST FUNCTION: Reverse the uniform green adjustment applied before keying.
    This restores the original vibrant colors after chroma keying is complete.
    
    Reverses the adjustments made by adjust_greens_away_from_chroma():
    - Green was reduced by 10% -> now increase by ~11%
    - Red was increased by 8 -> now decrease by 8
    - Blue was increased by 5 -> now decrease by 5
    """
    try:
        img = Image.open(image_path).convert("RGBA")
        pixels = np.array(img, dtype=np.float32)
        
        r, g, b, a = pixels[:,:,0], pixels[:,:,1], pixels[:,:,2], pixels[:,:,3]
        
        # Only adjust non-transparent pixels
        mask = a > 0
        
        # Reverse the adjustments:
        pixels[:,:,1] = np.where(mask, np.minimum(g / 0.90, 255), g)  # Restore green
        pixels[:,:,0] = np.where(mask, np.maximum(r - 8, 0), r)  # Remove added red
        pixels[:,:,2] = np.where(mask, np.maximum(b - 5, 0), b)  # Remove added blue
        
        # Convert back to uint8
        pixels = np.clip(pixels, 0, 255).astype(np.uint8)
        
        # Save restored image
        restored_img = Image.fromarray(pixels, 'RGBA')
        restored_img.save(image_path)
        
        return True
    except Exception as e:
        print(f"      ⚠️ Color restoration failed on {image_path}: {e}")
        return False

def process_video_with_opencv(video_path, output_path, lower_green, upper_green, erode_amount, dilate_amount, blur_amount, spill_amount, skip_encoding=False, job_id=None, motion_blur=False, motion_blur_strength=1.0, light_wrap=False, light_wrap_intensity=0.3, light_wrap_thickness=5, screen_color=None):
    """
    Processes a video using a manual ffmpeg pipeline. Audio is ignored.
    
    Args:
        skip_encoding: If True, only processes frames and returns (fps, frame_count, temp_frame_dir)
                       without encoding to WebM. Used when sticker effects will be applied next.
        job_id: Optional job ID for unique temp directory (prevents conflicts in parallel processing)
    
    Returns:
        If skip_encoding=False: None (output_path is created)
        If skip_encoding=True: (fps, frame_count, temp_frame_dir)
    """
    # Use unique PNG sequence directory per job - these are PERMANENT files, not temp!
    # Store in transparent_videos folder to keep organized
    base_dir = Path(__file__).parent / "static" / "library" / "transparent_videos" / "png_sequences"
    base_dir.mkdir(parents=True, exist_ok=True)
    
    temp_frame_dir = str(base_dir / f"keyed_frames_{job_id}") if job_id else str(base_dir / "keyed_frames")
    if os.path.exists(temp_frame_dir):
        shutil.rmtree(temp_frame_dir)
    os.makedirs(temp_frame_dir)

    try:
        print("-> Step 1: Extracting and processing frames...")
        video_capture = cv2.VideoCapture(video_path)
        original_fps = video_capture.get(cv2.CAP_PROP_FPS)
        frame_count = 0
        previous_keyed_frame = None
        
        while True:
            success, frame = video_capture.read()
            if not success:
                break
            
            bgra_frame = process_single_frame(frame, lower_green, upper_green, erode_amount, dilate_amount, blur_amount, spill_amount)
            
            # Apply optional post-keying effects
            if motion_blur and motion_blur_strength > 0 and previous_keyed_frame is not None:
                bgra_frame = apply_motion_blur_to_frame(bgra_frame, previous_keyed_frame, motion_blur_strength)
            
            if light_wrap and light_wrap_intensity > 0 and light_wrap_thickness > 0:
                bgra_frame = apply_light_wrap_to_frame(bgra_frame, light_wrap_intensity, light_wrap_thickness)
            
            frame_filename = os.path.join(temp_frame_dir, f"frame_{frame_count:05d}.png")
            
            # Store current frame for next iteration's motion blur
            previous_keyed_frame = bgra_frame.copy()
            
            # CRITICAL: Use PIL to save PNG with alpha, OpenCV can corrupt alpha channel
            # Convert BGRA (OpenCV) to RGBA (PIL)
            b, g, r, a = cv2.split(bgra_frame)
            rgba_frame = cv2.merge([r, g, b, a])  # Reorder to RGB + Alpha
            pil_image = Image.fromarray(rgba_frame, 'RGBA')
            pil_image.save(frame_filename, 'PNG')
            
            frame_count += 1
            
        video_capture.release()
        print(f"   ...processed and saved {frame_count} frames to {temp_frame_dir}")

        # If skip_encoding=True, return the frame info for further processing (sticker effects)
        if skip_encoding:
            print(f"   ⏸️  Skipping encoding - frames ready for post-processing")
            return (original_fps, frame_count, temp_frame_dir)

        # Restore saturation (40% → 100%) before encoding
        saturation_multiplier = 2.5
        screen_msg = f" ({screen_color.upper()} excluded)" if screen_color else ""
        all_frames = sorted([f for f in os.listdir(temp_frame_dir) if f.startswith('frame_') and f.endswith('.png')])
        print(f"-> Step 2: Restoring saturation for {len(all_frames)} frames (40% → 100%){screen_msg}...")
        
        for frame_file in all_frames:
            frame_path = os.path.join(temp_frame_dir, frame_file)
            try:
                img = Image.open(frame_path).convert("RGBA")
                rgb = np.array(img.convert("RGB"), dtype=np.float32) / 255.0
                alpha = np.array(img.split()[3])
                h, s, v = np.vectorize(rgb_to_hsv)(rgb[:,:,0], rgb[:,:,1], rgb[:,:,2])
                
                # Only process nearly-opaque pixels (excludes residual green fringe)
                alpha_mask = alpha > 200
                
                if screen_color and saturation_multiplier > 1.0:
                    # AFTER KEYING: Exclude screen color from boost
                    if screen_color == 'blue':
                        screen_hue_mask = (h >= 0.5) & (h <= 0.75)
                    else:  # green
                        screen_hue_mask = (h >= 0.167) & (h <= 0.5)
                    
                    # Also exclude very low saturation pixels (likely artifacts)
                    saturation_mask = s > 0.1
                    boost_mask = alpha_mask & ~screen_hue_mask & saturation_mask
                    
                    s_adjusted = s.copy()
                    s_adjusted[boost_mask] = np.clip(s[boost_mask] * saturation_multiplier, 0, 1)
                else:
                    # BEFORE ANIMATION: Apply to all opaque pixels
                    s_adjusted = s.copy()
                    s_adjusted[alpha_mask] = np.clip(s[alpha_mask] * saturation_multiplier, 0, 1)
                
                r, g, b = np.vectorize(hsv_to_rgb)(h, s_adjusted, v)
                rgb_adjusted = np.dstack([r, g, b]) * 255
                rgb_adjusted = np.clip(rgb_adjusted, 0, 255).astype(np.uint8)
                img_adjusted = Image.fromarray(rgb_adjusted, 'RGB')
                img_adjusted.putalpha(Image.fromarray(alpha))
                img_adjusted.save(frame_path)
            except Exception as e:
                print(f"   ⚠️ Saturation restore failed on {frame_file}: {e}")
        
        print("-> Step 3: Encoding to transparent WebM...")
        fps_int = int(round(original_fps)) if original_fps else 24
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-framerate', str(fps_int),
            '-i', os.path.join(temp_frame_dir, 'frame_%05d.png'),
            '-c:v', 'libvpx-vp9',
            '-pix_fmt', 'yuva420p',
            '-auto-alt-ref', '0',
            '-crf', '4',
            '-b:v', '0',
            output_path
        ]
        
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"   ✅ Successfully created transparent video at {output_path}")

    finally:
        # KEEP PNG FRAMES for video editor! Don't delete them.
        # The PNG sequence is needed for perfect transparency when applying effects
        if not skip_encoding:
            print(f"-> ✅ PNG frames saved at: {temp_frame_dir} (kept for video editor)")
            # DO NOT DELETE: These frames are needed for video effects with perfect alpha
            # shutil.rmtree(temp_frame_dir)  # DISABLED - keep frames for editor
        else:
            print(f"-> ✅ PNG frames ready at: {temp_frame_dir} (skip_encoding mode)")

def stitch_videos_with_ffmpeg(video_paths, output_path, target_resolution=None):
    """
    Stitches two videos together using a simple, reliable approach.
    Uses concat protocol for maximum reliability and speed.
    """
    print(f"-> Stitching videos: {video_paths}")
    
    # Create temporary file list for concat protocol (most reliable method)
    import tempfile
    
    try:
        # Create a temporary file list for ffmpeg concat
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for video_path in video_paths:
                # Ensure paths are absolute and escape special characters
                abs_path = os.path.abspath(video_path).replace("'", "\\'")
                f.write(f"file '{abs_path}'\n")
            concat_file = f.name
        
        print(f"   ...created concat file: {concat_file}")
        
        # Use simple concat protocol - fastest and most reliable
        ffmpeg_cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file,
            '-c', 'copy',  # Copy streams without re-encoding (fastest)
            '-avoid_negative_ts', 'make_zero',  # Handle timing issues
            '-y',
            output_path
        ]
        
        print("   ...running ffmpeg concat command")
        print(f"   ...command: {' '.join(ffmpeg_cmd)}")
        
        # Much shorter timeout - stitching should be very fast with copy mode
        process = None
        try:
            process = subprocess.run(
                ffmpeg_cmd, 
                check=True, 
                capture_output=True, 
                text=True, 
                timeout=60  # 1 minute max - copy mode should be under 10 seconds
            )
            print(f"   ...successfully stitched video to {output_path}")
        except subprocess.TimeoutExpired as e:
            print("   ...FFMPEG CONCAT TIMED OUT after 1 minute.")
            # Kill the process if it's still running
            if e.child_process and e.child_process.poll() is None:
                try:
                    e.child_process.kill()
                    e.child_process.wait(timeout=5)
                except:
                    pass
            # Try fallback method with re-encoding
            return _fallback_stitch_with_reencoding(video_paths, output_path)
        
    except subprocess.CalledProcessError as e:
        print("   ...FFMPEG CONCAT FAILED. Trying fallback method...")
        print(f"   ...stderr: {e.stderr}")
        # Try fallback method with re-encoding
        return _fallback_stitch_with_reencoding(video_paths, output_path)
        
    except Exception as e:
        print(f"   ...unexpected error: {e}")
        return _fallback_stitch_with_reencoding(video_paths, output_path)
        
    finally:
        # Clean up temp file
        try:
            if 'concat_file' in locals():
                os.unlink(concat_file)
        except:
            pass

def _fallback_stitch_with_reencoding(video_paths, output_path):
    """
    Fallback method that re-encodes videos to ensure compatibility.
    Used when the fast copy method fails.
    """
    print("   ...using fallback re-encoding method")
    
    # Simple filter_complex with re-encoding - more compatible but slower
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', video_paths[0],
        '-i', video_paths[1],
        '-filter_complex', '[0:v][1:v]concat=n=2:v=1[v]',  # Simple concat, no audio
        '-map', '[v]',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',  # Fastest encoding preset
        '-crf', '23',           # Reasonable quality for fallback
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        '-y',
        output_path
    ]
    
    try:
        print("   ...running fallback ffmpeg command")
        result = subprocess.run(
            ffmpeg_cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=120  # 2 minutes for re-encoding
        )
        print(f"   ...fallback method succeeded: {output_path}")
        
    except subprocess.TimeoutExpired as e:
        print("   ...FALLBACK ALSO TIMED OUT after 2 minutes.")
        # Kill the process if it's still running
        if e.child_process and e.child_process.poll() is None:
            try:
                e.child_process.kill()
                e.child_process.wait(timeout=5)
            except:
                pass
        raise Exception("Video stitching failed - both concat and re-encoding methods timed out")
        
    except subprocess.CalledProcessError as e:
        print("   ...FALLBACK ALSO FAILED.")
        print(f"   ...stderr: {e.stderr}")
        raise Exception(f"Video stitching failed completely: {e.stderr}")