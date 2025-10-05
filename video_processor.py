import cv2
import numpy as np
import os
import shutil
import subprocess
import tempfile

def process_single_frame(frame, lower_green, upper_green, erode_amount, dilate_amount, blur_amount, spill_amount):
    """
    Applies chroma keying and returns a single, transparent 4-channel BGRA frame.
    """
    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv_frame, np.array(lower_green), np.array(upper_green))
    
    # Handle erode (positive = erode, negative = dilate)
    if erode_amount > 0:
        erode_kernel = np.ones((erode_amount, erode_amount), np.uint8)
        mask = cv2.erode(mask, erode_kernel, iterations=1)
    elif erode_amount < 0:
        # Negative erode means dilate
        dilate_kernel = np.ones((abs(erode_amount), abs(erode_amount)), np.uint8)
        mask = cv2.dilate(mask, dilate_kernel, iterations=1)
        
    # Handle dilate (positive = dilate, negative = erode)
    if dilate_amount > 0:
        dilate_kernel = np.ones((dilate_amount, dilate_amount), np.uint8)
        mask = cv2.dilate(mask, dilate_kernel, iterations=1)
    elif dilate_amount < 0:
        # Negative dilate means erode
        erode_kernel = np.ones((abs(dilate_amount), abs(dilate_amount)), np.uint8)
        mask = cv2.erode(mask, erode_kernel, iterations=1)

    if blur_amount > 0:
        blur_amount = blur_amount if blur_amount % 2 != 0 else blur_amount + 1
        mask = cv2.GaussianBlur(mask, (blur_amount, blur_amount), 0)
        
    inverted_mask = cv2.bitwise_not(mask)
    
    spill_map = cv2.dilate(mask, np.ones((3,3), np.uint8), iterations=spill_amount)
    spill_map = cv2.GaussianBlur(spill_map, (5,5), 0)
    
    frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    frame_desaturated = cv2.cvtColor(frame_gray, cv2.COLOR_GRAY2BGR)
    
    spill_map_normalized = spill_map / 255.0
    spill_map_3d = np.stack([spill_map_normalized]*3, axis=-1)
    
    frame_despilled = (frame * (1 - spill_map_3d) + frame_desaturated * spill_map_3d).astype(np.uint8)
    
    b, g, r = cv2.split(frame_despilled)
    bgra_frame = cv2.merge([b, g, r, inverted_mask])
    
    return bgra_frame

def process_video_with_opencv(video_path, output_path, lower_green, upper_green, erode_amount, dilate_amount, blur_amount, spill_amount):
    """
    Processes a video using a manual ffmpeg pipeline. Audio is ignored.
    """
    temp_frame_dir = "temp_frames"
    if os.path.exists(temp_frame_dir):
        shutil.rmtree(temp_frame_dir)
    os.makedirs(temp_frame_dir)

    try:
        print("-> Step 1: Extracting and processing frames...")
        video_capture = cv2.VideoCapture(video_path)
        original_fps = video_capture.get(cv2.CAP_PROP_FPS)
        frame_count = 0
        while True:
            success, frame = video_capture.read()
            if not success:
                break
            
            bgra_frame = process_single_frame(frame, lower_green, upper_green, erode_amount, dilate_amount, blur_amount, spill_amount)
            frame_filename = os.path.join(temp_frame_dir, f"frame_{frame_count:05d}.png")
            cv2.imwrite(frame_filename, bgra_frame)
            frame_count += 1
            
        video_capture.release()
        print(f"   ...processed and saved {frame_count} frames.")

        print("-> Step 2: Compiling transparent video with ffmpeg...")
        ffmpeg_cmd = [
            'ffmpeg',
            '-framerate', str(original_fps),
            '-i', os.path.join(temp_frame_dir, 'frame_%05d.png'), # <--- FIX
            '-c:v', 'libvpx-vp9',
            '-pix_fmt', 'yuva420p',
            '-crf', '10',
            '-b:v', '0',
            '-y',
            output_path
        ]
        
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"   ...successfully created transparent video at {output_path}")

    finally:
        print("-> Step 3: Cleaning up temporary frame files...")
        if os.path.exists(temp_frame_dir):
            shutil.rmtree(temp_frame_dir)
        print("   ...done.")

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
        result = subprocess.run(
            ffmpeg_cmd, 
            check=True, 
            capture_output=True, 
            text=True, 
            timeout=60  # 1 minute max - copy mode should be under 10 seconds
        )
        
        print(f"   ...successfully stitched video to {output_path}")
        
    except subprocess.TimeoutExpired:
        print("   ...FFMPEG CONCAT TIMED OUT after 1 minute.")
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
        
    except subprocess.TimeoutExpired:
        print("   ...FALLBACK ALSO TIMED OUT after 2 minutes.")
        raise Exception("Video stitching failed - both concat and re-encoding methods timed out")
        
    except subprocess.CalledProcessError as e:
        print("   ...FALLBACK ALSO FAILED.")
        print(f"   ...stderr: {e.stderr}")
        raise Exception(f"Video stitching failed completely: {e.stderr}")