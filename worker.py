import sqlite3
import time
import json
import os
import requests
import replicate
from PIL import Image
import io
import uuid
import shutil
import base64
import traceback
import subprocess
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from replicate.exceptions import ReplicateError
from dotenv import load_dotenv
from openai import OpenAI

from video_processor import process_video_with_opencv, stitch_videos_with_ffmpeg
from s3_storage import storage, upload_file, save_uploaded_file, get_public_url, is_s3_enabled, download_file
import cv2
import numpy as np
from PIL import ImageChops, ImageEnhance, ImageFilter
import gc

# Optional: Memory monitoring (graceful degradation if psutil not available)
try:
    import psutil
    MEMORY_MONITORING_AVAILABLE = True
except ImportError:
    MEMORY_MONITORING_AVAILABLE = False
    print("⚠️ psutil not available - memory monitoring disabled")

# --- CONFIGURATION ---
load_dotenv()
LEONARDO_API_KEY = os.environ.get("LEONARDO_API_KEY")
REPLICATE_API_KEY = os.environ.get("REPLICATE_API_KEY")

# --- MEMORY MONITORING UTILITIES ---
def get_memory_usage():
    """Get current memory usage in MB (returns None if psutil unavailable)"""
    if not MEMORY_MONITORING_AVAILABLE:
        return None
    try:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        return {
            'rss_mb': mem_info.rss / 1024 / 1024,
            'vms_mb': mem_info.vms / 1024 / 1024,
        }
    except:
        return None

def log_memory(job_id, context=""):
    """Log current memory usage with context (safe if monitoring unavailable)"""
    mem = get_memory_usage()
    if mem:
        print(f"   JOB #{job_id}: 💾 Memory: {mem['rss_mb']:.1f} MB RSS {context}")
    return mem

def clear_memory():
    """Force garbage collection to free memory"""
    gc.collect()
    gc.collect()  # Call twice for thorough cleanup
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Parallel processing configuration
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "3"))  # Process up to 3 jobs simultaneously
print(f"Worker: Configured for {MAX_CONCURRENT_JOBS} concurrent jobs")

# Set REPLICATE_API_TOKEN for the replicate library
if REPLICATE_API_KEY:
    os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_KEY
    print(f"Worker: Replicate API key loaded: {REPLICATE_API_KEY[:10]}...")
else:
    print("Worker: No Replicate API key found in environment")

try:
    openai_client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        organization=os.environ.get("OPENAI_ORG_ID"),
    )
    print("Worker: OpenAI client initialized successfully.")
except Exception as e:
    openai_client = None
    print(f"Worker: OpenAI client could not be initialized: {e}")

# --- DETERMINE DATA DIRECTORY ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RENDER_PERSISTENT_DISK = '/opt/render/project/src/data'

if os.path.exists(RENDER_PERSISTENT_DISK):
    # Running on Render.com with persistent disk
    DATA_DIR = RENDER_PERSISTENT_DISK
    STATIC_FOLDER = os.path.join(DATA_DIR, 'static')
    DATABASE_PATH = os.path.join(DATA_DIR, 'jobs.db')
    print(f"☁️ Worker: Using Render persistent disk")
    print(f"📁 Worker: Data directory: {DATA_DIR}")
else:
    # Running in development mode or standalone
    DATA_DIR = BASE_DIR
    STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
    DATABASE_PATH = 'jobs.db'
    print(f"📁 Worker: Data directory: {BASE_DIR}")

LIBRARY_FOLDER = os.path.join(STATIC_FOLDER, 'library')
ANIMATIONS_FOLDER_GENERATED = os.path.join(STATIC_FOLDER, 'animations', 'generated')
UPLOADS_FOLDER = os.path.join(STATIC_FOLDER, 'uploads')
TRANSPARENT_VIDEOS_FOLDER = os.path.join(STATIC_FOLDER, 'library', 'transparent_videos')
os.makedirs(TRANSPARENT_VIDEOS_FOLDER, exist_ok=True)

# --- TEXTURE FOLDERS FOR STICKER EFFECT ---
TEXTURE_DISPLACEMENT_FOLDER = os.path.join(STATIC_FOLDER, 'textures', 'displacement')
TEXTURE_SCREEN_FOLDER = os.path.join(STATIC_FOLDER, 'textures', 'screen')
os.makedirs(TEXTURE_DISPLACEMENT_FOLDER, exist_ok=True)
os.makedirs(TEXTURE_SCREEN_FOLDER, exist_ok=True)

# --- STICKER EFFECT FUNCTIONS ---
def load_texture_sequence(folder_path):
    """Load all PNG files from a texture folder and return them sorted."""
    try:
        files = sorted([f for f in os.listdir(folder_path) if f.lower().endswith('.png')])
        if not files:
            print(f"   ⚠️ No PNG files found in {folder_path}")
            return []
        textures = []
        for file in files:
            filepath = os.path.join(folder_path, file)
            textures.append(Image.open(filepath).convert('RGBA'))
        print(f"   ✅ Loaded {len(textures)} textures from {os.path.basename(folder_path)}/")
        return textures
    except Exception as e:
        print(f"   ❌ Error loading textures from {folder_path}: {e}")
        return []

def blend_multiply(base, overlay, opacity=1.0):
    """Multiply blend mode with clipping mask (like Photoshop/After Effects)."""
    try:
        # STEP 1: Save original alpha FIRST
        original_alpha = base.split()[3]
        alpha_array = np.array(original_alpha)
        
        # STEP 2: Convert to numpy arrays
        base_array = np.array(base)
        overlay_array = np.array(overlay)
        
        # STEP 3: Create alpha mask (3D for RGB masking)
        alpha_mask = (alpha_array > 0).astype(float)
        alpha_mask_3d = np.stack([alpha_mask, alpha_mask, alpha_mask], axis=2)
        
        # STEP 4: Apply texture ONLY where alpha > 0 (clipping mask)
        base_rgb = base_array[:, :, :3].astype(float) / 255.0
        overlay_rgb = overlay_array[:, :, :3].astype(float) / 255.0
        
        # Multiply formula: base * overlay
        result_rgb = base_rgb * overlay_rgb
        
        # Apply opacity
        if opacity < 1.0:
            result_rgb = result_rgb * opacity + base_rgb * (1 - opacity)
        
        # STEP 5: Apply alpha mask - effect ONLY on non-transparent pixels
        result_rgb = result_rgb * alpha_mask_3d + (base_rgb * (1 - alpha_mask_3d))
        
        # Convert back to uint8
        result_array = np.zeros_like(base_array)
        result_array[:, :, :3] = (result_rgb * 255).astype(np.uint8)
        result_array[:, :, 3] = alpha_array  # CRITICAL: Restore original alpha
        
        return Image.fromarray(result_array, 'RGBA')
    except Exception as e:
        print(f"Multiply blend error: {e}")
        return base

def blend_add(base, overlay, opacity=1.0):
    """Add blend mode with clipping mask (like Photoshop/After Effects)."""
    try:
        # STEP 1: Save original alpha FIRST
        original_alpha = base.split()[3]
        alpha_array = np.array(original_alpha)
        
        # STEP 2: Convert to numpy arrays
        base_array = np.array(base)
        overlay_array = np.array(overlay)
        
        # STEP 3: Create alpha mask (3D for RGB masking)
        alpha_mask = (alpha_array > 0).astype(float)
        alpha_mask_3d = np.stack([alpha_mask, alpha_mask, alpha_mask], axis=2)
        
        # STEP 4: Apply texture ONLY where alpha > 0 (clipping mask)
        base_rgb = base_array[:, :, :3].astype(float) / 255.0
        overlay_rgb = overlay_array[:, :, :3].astype(float) / 255.0
        
        # Add (Linear Dodge) formula: base + overlay (clamped to 1.0)
        result_rgb = np.clip(base_rgb + overlay_rgb, 0, 1.0)
        
        # Apply opacity
        if opacity < 1.0:
            result_rgb = result_rgb * opacity + base_rgb * (1 - opacity)
        
        # STEP 5: Apply alpha mask - effect ONLY on non-transparent pixels
        result_rgb = result_rgb * alpha_mask_3d + (base_rgb * (1 - alpha_mask_3d))
        
        # Convert back to uint8
        result_array = np.zeros_like(base_array)
        result_array[:, :, :3] = (result_rgb * 255).astype(np.uint8)
        result_array[:, :, 3] = alpha_array  # CRITICAL: Restore original alpha
        
        return Image.fromarray(result_array, 'RGBA')
    except Exception as e:
        print(f"Add blend error: {e}")
        return base

def apply_displacement(image, displacement_map, intensity=5):
    """Warp image using displacement map."""
    try:
        # Convert to numpy arrays
        img_array = np.array(image)
        h, w = img_array.shape[:2]
        
        # Resize displacement map to match image size
        disp_map = displacement_map.resize((w, h), Image.Resampling.BILINEAR).convert('L')
        disp_array = np.array(disp_map).astype(float) / 255.0  # Normalize to 0-1
        
        # Create displacement vectors (center at 0.5, scale by intensity)
        disp_x = (disp_array - 0.5) * intensity
        disp_y = (disp_array - 0.5) * intensity
        
        # Create mesh grid for remapping
        map_x, map_y = np.meshgrid(np.arange(w), np.arange(h))
        map_x = (map_x + disp_x).astype(np.float32)
        map_y = (map_y + disp_y).astype(np.float32)
        
        # Remap the image
        warped = cv2.remap(img_array, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        
        return Image.fromarray(warped, 'RGBA')
    except Exception as e:
        print(f"   ⚠️ Displacement failed: {e}, returning original")
        return image

def apply_surface_bevel(image, depth=3, highlight=0.5, shadow=0.5):
    """Apply bevel & emboss effect using After Effects-style relief map (Overlay blend)."""
    try:
        # Convert to grayscale for relief calculation
        gray = image.convert('L')
        gray_array = np.array(gray, dtype=np.float32)
        
        # Create emboss kernel (relief map)
        kernel_size = max(3, depth)
        if kernel_size % 2 == 0:
            kernel_size += 1
        
        # Sobel filters for X and Y gradients
        grad_x = cv2.Sobel(gray_array, cv2.CV_32F, 1, 0, ksize=kernel_size)
        grad_y = cv2.Sobel(gray_array, cv2.CV_32F, 0, 1, ksize=kernel_size)
        
        # Combine gradients to create relief map
        relief = grad_x * highlight - grad_y * shadow
        relief = relief + 128  # Shift to mid-gray (neutral for Overlay)
        relief = np.clip(relief, 0, 255).astype(np.uint8)
        
        # Create relief RGB image
        relief_rgb = np.stack([relief, relief, relief], axis=2)
        relief_img = Image.fromarray(relief_rgb, 'RGB')
        
        # Apply Overlay blend mode
        base_rgb = np.array(image.convert('RGB')).astype(float) / 255.0
        overlay_rgb = np.array(relief_img).astype(float) / 255.0
        
        # Overlay formula: base < 0.5 ? 2*base*overlay : 1 - 2*(1-base)*(1-overlay)
        result_rgb = np.where(
            base_rgb < 0.5,
            2 * base_rgb * overlay_rgb,
            1 - 2 * (1 - base_rgb) * (1 - overlay_rgb)
        )
        result_rgb = (result_rgb * 255).astype(np.uint8)
        
        # Restore alpha
        result = Image.fromarray(result_rgb, 'RGB').convert('RGBA')
        result.putalpha(image.split()[3])
        return result
    except Exception as e:
        print(f"   ⚠️ Surface bevel failed: {e}, returning original")
        return image

def apply_alpha_bevel(image, size=15, blur=2, angle=70, highlight_intensity=0.6, shadow_intensity=0.6):
    """Apply bevel effect to the alpha channel boundaries."""
    try:
        # Get the current alpha channel
        alpha = image.split()[3]
        alpha_array = np.array(alpha, dtype=np.float32)
        
        # Calculate gradients (edge normals) of the alpha channel
        kernel_size = min(size, 31)
        if kernel_size % 2 == 0:
            kernel_size += 1  # Must be odd
        gradient_x = cv2.Sobel(alpha_array, cv2.CV_32F, 1, 0, ksize=min(kernel_size, 31))
        gradient_y = cv2.Sobel(alpha_array, cv2.CV_32F, 0, 1, ksize=min(kernel_size, 31))
        
        # Calculate the angle of each edge normal (in radians)
        edge_angles = np.arctan2(gradient_y, gradient_x)
        
        # Convert light angle from degrees to radians
        light_angle_rad = np.deg2rad(angle)
        
        # Calculate how aligned each edge is with the light direction
        angle_diff = edge_angles - light_angle_rad
        alignment = np.cos(angle_diff)
        
        # Calculate edge magnitude (strength)
        edge_magnitude = np.sqrt(gradient_x**2 + gradient_y**2)
        edge_magnitude = edge_magnitude / (edge_magnitude.max() + 1e-8)  # Normalize
        
        # Separate highlights and shadows with different intensities
        highlight_mask = np.maximum(0, alignment) * edge_magnitude * highlight_intensity
        shadow_mask = np.maximum(0, -alignment) * edge_magnitude * shadow_intensity
        
        # Blur the effect to create smooth bevels
        if blur > 0:
            blur_kernel = blur * 2 + 1
            if blur_kernel % 2 == 0:
                blur_kernel += 1
            highlight_mask = cv2.GaussianBlur(highlight_mask, (blur_kernel, blur_kernel), 0)
            shadow_mask = cv2.GaussianBlur(shadow_mask, (blur_kernel, blur_kernel), 0)
        
        # Apply the bevel effect to the image
        result_array = np.array(image)
        original_alpha = alpha_array.astype(np.uint8)
        
        # Apply highlights and shadows to RGB channels separately
        for c in range(3):  # RGB channels
            # Brighten with highlights
            result_array[:, :, c] = np.clip(
                result_array[:, :, c].astype(np.float32) + highlight_mask * 255,
                0, 255
            ).astype(np.uint8)
            
            # Darken with shadows
            result_array[:, :, c] = np.clip(
                result_array[:, :, c].astype(np.float32) - shadow_mask * 255,
                0, 255
            ).astype(np.uint8)
        
        # Keep the original alpha unchanged
        result_array[:, :, 3] = original_alpha
        
        return Image.fromarray(result_array, 'RGBA')
    except Exception as e:
        print(f"   ⚠️ Alpha bevel failed: {e}, returning original")
        return image

def apply_page_fold(image, fold_position=0.3, fold_angle=45, shadow_intensity=0.5, back_color=(180, 180, 180), return_steps=False):
    """
    Apply page fold effect - step-by-step process matching After Effects.
    
    Args:
        image: PIL Image with RGBA
        fold_position: Where diagonal fold line starts (0.0-1.0 from bottom-right corner)
        fold_angle: Angle of the fold line in degrees (0=horizontal, 45=diagonal, 90=vertical)
        shadow_intensity: Shadow darkness at fold (0.0-1.0)
        back_color: RGB color for back of page (default: gray)
        return_steps: If True, returns dict with all intermediate steps
    
    Returns:
        PIL Image with page fold effect applied (or dict if return_steps=True)
    """
    try:
        img_array = np.array(image)
        h, w = img_array.shape[:2]
        
        print(f"   📄 STEP-BY-STEP PAGE FOLD")
        print(f"   🔧 Image size: {w}x{h}, fold_position={fold_position}, fold_angle={fold_angle}°")
        
        fold_distance = int(min(w, h) * fold_position)
        
        # Convert angle to radians and calculate fold line direction
        angle_rad = np.deg2rad(fold_angle)
        
        # Store intermediate steps if requested
        steps = {} if return_steps else None
        
        # STEP 01: Cut the image along angled line from corner
        print(f"   ✂️ STEP 01: Cutting image at {fold_angle}° angle (fold_distance={fold_distance})")
        
        # Create mask for fold region (angled line from bottom-right corner)
        # For angle θ: the fold line equation is dx*sin(θ) + dy*cos(θ) < fold_distance
        # where dx, dy are distances from bottom-right corner
        fold_mask = np.zeros((h, w), dtype=bool)
        for y in range(h):
            for x in range(w):
                corner_dist_x = w - x
                corner_dist_y = h - y
                
                # Calculate perpendicular distance to angled fold line
                # At 0°: horizontal cut (only dy matters)
                # At 45°: diagonal cut (dx + dy matters)
                # At 90°: vertical cut (only dx matters)
                dist_to_fold = corner_dist_x * np.sin(angle_rad) + corner_dist_y * np.cos(angle_rad)
                fold_mask[y, x] = dist_to_fold < fold_distance
        
        # Layer 1: Front (everything except fold area)
        front_layer = img_array.copy()
        front_layer[fold_mask] = [0, 0, 0, 0]
        
        # Layer 2: Cut piece (the fold area) - moved to the side for visualization
        cut_piece = np.zeros_like(img_array)
        cut_piece[fold_mask] = img_array[fold_mask]
        
        if return_steps:
            # Show front and cut piece side by side for step 01
            step01_visual = front_layer.copy()
            steps['step_01_cut'] = Image.fromarray(step01_visual, 'RGBA')
            steps['step_01_cut_piece'] = Image.fromarray(cut_piece, 'RGBA')
        
        # STEP 02: Create smooth gradient curl (pure gradient approach like AE)
        print(f"   🔄 STEP 02: Creating gradient-based curved corner curl")
        
        # Create result with smooth gradient over entire curl region
        flipped_piece = np.zeros_like(img_array)
        
        corner_x = float(w)
        corner_y = float(h)
        curl_radius = fold_distance
        
        # For each pixel in the curl region, apply gradient shading
        for y in range(h):
            for x in range(w):
                corner_dist_x = corner_x - x
                corner_dist_y = corner_y - y
                
                # Perpendicular distance to the fold line (angled)
                dist_to_fold = corner_dist_x * np.sin(angle_rad) + corner_dist_y * np.cos(angle_rad)
                
                if dist_to_fold > 0 and dist_to_fold < curl_radius:
                    # Calculate gradient progress (0 = at corner/darkest, 1 = at fold/lightest)
                    progress = dist_to_fold / curl_radius
                    
                    # Create smooth gradient using ease-in-out curve
                    # This simulates 3D lighting on a curved surface
                    gradient_value = 0.5 + 0.5 * np.sin((progress - 0.5) * np.pi)
                    
                    # Blend between back color (dark) and lighter shade
                    # Dark at corner (shadow), light at fold line (highlight)
                    min_brightness = 0.4  # Darkest point
                    max_brightness = 0.9  # Lightest point
                    brightness = min_brightness + (max_brightness - min_brightness) * gradient_value
                    
                    # Apply to back color
                    back_r = int(back_color[0] * brightness)
                    back_g = int(back_color[1] * brightness)
                    back_b = int(back_color[2] * brightness)
                    
                    flipped_piece[y, x] = [back_r, back_g, back_b, 255]
        
        pixel_count = np.sum(flipped_piece[:, :, 3] > 0)
        print(f"   🔧 Created gradient curl with {pixel_count} pixels (radius={curl_radius})")
        
        if return_steps:
            steps['step_02_flipped'] = Image.fromarray(flipped_piece, 'RGBA')
        
        # STEP 03: Color the flipped piece (apply back color)
        print(f"   🎨 STEP 03: Applying back color to flipped piece")
        
        colored_piece = flipped_piece.copy()
        for y in range(h):
            for x in range(w):
                if colored_piece[y, x, 3] > 0:
                    # Mix original color with back color
                    tint = 0.5  # 50% back color
                    colored_piece[y, x, :3] = (
                        colored_piece[y, x, :3] * (1 - tint) + 
                        np.array(back_color) * tint
                    ).astype(np.uint8)
        
        if return_steps:
            steps['step_03_colored'] = Image.fromarray(colored_piece, 'RGBA')
        
        # STEP 04: Keep flipped piece in same location (no repositioning needed)
        print(f"   📍 STEP 04: Flipped piece positioned in place")
        positioned_piece = colored_piece.copy()
        
        if return_steps:
            # Composite with front for step 04
            step04_composite = front_layer.copy()
            mask = positioned_piece[:, :, 3] > 0
            step04_composite[mask] = positioned_piece[mask]
            steps['step_04_positioned'] = Image.fromarray(step04_composite, 'RGBA')
        
        # STEP 05: Add highlight (lighter on the outer edge)
        print(f"   ✨ STEP 05: Adding highlight to folded edge")
        
        # Calculate angle for proper distance
        angle_rad = np.deg2rad(fold_angle)
        
        for y in range(h):
            for x in range(w):
                if positioned_piece[y, x, 3] > 0:
                    corner_dist_x = w - x
                    corner_dist_y = h - y
                    
                    # Distance from fold line (perpendicular)
                    dist_to_fold = corner_dist_x * np.sin(angle_rad) + corner_dist_y * np.cos(angle_rad)
                    
                    if dist_to_fold < fold_distance:
                        # Normalize distance (0 at fold line, 1 at edge)
                        progress = dist_to_fold / fold_distance
                        
                        # Add white highlight on outer edge (progress close to 1)
                        if progress > 0.6:
                            highlight_factor = (progress - 0.6) / 0.4  # 0 to 1
                            highlight_amount = highlight_factor * 50
                            positioned_piece[y, x, :3] = np.clip(
                                positioned_piece[y, x, :3] + highlight_amount,
                                0, 255
                            ).astype(np.uint8)
        
        if return_steps:
            # Composite with front for step 05
            step05_composite = front_layer.copy()
            mask = positioned_piece[:, :, 3] > 0
            step05_composite[mask] = positioned_piece[mask]
            steps['step_05_highlight'] = Image.fromarray(step05_composite, 'RGBA')
        
        # STEP 06: Add shadow (darker near the fold line)
        print(f"   🌑 STEP 06: Adding shadow gradient")
        
        for y in range(h):
            for x in range(w):
                if positioned_piece[y, x, 3] > 0:
                    corner_dist_x = w - x
                    corner_dist_y = h - y
                    
                    # Distance from fold line
                    dist_to_fold = corner_dist_x * np.sin(angle_rad) + corner_dist_y * np.cos(angle_rad)
                    
                    if dist_to_fold < fold_distance:
                        # Normalize distance (0 at fold line, 1 at edge)
                        progress = dist_to_fold / fold_distance
                        
                        # Add shadow near fold line (progress close to 0)
                        if progress < 0.4:
                            shadow_factor = 1 - (progress / 0.4)  # 1 at fold line, 0 at 0.4
                            shadow_amount = shadow_factor * shadow_intensity * 0.6
                            positioned_piece[y, x, :3] = (
                                positioned_piece[y, x, :3] * (1 - shadow_amount)
                            ).astype(np.uint8)
        
        # Add shadow on the front layer near fold line
        front_with_shadow = front_layer.copy()
        for y in range(h):
            for x in range(w):
                if front_with_shadow[y, x, 3] > 0:
                    corner_dist_x = w - x
                    corner_dist_y = h - y
                    dist_to_fold = abs((corner_dist_x * np.sin(angle_rad) + corner_dist_y * np.cos(angle_rad)) - fold_distance)
                    shadow_width = fold_distance * 0.1
                    
                    if dist_to_fold < shadow_width:
                        shadow_amount = (1 - dist_to_fold / shadow_width) * shadow_intensity * 0.3
                        front_with_shadow[y, x, :3] = (
                            front_with_shadow[y, x, :3] * (1 - shadow_amount)
                        ).astype(np.uint8)
        
        # FINAL: Composite the layers
        print(f"   🎬 FINAL: Compositing layers")
        result = front_with_shadow.copy()
        mask = positioned_piece[:, :, 3] > 0
        result[mask] = positioned_piece[mask]
        
        if return_steps:
            steps['step_06_final'] = Image.fromarray(result, 'RGBA')
        
        print(f"   ✅ Page fold complete!")
        
        if return_steps:
            return steps
        else:
            return Image.fromarray(result, 'RGBA')
        
    except Exception as e:
        print(f"   ⚠️ Page fold failed: {e}")
        import traceback
        traceback.print_exc()
        return image

def apply_drop_shadow(image, blur=10, offset_x=5, offset_y=5, opacity=0.5):
    """Apply drop shadow to image."""
    try:
        # Create shadow layer
        alpha = image.split()[3]
        shadow = Image.new('RGBA', image.size, (0, 0, 0, 0))
        shadow.putalpha(alpha)
        
        # Blur the shadow
        if blur > 0:
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur))
        
        # Adjust shadow opacity
        shadow_alpha = shadow.split()[3]
        shadow_alpha = ImageEnhance.Brightness(shadow_alpha).enhance(opacity)
        shadow.putalpha(shadow_alpha)
        
        # Create result image with shadow
        result = Image.new('RGBA', image.size, (0, 0, 0, 0))
        result.paste(shadow, (offset_x, offset_y), shadow)
        result.paste(image, (0, 0), image)
        
        return result
    except Exception as e:
        print(f"   ⚠️ Drop shadow failed: {e}, returning original")
        return image

def apply_peel_effect(frame_pil, peel_frame_pil):
    """
    Composite the 3D peel frame onto the current frame.
    The peel frame is pre-rendered at 8 FPS with transparency.
    """
    try:
        if not peel_frame_pil:
            return frame_pil
        
        # Ensure peel frame matches the size of the video frame
        if peel_frame_pil.size != frame_pil.size:
            peel_frame_pil = peel_frame_pil.resize(frame_pil.size, Image.LANCZOS)
        
        # Ensure both images have alpha
        if frame_pil.mode != 'RGBA':
            frame_pil = frame_pil.convert('RGBA')
        if peel_frame_pil.mode != 'RGBA':
            peel_frame_pil = peel_frame_pil.convert('RGBA')
        
        # Composite peel frame over the base frame using alpha
        result = Image.alpha_composite(frame_pil, peel_frame_pil)
        
        return result
    except Exception as e:
        print(f"   ⚠️ Peel effect compositing failed: {e}")
        traceback.print_exc()
        return frame_pil

def apply_sticker_effect_to_frame(frame_pil, disp_texture, screen_texture, 
                                   displacement_intensity=50, darker_opacity=1.0, screen_opacity=0.7,
                                   enable_bevel=False, bevel_depth=3, bevel_highlight=0.5, bevel_shadow=0.5,
                                   enable_alpha_bevel=False, alpha_bevel_size=15, alpha_bevel_blur=2, 
                                   alpha_bevel_angle=70, alpha_bevel_highlight=0.6, alpha_bevel_shadow=0.6,
                                   enable_page_fold=False, fold_position=0.8, fold_angle=30, fold_shadow_intensity=0.5,
                                   enable_shadow=False, shadow_blur=0, shadow_x=1, shadow_y=1, shadow_opacity=1.0,
                                   peel_frame=None):
    """Apply sticker effect to a single frame with all advanced effects."""
    try:
        # Resize textures to match frame size
        if disp_texture:
            disp_texture = disp_texture.resize(frame_pil.size, Image.LANCZOS)
        if screen_texture:
            screen_texture = screen_texture.resize(frame_pil.size, Image.LANCZOS)
        
        # Step 1: Apply displacement using displacement texture
        if disp_texture and displacement_intensity > 0:
            frame_pil = apply_displacement(frame_pil, disp_texture, displacement_intensity)
        
        # Step 2: Apply Multiply blend (shadows/creases) using displacement texture
        if disp_texture and darker_opacity > 0:
            frame_pil = blend_multiply(frame_pil, disp_texture, darker_opacity)
        
        # Step 3: Apply Add blend (highlights) using screen texture
        if screen_texture and screen_opacity > 0:
            frame_pil = blend_add(frame_pil, screen_texture, screen_opacity)
        
        # Step 4: Apply surface bevel & emboss (relief map) if enabled
        if enable_bevel:
            frame_pil = apply_surface_bevel(frame_pil, bevel_depth, bevel_highlight, bevel_shadow)
        
        # Step 5: Apply alpha bevel (edge effect) if enabled
        if enable_alpha_bevel:
            frame_pil = apply_alpha_bevel(frame_pil, alpha_bevel_size, alpha_bevel_blur, 
                                         alpha_bevel_angle, alpha_bevel_highlight, alpha_bevel_shadow)
        
        # Step 6: Apply 3D peel effect if provided (8 FPS pre-rendered frames)
        if peel_frame:
            frame_pil = apply_peel_effect(frame_pil, peel_frame)
        
        # Step 7: Apply page fold effect if enabled (deprecated - use peel effect instead)
        if enable_page_fold:
            frame_pil = apply_page_fold(frame_pil, fold_position, fold_angle, fold_shadow_intensity)
        
        # Step 8: Apply drop shadow if enabled
        if enable_shadow:
            frame_pil = apply_drop_shadow(frame_pil, shadow_blur, shadow_x, shadow_y, shadow_opacity)
        
        return frame_pil
    except Exception as e:
        print(f"   ⚠️ Sticker effect failed on frame: {e}")
        traceback.print_exc()
        return frame_pil

def apply_sticker_effect_to_video(input_video_path, output_video_path, 
                                   displacement_intensity=50, darker_opacity=1.0, screen_opacity=0.7,
                                   enable_bevel=False, bevel_depth=3, bevel_highlight=0.5, bevel_shadow=0.5,
                                   enable_alpha_bevel=False, alpha_bevel_size=15, alpha_bevel_blur=2, 
                                   alpha_bevel_angle=70, alpha_bevel_highlight=0.6, alpha_bevel_shadow=0.6,
                                   enable_page_fold=False, fold_position=0.8, fold_angle=30, fold_shadow_intensity=0.5,
                                   enable_shadow=False, shadow_blur=0, shadow_x=1, shadow_y=1, shadow_opacity=1.0,
                                   peel_frame_paths=None):
    """Apply sticker effect to entire video frame-by-frame with animated textures and all advanced effects."""
    try:
        print(f"   🎨 Applying sticker effect to video...")
        print(f"      Displacement: {displacement_intensity}, Multiply opacity: {darker_opacity}, Add opacity: {screen_opacity}")
        print(f"      Surface bevel: {enable_bevel}, Alpha bevel: {enable_alpha_bevel}, Page fold: {enable_page_fold}, Drop shadow: {enable_shadow}")
        
        # Load peel frames if provided (pre-rendered at 8 FPS)
        peel_frames = []
        if peel_frame_paths:
            print(f"      Loading {len(peel_frame_paths)} peel frames at 8 FPS...")
            for peel_path in peel_frame_paths:
                full_path = os.path.join(BASE_DIR, peel_path)
                if os.path.exists(full_path):
                    peel_frames.append(Image.open(full_path).convert('RGBA'))
                else:
                    print(f"      ⚠️ Peel frame not found: {full_path}")
            print(f"      ✅ Loaded {len(peel_frames)} peel frames")
        
        # Load texture sequences
        disp_textures = load_texture_sequence(TEXTURE_DISPLACEMENT_FOLDER)
        screen_textures = load_texture_sequence(TEXTURE_SCREEN_FOLDER)
        
        if not disp_textures and not screen_textures:
            print(f"   ⚠️ No textures found, skipping sticker effect")
            return input_video_path  # Return original if no textures
        
        # Use ffmpeg to extract frames with alpha channel preserved
        print(f"      Extracting frames from video with alpha channel...")
        temp_extract_dir = os.path.join(TRANSPARENT_VIDEOS_FOLDER, f"sticker_extract_{uuid.uuid4().hex[:8]}")
        os.makedirs(temp_extract_dir, exist_ok=True)
        
        # Extract frames as PNG with alpha (PNG automatically preserves alpha)
        extract_cmd = [
            'ffmpeg', '-y', '-i', input_video_path,
            os.path.join(temp_extract_dir, 'frame_%06d.png')
        ]
        result = subprocess.run(extract_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"   ❌ Frame extraction failed: {result.stderr}")
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            return input_video_path
        
        # Get frame files
        frame_files = sorted([f for f in os.listdir(temp_extract_dir) if f.endswith('.png')])
        if not frame_files:
            print(f"   ❌ No frames extracted")
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            return input_video_path
        
        # Get video properties from first frame
        first_frame = Image.open(os.path.join(temp_extract_dir, frame_files[0]))
        width, height = first_frame.size
        total_frames = len(frame_files)
        
        # Get FPS from original video
        probe_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
                     '-show_entries', 'stream=r_frame_rate', '-of', 'default=noprint_wrappers=1:nokey=1', 
                     input_video_path]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        fps = 30  # Default
        if probe_result.returncode == 0 and probe_result.stdout.strip():
            try:
                fps_parts = probe_result.stdout.strip().split('/')
                fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])
            except:
                pass
        
        print(f"      Video: {width}x{height} @ {fps}fps, {total_frames} frames")
        
        # Create temporary directory for processed frames
        temp_frames_dir = os.path.join(TRANSPARENT_VIDEOS_FOLDER, f"sticker_temp_{uuid.uuid4().hex[:8]}")
        os.makedirs(temp_frames_dir, exist_ok=True)
        
        frame_idx = 0
        for frame_file in frame_files:
            # Load frame with alpha
            frame_path = os.path.join(temp_extract_dir, frame_file)
            frame_pil = Image.open(frame_path).convert('RGBA')
            
            # Store original alpha before any processing
            original_alpha = frame_pil.split()[3]
            
            # Get textures for this frame (loop if textures are shorter than video)
            disp_texture = disp_textures[frame_idx % len(disp_textures)] if disp_textures else None
            screen_texture = screen_textures[frame_idx % len(screen_textures)] if screen_textures else None
            
            # Get peel frame for this video frame (8 FPS: each peel frame used for 3 video frames at 24 FPS)
            peel_frame = None
            if peel_frames:
                peel_frame_index = frame_idx // 3  # Integer division: 0,1,2->0, 3,4,5->1, etc.
                if peel_frame_index < len(peel_frames):
                    peel_frame = peel_frames[peel_frame_index]
            
            # Apply sticker effect with all parameters
            processed_frame = apply_sticker_effect_to_frame(
                frame_pil, disp_texture, screen_texture,
                displacement_intensity, darker_opacity, screen_opacity,
                enable_bevel, bevel_depth, bevel_highlight, bevel_shadow,
                enable_alpha_bevel, alpha_bevel_size, alpha_bevel_blur, 
                alpha_bevel_angle, alpha_bevel_highlight, alpha_bevel_shadow,
                enable_page_fold, fold_position, fold_angle, fold_shadow_intensity,
                enable_shadow, shadow_blur, shadow_x, shadow_y, shadow_opacity,
                peel_frame
            )
            
            # CRITICAL: Ensure original alpha is preserved exactly (no modifications to transparent areas)
            processed_frame.putalpha(original_alpha)
            
            # Zero out RGB values in fully transparent areas to prevent compression artifacts
            frame_array = np.array(processed_frame)
            alpha_array = np.array(original_alpha)
            # Where alpha is 0, set RGB to 0 (fully transparent black)
            mask = (alpha_array == 0)
            # Apply mask to each RGB channel separately
            frame_array[:, :, 0] = np.where(mask, 0, frame_array[:, :, 0])  # Red
            frame_array[:, :, 1] = np.where(mask, 0, frame_array[:, :, 1])  # Green
            frame_array[:, :, 2] = np.where(mask, 0, frame_array[:, :, 2])  # Blue
            processed_frame = Image.fromarray(frame_array, 'RGBA')
            
            # Save frame
            frame_path = os.path.join(temp_frames_dir, f"frame_{frame_idx:06d}.png")
            processed_frame.save(frame_path, 'PNG')
            
            frame_idx += 1
            if frame_idx % 10 == 0:
                print(f"      Processed {frame_idx}/{total_frames} frames...")
        
        print(f"   ✅ Processed all {frame_idx} frames")
        
        # Clean up extraction directory
        shutil.rmtree(temp_extract_dir, ignore_errors=True)
        
        # Re-encode video using FFmpeg with near-lossless quality and alpha preservation
        print(f"   🎬 Re-encoding video with FFmpeg (preserving alpha, CRF=4 for high quality)...")
        fps_int = int(round(fps)) if fps else 24  # Convert to integer for ffmpeg
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-framerate', str(fps_int),
            '-i', os.path.join(temp_frames_dir, 'frame_%06d.png'),
            '-c:v', 'libvpx-vp9',
            '-pix_fmt', 'yuva420p',
            '-crf', '4',  # Near-lossless quality (changed from 15)
            '-b:v', '0',
            output_video_path
        ]
        
        print(f"   📝 FFmpeg command: {' '.join(ffmpeg_cmd)}")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"   ❌ FFmpeg error: {result.stderr}")
            return input_video_path
        
        # Verify the output has alpha
        verify_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
                      '-show_entries', 'stream=pix_fmt', '-of', 'default=noprint_wrappers=1:nokey=1', 
                      output_video_path]
        verify_result = subprocess.run(verify_cmd, capture_output=True, text=True)
        output_pix_fmt = verify_result.stdout.strip()
        print(f"   🔍 Output pixel format: {output_pix_fmt}")
        if 'yuva' not in output_pix_fmt:
            print(f"   ⚠️ WARNING: Output video may not have alpha channel! Got {output_pix_fmt} instead of yuva420p")
        
        # Clean up temp frames
        shutil.rmtree(temp_frames_dir, ignore_errors=True)
        
        print(f"   ✅ Sticker effect video saved: {output_video_path}")
        return output_video_path
        
    except Exception as e:
        print(f"   ❌ Sticker effect failed: {e}")
        traceback.print_exc()
        return input_video_path  # Return original if processing fails

# --- IMAGE PREPROCESSING FOR BOOMERANG ---
def composite_on_green_screen(source_image_path):
    """
    Simple wrapper for image generation: composite onto green background.
    """
    return composite_on_green_screen_only(source_image_path, "green")

def composite_on_green_screen_only(source_image_path, background_color_str):
    """
    For boomerang: Composite PNG frames onto colored background WITHOUT desaturation.
    These are clean frames from video editor, not generated images.
    """
    try:
        # Handle both relative and absolute paths
        if source_image_path.startswith('/'):
            source_full_path = os.path.join(BASE_DIR, source_image_path.lstrip('/'))
        else:
            source_full_path = os.path.join(BASE_DIR, source_image_path)
        
        if not os.path.exists(source_full_path):
            print(f"   ...composite error: Source file not found at {source_full_path}")
            return source_image_path

        color_map = {"green": (0, 255, 0), "blue": (0, 0, 255)}
        background_color = color_map.get(background_color_str)
        if not background_color: 
            print(f"   ...using original image (unsupported background color: {background_color_str})")
            return source_image_path

        print(f"   ...compositing {os.path.basename(source_image_path)} onto {background_color_str} (no desaturation)")
        
        # Open and composite directly - NO saturation adjustment for boomerang
        with Image.open(source_full_path).convert("RGBA") as fg_image:
            bg_image = Image.new("RGBA", fg_image.size, background_color)
            # Scale down to 90% to add padding
            new_size = (int(fg_image.width * 0.9), int(fg_image.height * 0.9))
            fg_image_resized = fg_image.resize(new_size, Image.Resampling.LANCZOS)
            paste_position = ((bg_image.width - fg_image_resized.width) // 2, (bg_image.height - fg_image_resized.height) // 2)
            bg_image.paste(fg_image_resized, paste_position, fg_image_resized)
            
            output_filename = f"boomerang_composite_{uuid.uuid4()}.png"
            output_full_path = os.path.join(LIBRARY_FOLDER, output_filename)
            bg_image.convert("RGB").save(output_full_path, 'PNG')
            print(f"   ...saved composite to {output_full_path}")
            
            # Upload to S3 if enabled
            s3_key = f"library/{output_filename}"
            public_url = upload_file(output_full_path, s3_key)
            return public_url
            
    except Exception as e:
        print(f"   ...error during composite: {e}")
        traceback.print_exc()
        return source_image_path

def preprocess_animation_image_for_boomerang(source_image_path, background_color_str):
    """
    Preprocess images for boomerang automation:
    1. Apply saturation adjustment (like regular image generation)
    2. Composite onto colored background
    3. Use full-resolution original PNGs
    """
    try:
        # Handle both relative and absolute paths more safely
        if source_image_path.startswith('/'):
            source_full_path = os.path.join(BASE_DIR, source_image_path.lstrip('/'))
        else:
            source_full_path = os.path.join(BASE_DIR, source_image_path)
        
        if not os.path.exists(source_full_path):
            print(f"   ...preprocessing error: Source file not found at {source_full_path}")
            return source_image_path

        color_map = {"green": (0, 255, 0), "blue": (0, 0, 255)}
        background_color = color_map.get(background_color_str)
        if not background_color: 
            print(f"   ...using original image (unsupported background color: {background_color_str})")
            return source_image_path

        print(f"   ...preprocessing {source_image_path} with {background_color_str} background + saturation adjustment")
        
        # Create a temp copy for adjustments (preserve original)
        temp_adjusted_path = os.path.join(LIBRARY_FOLDER, f"temp_adjusted_{uuid.uuid4()}.png")
        shutil.copy2(source_full_path, temp_adjusted_path)
        
        # Apply saturation adjustment only (same as image generation - 0.4 multiplier, no hue shift)
        apply_saturation_adjustment(temp_adjusted_path, saturation_multiplier=0.4)
        
        # Now composite onto background
        with Image.open(temp_adjusted_path).convert("RGBA") as fg_image:
            bg_image = Image.new("RGBA", fg_image.size, background_color)
            new_size = (int(fg_image.width * 0.9), int(fg_image.height * 0.9))
            fg_image_resized = fg_image.resize(new_size, Image.Resampling.LANCZOS)
            paste_position = ((bg_image.width - fg_image_resized.width) // 2, (bg_image.height - fg_image_resized.height) // 2)
            bg_image.paste(fg_image_resized, paste_position, fg_image_resized)
            
            output_filename = f"boomerang_preprocessed_{uuid.uuid4()}.png"
            output_full_path = os.path.join(LIBRARY_FOLDER, output_filename)
            bg_image.convert("RGB").save(output_full_path, 'PNG')
            print(f"   ...saved preprocessed image with adjustments to {output_full_path}")
            
            # Clean up temp file
            try:
                os.remove(temp_adjusted_path)
            except:
                pass
            
            # Upload to S3 if enabled
            s3_key = f"library/{output_filename}"
            public_url = upload_file(output_full_path, s3_key)
            return public_url
            
    except Exception as e:
        print(f"   ...error during boomerang preprocessing: {e}")
        traceback.print_exc()
        return source_image_path

# --- DATABASE HELPER ---
def get_db_connection():
    """Creates a database connection with WAL mode enabled for high concurrency."""
    try:
        conn = sqlite3.connect(DATABASE_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")  # 30 second timeout for busy database
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        raise

def add_white_outline(image_path, outline_width=3):
    """
    Add a white outline around the subject in an image.
    Works best with transparent/semi-transparent PNGs.
    """
    try:
        from PIL import ImageFilter, ImageOps
        
        print(f"   ...adding {outline_width}px white outline to image")
        
        # Open image
        img = Image.open(image_path).convert("RGBA")
        
        # Extract alpha channel (transparency mask)
        alpha = img.split()[3]
        
        # Create outline by dilating the alpha mask
        outline = alpha.filter(ImageFilter.MaxFilter(outline_width * 2 + 1))
        
        # Create white outline layer
        outline_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
        outline_layer.putalpha(outline)
        
        # Create final image: white outline + original image
        result = Image.alpha_composite(outline_layer, img)
        
        # Save to temp file
        output_filename = f"outlined_{uuid.uuid4()}.png"
        output_path = os.path.join(LIBRARY_FOLDER, output_filename)
        result.save(output_path, 'PNG')
        
        print(f"   ...white outline applied, saved to {output_path}")
        
        # Upload to S3 if enabled
        s3_key = f"library/{output_filename}"
        public_url = upload_file(output_path, s3_key)
        return public_url
        
    except Exception as e:
        print(f"   ...warning: could not add white outline: {e}")
        traceback.print_exc()
        return image_path  # Return original if outline fails

# --- JOB HANDLERS ---
def handle_boomerang_automation(job, conn):
    print(f"-> Starting A-B-A Loop Automation for meta-job {job['id']}...")
    try:
        input_data = json.loads(job['input_data'])
        base_params = {key: value for key, value in input_data.items() if key != 'boomerang_automation'}
        
        # Preprocess both frames with consistent background for boomerang automation
        background_color = input_data.get('background', 'green')
        start_frame_url = input_data['image_url']
        end_frame_url = input_data['end_image_url']
        
        # Check if preprocessing should be skipped (frames already clean PNGs from editor)
        if input_data.get('skip_preprocessing'):
            print(f"   ...skipping Flask-side preprocessing, compositing only for boomerang frames")
            processed_start_url = composite_on_green_screen_only(start_frame_url, background_color)
            processed_end_url = composite_on_green_screen_only(end_frame_url, background_color)
        else:
            print(f"   ...preprocessing frames: desaturation + {background_color} background + scale down")
            processed_start_url = preprocess_animation_image_for_boomerang(start_frame_url, background_color)
            processed_end_url = preprocess_animation_image_for_boomerang(end_frame_url, background_color)
        
        print(f"   ...processed start frame: {processed_start_url}")
        print(f"   ...processed end frame: {processed_end_url}")
        
        # --- Create Job 1: A -> B ---
        input_data_ab = base_params.copy()
        input_data_ab['image_url'] = processed_start_url
        input_data_ab['end_image_url'] = processed_end_url
        prompt_ab = f"Animation A->B: {input_data_ab['prompt']}"
        conn.cursor().execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
            ('animation', 'queued', datetime.now(), prompt_ab, json.dumps(input_data_ab), job['id'])
        )
        print(f"   ...queued Job 1 (A->B)")
        
        # --- Create Job 2: B -> A ---
        input_data_ba = base_params.copy()
        input_data_ba['image_url'] = processed_end_url
        input_data_ba['end_image_url'] = processed_start_url
        prompt_ba = f"Animation B->A: {input_data_ba['prompt']}"
        conn.cursor().execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
            ('animation', 'queued', datetime.now(), prompt_ba, json.dumps(input_data_ba), job['id'])
        )
        print(f"   ...queued Job 2 (B->A)")

        conn.commit()
        return "waiting_for_children", None
    except Exception as e:
        print(f"Error in boomerang automation setup: {e}")
        traceback.print_exc()
        # Try to rollback the transaction
        try:
            conn.rollback()
        except Exception as rollback_error:
            print(f"Could not rollback transaction: {rollback_error}")
        return None, f"A-B-A Loop Automation setup failed: {e}"

def upscale_video(video_url, target_resolution="1080p", target_fps=30):
    """
    Upscale video using Topaz Labs Video Upscaler on Replicate
    Reference: https://replicate.com/topazlabs/video-upscale
    
    Args:
        video_url: URL of video to upscale (S3 URL)
        target_resolution: "720p", "1080p", or "4k" (default: 1080p)
        target_fps: 15-60 fps (default: 30)
    
    Returns:
        (upscaled_video_url, error) tuple
    """
    try:
        print(f"   🔼 Starting video upscale...")
        print(f"   🔼 Input: {video_url}")
        print(f"   🔼 Target: {target_resolution} @ {target_fps}fps")
        
        # Call Topaz Labs upscaler on Replicate
        # Reference: https://replicate.com/topazlabs/video-upscale
        output = replicate.run(
            "topazlabs/video-upscale",
            input={
                "video": video_url,
                "target_resolution": target_resolution,
                "target_fps": target_fps
            }
        )
        
        # The output is a URL to the upscaled video
        upscaled_url = output
        print(f"   ✅ Video upscaled: {upscaled_url}")
        
        # Download and re-upload to our S3 bucket for consistency
        print(f"   📥 Downloading upscaled video...")
        response = requests.get(upscaled_url)
        response.raise_for_status()
        
        upscaled_filename = f"upscaled_{uuid.uuid4()}.mp4"
        upscaled_filepath = os.path.join(ANIMATIONS_FOLDER_GENERATED, upscaled_filename)
        
        with open(upscaled_filepath, "wb") as f:
            f.write(response.content)
        
        print(f"   📤 Uploading upscaled video to S3...")
        s3_key = f"animations/upscaled/{upscaled_filename}"
        final_url = upload_file(upscaled_filepath, s3_key)
        
        # Clean up local file
        try:
            os.remove(upscaled_filepath)
        except Exception as e:
            print(f"   ⚠️ Could not delete temp upscaled file: {e}")
        
        print(f"   ✅ Upscale complete: {final_url}")
        return final_url, None
        
    except Exception as e:
        print(f"   ❌ Upscale failed: {e}")
        traceback.print_exc()
        return None, f"Video upscale error: {e}"

def handle_animation(job):
    try:
        print(f"-> Starting animation generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        video_model_name = input_data.get("video_model")
        
        # Map short names to full Replicate model IDs
        model_map = {
            "seedance": "bytedance/seedance-1-pro",
            "kling": "kwaivgi/kling-v2.1",
            "kling-v2.1": "kwaivgi/kling-v2.1",
        }
        
        video_model = model_map.get(video_model_name, video_model_name)
        print(f"   ...using model: {video_model_name} -> {video_model}")
        
        # Handle both S3 URLs and local file paths for start image
        image_url = input_data['image_url']
        
        # FIX: If re-animating a previously adjusted image, use the original instead
        # to avoid double desaturation
        if isinstance(image_url, str):
            if "_2_ADJUSTED" in image_url or "_3_GREENSCREEN" in image_url:
                original_url = image_url.replace("_2_ADJUSTED", "_1_ORIGINAL").replace("_3_GREENSCREEN", "_1_ORIGINAL")
                # Check if original exists (for local paths)
                if not original_url.startswith('http'):
                    original_path = os.path.join(BASE_DIR, original_url.lstrip('/'))
                    if os.path.exists(original_path):
                        print(f"   ✓ Using original image (avoiding double desaturation): {original_url}")
                        image_url = original_url
                    else:
                        print(f"   ⚠️ Original not found, using adjusted: {image_url}")
                else:
                    # For S3 URLs, just use the original URL (assume it exists)
                    print(f"   ✓ Using original S3 image (avoiding double desaturation): {original_url}")
                    image_url = original_url
        
        temp_start_file = None
        if image_url.startswith('http'):
            # It's an S3 URL - download it first
            print(f"   ...downloading start image from S3: {image_url}")
            img_response = requests.get(image_url)
            img_response.raise_for_status()
            temp_start_file = f"temp_start_{uuid.uuid4()}.png"
            start_image_path = os.path.join(LIBRARY_FOLDER, temp_start_file)
            with open(start_image_path, "wb") as f:
                f.write(img_response.content)
        else:
            # It's a local path
            start_image_path = os.path.join(BASE_DIR, image_url.lstrip('/'))
            if not os.path.exists(start_image_path):
                raise FileNotFoundError(f"Start image not found at {start_image_path}")
        
        user_negative_prompt = input_data.get("negative_prompt", "").strip()
        # CRITICAL: Prevent background color bleeding into subject during animation
        base_negative_additions = "contact shadow, drop shadow, change background color, no additions, motion blur, blurry movement, speed blur, fast motion artifacts, color bleeding, color contamination, background color on subject, green tint, blue tint, color spill"
        final_negative_prompt = f"{user_negative_prompt}, {base_negative_additions}" if user_negative_prompt else base_negative_additions
        
        # Add model-specific prompt instructions
        user_prompt = input_data.get('prompt')
        if 'kling' in video_model:
            # Instructions to reduce motion blur, improve keying quality, and prevent color bleeding
            kling_instructions = "No zoom, no scale changes. Smooth slow movement, sharp edges, crisp details, no motion blur, clean outlines throughout the animation. Keep subject colors pure and unchanged from the input image, no background color contamination."
            final_prompt = f"{user_prompt}. {kling_instructions}"
            api_input = {"prompt": final_prompt, "negative_prompt": final_negative_prompt}
            api_input["duration"] = input_data.get('kling_duration', input_data.get('duration', 5))
            if 'v2.1' in video_model: api_input["mode"] = input_data.get("kling_mode", "pro")
        elif 'seedance' in video_model:
            # Add similar instructions for Seedance
            seedance_instructions = "Keep subject colors pure and unchanged from the input image. No background color contamination, no color bleeding, maintain original subject colors throughout animation."
            final_prompt = f"{user_prompt}. {seedance_instructions}"
            api_input = {"prompt": final_prompt, "negative_prompt": final_negative_prompt}
            api_input["duration"] = input_data.get('seedance_duration', input_data.get('duration', 5))
            api_input["resolution"] = input_data.get('seedance_resolution', '1080p')
            # Get aspect ratio from image or default to 1:1
            api_input["aspect_ratio"] = input_data.get('seedance_aspect_ratio', '1:1')
        else:
            api_input = {"prompt": user_prompt, "negative_prompt": final_negative_prompt}
        end_file_obj = None
        last_frame_file_obj = None
        temp_end_file = None
        temp_last_frame_file = None
        try:
            with open(start_image_path, "rb") as start_file:
                if 'seedance' in video_model: api_input["image"] = start_file
                else: api_input["start_image"] = start_file
                end_image_url = input_data.get("end_image_url")
                
                if end_image_url and isinstance(end_image_url, str) and end_image_url.strip():
                    # Handle both S3 URLs and local file paths for end image
                    if end_image_url.startswith('http'):
                        # It's an S3 URL - download it first
                        print(f"   ...downloading end image from S3: {end_image_url}")
                        img_response = requests.get(end_image_url)
                        img_response.raise_for_status()
                        temp_end_file = f"temp_end_{uuid.uuid4()}.png"
                        end_image_path = os.path.join(LIBRARY_FOLDER, temp_end_file)
                        with open(end_image_path, "wb") as f:
                            f.write(img_response.content)
                        end_file_obj = open(end_image_path, "rb")
                    else:
                        # It's a local path
                        end_image_path = os.path.join(DATA_DIR, end_image_url.lstrip('/'))
                        if os.path.exists(end_image_path):
                            print(f"   ...using end frame from {end_image_path}")
                            end_file_obj = open(end_image_path, "rb")
                    
                    # Assign to correct parameter based on model
                    if end_file_obj:
                        if 'seedance' in video_model:
                            api_input["last_frame_image"] = end_file_obj
                            print(f"   ...set end_image_url as last_frame_image for Seedance")
                        else:
                            api_input["end_image"] = end_file_obj
                            print(f"   ...set end_image_url as end_image for Kling")
                # Handle last_frame_url for both Kling and Seedance
                last_frame_url = input_data.get("last_frame_url")
                if last_frame_url:
                    if last_frame_url.startswith('http'):
                        # Download from S3
                        print(f"   ...downloading last frame from S3: {last_frame_url}")
                        img_response = requests.get(last_frame_url)
                        img_response.raise_for_status()
                        temp_last_frame_file = f"temp_last_{uuid.uuid4()}.png"
                        last_frame_path = os.path.join(LIBRARY_FOLDER, temp_last_frame_file)
                        with open(last_frame_path, "wb") as f:
                            f.write(img_response.content)
                        last_frame_file_obj = open(last_frame_path, "rb")
                    else:
                        # Local path
                        last_frame_path = os.path.join(BASE_DIR, last_frame_url.lstrip('/'))
                        if os.path.exists(last_frame_path):
                            print(f"   ...using last frame from {last_frame_path}")
                            last_frame_file_obj = open(last_frame_path, "rb")
                    
                    # Assign to correct parameter based on model
                    if last_frame_file_obj:
                        if 'seedance' in video_model:
                            api_input["last_frame_image"] = last_frame_file_obj
                            print(f"   ...set last_frame_image for Seedance")
                        else:
                            api_input["end_image"] = last_frame_file_obj
                            print(f"   ...set end_image for Kling")
                if "end_image" in api_input and 'kling-v2.1' in video_model:
                    api_input["mode"] = "pro"
                    print("   ...forcing 'pro' mode for Kling because end_image is present.")
                loggable_input = {k: v for k, v in api_input.items() if not isinstance(v, io.IOBase)}
                if "start_image" in api_input or "image" in api_input: loggable_input['start_image_provided'] = True
                if "end_image" in api_input: loggable_input['end_image_provided'] = True
                if "last_frame_image" in api_input: loggable_input['last_frame_image_provided'] = True
                print(f"   ...calling Replicate with parameters: {loggable_input}")
                video_output_url = replicate.run(video_model, input=api_input)
        finally:
            if end_file_obj and not isinstance(end_file_obj, io.BytesIO):
                try:
                    end_file_obj.close()
                except Exception as e:
                    print(f"   ...warning: could not close end_file_obj: {e}")
            if last_frame_file_obj and not isinstance(last_frame_file_obj, io.BytesIO):
                try:
                    last_frame_file_obj.close()
                except Exception as e:
                    print(f"   ...warning: could not close last_frame_file_obj: {e}")
        video_response = requests.get(video_output_url)
        video_response.raise_for_status()
        video_filename = f"{uuid.uuid4()}.mp4"
        video_filepath = os.path.join(ANIMATIONS_FOLDER_GENERATED, video_filename)
        with open(video_filepath, "wb") as f: f.write(video_response.content)
        
        # Clean up temp files if we downloaded from S3
        if temp_start_file:
            try:
                os.remove(os.path.join(LIBRARY_FOLDER, temp_start_file))
                print(f"   ...cleaned up temp start file")
            except Exception as e:
                print(f"   ...warning: could not delete temp start file: {e}")
        if temp_end_file:
            try:
                os.remove(os.path.join(LIBRARY_FOLDER, temp_end_file))
                print(f"   ...cleaned up temp end file")
            except Exception as e:
                print(f"   ...warning: could not delete temp end file: {e}")
        if temp_last_frame_file:
            try:
                os.remove(os.path.join(LIBRARY_FOLDER, temp_last_frame_file))
                print(f"   ...cleaned up temp last frame file")
            except Exception as e:
                print(f"   ...warning: could not delete temp last frame file: {e}")
        
        # Upload to S3 if enabled
        s3_key = f"animations/generated/{video_filename}"
        public_url = upload_file(video_filepath, s3_key)
        return public_url, None
    except Exception as e:
        traceback.print_exc()
        return None, f"Animation generation error: {e}"

def handle_trim(job):
    """Handle video trimming jobs"""
    try:
        job_id = job['id']
        print(f"-> Starting trim job #{job_id}...")
        
        # Parse trim parameters from input_data
        trim_params = json.loads(job['input_data'])
        source_video_url = trim_params['source_video_url']
        in_point = float(trim_params['in_point'])
        out_point = float(trim_params['out_point'])
        pingpong = trim_params.get('pingpong', False)
        
        print(f"   Source: {source_video_url}")
        print(f"   In Point: {in_point}s")
        print(f"   Out Point: {out_point}s")
        print(f"   Pingpong: {pingpong}")
        
        # Handle S3 URLs or local paths
        if source_video_url.startswith('http'):
            # Download from S3 first
            import requests
            print(f"   Downloading video from S3...")
            response = requests.get(source_video_url)
            response.raise_for_status()
            temp_input = f"temp_trim_input_{uuid.uuid4().hex[:8]}.webm"
            input_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, temp_input)
            with open(input_path, 'wb') as f:
                f.write(response.content)
            cleanup_input = True
        else:
            # Use DATA_DIR for persistent disk compatibility
            if source_video_url.startswith('/'):
                input_path = os.path.join(DATA_DIR, source_video_url.lstrip('/'))
            else:
                input_path = os.path.join(STATIC_FOLDER, source_video_url)
            
            if not os.path.exists(input_path):
                print(f"   ❌ Video not found at: {input_path}")
                return None, f"Source video file not found: {input_path}"
            cleanup_input = False
        
        # Create output filename - use MP4 for H.264 encoding
        output_filename = f"trimmed_{job_id}_{uuid.uuid4().hex[:8]}.mp4"
        output_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, output_filename)
        
        # Trim video using ffmpeg
        duration = out_point - in_point
        
        if pingpong:
            # For pingpong loop: create forward then backward (reverse) sequence
            print(f"   Creating pingpong loop with H.264 (fast encoding)...")
            
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-ss', str(in_point),
                '-i', input_path,
                '-filter_complex',
                f'[0:v]trim=duration={duration},setpts=PTS-STARTPTS,split[main][copy]; '
                f'[copy]reverse[rev]; [main][rev]concat=n=2:v=1:a=0[out]',
                '-map', '[out]',
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '18',
                '-pix_fmt', 'yuv420p',
                output_path
            ]
        else:
            # Normal trim without pingpong - use fast H.264
            print(f"   Trimming video with H.264 (fast encoding)...")
            
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-ss', str(in_point),
                '-i', input_path,
                '-t', str(duration),
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '18',
                '-pix_fmt', 'yuv420p',
                output_path
            ]
        
        print(f"   Running FFmpeg...")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"   ❌ FFmpeg trim error: {result.stderr}")
            if cleanup_input and os.path.exists(input_path):
                os.remove(input_path)
            return None, f"FFmpeg trimming failed: {result.stderr[:500]}"
        
        # Upload trimmed video to S3 if enabled
        s3_key = f"library/transparent_videos/{output_filename}"
        trimmed_url = upload_file(output_path, s3_key)
        
        # Clean up temp input file if downloaded from S3
        if cleanup_input and os.path.exists(input_path):
            os.remove(input_path)
        
        print(f"   ✅ Video trimmed successfully: {trimmed_url}")
        return trimmed_url, None
        
    except Exception as e:
        traceback.print_exc()
        return None, f"Trim error: {e}"

def handle_video_effect_from_png(job, effect_params):
    """Process video effects using PNG sequence for perfect transparency"""
    import shutil
    
    job_id = job['id']
    png_sequence_path = effect_params['png_sequence_path']
    effect_type = effect_params.get('effect', 'linear')
    in_point = float(effect_params.get('in_point', 0))
    out_point = effect_params.get('out_point')
    speed = float(effect_params.get('speed', 1.0))
    speed_segments = effect_params.get('speed_segments')
    fps = effect_params.get('fps', 30)
    pingpong = effect_params.get('pingpong', False)
    
    try:
        # Convert path to absolute if needed and handle BOTH old and new formats
        if png_sequence_path:
            # Paths like /static/... are relative to BASE_DIR
            if png_sequence_path.startswith('/static/') or not png_sequence_path.startswith(BASE_DIR):
                png_sequence_path = os.path.join(BASE_DIR, png_sequence_path.lstrip('/'))
            
            print(f"   🔍 Checking PNG path: {png_sequence_path}")
            
            # Check if path exists
            if not os.path.exists(png_sequence_path):
                # Try old format in root directory (for backward compatibility)
                old_format_path = os.path.join(BASE_DIR, os.path.basename(png_sequence_path.rstrip('/')))
                print(f"   🔍 Trying old location: {old_format_path}")
                if os.path.exists(old_format_path):
                    print(f"   🔄 Found PNG sequence in old location (root): {old_format_path}")
                    png_sequence_path = old_format_path
                else:
                    print(f"   ❌ PNG sequence not found at: {png_sequence_path}")
                    print(f"   ❌ Also checked old location: {old_format_path}")
                    return None, f"PNG sequence directory not found: {png_sequence_path}"
        
        if not png_sequence_path or not os.path.exists(png_sequence_path):
            return None, "PNG sequence directory not found"
        
        # List all PNG files
        all_pngs = sorted([f for f in os.listdir(png_sequence_path) if f.lower().endswith('.png')])
        total_frames = len(all_pngs)
        
        if total_frames == 0:
            return None, "No PNG files in sequence"
        
        print(f"   Found {total_frames} PNG frames at {fps} FPS")
        
        # Calculate frame indices for trim
        in_frame = int(in_point * fps)
        out_frame = int(out_point * fps) if out_point else total_frames
        
        print(f"   Trimming to frames {in_frame}-{out_frame}")
        
        # Create temp directory for processed frames
        temp_frames_dir = os.path.join(TRANSPARENT_VIDEOS_FOLDER, f"temp_effect_{job_id}")
        os.makedirs(temp_frames_dir, exist_ok=True)
        
        # Build frame sequence based on effect type
        output_frames = []
        
        # CHECK SPEED FIRST (before effect type) - speed can be combined with any effect
        if speed_segments and len(speed_segments) > 0:
            # Variable speed - complex frame manipulation
            print(f"   🎬 Applying {len(speed_segments)} speed segments...")
            
            # Build frame map for the selected range
            for frame_idx in range(in_frame, min(out_frame, total_frames)):
                # Find if this frame is in a speed segment
                current_speed = 1.0
                for seg in speed_segments:
                    if seg['startFrame'] <= frame_idx <= seg['endFrame']:
                        current_speed = seg['speed']
                        break
                
                # Add frames based on speed
                if current_speed > 1.0:
                    # Speed up: skip frames
                    # e.g. 2x = show every 2nd frame, 3x = show every 3rd frame
                    skip_rate = int(current_speed)
                    if (frame_idx - in_frame) % skip_rate == 0:
                        output_frames.append(all_pngs[frame_idx])
                elif current_speed < 1.0:
                    # Slow motion: duplicate frames
                    duplicates = int(1.0 / current_speed)
                    for _ in range(duplicates):
                        output_frames.append(all_pngs[frame_idx])
                else:
                    # Normal speed
                    output_frames.append(all_pngs[frame_idx])
            
            # Apply effect type to the speed-adjusted frames
            if effect_type == 'boomerang' or effect_type == 'pingpong':
                forward_frames = output_frames[:]
                backward_frames = list(reversed(forward_frames[:-1]))
                output_frames = forward_frames + backward_frames
                print(f"   🔄 Applied {effect_type} effect to speed-adjusted frames")
        
        elif speed != 1.0:
            # Uniform speed adjustment
            print(f"   ⚡ Applying uniform speed: {speed}x")
            for i in range(in_frame, min(out_frame, total_frames)):
                if speed > 1.0:
                    # Speed up: skip frames
                    skip_rate = int(speed)
                    if (i - in_frame) % skip_rate == 0:
                        output_frames.append(all_pngs[i])
                elif speed < 1.0:
                    # Slow motion: duplicate frames
                    duplicates = int(1.0 / speed)
                    for _ in range(duplicates):
                        output_frames.append(all_pngs[i])
                else:
                    output_frames.append(all_pngs[i])
            
            # Apply effect type
            if effect_type == 'boomerang' or effect_type == 'pingpong':
                forward_frames = output_frames[:]
                backward_frames = list(reversed(forward_frames[:-1]))
                output_frames = forward_frames + backward_frames
        
        elif effect_type == 'boomerang' or effect_type == 'pingpong':
            # Forward then backward (no speed adjustment)
            forward_frames = [all_pngs[i] for i in range(in_frame, min(out_frame, total_frames))]
            backward_frames = list(reversed(forward_frames[:-1]))  # Exclude last frame to avoid duplicate
            output_frames = forward_frames + backward_frames
        
        else:
            # Simple trim (linear, no effects)
            for i in range(in_frame, min(out_frame, total_frames)):
                output_frames.append(all_pngs[i])
        
        print(f"   Generated {len(output_frames)} output frames")
        
        # Copy/link frames to temp directory with sequential naming
        for idx, frame_name in enumerate(output_frames):
            src = os.path.join(png_sequence_path, frame_name)
            dst = os.path.join(temp_frames_dir, f"frame_{idx:06d}.png")
            shutil.copy2(src, dst)
        
        # Compile to WebM with alpha using FFmpeg
        output_filename = f"effect_{effect_type}_{job_id}_{uuid.uuid4().hex[:8]}.webm"
        output_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, output_filename)
        
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-framerate', str(fps),
            '-i', os.path.join(temp_frames_dir, 'frame_%06d.png'),
            '-c:v', 'libvpx-vp9',
            '-pix_fmt', 'yuva420p',
            '-crf', '4',  # Near-lossless quality
            '-b:v', '0',
            output_path
        ]
        
        print(f"   Compiling {len(output_frames)} frames to WebM+alpha...")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"   ❌ FFmpeg error: {result.stderr}")
            shutil.rmtree(temp_frames_dir, ignore_errors=True)
            return None, f"FFmpeg compilation failed: {result.stderr[:500]}"
        
        # Clean up temp frames (NOT the source PNG sequence - we keep that!)
        shutil.rmtree(temp_frames_dir, ignore_errors=True)
        
        # Upload to S3 if enabled
        s3_key = f"library/transparent_videos/{output_filename}"
        effect_url = upload_file(output_path, s3_key)
        
        print(f"   ✅ Effect applied from PNG sequence: {effect_url}")
        return effect_url, None
        
    except Exception as e:
        traceback.print_exc()
        return None, f"PNG effect processing error: {e}"

def handle_video_effect(job):
    """Handle video effect jobs (boomerang, speed adjust, etc.)"""
    try:
        job_id = job['id']
        print(f"-> Starting video effect job #{job_id}...")
        
        # Parse effect parameters
        effect_params = json.loads(job['input_data'])
        source_video_url = effect_params['source_video_url']
        png_sequence_path = effect_params.get('png_sequence_path')
        effect_type = effect_params.get('effect', 'linear')
        in_point = float(effect_params.get('in_point', 0))
        out_point = effect_params.get('out_point')
        speed = float(effect_params.get('speed', 1.0))
        speed_segments = effect_params.get('speed_segments')
        pingpong = effect_params.get('pingpong', False)
        fps = effect_params.get('fps', 30)
        
        print(f"   Effect: {effect_type}")
        print(f"   PNG Sequence: {png_sequence_path}")
        print(f"   Video URL: {source_video_url}")
        
        if speed_segments and len(speed_segments) > 0:
            print(f"   🎨 Variable speed: {len(speed_segments)} segments")
        else:
            print(f"   ⚡ Uniform speed: {speed}x")
        
        # =====================================================================
        # PRIORITY 1: Use PNG sequence if available (BEST - perfect transparency)
        # =====================================================================
        if png_sequence_path:
            print(f"   📁 Using PNG sequence for guaranteed transparency!")
            return handle_video_effect_from_png(job, effect_params)
        
        # =====================================================================
        # PRIORITY 2: Fallback to video processing (may lose some alpha quality)
        # =====================================================================
        print(f"   ⚠️ PNG sequence not available, processing video directly")
        
        # Handle S3 URLs or local paths
        if source_video_url.startswith('http'):
            import requests
            print(f"   Downloading video from S3...")
            response = requests.get(source_video_url)
            response.raise_for_status()
            temp_input = f"temp_effect_input_{uuid.uuid4().hex[:8]}.webm"
            input_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, temp_input)
            with open(input_path, 'wb') as f:
                f.write(response.content)
            cleanup_input = True
        else:
            if source_video_url.startswith('/'):
                input_path = os.path.join(DATA_DIR, source_video_url.lstrip('/'))
            else:
                input_path = os.path.join(STATIC_FOLDER, source_video_url)
            
            if not os.path.exists(input_path):
                print(f"   ❌ Video not found at: {input_path}")
                return None, f"Source video file not found: {input_path}"
            cleanup_input = False
        
        # Get video info
        probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_path]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        video_duration = float(probe_result.stdout.strip())
        
        # Set out_point if not specified
        if out_point is None:
            out_point = video_duration
        else:
            out_point = float(out_point)
        
        trim_duration = out_point - in_point
        
        # Create output filename
        output_filename = f"effect_{effect_type}_{job_id}_{uuid.uuid4().hex[:8]}.webm"
        output_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, output_filename)
        
        # Build FFmpeg filter based on effect type and speed segments
        if speed_segments and len(speed_segments) > 0:
            # Variable speed segments - complex filter
            print(f"   🎬 Applying {len(speed_segments)} variable speed segments...")
            fps_val = effect_params.get('fps', 30)
            
            # Build list of all segments (including gaps at normal speed)
            segments_to_process = []
            
            # Convert frame numbers to time
            for seg in speed_segments:
                seg_start_time = in_point + (seg['startFrame'] / fps_val)
                seg_end_time = in_point + (seg['endFrame'] / fps_val)
                segments_to_process.append({
                    'start': seg_start_time,
                    'end': seg_end_time,
                    'speed': seg['speed']
                })
            
            # Sort by start time
            segments_to_process.sort(key=lambda x: x['start'])
            
            # Fill gaps with normal speed
            all_segments = []
            current_time = in_point
            
            for seg in segments_to_process:
                # Add gap before this segment if needed
                if current_time < seg['start']:
                    all_segments.append({
                        'start': current_time,
                        'end': seg['start'],
                        'speed': 1.0
                    })
                
                # Add the speed segment
                all_segments.append(seg)
                current_time = seg['end']
            
            # Add final gap if needed
            if current_time < out_point:
                all_segments.append({
                    'start': current_time,
                    'end': out_point,
                    'speed': 1.0
                })
            
            # Build filter string
            filter_parts = []
            for i, seg in enumerate(all_segments):
                duration = seg['end'] - seg['start']
                if duration < 0.01:  # Skip tiny segments
                    continue
                    
                # Trim segment
                speed_val = seg['speed']
                pts_multiplier = 1.0 / speed_val  # Speed up = smaller PTS multiplier
                
                filter_parts.append(
                    f"[0:v]trim=start={seg['start']:.3f}:end={seg['end']:.3f},setpts=PTS-STARTPTS,setpts={pts_multiplier:.3f}*PTS[v{i}]"
                )
            
            # Concatenate all segments
            concat_inputs = ''.join([f'[v{i}]' for i in range(len(filter_parts))])
            filter_str = ';'.join(filter_parts) + f';{concat_inputs}concat=n={len(filter_parts)}:v=1:a=0[out]'
            
            print(f"   📊 Created {len(all_segments)} segments (including gaps)")
            
        elif effect_type == 'boomerang':
            # Trim, then play forward-backward once
            filter_str = f'[0:v]trim=start={in_point}:end={out_point},setpts=PTS-STARTPTS,split[main][copy]; [copy]reverse[rev]; [main][rev]concat=n=2:v=1:a=0[out]'
        elif effect_type == 'pingpong' or pingpong:
            # Trim, then loop forward-backward
            filter_str = f'[0:v]trim=start={in_point}:end={out_point},setpts=PTS-STARTPTS,split[main][copy]; [copy]reverse[rev]; [main][rev]concat=n=2:v=1:a=0[out]'
        elif speed != 1.0:
            # Apply uniform speed adjustment
            filter_str = f'[0:v]trim=start={in_point}:end={out_point},setpts=PTS-STARTPTS,setpts={1/speed}*PTS[out]'
        else:
            # Linear - just trim
            filter_str = f'[0:v]trim=start={in_point}:end={out_point},setpts=PTS-STARTPTS[out]'
        
        print(f"   Filter: {filter_str[:200]}..." if len(filter_str) > 200 else f"   Filter: {filter_str}")
        
        # Build FFmpeg command
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-filter_complex', filter_str,
            '-map', '[out]',
            '-c:v', 'libvpx-vp9',
            '-pix_fmt', 'yuva420p',
            '-crf', '30',
            '-b:v', '0',
            output_path
        ]
        
        print(f"   Running FFmpeg...")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"   ❌ FFmpeg effect error: {result.stderr}")
            if cleanup_input and os.path.exists(input_path):
                os.remove(input_path)
            return None, f"FFmpeg effect processing failed: {result.stderr[:500]}"
        
        # Upload to S3 if enabled
        s3_key = f"library/transparent_videos/{output_filename}"
        effect_url = upload_file(output_path, s3_key)
        
        # Clean up
        if cleanup_input and os.path.exists(input_path):
            os.remove(input_path)
        
        print(f"   ✅ Effect applied successfully: {effect_url}")
        return effect_url, None
        
    except Exception as e:
        traceback.print_exc()
        return None, f"Video effect error: {e}"

def handle_video_stitching(job):
    temp_video_a = None
    temp_video_b = None
    try:
        print(f"-> Starting video stitching for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        
        # Handle both S3 URLs and local file paths for video A
        video_a_url = input_data['video_a_path']
        if video_a_url.startswith('http'):
            # It's an S3 URL - download it first
            print(f"   ...downloading video A from S3: {video_a_url}")
            vid_response = requests.get(video_a_url)
            vid_response.raise_for_status()
            temp_video_a = f"temp_stitch_a_{uuid.uuid4()}.mp4"
            video_a_path = os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video_a)
            with open(video_a_path, "wb") as f:
                f.write(vid_response.content)
        else:
            # Use DATA_DIR for persistent disk compatibility
            if video_a_url.startswith('/'):
                video_a_path = os.path.join(DATA_DIR, video_a_url.lstrip('/'))
            else:
                video_a_path = os.path.join(STATIC_FOLDER, video_a_url)
            
            if not os.path.exists(video_a_path):
                print(f"   ❌ Video A not found at: {video_a_path}")
                return None, f"Source video A not found: {video_a_path}"
        
        # Handle both S3 URLs and local file paths for video B
        video_b_url = input_data['video_b_path']
        if video_b_url.startswith('http'):
            # It's an S3 URL - download it first
            print(f"   ...downloading video B from S3: {video_b_url}")
            vid_response = requests.get(video_b_url)
            vid_response.raise_for_status()
            temp_video_b = f"temp_stitch_b_{uuid.uuid4()}.mp4"
            video_b_path = os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video_b)
            with open(video_b_path, "wb") as f:
                f.write(vid_response.content)
        else:
            # Use DATA_DIR for persistent disk compatibility
            if video_b_url.startswith('/'):
                video_b_path = os.path.join(DATA_DIR, video_b_url.lstrip('/'))
            else:
                video_b_path = os.path.join(STATIC_FOLDER, video_b_url)
            
            if not os.path.exists(video_b_path):
                print(f"   ❌ Video B not found at: {video_b_path}")
                return None, f"Source video B not found: {video_b_path}"
            
        # Check file sizes (basic validation)
        size_a = os.path.getsize(video_a_path)
        size_b = os.path.getsize(video_b_path)
        print(f"   ...video A: {size_a/1024/1024:.1f}MB, video B: {size_b/1024/1024:.1f}MB")
        
        # Reject very large files to prevent hanging
        max_size = 100 * 1024 * 1024  # 100MB limit
        if size_a > max_size or size_b > max_size:
            return None, f"Video files too large for stitching (limit: 100MB). A: {size_a/1024/1024:.1f}MB, B: {size_b/1024/1024:.1f}MB"
        
        output_filename = f"stitched_{uuid.uuid4()}.mp4"
        output_filepath = os.path.join(LIBRARY_FOLDER, output_filename)
        
        print(f"   ...output will be: {output_filepath}")
        
        # Import here to avoid circular imports
        from video_processor import stitch_videos_with_ffmpeg
        
        # Call stitching with timeout protection
        stitch_videos_with_ffmpeg(video_paths=[video_a_path, video_b_path], output_path=output_filepath)
        
        # Verify output file was created and has reasonable size
        if not os.path.exists(output_filepath):
            return None, "Stitching completed but output file was not created"
            
        output_size = os.path.getsize(output_filepath)
        if output_size < 1024:  # Less than 1KB suggests failure
            return None, f"Stitching produced invalid output file ({output_size} bytes)"
            
        print(f"   ...stitching successful: {output_size/1024/1024:.1f}MB output")
        
        # Upload to S3 if enabled
        s3_key = f"library/{output_filename}"
        public_url = upload_file(output_filepath, s3_key)
        
        # Clean up temp files if we downloaded from S3
        if temp_video_a:
            try:
                os.remove(os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video_a))
                print(f"   ...cleaned up temp video A")
            except Exception as e:
                print(f"   ...warning: could not delete temp video A: {e}")
        if temp_video_b:
            try:
                os.remove(os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video_b))
                print(f"   ...cleaned up temp video B")
            except Exception as e:
                print(f"   ...warning: could not delete temp video B: {e}")
        
        # Check if we should auto-queue keying job (for boomerang automation)
        if input_data.get('auto_key_after_stitch'):
            print(f"   ...auto-queuing keying job to remove green background")
            with get_db_connection() as conn:
                cursor = conn.cursor()
                keying_settings = json.dumps({
                    "hue_center": 60,  # Green hue (HSV 0-180 range)
                    "hue_tolerance": 25,  # Updated tolerance
                    "saturation_min": 140,  # Reduced from 100/160 to catch more greens
                    "value_min": 80,  # Increased from 50/100 for better bright green isolation
                    "erode": 2,  # Choke edges inward
                    "dilate": 2,  # Soften edges outward
                    "blur": 5,  # Edge blur
                    "spill_suppression": 5
                })
                keying_input_data = json.dumps({
                    "video_path": public_url
                })
                cursor.execute(
                    "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, keying_settings, parent_job_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ('keying', 'keying_queued', datetime.now(), f"Auto-keying: {job['prompt']}", keying_input_data, keying_settings, job['id'])
                )
                conn.commit()
                print(f"   ...keying job #{cursor.lastrowid} queued for {public_url}")
        
        return public_url, None
        
    except Exception as e:
        print(f"   ...ERROR in video stitching: {e}")
        traceback.print_exc()
        
        # Clean up temp files on error too
        if temp_video_a:
            try:
                os.remove(os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video_a))
            except:
                pass
        if temp_video_b:
            try:
                os.remove(os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video_b))
            except:
                pass
        
        return None, f"Video stitching error: {e}"

def handle_replicate_openai_generation(job):
    import shutil
    import time
    if not OPENAI_API_KEY: return None, "OpenAI API Key is required for this model but not found in .env file."
    try:
        print(f"-> Starting OpenAI via Replicate generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        
        # Support both v2 format (object_prompt + style_prompt) and v3 format (single prompt)
        if 'prompt' in input_data and 'object_prompt' not in input_data:
            # v3 format: use prompt as-is
            user_prompt = input_data['prompt']
            aspect_ratio = input_data.get('aspect_ratio', '1:1')
            
            print(f"   ...v3 format detected")
            full_prompt = f"{user_prompt}, on a transparent background, clean solid edges, no fur, no hair, no fluffy details, smooth silhouette"
        else:
            # v2 format: combine object_prompt + style_prompt
            aspect_ratio = input_data.get('aspect_ratio', '1:1')
            full_prompt = f"{input_data['object_prompt']}, in the style of {input_data['style_prompt']}, on a transparent background, clean solid edges, no fur, no hair, no fluffy details, smooth silhouette"
        
        api_input = {"prompt": full_prompt, "openai_api_key": OPENAI_API_KEY, "background": "transparent", "quality": "high", "output_format": "png", "aspect_ratio": aspect_ratio}
        print("   ...calling openai/gpt-image-1 on Replicate.")
        output = replicate.run("openai/gpt-image-1", input=api_input)
        output_url = output[0] if isinstance(output, list) and output else output if isinstance(output, str) else None
        if not output_url: return None, "Replicate OpenAI model did not return an image URL."
        print(f"   ...downloading transparent image from Replicate: {output_url}")
        image_res = requests.get(output_url)
        image_res.raise_for_status()
        transparent_filename = f"{uuid.uuid4()}_transparent.png"
        transparent_filepath = os.path.join(LIBRARY_FOLDER, transparent_filename)
        with open(transparent_filepath, "wb") as f: f.write(image_res.content)
        
        # NEW WORKFLOW: Only save transparent image, skip desaturation and greenscreen
        # Desaturation and greenscreen will be created ONLY when user clicks "Animate"
        print(f"   📸 Image generation complete - transparent image ready for display")
        
        # Upload transparent version (this is what user sees)
        transparent_s3_key = f"library/{os.path.basename(transparent_filepath)}"
        transparent_public_url = upload_file(transparent_filepath, transparent_s3_key)
        
        # Store transparent URL - greenscreen will be created later during animation
        result = {
            'transparent': transparent_public_url,  # User sees this in card with checkerboard
            'original': transparent_public_url,  # Keep for backward compatibility
        }
        
        print(f"   ✅ Transparent URL (ChatGPT): {transparent_public_url}")
        print(f"   💡 Greenscreen will be created when user clicks Animate")
        
        return json.dumps(result), None
    except Exception as e:
        return None, f"Replicate OpenAI generation error: {e}"

def adjust_greens_away_from_chroma(image_path):
    """
    TEST FUNCTION: Apply uniform green adjustment to entire image to prevent chroma key conflicts.
    This applies a subtle shift across ALL pixels to avoid patchy artifacts.
    """
    try:
        print(f"   🎨 TEST: Applying uniform green adjustment to entire image...")
        img = Image.open(image_path).convert("RGBA")
        pixels = np.array(img, dtype=np.float32)  # Use float for smoother math
        
        # TEST: Save BEFORE version for comparison
        before_path = image_path.replace('.png', '_BEFORE_adjustment.png')
        img.save(before_path)
        print(f"   📸 Saved BEFORE: {os.path.basename(before_path)}")
        
        r, g, b, a = pixels[:,:,0], pixels[:,:,1], pixels[:,:,2], pixels[:,:,3]
        
        # Count problematic greens for reporting
        is_green_dominant = (g > r + 20) & (g > b + 20)
        is_too_pure_green = (g > 180) & (r < 100) & (b < 100)
        problem_pixels = np.sum(is_green_dominant & is_too_pure_green & (a > 0))
        
        if problem_pixels > 0:
            print(f"   📊 Found {problem_pixels} pixels with problematic greens")
            print(f"   🌈 Applying UNIFORM adjustment to entire image for natural look...")
            
            # Apply uniform adjustment to ALL pixels (where alpha > 0)
            # Reduce green channel by 8-10%, add slight warmth (red) and coolness (blue)
            mask = a > 0  # Only adjust non-transparent pixels
            
            # Subtle uniform adjustments:
            pixels[:,:,1] = np.where(mask, g * 0.90, g)  # Reduce green by 10%
            pixels[:,:,0] = np.where(mask, np.minimum(r + 8, 255), r)  # Add slight red
            pixels[:,:,2] = np.where(mask, np.minimum(b + 5, 255), b)  # Add slight blue
            
            # Convert back to uint8
            pixels = np.clip(pixels, 0, 255).astype(np.uint8)
            
            # Save adjusted image
            adjusted_img = Image.fromarray(pixels, 'RGBA')
            adjusted_img.save(image_path)
            
            # TEST: Save AFTER version for comparison
            after_path = image_path.replace('.png', '_AFTER_adjustment.png')
            adjusted_img.save(after_path)
            print(f"   📸 Saved AFTER: {os.path.basename(after_path)}")
            print(f"   ✅ Uniform green adjustment applied across entire image")
        else:
            print(f"   ✅ No problematic greens found - image is safe for chroma keying")
        
        return True
    except Exception as e:
        print(f"   ⚠️ Green adjustment failed: {e} - continuing anyway")
        return False

def detect_dominant_color(transparent_image_path):
    """
    Analyze image to detect if GREEN or BLUE are dominant colors in the subject.
    Returns 'blue' if green is dominant (use blue screen), 'green' otherwise.
    """
    try:
        from colorsys import rgb_to_hsv
        img = Image.open(transparent_image_path).convert("RGBA")
        pixels = np.array(img)
        
        # Only analyze pixels with significant alpha (actual subject, not background)
        alpha = pixels[:, :, 3]
        opaque_mask = alpha > 128
        opaque_pixels = pixels[opaque_mask][:, :3]  # RGB only
        
        if len(opaque_pixels) == 0:
            return 'green'  # Default if no opaque pixels
        
        # Convert to HSV to analyze hue
        rgb_normalized = opaque_pixels.astype(np.float32) / 255.0
        h, s, v = np.vectorize(rgb_to_hsv)(rgb_normalized[:, 0], rgb_normalized[:, 1], rgb_normalized[:, 2])
        
        # Count pixels in green hue range (60-180° = 0.167-0.5 normalized)
        # Only count saturated pixels (avoid grays)
        saturated_mask = (s > 0.2) & (v > 0.2)
        green_mask = (h >= 0.167) & (h <= 0.5) & saturated_mask
        blue_mask = (h >= 0.5) & (h <= 0.75) & saturated_mask  # Blue range 180-270°
        
        green_ratio = np.sum(green_mask) / len(h) if len(h) > 0 else 0
        blue_ratio = np.sum(blue_mask) / len(h) if len(h) > 0 else 0
        
        print(f"   🎨 Color analysis: {green_ratio*100:.1f}% green, {blue_ratio*100:.1f}% blue")
        
        # IMPROVED LOGIC: Compare ratios to pick the better screen color
        # Use higher threshold (20%) and check which color is MORE dominant
        threshold = 0.20  # 20% of pixels must be that color
        
        if green_ratio > threshold and blue_ratio > threshold:
            # BOTH colors present - use opposite of the MORE dominant one
            if green_ratio > blue_ratio:
                print(f"   ⚠️ BOTH colors present, but GREEN is more dominant ({green_ratio*100:.1f}% vs {blue_ratio*100:.1f}%) → Using BLUE screen")
                return 'blue'
            else:
                print(f"   🔵 BOTH colors present, but BLUE is more dominant ({blue_ratio*100:.1f}% vs {green_ratio*100:.1f}%) → Using GREEN screen")
                return 'green'
        elif green_ratio > threshold:
            # Only green is significant
            print(f"   🟢 GREEN subject detected ({green_ratio*100:.1f}%) → Using BLUE screen")
            return 'blue'
        elif blue_ratio > threshold:
            # Only blue is significant
            print(f"   🔵 BLUE subject detected ({blue_ratio*100:.1f}%) → Using GREEN screen")
            return 'green'
        else:
            # Neither color is dominant enough to matter
            print(f"   ✅ No dominant green/blue (both <{threshold*100:.0f}%) → Using GREEN screen (default)")
            return 'green'
            
    except Exception as e:
        print(f"   ⚠️ Color detection error: {e}, defaulting to green screen")
        return 'green'

def composite_on_colored_screen(transparent_image_path, screen_color='green'):
    """
    Composite a transparent PNG onto a colored screen background (green or blue).
    Returns tuple: (path, screen_color_used)
    
    IMPORTANT: This should be called AFTER all color adjustments are complete.
    """
    try:
        color_name = screen_color
        print(f"   🎬 Compositing transparent image onto {color_name.upper()} screen...")
        
        # Force file system sync
        import time
        time.sleep(0.1)
        
        # Load transparent image
        foreground = Image.open(transparent_image_path).convert("RGBA")
        original_size = foreground.size
        print(f"      📊 Original image size: {original_size}, mode: {foreground.mode}")
        
        # Scale down by 15% (to 85% size) to give room for animation
        scale_factor = 0.85
        new_size = (int(original_size[0] * scale_factor), int(original_size[1] * scale_factor))
        foreground_scaled = foreground.resize(new_size, Image.Resampling.LANCZOS)
        print(f"      📐 Scaled down to: {new_size} ({int(scale_factor*100)}% of original)")
        
        # Create colored background (keep original dimensions)
        if color_name == 'blue':
            bg_color = (0, 0, 255)  # Pure blue RGB
            suffix = '_bluescreen.png'
        else:  # default to green
            bg_color = (0, 255, 0)  # Pure green RGB
            suffix = '_greenscreen.png'
        
        background = Image.new("RGB", original_size, bg_color)
        
        # Center the scaled foreground on the background
        x_offset = (original_size[0] - new_size[0]) // 2
        y_offset = (original_size[1] - new_size[1]) // 2
        background.paste(foreground_scaled, (x_offset, y_offset), foreground_scaled)
        print(f"      ✨ Centered at offset: ({x_offset}, {y_offset})")
        
        # Save as new file
        screen_path = transparent_image_path.replace('.png', suffix)
        background.save(screen_path, "PNG")
        
        print(f"   ✅ {color_name.capitalize()} screen composite saved: {os.path.basename(screen_path)}")
        return screen_path, color_name
    except Exception as e:
        print(f"   ⚠️ {color_name.capitalize()} screen composite failed: {e}")
        return None, 'green'

def apply_hue_shift(image_path, shift_degrees):
    """
    TEST FUNCTION: Apply a hue shift to the entire image to move colors away from green hue range.
    Green is at ~120° in HSV. Shifting by +30° moves all colors away from problematic green range.
    
    Args:
        image_path: Path to the image
        shift_degrees: Degrees to shift hue (positive = clockwise, negative = counter-clockwise)
    """
    try:
        print(f"      🌈 Applying hue shift: {shift_degrees:+.0f}° to avoid green conflicts...")
        img = Image.open(image_path).convert("RGBA")
        
        # Split into RGB and alpha
        rgb = np.array(img.convert("RGB"), dtype=np.float32) / 255.0
        alpha = np.array(img.split()[3])
        
        # Convert RGB to HSV
        from colorsys import rgb_to_hsv, hsv_to_rgb
        h, s, v = np.vectorize(rgb_to_hsv)(rgb[:,:,0], rgb[:,:,1], rgb[:,:,2])
        
        # Shift hue (normalize to 0-1 range)
        h = (h + (shift_degrees / 360.0)) % 1.0
        
        # Convert back to RGB
        r, g, b = np.vectorize(hsv_to_rgb)(h, s, v)
        
        # Stack and convert back to uint8
        rgb_shifted = np.dstack([r, g, b]) * 255
        rgb_shifted = np.clip(rgb_shifted, 0, 255).astype(np.uint8)
        
        # Recombine with alpha
        img_shifted = Image.fromarray(rgb_shifted, 'RGB')
        img_shifted.putalpha(Image.fromarray(alpha))
        
        # Close original image to release file handle
        img.close()
        
        # Save with explicit file sync
        img_shifted.save(image_path, "PNG")
        del img_shifted  # Explicitly delete to ensure file is closed
        
        # Force file system sync
        import os
        os.sync() if hasattr(os, 'sync') else None
        
        print(f"      ✅ Hue shifted by {shift_degrees:+.0f}°")
        return True
    except Exception as e:
        print(f"      ⚠️ Hue shift failed: {e} - continuing anyway")
        return False

def apply_saturation_adjustment(image_path, saturation_multiplier, exclude_green=False, screen_color=None):
    """
    Adjust saturation of the entire image.
    
    Args:
        image_path: Path to the image
        saturation_multiplier: Multiplier for saturation (0.4 = reduce to 40%, 2.5 = boost to 250%)
        exclude_green: DEPRECATED - use screen_color instead
        screen_color: 'green' or 'blue' - excludes this color from boost (prevents fringing after keying)
    """
    try:
        # Handle backwards compatibility
        if exclude_green and screen_color is None:
            screen_color = 'green'
        
        percent = int(saturation_multiplier * 100)
        exclude_msg = f", excluding {screen_color}" if screen_color else ""
        print(f"      💧 Adjusting saturation: {percent}% (multiplier: {saturation_multiplier:.2f}{exclude_msg})...")
        img = Image.open(image_path).convert("RGBA")
        
        # Split into RGB and alpha
        rgb = np.array(img.convert("RGB"), dtype=np.float32) / 255.0
        alpha = np.array(img.split()[3])
        
        # Convert RGB to HSV
        from colorsys import rgb_to_hsv, hsv_to_rgb
        h, s, v = np.vectorize(rgb_to_hsv)(rgb[:,:,0], rgb[:,:,1], rgb[:,:,2])
        
        # Exclude transparent/semi-transparent pixels and screen color from saturation adjustments
        alpha_mask = alpha > 200  # ONLY process nearly-opaque pixels (excludes residual green fringe)
        
        if screen_color and saturation_multiplier > 1.0:
            # AFTER KEYING: Exclude screen color from boost to prevent dark green/blue artifacts
            if screen_color == 'blue':
                # Blue hue range (180-270° = 0.5-0.75 in normalized hue) - exclude ALL blues
                screen_hue_mask = (h >= 0.5) & (h <= 0.75)
                print(f"      🔵 Excluding ALL BLUE pixels from saturation boost")
            else:  # green
                # Green hue range (60-180° = 0.167-0.5 in normalized hue) - exclude ALL greens
                screen_hue_mask = (h >= 0.167) & (h <= 0.5)
                print(f"      🟢 Excluding ALL GREEN pixels from saturation boost")
            
            # Also exclude very low saturation pixels (likely artifacts)
            saturation_mask = s > 0.1
            
            # Create combined mask: opaque + not green + not too desaturated
            boost_mask = alpha_mask & ~screen_hue_mask & saturation_mask
            
            s_adjusted = s.copy()
            s_adjusted[boost_mask] = np.clip(s[boost_mask] * saturation_multiplier, 0, 1)
        else:
            # BEFORE ANIMATION: Apply to all opaque pixels equally
            s_adjusted = s.copy()
            s_adjusted[alpha_mask] = np.clip(s[alpha_mask] * saturation_multiplier, 0, 1)
        
        # Convert back to RGB
        r, g, b = np.vectorize(hsv_to_rgb)(h, s_adjusted, v)
        
        # Stack and convert back to uint8
        rgb_adjusted = np.dstack([r, g, b]) * 255
        rgb_adjusted = np.clip(rgb_adjusted, 0, 255).astype(np.uint8)
        
        # Recombine with alpha
        img_adjusted = Image.fromarray(rgb_adjusted, 'RGB')
        img_adjusted.putalpha(Image.fromarray(alpha))
        
        # Close original image to release file handle
        img.close()
        
        # Save with explicit file sync
        img_adjusted.save(image_path, "PNG")
        del img_adjusted  # Explicitly delete to ensure file is closed
        
        # Force file system sync
        import os
        os.sync() if hasattr(os, 'sync') else None
        
        print(f"      ✅ Saturation adjusted to {percent}%")
        return True
    except Exception as e:
        print(f"      ⚠️ Saturation adjustment failed: {e} - continuing anyway")
        return False

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
        print(f"      🔄 Reversing green adjustment to restore original colors...")
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
        
        print(f"      ✅ Original colors restored")
        return True
    except Exception as e:
        print(f"      ⚠️ Color restoration failed: {e} - continuing anyway")
        return False

def shorten_prompt_with_gpt(prompt, max_length=150, model_name="unknown"):
    """
    Intelligently shorten a prompt using ChatGPT while preserving key details.
    Returns the original prompt if it's already short enough or if shortening fails.
    """
    if len(prompt) <= max_length:
        return prompt
    
    if not OPENAI_API_KEY:
        print(f"   ⚠️ No OpenAI key - truncating prompt to {max_length} chars")
        return prompt[:max_length]
    
    try:
        print(f"   📝 Shortening {model_name} prompt from {len(prompt)} to ~{max_length} chars using GPT...")
        
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"You are a prompt optimization expert. Condense the following image generation prompt to approximately {max_length} characters while preserving ALL key visual details, style elements, colors, and artistic characteristics. Keep the most important descriptive words. Remove filler words and redundancy. Return ONLY the condensed prompt, no explanations."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=100,
            temperature=0.3
        )
        
        shortened = response.choices[0].message.content.strip()
        
        # Safety check: if GPT made it too long, hard truncate
        if len(shortened) > max_length + 20:
            shortened = shortened[:max_length]
        
        print(f"   ✅ Shortened to {len(shortened)} chars: {shortened[:80]}...")
        return shortened
        
    except Exception as e:
        print(f"   ⚠️ GPT shortening failed: {e} - using truncation")
        return prompt[:max_length]

def extract_url_from_output(output):
    """Extract URL string from various Replicate output types (FileOutput, string, list, iterator)"""
    if output is None:
        return None
    
    # FileOutput object - try .url() method first (newer Replicate API)
    if hasattr(output, 'url'):
        try:
            if callable(output.url):
                return output.url()
            elif isinstance(output.url, str):
                return output.url
        except Exception as e:
            print(f"   ...warning: failed to get url from FileOutput: {e}")
    
    # Direct string URL (must start with http)
    if isinstance(output, str) and output.startswith('http'):
        return output
    
    # List of outputs - recursively extract from first item
    if isinstance(output, list) and output:
        return extract_url_from_output(output[0])
    
    # Iterator - convert to list first (but not strings/bytes which are also iterable)
    if hasattr(output, '__iter__') and not isinstance(output, (str, bytes)):
        try:
            output_list = list(output)
            if output_list:
                return extract_url_from_output(output_list[0])
        except Exception as e:
            print(f"   ...warning: failed to iterate output: {e}")
    
    # Last resort - try to get string representation (but avoid binary data)
    if not isinstance(output, bytes):
        try:
            str_output = str(output)
            if str_output.startswith('http'):
                return str_output
        except:
            pass
    
    return None

def handle_bytedance_generation(job):
    import shutil
    import time
    try:
        print(f"-> Starting Bytedance Seedream-4 generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        
        # Support both v2 format (object_prompt + style_prompt) and v3 format (single prompt)
        if 'prompt' in input_data and 'object_prompt' not in input_data:
            # v3 format: use prompt as-is
            user_prompt = input_data['prompt']
            aspect_ratio = input_data.get('aspect_ratio', '1:1')
            
            print(f"   ...v3 format detected, using prompt directly")
            engineered_prompt = f"professional product shot, {user_prompt}, centered, on a solid white flat neutral background, no shadows, clean solid edges, no fur, no hair, no fluffy details, smooth silhouette"
        else:
            # v2 format: combine object_prompt + style_prompt
            style_prompt = shorten_prompt_with_gpt(
                input_data['style_prompt'], 
                max_length=150, 
                model_name="Bytedance"
            )
            aspect_ratio = input_data.get('aspect_ratio', '1:1')
        
            print(f"   ...v2 format detected, combining prompts")
            engineered_prompt = (f"professional product shot of a {input_data['object_prompt']}, " 
                               f"in the style of {style_prompt}, centered, " 
                               f"on a solid white flat neutral background, no shadows, clean solid edges, no fur, no hair, no fluffy details, smooth silhouette")
        
        # Use bytedance/seedream-4 for white background generation
        print(f"   ...using bytedance/seedream-4")
        print(f"   ...calling bytedance/seedream-4")
        print(f"   ...prompt: {engineered_prompt[:100]}...")
        print(f"   ...aspect_ratio: {aspect_ratio}")
        white_bg_output = replicate.run("bytedance/seedream-4", input={
            "prompt": engineered_prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "png"
        })
        # Handle Flux output format - can be FileOutput, string, list, or iterator
        print(f"   ...Flux output type: {type(white_bg_output)}, value: {str(white_bg_output)[:100]}")
        white_bg_url = extract_url_from_output(white_bg_output)
            
        if not white_bg_url: 
            return None, f"Image generation model did not return an image URL. Got type: {type(white_bg_output)}"
        
        print(f"   ...downloading white-background image from: {white_bg_url[:80]}...")
        img_res = requests.get(white_bg_url)
        img_res.raise_for_status()
        white_filename = f"{uuid.uuid4()}_white.png"
        white_filepath = os.path.join(LIBRARY_FOLDER, white_filename)
        with open(white_filepath, "wb") as f: f.write(img_res.content)
        
        # TEST WORKFLOW: Remove background -> Adjust greens -> Composite on green
        print(f"   🧪 TEST: Removing white background...")
        output = replicate.run(
            "851-labs/background-remover:a029dff38972b5fda4ec5d75d7d1cd25aeff621d2cf4946a41055d7db66b80bc",
            input={"image": open(white_filepath, "rb")}
        )
        
        # Handle FileOutput object properly - use extract_url_from_output helper
        result_url = extract_url_from_output(output)
        if not result_url:
            return None, f"Background remover did not return an image URL. Got type: {type(output)}"
        
        print(f"   ...downloading transparent image from: {result_url[:80]}...")
        transparent_res = requests.get(result_url)
        transparent_res.raise_for_status()
        transparent_filename = f"{uuid.uuid4()}_transparent.png"
        transparent_filepath = os.path.join(LIBRARY_FOLDER, transparent_filename)
        with open(transparent_filepath, "wb") as f: f.write(transparent_res.content)
        
        # TEST: DISABLED green adjustment - conflicts with hue shift
        # adjust_greens_away_from_chroma(transparent_filepath)
        
        # NEW WORKFLOW: Only save transparent image, skip desaturation and greenscreen
        # Desaturation and greenscreen will be created ONLY when user clicks "Animate"
        print(f"   📸 Image generation complete - transparent image ready for display")
        
        # Upload transparent version (this is what user sees)
        transparent_s3_key = f"library/{os.path.basename(transparent_filepath)}"
        transparent_public_url = upload_file(transparent_filepath, transparent_s3_key)
        
        # Store transparent URL - greenscreen will be created later during animation
        result = {
            'transparent': transparent_public_url,  # User sees this in card with checkerboard
            'original': transparent_public_url,  # Keep for backward compatibility
        }
        
        print(f"   ✅ Transparent URL (Bytedance): {transparent_public_url}")
        print(f"   💡 Greenscreen will be created when user clicks Animate")
        
        return json.dumps(result), None
    except Exception as e:
        print(f"   ❌ Bytedance generation error: {e}")
        traceback.print_exc()
        return None, f"Bytedance generation error: {e}"

def handle_flux_generation(job):
    import shutil
    import time
    try:
        print(f"-> Starting FLUX 1.1 Pro generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        
        # Support both v2 format (object_prompt + style_prompt) and v3 format (single prompt)
        if 'prompt' in input_data and 'object_prompt' not in input_data:
            # v3 format: use prompt as-is
            user_prompt = input_data['prompt']
            aspect_ratio = input_data.get('aspect_ratio', '1:1')
            
            print(f"   ...v3 format detected")
            full_prompt = f"{user_prompt}, isolated and centered in the frame not touching the edges, on a solid white flat background, clean solid edges, no fur, no hair, no fluffy details, smooth silhouette"
        else:
            # v2 format: combine object_prompt + style_prompt
            aspect_ratio = input_data.get('aspect_ratio', '1:1')
            full_prompt = f"{input_data['object_prompt']}, in the style of {input_data['style_prompt']}, isolated and centered in the frame not touching the edges, on a solid white flat background, clean solid edges, no fur, no hair, no fluffy details, smooth silhouette"
        
        # FLUX 1.1 Pro API input
        api_input = {
            "prompt": full_prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "png"
        }
        
        print(f"   ...calling black-forest-labs/flux-1.1-pro on Replicate")
        print(f"   ...prompt: {full_prompt[:100]}...")
        
        output = replicate.run("black-forest-labs/flux-1.1-pro", input=api_input)
        
        # DEBUG: See what FLUX actually returns
        print(f"   ...FLUX output type: {type(output)}")
        print(f"   ...FLUX output: {str(output)[:200]}")
        
        # Handle different output types from FLUX - use module-level helper
        output_url = extract_url_from_output(output)
        
        if not output_url:
            print(f"   ...ERROR: Could not extract URL from output type {type(output)}")
            return None, f"FLUX model did not return an image URL. Got: {type(output).__name__}"
        
        print(f"   ...downloading white-background image from Replicate: {output_url[:80]}...")
        image_res = requests.get(output_url)
        image_res.raise_for_status()
        
        white_filename = f"{uuid.uuid4()}_white.png"
        white_filepath = os.path.join(LIBRARY_FOLDER, white_filename)
        with open(white_filepath, "wb") as f:
            f.write(image_res.content)
        
        # TEST WORKFLOW: Remove background -> Adjust greens -> Composite on green
        print(f"   🧪 TEST: Removing white background...")
        bg_output = replicate.run(
            "851-labs/background-remover:a029dff38972b5fda4ec5d75d7d1cd25aeff621d2cf4946a41055d7db66b80bc",
            input={"image": open(white_filepath, "rb")}
        )
        
        # Handle FileOutput object properly - use extract_url_from_output helper
        result_url = extract_url_from_output(bg_output)
        if not result_url:
            return None, f"Background remover did not return an image URL. Got type: {type(bg_output)}"
        
        print(f"   ...downloading transparent image from: {result_url[:80]}...")
        transparent_res = requests.get(result_url)
        transparent_res.raise_for_status()
        transparent_filename = f"{uuid.uuid4()}_transparent.png"
        transparent_filepath = os.path.join(LIBRARY_FOLDER, transparent_filename)
        with open(transparent_filepath, "wb") as f: f.write(transparent_res.content)
        
        # NEW WORKFLOW: Only save transparent image, skip desaturation and greenscreen
        # Desaturation and greenscreen will be created ONLY when user clicks "Animate"
        print(f"   📸 Image generation complete - transparent image ready for display")
        
        # Upload transparent version (this is what user sees)
        transparent_s3_key = f"library/{os.path.basename(transparent_filepath)}"
        transparent_public_url = upload_file(transparent_filepath, transparent_s3_key)
        
        # Store transparent URL - greenscreen will be created later during animation
        result = {
            'transparent': transparent_public_url,  # User sees this in card with checkerboard
            'original': transparent_public_url,  # Keep for backward compatibility
        }
        
        print(f"   ✅ Transparent URL (Flux): {transparent_public_url}")
        print(f"   💡 Greenscreen will be created when user clicks Animate")
        
        return json.dumps(result), None
        
    except Exception as e:
        print(f"   ❌ FLUX generation error: {e}")
        traceback.print_exc()
        return None, f"FLUX generation error: {e}"

def handle_background_removal(job):
    try:
        print(f"-> Starting BRIA background removal for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        image_path = input_data.get("image_path")
        if not image_path: return None, "No image path provided for background removal."
        
        # Handle both S3 URLs and local file paths
        temp_input_file = None
        if image_path.startswith('http'):
            # It's an S3 URL - download it first
            print(f"   ...downloading image from S3: {image_path}")
            img_response = requests.get(image_path)
            img_response.raise_for_status()
            temp_filename = f"temp_{uuid.uuid4()}.png"
            temp_input_file = os.path.join(LIBRARY_FOLDER, temp_filename)
            with open(temp_input_file, "wb") as f:
                f.write(img_response.content)
            input_file_handle = open(temp_input_file, "rb")
        else:
            # It's a local path
            if image_path.startswith('/'):
                full_image_path = os.path.join(BASE_DIR, image_path.lstrip('/'))
            else:
                full_image_path = os.path.join(BASE_DIR, image_path)
            if not os.path.exists(full_image_path): 
                return None, f"File not found for background removal: {full_image_path}"
            input_file_handle = open(full_image_path, "rb")
        
        print(f"   ...uploading to Replicate (851-labs/background-remover)")
        output = replicate.run(
            "851-labs/background-remover:a029dff38972b5fda4ec5d75d7d1cd25aeff621d2cf4946a41055d7db66b80bc",
            input={
                "image": input_file_handle,
                "threshold": 0,
                "background_type": "rgba",
                "format": "png"
            }
        )
        input_file_handle.close()
        
        # Clean up temp file if we downloaded from S3
        if temp_input_file:
            try:
                os.remove(temp_input_file)
                print(f"   ...cleaned up temp input file")
            except Exception as e:
                print(f"   ...warning: could not delete temp file: {e}")
        
        print(f"   ...downloading result from Replicate")
        # Handle FileOutput object from 851-labs
        if hasattr(output, 'url'):
            result_url = output.url
        elif isinstance(output, str):
            result_url = output
        else:
            result_url = output[0] if isinstance(output, list) and output else str(output)
        print(f"   ...result URL: {result_url}")
        result_response = requests.get(result_url)
        result_response.raise_for_status()
        
        filename = f"{uuid.uuid4()}.png"
        filepath = os.path.join(LIBRARY_FOLDER, filename)
        with open(filepath, "wb") as f:
            f.write(result_response.content)
        
        print(f"   ...background removed successfully with 851-labs")
        
        # Upload to S3 if enabled
        s3_key = f"library/{filename}"
        public_url = upload_file(filepath, s3_key)
        return public_url, None
    except Exception as e:
        print(f"   ❌ Background removal error: {e}")
        traceback.print_exc()
        return None, f"851-labs background removal error: {e}"

def handle_leonardo_generation(job):
    import shutil
    import time
    try:
        print(f"-> Starting Leonardo AI image generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        model_id = input_data.get("modelId", "b24e16ff-06e3-43eb-8d33-4416c2d75876")
        preset_style = input_data.get("presetStyle", "NONE")
        
        # Shorten style prompt if too long (Leonardo has moderate limits)
        style_prompt = shorten_prompt_with_gpt(
            input_data['style_prompt'], 
            max_length=200, 
            model_name="Leonardo"
        )
        
        full_prompt = f"{input_data['object_prompt']}, in the style of {style_prompt}, centered, professional product shot"
        url = "https://cloud.leonardo.ai/api/rest/v1/generations"
        payload = {"height": 1024, "width": 1024, "modelId": model_id, "prompt": full_prompt, "num_images": 1, "presetStyle": preset_style, "transparency": "foreground_only", "negative_prompt": "text, watermark, blurry, deformed, distorted, ugly, signature"}
        headers = {"accept": "application/json", "content-type": "application/json", "authorization": f"Bearer {LEONARDO_API_KEY}"}
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            error_details = response.json().get('error', response.text)
            print(f"   Leonardo API Error: Status {response.status_code}, Details: {error_details}")
            return None, f"Leonardo API Error: {error_details}"
        generation_id = response.json()['sdGenerationJob']['generationId']
        print(f"   Job submitted with ID: {generation_id}")
        get_url = f"https://cloud.leonardo.ai/api/rest/v1/generations/{generation_id}"
        while True:
            time.sleep(8)
            response = requests.get(get_url, headers=headers)
            response.raise_for_status()
            response_data = response.json()
            status = response_data['generations_by_pk']['status']
            if status == "COMPLETE":
                image_urls = [img['url'] for img in response_data['generations_by_pk']['generated_images']]
                filepaths = []
                for url in image_urls:
                    img_res = requests.get(url)
                    transparent_filename = f"{uuid.uuid4()}_transparent.png"
                    transparent_filepath = os.path.join(LIBRARY_FOLDER, transparent_filename)
                    with open(transparent_filepath, "wb") as f: f.write(img_res.content)
                    
                    # TEST: DISABLED green adjustment - conflicts with hue shift
                    # adjust_greens_away_from_chroma(transparent_filepath)
                    
                    # Save ORIGINAL (what user sees in gallery)
                    original_filepath = transparent_filepath.replace('_transparent.png', '_ORIGINAL.png')
                    shutil.copy2(transparent_filepath, original_filepath)
                    print(f"   📸 Saved ORIGINAL: {os.path.basename(original_filepath)}")
                    
                    # DISABLED: Hue shift not needed (saturation-only approach)
                    # apply_hue_shift(transparent_filepath, shift_degrees=-30)
                    
                    # OPTIMAL: Reduce saturation to 40% for cleaner keying (validated via testing)
                    apply_saturation_adjustment(transparent_filepath, saturation_multiplier=0.4)
                    
                    # TEST: Force file sync before saving adjusted copy
                    time.sleep(0.2)  # Ensure previous saves are flushed
                    
                    # TEST: Save adjusted version for comparison (AFTER hue shift + desaturation)
                    adjusted_filepath = transparent_filepath.replace('_transparent.png', '_2_ADJUSTED.png')
                    shutil.copy2(transparent_filepath, adjusted_filepath)
                    
                    # Verify the file was created
                    if os.path.exists(adjusted_filepath):
                        print(f"   📸 Saved ADJUSTED: {os.path.basename(adjusted_filepath)} ({os.path.getsize(adjusted_filepath)} bytes)")
                    else:
                        print(f"   ⚠️ WARNING: Adjusted file not created!")
                    
                    # TEST: Composite onto pure green screen (should use the adjusted version)
                    greenscreen_filepath = composite_on_green_screen(transparent_filepath)
                    if greenscreen_filepath:
                        # Rename for clarity
                        final_greenscreen = greenscreen_filepath.replace('_transparent_greenscreen.png', '_3_GREENSCREEN.png')
                        shutil.move(greenscreen_filepath, final_greenscreen)
                        greenscreen_filepath = final_greenscreen
                        print(f"   📸 Saved GREENSCREEN: {os.path.basename(greenscreen_filepath)}")
                    else:
                        # Fallback to transparent version if composite fails
                        greenscreen_filepath = transparent_filepath
                    
                    # Upload ORIGINAL to S3 (what user sees in gallery)
                    original_s3_key = f"library/{os.path.basename(original_filepath)}"
                    original_public_url = upload_file(original_filepath, original_s3_key)
                    
                    # Also upload greenscreen version (for animation backend)
                    greenscreen_s3_key = f"library/{os.path.basename(greenscreen_filepath)}"
                    greenscreen_public_url = upload_file(greenscreen_filepath, greenscreen_s3_key)
                    
                    # Store both URLs - original for display, greenscreen for animation
                    result = {
                        'original': original_public_url,  # User sees this
                        'greenscreen': greenscreen_public_url  # Animation uses this
                    }
                    filepaths.append(json.dumps(result))
                    
                    print(f"   ✅ Original URL: {original_public_url}")
                    print(f"   ✅ Greenscreen URL: {greenscreen_public_url}")
                
                return filepaths[0], None
            elif status == "FAILED":
                return None, "Leonardo AI job failed."
    except Exception as e:
        print(f"   ❌ Leonardo generation error: {e}")
        traceback.print_exc()
        return None, f"Image generation error: {e}"

def handle_image_generation(job):
    input_data = json.loads(job['input_data'])
    
    # Support both v2 (modelId) and v3 (model) formats
    model_id = input_data.get("modelId")
    model = input_data.get("model")
    
    # v3 format: simple model names
    if model:
        if model == "seedream": return handle_bytedance_generation(job)
        elif model == "flux": return handle_flux_generation(job)
        elif model == "chatgpt": return handle_replicate_openai_generation(job)
    
    # v2 format: full model IDs (backward compatibility)
    if model_id:
        if model_id == "bytedance-seedream-4": return handle_bytedance_generation(job)
        elif model_id == "replicate-gpt-image-1": return handle_replicate_openai_generation(job)
        elif model_id == "replicate-flux-1.1-pro": return handle_flux_generation(job)
        else: return handle_leonardo_generation(job)
    
    # Default fallback
    return None, "No valid model specified"

def handle_video_generation(job, conn):
    """
    Handle video generation job - fully automated pipeline:
    1. Generate or use uploaded image
    2. Remove background if needed
    3. Desaturate + add green background
    4. Generate video
    5. Auto-key video
    6. Save PNG sequence
    """
    job_id = job['id']
    print(f"🎬 Starting video generation job {job_id}")
    
    try:
        input_data = json.loads(job['input_data'])
        prompt = input_data.get('prompt')
        uploaded_image = input_data.get('uploaded_image')
        image_model = input_data.get('image_model', 'seedream')
        video_models = input_data.get('video_model', 'seedance')
        duration = input_data.get('duration', 5)
        loop_animation = input_data.get('loop_animation', True)
        remove_bg = input_data.get('remove_bg', False)
        aspect_ratio = input_data.get('aspect_ratio', '1:1')
        
        # STEP 1: Get or generate image
        original_image_path = None
        transparent_image_path = None
        greenscreen_image_path = None
        
        if uploaded_image:
            print(f"   ✅ Using uploaded image: {uploaded_image}")
            original_image_path = uploaded_image
            transparent_image_path = uploaded_image  # Will be processed below
            # Uploaded images need processing - will be handled after bg removal step
        else:
            # Generate image using specified model
            print(f"   🎨 Generating image with {image_model} model...")
            print(f"   🎨 Prompt: {prompt}")
            
            img_gen_input = {
                "prompt": prompt,
                "model": image_model,
                "aspect_ratio": aspect_ratio
            }
            
            # Create a temporary job for image generation
            temp_job = {
                'id': f"temp_{job_id}",
                'input_data': json.dumps(img_gen_input)
            }
            
            img_result, img_error = handle_image_generation(temp_job)
            if img_error:
                return None, f"Image generation failed: {img_error}"
            
            result_obj = json.loads(img_result)
            transparent_image_path = result_obj.get('transparent', result_obj.get('original'))
            print(f"   ✅ Image generated (transparent): {transparent_image_path}")
            print(f"   💡 Processing fresh image for animation...")
            
            # Process the fresh transparent image for animation
            try:
                # Download if it's a URL
                if transparent_image_path.startswith('http'):
                    img_response = requests.get(transparent_image_path)
                    img_response.raise_for_status()
                    temp_file = f"temp_fresh_{uuid.uuid4()}.png"
                    local_image_path = os.path.join(LIBRARY_FOLDER, temp_file)
                    with open(local_image_path, 'wb') as f:
                        f.write(img_response.content)
                else:
                    local_image_path = os.path.join(BASE_DIR, transparent_image_path.lstrip('/'))
                
                # Apply desaturation
                apply_saturation_adjustment(local_image_path, saturation_multiplier=0.4)
                print(f"   ✅ Desaturated fresh image")
                
                # SMART COLOR DETECTION: Detect dominant color and choose screen color
                screen_color = detect_dominant_color(local_image_path)
                
                # Composite on colored screen (green or blue)
                screen_path, actual_color = composite_on_colored_screen(local_image_path, screen_color)
                if screen_path:
                    image_path = screen_path
                    print(f"   ✅ Fresh image on {actual_color} screen: {image_path}")
                else:
                    image_path = local_image_path
                    print(f"   ⚠️ Screen composite failed, using desaturated image")
            except Exception as e:
                print(f"   ⚠️ Image processing failed: {e}, using transparent")
                traceback.print_exc()
                image_path = transparent_image_path
        
        # STEP 2: Handle background removal and processing for uploaded images
        if uploaded_image:
            # Check if image is already processed (from "Animate" button on existing job)
            # Make the check case-insensitive to catch both _greenscreen.png and _GREENSCREEN.png
            uploaded_lower = uploaded_image.lower()
            is_already_processed = any(indicator in uploaded_lower for indicator in [
                '_greenscreen', '_bluescreen', '_adjusted'
            ])
            
            if is_already_processed:
                print(f"   ♻️ Image already processed (detected: {uploaded_image}), skipping desaturation/screen composite")
                image_path = uploaded_image
            elif remove_bg:
                print(f"   🔄 Attempting background removal...")
                try:
                    from rembg import remove
                    from PIL import Image as PILImage
                    import io
                    
                    # Download if S3 URL
                    if uploaded_image.startswith('http'):
                        img_response = requests.get(uploaded_image)
                        img_response.raise_for_status()
                        input_img = PILImage.open(io.BytesIO(img_response.content))
                    else:
                        img_path = os.path.join(BASE_DIR, uploaded_image.lstrip('/'))
                        input_img = PILImage.open(img_path)
                    
                    # Remove background
                    output_img = remove(input_img)
                    
                    # Save transparent image
                    transparent_filename = f"transparent_{uuid.uuid4()}.png"
                    transparent_path = os.path.join(LIBRARY_FOLDER, transparent_filename)
                    output_img.save(transparent_path)
                    
                    image_path = f'static/library/{transparent_filename}'
                    print(f"   ✅ Background removed: {image_path}")
                    
                    # Now process this transparent image
                    # STEP 2.5: Process uploaded image same as generated images
                    # Apply desaturation and green screen compositing
                    print(f"   🎨 Processing uploaded image for animation...")
                    try:
                        local_image_path = transparent_path
                        
                        # Apply desaturation (same as image generation)
                        apply_saturation_adjustment(local_image_path, saturation_multiplier=0.4)
                        print(f"   ✅ Desaturated uploaded image")
                        
                        # SMART COLOR DETECTION: Detect dominant color and choose screen color
                        screen_color = detect_dominant_color(local_image_path)
                        
                        # Composite on colored screen (green or blue)
                        screen_path, actual_color = composite_on_colored_screen(local_image_path, screen_color)
                        if screen_path:
                            image_path = screen_path
                            print(f"   ✅ Uploaded image on {actual_color} screen: {image_path}")
                        else:
                            print(f"   ⚠️ Screen composite failed, using desaturated image")
                    except Exception as e:
                        print(f"   ⚠️ Image processing failed: {e}, using transparent")
                        traceback.print_exc()
                        
                except ImportError:
                    print(f"   ⚠️ rembg not installed, skipping background removal")
                except Exception as e:
                    print(f"   ⚠️ Background removal failed: {e}")
            else:
                # Image has transparent background but needs processing
                # STEP 2.5: Process uploaded image same as generated images
                # Apply desaturation and green screen compositing
                print(f"   🎨 Processing uploaded image for animation...")
                try:
                    # Get the local file path
                    if uploaded_image.startswith('http'):
                        img_response = requests.get(uploaded_image)
                        img_response.raise_for_status()
                        temp_file = f"temp_upload_{uuid.uuid4()}.png"
                        local_image_path = os.path.join(LIBRARY_FOLDER, temp_file)
                        with open(local_image_path, 'wb') as f:
                            f.write(img_response.content)
                    else:
                        local_image_path = os.path.join(BASE_DIR, uploaded_image.lstrip('/'))
                    
                    # Apply desaturation (same as image generation)
                    apply_saturation_adjustment(local_image_path, saturation_multiplier=0.4)
                    print(f"   ✅ Desaturated uploaded image")
                    
                    # SMART COLOR DETECTION: Detect dominant color and choose screen color
                    screen_color = detect_dominant_color(local_image_path)
                    
                    # Composite on colored screen (green or blue)
                    screen_path, actual_color = composite_on_colored_screen(local_image_path, screen_color)
                    if screen_path:
                        image_path = screen_path
                        print(f"   ✅ Uploaded image on {actual_color} screen: {image_path}")
                    else:
                        image_path = local_image_path
                        print(f"   ⚠️ Screen composite failed, using desaturated image")
                except Exception as e:
                    print(f"   ⚠️ Image processing failed: {e}, using original")
                    traceback.print_exc()
                    image_path = uploaded_image
        
        # STEP 3: Prepare animation input using existing handle_animation
        print(f"   🎬 Preparing video generation...")
        
        # Convert absolute path to relative path for animation
        if image_path.startswith(BASE_DIR):
            image_path = image_path.replace(BASE_DIR + '/', '')
            print(f"   🔧 Converted to relative path: {image_path}")
        
        # Handle multiple video models (comma-separated)
        model_list = [m.strip() for m in video_models.split(',') if m.strip()]
        print(f"   📹 Video models requested: {model_list}")
        
        # Create animation job(s) - one per model if multiple selected
        animation_job_ids = []
        cursor = conn.cursor()
        
        for video_model in model_list:
            # Create animation input data
            animation_input = {
                "prompt": prompt,
                "image_url": image_path,
                "video_model": video_model,  # Single model, not comma-separated
                "duration": duration,
                "aspect_ratio": aspect_ratio
            }
            
            if loop_animation:
                # Use same image as end frame for seamless loop
                animation_input["end_image_url"] = image_path
                animation_input["last_frame_url"] = image_path
            
            # Create a temporary animation job
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                ('animation', 'processing', datetime.now(), prompt, json.dumps(animation_input), job_id)
            )
            conn.commit()
            animation_job_id = cursor.lastrowid
            animation_job_ids.append(animation_job_id)
            print(f"   ✅ Created animation sub-job {animation_job_id} with model: {video_model}")
        
        # Use the first animation job for keying
        animation_job_id = animation_job_ids[0]
        
        # Fetch and process the animation job
        animation_job = conn.execute("SELECT * FROM jobs WHERE id = ?", (animation_job_id,)).fetchone()
        animation_result, animation_error = handle_animation(dict(animation_job))
        
        if animation_error:
            conn.execute(
                "UPDATE jobs SET status = ?, error_message = ? WHERE id = ?",
                ('failed', animation_error, animation_job_id)
            )
            conn.commit()
            return None, f"Animation generation failed: {animation_error}"
        
        # Update animation job as completed
        # animation_result is the video URL string from handle_animation
        video_path = animation_result
        conn.execute(
            "UPDATE jobs SET status = ?, result_data = ? WHERE id = ?",
            ('completed', video_path, animation_job_id)
        )
        conn.commit()
        
        print(f"   ✅ Video generated: {video_path}")
        
        # STEP 3.5: Upscale the video to 1080p
        print(f"   🔼 Upscaling video to 1080p...")
        upscaled_path, upscale_error = upscale_video(video_path, target_resolution="1080p", target_fps=30)
        
        if upscale_error:
            print(f"   ⚠️ Upscale failed, using original video: {upscale_error}")
            # Continue with original video if upscale fails
            final_video_path = video_path
        else:
            print(f"   ✅ Video upscaled: {upscaled_path}")
            final_video_path = upscaled_path
            
            # Update animation job with upscaled video
            conn.execute(
                "UPDATE jobs SET result_data = ? WHERE id = ?",
                (upscaled_path, animation_job_id)
            )
            conn.commit()
        
        # STEP 4: Auto-key the video (using upscaled version)
        print(f"   🔑 Queuing auto-keying job...")
        
        keying_input = {
            "video_url": final_video_path,  # handle_keying expects 'video_url', not 'video_path'
            "source_job_id": animation_job_id,
            # Green screen keying settings - updated parameters
            "hue_center": 60,  # Green hue (or 240 for blue screen)
            "hue_tolerance": 25,
            "saturation_min": 140,  # Reduced from 160 to catch more greens
            "value_min": 80,  # Increased from 50 for better bright green isolation
            "erode": 2,  # Choke edges inward
            "dilate": 2,  # Soften edges outward
            "blur": 5,  # Edge blur
            "spill_amount": 0.25,  # 5/20 from slider
            "export_png_zip": True  # Always export PNG sequence
        }
        
        cursor.execute(
            "INSERT INTO jobs (job_type, status, created_at, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?)",
            ('keying', 'keying_queued', datetime.now(), json.dumps(keying_input), job_id)
        )
        conn.commit()
        keying_job_id = cursor.lastrowid
        print(f"   ✅ Created keying sub-job {keying_job_id} (will be processed by worker)")
        
        # Return result as JSON string for database storage
        result_data = {
            "image_path": image_path,
            "video_path": final_video_path,  # Use upscaled path if available
            "original_video_path": video_path,  # Keep original for reference
            "upscaled": final_video_path != video_path,  # Flag if upscaling was successful
            "animation_job_id": animation_job_id,
            "keying_job_id": keying_job_id,
            "status": "Video generated, upscaled, keying queued" if final_video_path != video_path else "Video generated, keying queued"
        }
        
        print(f"🎉 Video generation complete! Keying will process automatically.")
        return json.dumps(result_data), None
        
    except Exception as e:
        print(f"❌ Error in video generation: {e}")
        traceback.print_exc()
        return None, str(e)

def handle_openai_vision_analysis(job):
    temp_image = None
    if not OPENAI_API_KEY: return None, "OpenAI API key is not initialized. Check API keys."
    try:
        job_type = job['job_type'].replace('_', ' ').capitalize()
        print(f"-> Starting OpenAI GPT-4o Vision Analysis ({job_type}) for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        print(f"   DEBUG: input_data keys: {input_data.keys()}")
        print(f"   DEBUG: image_path from input_data: {input_data.get('image_path', 'NOT FOUND')}")
        system_prompt = input_data.get('system_prompt', 'Analyze this image.')
        
        # Handle both S3 URLs and local file paths
        image_url = input_data['image_path']
        if image_url.startswith('http'):
            # It's an S3 URL - download it first
            print(f"   ...downloading image from S3: {image_url}")
            img_response = requests.get(image_url)
            img_response.raise_for_status()
            temp_image = f"temp_analysis_{uuid.uuid4()}.png"
            image_path = os.path.join(LIBRARY_FOLDER, temp_image)
            with open(image_path, "wb") as f:
                f.write(img_response.content)
        else:
            image_path = os.path.join(BASE_DIR, image_url.lstrip('/'))
            if not os.path.exists(image_path): 
                return None, f"Image file not found at {image_path}"
        
        print(f"   DEBUG: Full image path: {image_path}")
        print(f"   DEBUG: Image file exists: {os.path.exists(image_path)}")
        
        # Determine the appropriate user message based on job type
        # For vision models, combine system prompt with user message for better instruction following
        if job['job_type'] == 'style_analysis':
            user_message = f"{system_prompt}\n\nNow analyze this image's visual style following the guidelines above."
        elif job['job_type'] == 'palette_analysis':
            user_message = f"{system_prompt}\n\nNow analyze the color palette of this image."
        else:  # animation_prompting
            user_message = f"{system_prompt}\n\nNow provide animation ideas for this image."
        
        print(f"   ...calling OpenAI GPT-4o Vision API")
        print(f"   ...combined prompt length: {len(user_message)}")
        print(f"   ...user message preview: {user_message[:150]}...")
        
        # Encode image to base64
        import base64
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        
        # Use OpenAI's GPT-4o Vision model directly
        # Note: For vision models, instructions work better in the user message with the image
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_message
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=600,  # Reduced to ensure shorter responses (under 1200 chars for Leonardo)
            temperature=0.7
        )
        
        analysis_text = response.choices[0].message.content
        
        print(f"   ...OpenAI GPT-4o analysis complete. Result length: {len(analysis_text) if analysis_text else 0}")
        if analysis_text:
            print(f"   ...Result preview: {analysis_text[:100]}...")
        else:
            print("   ...WARNING: Empty result from OpenAI!")
        
        # Clean up temp file if we downloaded from S3
        if temp_image:
            try:
                os.remove(os.path.join(LIBRARY_FOLDER, temp_image))
                print(f"   ...cleaned up temp image")
            except Exception as e:
                print(f"   ...warning: could not delete temp image: {e}")
            
        return analysis_text if analysis_text else None, None if analysis_text else "Empty response from OpenAI GPT-4o"
    except Exception as e:
        # Clean up temp file on error too
        if temp_image:
            try:
                os.remove(os.path.join(LIBRARY_FOLDER, temp_image))
            except:
                pass
        return None, f"OpenAI GPT-4o Vision API error: {e}"

def detect_screen_color_from_video(video_path):
    """
    Detect if video has green or blue screen by sampling background pixels.
    Returns 'green' or 'blue'.
    """
    try:
        import cv2
        from colorsys import rgb_to_hsv
        
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return 'green'  # Default
        
        # Sample corner pixels (background)
        h, w = frame.shape[:2]
        corners = [
            frame[0:10, 0:10],  # Top-left
            frame[0:10, w-10:w],  # Top-right
            frame[h-10:h, 0:10],  # Bottom-left
            frame[h-10:h, w-10:w]  # Bottom-right
        ]
        
        # Calculate average hue of corner pixels
        hues = []
        for corner in corners:
            bgr = corner.reshape(-1, 3)
            rgb = bgr[:, [2, 1, 0]] / 255.0  # BGR to RGB, normalize
            for pixel in rgb:
                h, s, v = rgb_to_hsv(pixel[0], pixel[1], pixel[2])
                if s > 0.5 and v > 0.5:  # Only saturated pixels
                    hues.append(h)
        
        if len(hues) == 0:
            return 'green'  # Default
        
        avg_hue = sum(hues) / len(hues)
        # Green: 60-180° = 0.167-0.5
        # Blue: 180-270° = 0.5-0.75
        if 0.45 < avg_hue < 0.85:  # Blue range (with margin)
            print(f"   🔵 Detected BLUE screen (hue: {avg_hue*360:.0f}°)")
            return 'blue'
        else:
            print(f"   🟢 Detected GREEN screen (hue: {avg_hue*360:.0f}°)")
            return 'green'
            
    except Exception as e:
        print(f"   ⚠️ Screen color detection error: {e}, defaulting to green")
        return 'green'

def handle_keying(job):
    temp_video = None
    try:
        job_id = job['id']
        print(f"-> Starting OpenCV keying for job #{job_id}...")
        print(f"   JOB #{job_id}: Job type: {job['job_type']}")
        
        # Parse input_data to get video URL/path
        input_data = json.loads(job['input_data'])
        video_url = input_data.get('video_url') or input_data.get('video_path')
        
        print(f"   JOB #{job_id}: Input video URL/path: {video_url}")
        
        # Validate video_url is not None
        if not video_url:
            error_msg = "No video_url or video_path provided in input_data for keying job."
            print(f"   JOB #{job_id}: ERROR - {error_msg}")
            return None, error_msg
        
        # Parse keying settings - check keying_settings column first (for auto-keying jobs), then input_data
        if job['keying_settings']:
            try:
                settings = json.loads(job['keying_settings'])
                print(f"   JOB #{job_id}: Using settings from keying_settings column")
            except:
                settings = input_data
                print(f"   JOB #{job_id}: Failed to parse keying_settings, using input_data")
        else:
            settings = input_data  # Settings are directly in input_data for manual keying jobs
            print(f"   JOB #{job_id}: Using settings from input_data")

        # Check if sticker effect OR posterize OR any exports are requested BEFORE processing
        sticker_effect_requested = settings.get('sticker_effect', False)
        posterize_requested = settings.get('posterize_enabled', False)
        export_gif = settings.get('export_gif', False)
        export_png_zip = settings.get('export_png_zip', False)
        skip_encoding_needed = sticker_effect_requested or posterize_requested or export_gif or export_png_zip

        # Optional: Use Blender server if configured and no post-processing is needed
        blender_server_url = os.getenv("BLENDER_SERVER_URL")
        blender_api_key = os.getenv("BLENDER_SERVER_API_KEY")
        if blender_server_url and blender_api_key and video_url.startswith('http') and not skip_encoding_needed:
            detected_screen_color = (
                settings.get('screen_color')
                or settings.get('key_color')
                or 'green'
            )
            blender_params = {
                "key_color": detected_screen_color,
                "clip_white": settings.get("clip_white", settings.get("white_level", 0.887)),
                "saturation": settings.get("saturation", 1.5),
                "curve_x": settings.get("curve_x", 0.6),
                "curve_y": settings.get("curve_y", 0.7),
                "crf": settings.get("crf", "LOSSLESS"),
                "gopsize": settings.get("gopsize", 18),
                "threads": settings.get("threads", 4),
            }
            try:
                print(f"   JOB #{job_id}: 🚀 Sending to Blender server for keying...")
                response = requests.post(
                    f"{blender_server_url.rstrip('/')}/key_video",
                    json={"video_url": video_url, "job_id": job_id, "params": blender_params},
                    headers={"X-API-Key": blender_api_key},
                    timeout=900,
                )
                if response.ok:
                    data = response.json()
                    if data.get("success") and data.get("result_url"):
                        result_data = {
                            "webm": data["result_url"],
                            "gif": None,
                            "png_zip": None,
                            "png_sequence_path": None,
                        }
                        result_json = json.dumps(result_data)
                        print(f"   JOB #{job_id}: 🎉 Blender keying complete: {result_json}")
                        return result_json, None
                print(f"   JOB #{job_id}: ⚠️ Blender server failed, falling back to OpenCV")
            except Exception as e:
                print(f"   JOB #{job_id}: ⚠️ Blender server error: {e}, falling back to OpenCV")

        if video_url.startswith('http'):
            # It's an S3 URL - download it first
            print(f"   JOB #{job_id}: Downloading video from S3...")
            vid_response = requests.get(video_url)
            vid_response.raise_for_status()
            temp_video = f"temp_keying_{uuid.uuid4()}.mp4"
            greenscreen_video_path = os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video)
            with open(greenscreen_video_path, "wb") as f:
                f.write(vid_response.content)
            print(f"   JOB #{job_id}: Downloaded {len(vid_response.content)} bytes to {greenscreen_video_path}")
        else:
            # It's a local path
            greenscreen_video_path = os.path.join(BASE_DIR, video_url.lstrip('/'))
            if not os.path.exists(greenscreen_video_path):
                error_msg = f"Input video file not found: {greenscreen_video_path}"
                print(f"   JOB #{job_id}: ERROR - {error_msg}")
                return None, error_msg
            
        print(f"   JOB #{job_id}: Full input path: {greenscreen_video_path}")
        print(f"   JOB #{job_id}: File exists: {os.path.exists(greenscreen_video_path)}")
        print(f"   JOB #{job_id}: File size: {os.path.getsize(greenscreen_video_path)} bytes")
        
        # AUTO-DETECT screen color from video
        detected_screen_color = detect_screen_color_from_video(greenscreen_video_path)
        
        # SMART KEYING: Adjust hue_center based on detected screen color
        if detected_screen_color == 'blue':
            settings['hue_center'] = 120  # Blue hue in OpenCV HSV (0-180 range, 240° / 2 = 120)
            settings['hue_tolerance'] = 25
            print(f"   🔵 BLUE screen detected! Adjusted hue_center to 120")
        else:
            # Default green settings
            if 'hue_center' not in settings:
                settings['hue_center'] = 60  # Green hue
        
        print(f"   JOB #{job_id}: Keying settings: {settings}")
        
        # Generate unique output filename
        output_filename = f"keyed_{job_id}_{uuid.uuid4().hex[:8]}.webm"
        final_output_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, output_filename)
        print(f"   JOB #{job_id}: Output will be: {final_output_path}")
        
        # Prepare keying parameters
        lower_green = [settings['hue_center'] - settings['hue_tolerance'], settings['saturation_min'], settings['value_min']]
        upper_green = [settings['hue_center'] + settings['hue_tolerance'], 255, 255]
        print(f"   JOB #{job_id}: Color range - Lower: {lower_green}, Upper: {upper_green}")
        
        # Initialize export URLs (will be set if exports are requested)
        gif_url = None
        zip_url = None
        
        # Process video (keying)
        print(f"   JOB #{job_id}: ▶️  Starting video keying...")
        if skip_encoding_needed:
            effects_list = []
            if sticker_effect_requested:
                effects_list.append("sticker effects")
            if posterize_requested:
                effects_list.append("posterize time")
            if export_gif:
                effects_list.append("GIF export")
            if export_png_zip:
                effects_list.append("PNG ZIP export")
            print(f"   JOB #{job_id}: 🎨 {', '.join(effects_list)} requested - will skip encoding until after processing")
        
        keying_result = process_video_with_opencv(
            video_path=greenscreen_video_path, 
            output_path=final_output_path, 
            lower_green=lower_green, 
            upper_green=upper_green, 
            erode_amount=settings['erode'], 
            dilate_amount=settings['dilate'], 
            blur_amount=settings['blur'], 
            spill_amount=settings.get('spill', 10) / 20.0,  # Normalize 0-20 slider to 0.0-1.0 range
            skip_encoding=skip_encoding_needed,  # Skip encoding if any post-effects will be applied
            job_id=job_id,  # Unique temp directory to prevent parallel job conflicts
            # Post-keying effects (optional)
            motion_blur=False,  # DISABLED - not working well on alpha edges
            motion_blur_strength=0,
            light_wrap=settings.get('light_wrap', False),
            light_wrap_intensity=settings.get('light_wrap_intensity', 0.3),
            light_wrap_thickness=settings.get('light_wrap_thickness', 5),
            screen_color=detected_screen_color  # Pass detected screen color to exclude from saturation boost
        )
        
        # If any post-processing is requested, keying_result = (fps, frame_count, keyed_frames_dir)
        if skip_encoding_needed:
            fps, frame_count, keyed_frames_dir = keying_result
            print(f"   JOB #{job_id}: ✅ Keying complete - {frame_count} frames saved to {keyed_frames_dir}")
            
            # STEP 1: Apply sticker effects if requested
            if sticker_effect_requested:
                print(f"   JOB #{job_id}: 🎨 Applying sticker effects to keyed frames...")
                
                # Get sticker effect parameters
                displacement_intensity = settings.get('displacement_intensity', 50)
                darker_opacity = settings.get('darker_opacity', 1.0)
                screen_opacity = settings.get('screen_opacity', 0.7)
                enable_bevel = settings.get('enable_bevel', False)
                bevel_depth = settings.get('bevel_depth', 3)
                bevel_highlight = settings.get('bevel_highlight', 0.5)
                bevel_shadow = settings.get('bevel_shadow', 0.5)
                enable_alpha_bevel = settings.get('enable_alpha_bevel', False)
                alpha_bevel_size = settings.get('alpha_bevel_size', 15)
                alpha_bevel_blur = settings.get('alpha_bevel_blur', 2)
                alpha_bevel_angle = settings.get('alpha_bevel_angle', 70)
                alpha_bevel_highlight = settings.get('alpha_bevel_highlight', 0.6)
                alpha_bevel_shadow = settings.get('alpha_bevel_shadow', 0.6)
                enable_shadow = settings.get('enable_shadow', False)
                shadow_blur = settings.get('shadow_blur', 0)
                shadow_x = settings.get('shadow_x', 1)
                shadow_y = settings.get('shadow_y', 1)
                shadow_opacity = settings.get('shadow_opacity', 1.0)
                
                print(f"      Displacement: {displacement_intensity}, Multiply: {darker_opacity}, Add: {screen_opacity}")
                print(f"      Surface bevel: {enable_bevel}, Alpha bevel: {enable_alpha_bevel}, Drop shadow: {enable_shadow}")
                
                # Load textures
                disp_textures = load_texture_sequence(TEXTURE_DISPLACEMENT_FOLDER)
                screen_textures = load_texture_sequence(TEXTURE_SCREEN_FOLDER)
                print(f"   JOB #{job_id}: 📦 Loaded {len(disp_textures)} displacement textures, {len(screen_textures)} screen textures")
                
                # Load peel frames if provided (pre-rendered at 8 FPS)
                peel_frames = []
                peel_frame_paths = settings.get('peel_frame_paths', [])
                if peel_frame_paths:
                    print(f"   JOB #{job_id}: 📄 Loading {len(peel_frame_paths)} peel frames at 8 FPS...")
                    for peel_path in peel_frame_paths:
                        full_path = os.path.join(BASE_DIR, peel_path)
                        if os.path.exists(full_path):
                            peel_frames.append(Image.open(full_path).convert('RGBA'))
                        else:
                            print(f"      ⚠️ Peel frame not found: {full_path}")
                    print(f"   JOB #{job_id}: ✅ Loaded {len(peel_frames)} peel frames")
                
                # Process each keyed frame with sticker effects
                for frame_idx in range(frame_count):
                    frame_filename = f"frame_{frame_idx:05d}.png"
                    frame_path = os.path.join(keyed_frames_dir, frame_filename)
                    
                    if not os.path.exists(frame_path):
                        print(f"   ⚠️ Warning: Frame {frame_idx} not found at {frame_path}")
                        continue
                    
                    # Read keyed frame as PIL Image with alpha
                    frame_pil = Image.open(frame_path).convert('RGBA')
                    
                    # Get animated textures for this frame
                    disp_texture = disp_textures[frame_idx % len(disp_textures)] if disp_textures else None
                    screen_texture = screen_textures[frame_idx % len(screen_textures)] if screen_textures else None
                    
                    # Get peel frame for this video frame (8 FPS: each peel frame used for 3 video frames at 24 FPS)
                    peel_frame = None
                    if peel_frames:
                        peel_frame_index = frame_idx // 3  # Integer division: 0,1,2->0, 3,4,5->1, etc.
                        if peel_frame_index < len(peel_frames):
                            peel_frame = peel_frames[peel_frame_index]
                    
                    # Resize textures to match frame size
                    if disp_texture:
                        disp_texture = disp_texture.resize(frame_pil.size, Image.LANCZOS)
                    if screen_texture:
                        screen_texture = screen_texture.resize(frame_pil.size, Image.LANCZOS)
                    
                    # Apply sticker effects to this frame
                    processed_frame = apply_sticker_effect_to_frame(
                        frame_pil, disp_texture, screen_texture,
                        displacement_intensity, darker_opacity, screen_opacity,
                        enable_bevel, bevel_depth, bevel_highlight, bevel_shadow,
                        enable_alpha_bevel, alpha_bevel_size, alpha_bevel_blur, 
                        alpha_bevel_angle, alpha_bevel_highlight, alpha_bevel_shadow,
                        enable_shadow, shadow_blur, shadow_x, shadow_y, shadow_opacity,
                        peel_frame
                    )
                    
                    # Save processed frame (overwrite the keyed frame)
                    processed_frame.save(frame_path, 'PNG')
                    
                    # CRITICAL: Clear frame from memory immediately to prevent accumulation
                    del frame_pil, processed_frame
                    if disp_texture:
                        del disp_texture
                    if screen_texture:
                        del screen_texture
                    
                    if frame_idx % 10 == 0 and frame_idx > 0:
                        print(f"      Processed {frame_idx}/{frame_count} frames...")
                        log_memory(job_id, f"at frame {frame_idx}/{frame_count}")
                        clear_memory()  # Periodic cleanup during processing
                
                print(f"   JOB #{job_id}: ✅ All {frame_count} frames processed with sticker effects")
                log_memory(job_id, "after sticker effects")
                clear_memory()  # Force cleanup before next step
            
            # STEP 2: Apply posterize time if requested
            # Convert fps to integer (ffmpeg can have issues with float framerates like "24.0")
            output_fps = int(round(fps)) if fps else 24
            if posterize_requested:
                target_fps = int(settings.get('posterize_fps', 12))  # Convert to int
                print(f"   JOB #{job_id}: ⏱️  Applying posterize time: {fps}fps → {target_fps}fps")
                
                # Calculate frame interval: keep every Nth frame
                frame_interval = int(fps / target_fps)
                print(f"   JOB #{job_id}: 📐 Frame interval: keeping every {frame_interval} frame(s)")
                
                # Get all frame files
                all_frames = sorted([f for f in os.listdir(keyed_frames_dir) if f.startswith('frame_') and f.endswith('.png')])
                print(f"   JOB #{job_id}: 📋 Found {len(all_frames)} total frames")
                
                # Delete frames that don't match the interval
                frames_to_keep = []
                for i, frame_file in enumerate(all_frames):
                    if i % frame_interval == 0:
                        frames_to_keep.append(frame_file)
                    else:
                        frame_path = os.path.join(keyed_frames_dir, frame_file)
                        os.remove(frame_path)
                
                print(f"   JOB #{job_id}: 🗑️  Deleted {len(all_frames) - len(frames_to_keep)} frames, kept {len(frames_to_keep)}")
                
                # Rename remaining frames to be sequential
                for new_idx, old_frame_file in enumerate(frames_to_keep):
                    old_path = os.path.join(keyed_frames_dir, old_frame_file)
                    new_filename = f"frame_{new_idx:05d}.png"
                    new_path = os.path.join(keyed_frames_dir, new_filename)
                    
                    if old_path != new_path:
                        os.rename(old_path, new_path)
                
                print(f"   JOB #{job_id}: ✅ Frames renumbered sequentially: 0 to {len(frames_to_keep)-1}")
                
                # Update frame count and output FPS
                frame_count = len(frames_to_keep)
                output_fps = target_fps
                print(f"   JOB #{job_id}: 🎬 Will encode at {output_fps}fps for stop-motion effect")
                log_memory(job_id, "after posterize time")
                clear_memory()  # Force cleanup before encoding
            
            # STEP 3: Export GIF if requested
            gif_url = None
            if settings.get('export_gif', False):
                print(f"   JOB #{job_id}: 🎞️  Exporting GIF from PNG sequence...")
                gif_filename = f"keyed_{job_id}_{uuid.uuid4().hex[:8]}.gif"
                gif_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, gif_filename)
                
                try:
                    # Use ffmpeg to create GIF with good quality and transparency support
                    # Create palette first for better quality
                    palette_path = os.path.join(keyed_frames_dir, 'palette.png')
                    palette_cmd = [
                        'ffmpeg', '-y',
                        '-framerate', str(output_fps),
                        '-i', os.path.join(keyed_frames_dir, 'frame_%05d.png'),
                        '-vf', 'palettegen=stats_mode=diff',
                        palette_path
                    ]
                    subprocess.run(palette_cmd, capture_output=True, check=True)
                    
                    # Generate GIF using the palette
                    gif_cmd = [
                        'ffmpeg', '-y',
                        '-framerate', str(output_fps),
                        '-i', os.path.join(keyed_frames_dir, 'frame_%05d.png'),
                        '-i', palette_path,
                        '-lavfi', 'paletteuse=dither=bayer:bayer_scale=5',
                        gif_path
                    ]
                    result = subprocess.run(gif_cmd, capture_output=True, text=True)
                    
                    if result.returncode == 0:
                        # Upload to S3 if enabled
                        s3_key = f"library/transparent_videos/{gif_filename}"
                        gif_url = upload_file(gif_path, s3_key)
                        print(f"   JOB #{job_id}: ✅ GIF exported: {gif_url}")
                    else:
                        print(f"   JOB #{job_id}: ⚠️ GIF export failed: {result.stderr}")
                except Exception as e:
                    print(f"   JOB #{job_id}: ⚠️ GIF export error: {e}")
            
            # STEP 4: Export PNG sequence as ZIP if requested
            zip_url = None
            if settings.get('export_png_zip', False):
                print(f"   JOB #{job_id}: 📦 Exporting PNG sequence as ZIP...")
                zip_filename = f"keyed_{job_id}_{uuid.uuid4().hex[:8]}.zip"
                zip_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, zip_filename)
                
                try:
                    import zipfile
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
                        frame_files = sorted([f for f in os.listdir(keyed_frames_dir) if f.startswith('frame_') and f.endswith('.png')])
                        for frame_file in frame_files:
                            frame_path = os.path.join(keyed_frames_dir, frame_file)
                            zipf.write(frame_path, arcname=frame_file)
                    
                    # Upload to S3 if enabled
                    s3_key = f"library/transparent_videos/{zip_filename}"
                    zip_url = upload_file(zip_path, s3_key)
                    print(f"   JOB #{job_id}: ✅ PNG ZIP exported ({len(frame_files)} frames): {zip_url}")
                except Exception as e:
                    print(f"   JOB #{job_id}: ⚠️ PNG ZIP export error: {e}")
            
            # STEP 4a: Restore saturation to original vibrancy (0.4 × 2.5 = 1.0), EXCLUDING screen color
            screen_color_msg = detected_screen_color.upper() if detected_screen_color else "UNKNOWN"
            print(f"   JOB #{job_id}: 🎨 Restoring saturation on {len([f for f in os.listdir(keyed_frames_dir) if f.startswith('frame_')])} keyed frames (40% → 100%, {screen_color_msg} excluded)...")
            all_frames_after_processing = sorted([f for f in os.listdir(keyed_frames_dir) if f.startswith('frame_') and f.endswith('.png')])
            frames_saturation_restored = 0
            for frame_file in all_frames_after_processing:
                frame_path = os.path.join(keyed_frames_dir, frame_file)
                if apply_saturation_adjustment(frame_path, saturation_multiplier=2.5, screen_color=detected_screen_color):  # Exclude screen color from boost
                    frames_saturation_restored += 1
            print(f"   JOB #{job_id}: ✅ Saturation restored on {frames_saturation_restored}/{len(all_frames_after_processing)} frames")
            
            # STEP 4b: DISABLED - No hue shift reversal (saturation-only approach validated via testing)
            # Hue shift was disabled in the pre-animation phase, so there's nothing to reverse
            
            # STEP 4c: DISABLED - Green adjustment no longer used
            # print(f"   JOB #{job_id}: 🔄 TEST: Reversing green adjustment on all frames to restore original colors...")
            # frames_green_reversed = 0
            # for frame_file in all_frames_after_processing:
            #     frame_path = os.path.join(keyed_frames_dir, frame_file)
            #     if reverse_green_adjustment(frame_path):
            #         frames_green_reversed += 1
            # print(f"   JOB #{job_id}: ✅ Reversed green adjustment on {frames_green_reversed}/{len(all_frames_after_processing)} frames")
            
            print(f"   JOB #{job_id}: 🎬 Now encoding to final transparent WebM...")
            log_memory(job_id, "before encoding")
            
            # Encode the processed frames to WebM with transparency
            # Use output_fps (which may be modified by posterize time)
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-framerate', str(output_fps),
                '-i', os.path.join(keyed_frames_dir, 'frame_%05d.png'),
                '-c:v', 'libvpx-vp9',
                '-pix_fmt', 'yuva420p',
                '-crf', '4',  # Near-lossless quality (changed from 15)
                '-b:v', '0',
                final_output_path
            ]
            
            print(f"   📝 FFmpeg command: {' '.join(ffmpeg_cmd)}")
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"   ❌ FFmpeg encoding error: {result.stderr}")
                print(f"   📄 FFmpeg stdout: {result.stdout}")
                shutil.rmtree(keyed_frames_dir, ignore_errors=True)
                return None, "FFmpeg encoding failed after sticker effects"
            
            # Verify output
            verify_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
                          '-show_entries', 'stream=pix_fmt', '-of', 'default=noprint_wrappers=1:nokey=1', 
                          final_output_path]
            verify_result = subprocess.run(verify_cmd, capture_output=True, text=True)
            output_pix_fmt = verify_result.stdout.strip()
            print(f"   🔍 Output pixel format: {output_pix_fmt}")
            if 'yuva' not in output_pix_fmt:
                print(f"   ⚠️ WARNING: Output video may not have alpha channel! Got {output_pix_fmt} instead of yuva420p")
            
            # PRESERVE PNG sequence for post-processing (trim/loop creator)
            print(f"   JOB #{job_id}: 💾 Preserving PNG sequence at: {keyed_frames_dir}")
            print(f"   JOB #{job_id}: 📁 Sequence contains {len(all_frames_after_processing)} frames")
            # Store the relative path for database (now in organized png_sequences folder)
            png_sequence_relative_path = f"/static/library/transparent_videos/png_sequences/keyed_frames_{job_id}/"
            clear_memory()  # Cleanup memory
            log_memory(job_id, "after encoding")
            
        else:
            # No sticker effects - video was encoded directly by process_video_with_opencv
            print(f"   JOB #{job_id}: ✅ Keying completed (no sticker effects)")
            
            # Extract and save PNG sequence for v3 UI (even without sticker effects)
            print(f"   JOB #{job_id}: 📸 Extracting PNG sequence from keyed video...")
            # Store in organized png_sequences folder
            png_sequence_dir = os.path.join(TRANSPARENT_VIDEOS_FOLDER, "png_sequences", f"keyed_frames_{job_id}")
            os.makedirs(png_sequence_dir, exist_ok=True)
            
            try:
                # Extract frames from the output video
                extract_cmd = [
                    'ffmpeg', '-i', final_output_path,
                    '-vsync', '0',
                    os.path.join(png_sequence_dir, 'frame_%05d.png')
                ]
                result = subprocess.run(extract_cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    frame_count = len([f for f in os.listdir(png_sequence_dir) if f.endswith('.png')])
                    print(f"   JOB #{job_id}: ✅ Extracted {frame_count} PNG frames")
                    png_sequence_relative_path = f"/static/library/transparent_videos/png_sequences/keyed_frames_{job_id}/"
                else:
                    print(f"   JOB #{job_id}: ⚠️ PNG extraction failed: {result.stderr}")
                    png_sequence_relative_path = None
            except Exception as e:
                print(f"   JOB #{job_id}: ⚠️ PNG extraction error: {e}")
                png_sequence_relative_path = None
        
        # Verify final output was created
        if not os.path.exists(final_output_path):
            error_msg = f"Output file was not created: {final_output_path}"
            print(f"   JOB #{job_id}: ERROR - {error_msg}")
            return None, error_msg
            
        output_size = os.path.getsize(final_output_path)
        print(f"   JOB #{job_id}: ✅ Final video ready!")
        print(f"   JOB #{job_id}: Output file: {final_output_path}")
        print(f"   JOB #{job_id}: Output size: {output_size} bytes")
        
        # Upload to S3 if enabled
        s3_key = f"library/transparent_videos/{output_filename}"
        print(f"   JOB #{job_id}: 📤 Uploading keyed video to S3: {s3_key}")
        public_url = upload_file(final_output_path, s3_key)
        print(f"   JOB #{job_id}: 📤 S3 upload complete. Public URL: {public_url}")
        
        if not public_url:
            error_msg = "S3 upload failed - no URL returned"
            print(f"   JOB #{job_id}: ❌ ERROR: {error_msg}")
            return None, error_msg
        
        # Clean up temp INPUT file if we downloaded from S3
        if temp_video:
            temp_path = os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video)
            try:
                print(f"   JOB #{job_id}: 🧹 Cleaning up temp INPUT file: {temp_path}")
                os.remove(temp_path)
                print(f"   JOB #{job_id}: ✅ Temp INPUT file deleted")
            except Exception as e:
                print(f"   JOB #{job_id}: ⚠️ Warning: could not delete temp INPUT file: {e}")
        
        # Build result data with all export URLs and PNG sequence path
        result_data = {
            'webm': public_url,
            'gif': gif_url,
            'png_zip': zip_url,
            'png_sequence_path': png_sequence_relative_path if 'png_sequence_relative_path' in locals() else None
        }
        
        # Return as JSON string for backward compatibility with existing code
        result_json = json.dumps(result_data)
        print(f"   JOB #{job_id}: 🎉 Returning keyed video result: {result_json}")
        return result_json, None
    except Exception as e:
        print(f"   JOB #{job.get('id', '???')}: ❌ Keying failed with error: {e}")
        traceback.print_exc()
        
        # Clean up temp file on error too
        if temp_video:
            try:
                os.remove(os.path.join(ANIMATIONS_FOLDER_GENERATED, temp_video))
            except:
                pass
        
        return None, f"Keying error: {e}"

def kill_stuck_ffmpeg_processes():
    """
    Kill ffmpeg processes that have been running too long.
    This prevents system resource exhaustion from stuck processes.
    """
    try:
        # Find ffmpeg processes
        result = subprocess.run(['pgrep', '-f', 'ffmpeg'], capture_output=True, text=True)
        if result.returncode != 0:
            return  # No ffmpeg processes found
            
        pids = result.stdout.strip().split('\n')
        for pid in pids:
            if not pid:
                continue
                
            try:
                # Get process start time
                ps_result = subprocess.run(['ps', '-o', 'etime=', '-p', pid], capture_output=True, text=True)
                if ps_result.returncode != 0:
                    continue
                    
                elapsed_str = ps_result.stdout.strip()
                
                # Parse elapsed time (formats: MM:SS, H:MM:SS, or D-HH:MM:SS)
                minutes = 0
                if ':' in elapsed_str:
                    parts = elapsed_str.split(':')
                    if len(parts) == 2:  # MM:SS
                        minutes = int(parts[0])
                    elif len(parts) == 3:  # H:MM:SS or HH:MM:SS
                        minutes = int(parts[0]) * 60 + int(parts[1])
                    elif '-' in elapsed_str:  # D-HH:MM:SS
                        days_part, time_part = elapsed_str.split('-')
                        hours, mins, secs = time_part.split(':')
                        minutes = int(days_part) * 24 * 60 + int(hours) * 60 + int(mins)
                
                # Kill processes running more than 5 minutes
                if minutes > 5:
                    print(f"-> Killing stuck ffmpeg process {pid} (running {minutes} minutes)")
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(1)
                    # Force kill if still running
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Already dead
                        
            except (ValueError, ProcessLookupError, PermissionError) as e:
                # Process might have died or we don't have permission
                continue
                
    except Exception as e:
        print(f"   ...error checking ffmpeg processes: {e}")

def check_for_completed_automations(conn):
    cursor = conn.cursor()
    waiting_jobs = cursor.execute("SELECT * FROM jobs WHERE job_type = 'boomerang_automation' AND status = 'waiting_for_children'").fetchall()
    for meta_job in waiting_jobs:
        children = cursor.execute("SELECT * FROM jobs WHERE parent_job_id = ? AND job_type = 'animation'", (meta_job['id'],)).fetchall()
        if len(children) < 2: continue
        
        # Check for completed children - only consider truly completed (not pending_review)
        # For boomerang automation, we only need result_data, not keyed_result_data
        completed_children = [c for c in children if c['status'] == 'completed' and c['result_data']]
        failed_children = [c for c in children if c['status'] == 'failed']
        
        # Count pending_review as not completed for boomerang - they need to finish processing first
        pending_review = [c for c in children if c['status'] == 'pending_review']
        
        print(f"Checking automation job #{meta_job['id']}: {len(children)} children, {len(completed_children)} completed, {len(pending_review)} pending_review, {len(failed_children)} failed")
        
        if failed_children:
            print(f"A child job for Automation Job #{meta_job['id']} failed. Marking as failed.")
            error_messages = [f"Child job #{c['id']} failed: {c['error_message']}" for c in failed_children]
            cursor.execute("UPDATE jobs SET status = 'failed', error_message = ? WHERE id = ?", ("\n".join(error_messages), meta_job['id']))
            conn.commit()
            continue
            
        if len(completed_children) == 2:
            print(f"All children for Automation Job #{meta_job['id']} are complete. Triggering stitch.")
            
            # Check if stitching job already exists to prevent duplicates
            existing_stitch = cursor.execute("SELECT id FROM jobs WHERE parent_job_id = ? AND job_type = 'video_stitching'", (meta_job['id'],)).fetchone()
            if existing_stitch:
                print(f"   ...stitching job already exists (#{existing_stitch['id']}), skipping duplicate creation")
                cursor.execute("UPDATE jobs SET status = 'stitching' WHERE id = ?", (meta_job['id'],))
                conn.commit()
                continue
            
            # For boomerang automation, use raw green-screen video results for stitching
            # Sort to ensure consistent A->B, B->A order (first created, then second created)
            children_sorted = sorted(completed_children, key=lambda x: x['id'])
            video_paths = []
            for c in children_sorted:
                # Use raw result_data (green-screen MP4s from Replicate)
                video_path = c['result_data']
                if not video_path:
                    print(f"   ...warning: child job {c['id']} has no result_data")
                    continue
                video_paths.append(video_path)
            
            if len(video_paths) == 2:
                prompt = f"Stitched Loop: {meta_job['prompt']}"
                stitch_input_data = json.dumps({
                    "video_a_path": video_paths[0], 
                    "video_b_path": video_paths[1],
                    "auto_key_after_stitch": True  # Flag to queue keying after stitch
                })
                # Create stitching job with current timestamp
                stitch_timestamp = datetime.now()
                cursor.execute("INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)", ('video_stitching', 'queued', stitch_timestamp, prompt, stitch_input_data, meta_job['id']))
                # Update parent job status and timestamp to be 1 second after stitching job so it appears above in queue
                parent_timestamp = stitch_timestamp + timedelta(seconds=1)
                cursor.execute("UPDATE jobs SET status = 'stitching', created_at = ? WHERE id = ?", (parent_timestamp, meta_job['id']))
                conn.commit()
                print(f"   ...queued stitching job for green-screen videos: {video_paths}")
            else:
                print(f"   ...error: not enough valid video paths for stitching: {video_paths}")
        else:
            print(f"   ...waiting for more children to complete: {len(completed_children)}/2")

def check_for_analysis_completion(conn):
    """Check if image generation jobs waiting for analysis can proceed"""
    cursor = conn.cursor()
    waiting_jobs = cursor.execute(
        "SELECT * FROM jobs WHERE job_type = 'image_generation' AND status = 'waiting_for_analysis'"
    ).fetchall()
    
    for job in waiting_jobs:
        try:
            input_data = json.loads(job['input_data'])
            style_job_id = input_data.get('style_analysis_job_id')
            color_job_id = input_data.get('color_analysis_job_id')
            
            # Check if all required analysis jobs are completed or failed
            analyses_done = True  # Done = completed or failed (we can proceed)
            style_result = None
            color_result = None
            
            if style_job_id:
                style_job = cursor.execute(
                    "SELECT status, result_data FROM jobs WHERE id = ?", (style_job_id,)
                ).fetchone()
                if style_job:
                    if style_job['status'] == 'completed':
                        style_result = style_job['result_data']
                    elif style_job['status'] == 'failed':
                        print(f"   Style analysis {style_job_id} failed, proceeding without it")
                    else:
                        analyses_done = False  # Still processing
                else:
                    analyses_done = False
            
            if color_job_id:
                color_job = cursor.execute(
                    "SELECT status, result_data FROM jobs WHERE id = ?", (color_job_id,)
                ).fetchone()
                if color_job:
                    if color_job['status'] == 'completed':
                        color_result = color_job['result_data']
                    elif color_job['status'] == 'failed':
                        print(f"   Color analysis {color_job_id} failed, proceeding without it")
                    else:
                        analyses_done = False  # Still processing
                else:
                    analyses_done = False
            
            # If all analyses are done (completed or failed), merge results and queue the job
            if analyses_done:
                # Merge analysis results into style_prompt
                merged_style = input_data.get('style_prompt', '')
                
                if style_result:
                    merged_style = style_result if not merged_style else f"{style_result}. {merged_style}"
                
                if color_result:
                    # Parse color palette and append
                    try:
                        color_data = json.loads(color_result)
                        if 'palette' in color_data:
                            color_desc = ", ".join([f"{c['name']} ({c['hex']})" for c in color_data['palette']])
                            merged_style = f"{merged_style}. Color palette: {color_desc}" if merged_style else f"Color palette: {color_desc}"
                    except:
                        merged_style = f"{merged_style}. {color_result}" if merged_style else color_result
                
                # Handle both v2 (object_prompt + style_prompt) and v3 (prompt) formats
                if 'object_prompt' in input_data:
                    # v2 format
                    input_data['style_prompt'] = merged_style
                    object_prompt = input_data.get('object_prompt', '')
                    new_prompt = f"{object_prompt}, in the style of {merged_style}" if merged_style else object_prompt
                else:
                    # v3 format
                    base_prompt = input_data.get('prompt', '')
                    input_data['style_prompt'] = merged_style  # For handler compatibility
                    input_data['object_prompt'] = base_prompt  # For handler compatibility
                    new_prompt = f"{base_prompt}, in the style of {merged_style}" if merged_style else base_prompt
                
                # Update job to queued status with merged data
                cursor.execute(
                    "UPDATE jobs SET status = 'queued', prompt = ?, input_data = ? WHERE id = ?",
                    (new_prompt, json.dumps(input_data), job['id'])
                )
                conn.commit()
                print(f"-> Analysis complete for image_generation job {job['id']}, queued for processing")
                
        except Exception as e:
            print(f"Error checking analysis for job {job['id']}: {e}")
            traceback.print_exc()

def process_job(job, conn):
    job_type = job['job_type']
    status = job['status']
    print(f"Processing job {job['id']} of type '{job_type}' with status '{status}'...")
    
    # Job-type based routing - keying jobs get priority
    if job_type == 'keying': 
        print(f"   → Routing to handle_keying() - type: {job_type}, status: {status}")
        return handle_keying(job)
    elif job_type == 'image_generation': return handle_image_generation(job)
    elif job_type == 'video_generation': return handle_video_generation(job, conn)
    elif job_type == 'background_removal': return handle_background_removal(job)
    elif job_type in ['style_analysis', 'palette_analysis', 'animation_prompting']: return handle_openai_vision_analysis(job)
    elif job_type == 'video_stitching': return handle_video_stitching(job)
    elif job_type == 'boomerang_automation': return handle_boomerang_automation(job, conn)
    elif job_type == 'trim': return handle_trim(job)
    elif job_type == 'video_effect': return handle_video_effect(job)
    elif job_type == 'animation' and status in ['queued', 'processing']: return handle_animation(job)
    else: return None, f"Unknown job type/status: {job_type}/{status}"

def process_single_job_worker(job):
    """
    Process a single job in a worker thread.
    This function handles the entire lifecycle of job processing.
    """
    job_id = job['id']
    try:
        print(f"[Thread-{threading.current_thread().name}] Processing job {job_id}...")
        
        # Process the job
        result_data, error_message = None, None
        try:
            with get_db_connection() as conn:
                result_data, error_message = process_job(dict(job), conn)
        except Exception as e:
            print(f"[Thread-{threading.current_thread().name}] Unhandled exception during job {job_id} processing: {e}")
            traceback.print_exc()
            error_message = f"Unhandled worker exception: {e}"

        # Update job status in database
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                if error_message is not None:
                    new_status = 'failed'
                    print(f"   JOB #{job_id}: ❌ Marking as FAILED with error: {error_message}")
                    cursor.execute("UPDATE jobs SET status = ?, error_message = ? WHERE id = ?", (new_status, str(error_message), job_id))
                elif job['status'] in ['keying_queued', 'keying_processing']:
                    # Handle keying completion BEFORE checking job_type
                    new_status = 'completed'
                    print(f"   JOB #{job_id}: ✅ Marking as COMPLETED with keyed_result_data: {result_data}")
                    
                    # Extract PNG sequence path if present
                    png_sequence_path = None
                    try:
                        result_parsed = json.loads(result_data) if isinstance(result_data, str) else result_data
                        png_sequence_path = result_parsed.get('png_sequence_path')
                        print(f"   JOB #{job_id}: 💾 PNG sequence preserved at: {png_sequence_path}")
                    except:
                        pass
                    
                    cursor.execute("UPDATE jobs SET status = ?, keyed_result_data = ?, png_sequence_path = ? WHERE id = ?", 
                                   (new_status, result_data, png_sequence_path, job_id))
                    print(f"   JOB #{job_id}: 💾 Database updated successfully")
                elif job['job_type'] == 'boomerang_automation':
                    # This is for initial boomerang setup, not keying
                    new_status = result_data # This should be 'waiting_for_children'
                    cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
                elif job['status'] in ['queued', 'processing']:
                    # For animations that are part of automation pipelines, complete them automatically
                    if job['job_type'] == 'animation' and job['parent_job_id']:
                        try:
                            parent_job = cursor.execute("SELECT job_type FROM jobs WHERE id = ?", (job['parent_job_id'],)).fetchone()
                            if parent_job and parent_job['job_type'] in ['boomerang_automation', 'video_generation']:
                                new_status = 'completed'  # Complete without auto-keying (parent handles it)
                                print(f"   ...auto-completing animation job {job_id} (part of {parent_job['job_type']} #{job['parent_job_id']})")
                                cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                            else:
                                new_status = 'pending_review'  # Regular workflow needs review
                                print(f"   ...setting animation job {job_id} to pending_review (parent type: {parent_job['job_type'] if parent_job else 'None'})")
                                cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                        except Exception as e:
                            print(f"   ...error checking parent job for {job_id}: {e}, defaulting to completed")
                            new_status = 'completed'  # Safe default for boomerang children
                            cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                    # For stitching jobs that are part of boomerang automation, update the parent with the result
                    elif job['job_type'] == 'video_stitching' and job['parent_job_id']:
                        try:
                            parent_job = cursor.execute("SELECT job_type FROM jobs WHERE id = ?", (job['parent_job_id'],)).fetchone()
                            if parent_job and parent_job['job_type'] == 'boomerang_automation':
                                new_status = 'completed'  # Complete the stitching job
                                print(f"   ...completing stitching job {job_id} (part of boomerang automation #{job['parent_job_id']})")
                                cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                                # Update the parent boomerang automation job with the stitched result
                                print(f"   ...updating parent boomerang job #{job['parent_job_id']} with stitched result")
                                cursor.execute("UPDATE jobs SET status = 'completed', result_data = ? WHERE id = ?", (result_data, job['parent_job_id']))
                            else:
                                new_status = 'pending_review'  # Regular stitching workflow needs review
                                cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                        except Exception as e:
                            print(f"   ...error checking parent job for stitching {job_id}: {e}, defaulting to pending_review")
                            new_status = 'pending_review'
                            cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                    else:
                        # AUTO-KEYING PIPELINE: Animation jobs automatically trigger keying
                        if job['job_type'] == 'animation':
                            # Mark animation as completed first
                            new_status = 'completed'
                            cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                            conn.commit()
                            
                            # Only auto-trigger keying if animation actually produced a video
                            if result_data and isinstance(result_data, str) and result_data.strip():
                                print(f"   🎬→🔑 Animation complete! Auto-triggering keying for job {job_id}...")
                                
                                # Create a new keying job for this animation
                                try:
                                    keying_job_input = json.dumps({
                                        'video_url': result_data,
                                        'parent_animation_job_id': job_id,
                                        # Updated keying settings
                                        'hue_center': 60,  # Green (or 240 for blue screen)
                                        'hue_tolerance': 25,
                                        'saturation_min': 140,  # Reduced from 160 to catch more greens
                                        'value_min': 80,  # Increased from 50 for better bright green isolation
                                        'erode': 2,  # Choke edges inward
                                        'dilate': 2,  # Soften edges outward
                                        'blur': 5,  # Edge blur
                                        'spill': 5  # Spill suppression (0.25 after normalization)
                                    })
                                    
                                    cursor.execute("""
                                        INSERT INTO jobs (job_type, status, created_at, input_data, parent_job_id)
                                        VALUES ('keying', 'keying_queued', datetime('now'), ?, ?)
                                    """, (keying_job_input, job_id))
                                    
                                    keying_job_id = cursor.lastrowid
                                    conn.commit()
                                    print(f"   ✅ Created auto-keying job #{keying_job_id} for animation #{job_id}")
                                    
                                except Exception as keying_error:
                                    print(f"   ⚠️ Failed to create auto-keying job: {keying_error}")
                                    traceback.print_exc()
                            else:
                                print(f"   ⚠️ Animation completed but has no result_data - skipping auto-keying")
                        else:
                            # Non-animation jobs just complete normally
                            new_status = 'completed'
                            cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                else: # Default case for completion
                    new_status = 'completed'
                    cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job_id))

                conn.commit()
                print(f"[Thread-{threading.current_thread().name}] Job {job_id} finished with status: {new_status}")
        except Exception as db_error:
            print(f"[Thread-{threading.current_thread().name}] Database error updating job {job_id}: {db_error}")
            # Try to at least mark the job as failed if we can't update it properly
            try:
                with get_db_connection() as conn:
                    conn.cursor().execute("UPDATE jobs SET status = 'failed', error_message = ? WHERE id = ?", (f"Database update error: {db_error}", job_id))
                    conn.commit()
            except Exception as final_error:
                print(f"[Thread-{threading.current_thread().name}] Could not even mark job {job_id} as failed: {final_error}")
                
    except Exception as e:
        print(f"[Thread-{threading.current_thread().name}] FATAL ERROR processing job {job_id}: {e}")
        traceback.print_exc()
        try:
            with get_db_connection() as conn:
                conn.cursor().execute("UPDATE jobs SET status = 'failed', error_message = ? WHERE id = ?", (f"Fatal worker error: {e}", job_id))
                conn.commit()
        except Exception as db_e:
            print(f"[Thread-{threading.current_thread().name}] Could not even update DB for failed job: {db_e}")

def main():
    print("=" * 60)
    print("Starting Multi-Threaded Worker")
    print(f"Max concurrent jobs: {MAX_CONCURRENT_JOBS}")
    print("=" * 60)
    
    last_cleanup = time.time()
    executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="JobWorker")
    active_futures = {}  # Maps future -> job_id for tracking
    
    try:
        while True:
            try:
                # Kill stuck ffmpeg processes every 30 seconds
                current_time = time.time()
                if current_time - last_cleanup > 30:
                    kill_stuck_ffmpeg_processes()
                    last_cleanup = current_time
                
                # Check for completed automations and analysis in main thread
                with get_db_connection() as conn:
                    check_for_completed_automations(conn)
                    check_for_analysis_completion(conn)
                
                # Clean up completed futures
                completed_futures = [f for f in active_futures.keys() if f.done()]
                for future in completed_futures:
                    job_id = active_futures.pop(future)
                    try:
                        future.result()  # This will raise any exceptions that occurred
                    except Exception as e:
                        print(f"Future for job {job_id} raised exception: {e}")
                
                # Check if we have capacity for more jobs
                if len(active_futures) < MAX_CONCURRENT_JOBS:
                    # Try to fetch a new job
                    job = None
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        
                        # Count jobs in each status for debugging
                        keying_count = cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'keying_queued'").fetchone()[0]
                        queued_count = cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued'").fetchone()[0]
                        print(f"🔍 Worker checking for jobs: {keying_count} keying_queued, {queued_count} queued, {len(active_futures)}/{MAX_CONCURRENT_JOBS} active")
                        
                        # Priority: keying jobs first
                        job = cursor.execute("SELECT * FROM jobs WHERE status = 'keying_queued' ORDER BY created_at ASC LIMIT 1").fetchone()
                        if job:
                            print(f"   🎬 Found KEYING job #{job['id']} - updating to keying_processing")
                            cursor.execute("UPDATE jobs SET status = 'keying_processing' WHERE id = ?", (job['id'],))
                            conn.commit()
                            job = cursor.execute("SELECT * FROM jobs WHERE id = ?", (job['id'],)).fetchone()
                        else:
                            # Then regular queued jobs
                            job = cursor.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
                            if job:
                                print(f"   📋 Found REGULAR job #{job['id']} - updating to processing")
                                cursor.execute("UPDATE jobs SET status = 'processing' WHERE id = ?", (job['id'],))
                                conn.commit()
                                job = cursor.execute("SELECT * FROM jobs WHERE id = ?", (job['id'],)).fetchone()
                    
                    if job:
                        # Submit job to thread pool
                        job_dict = dict(job)
                        print(f"   ✅ Submitting job #{job['id']} to thread pool (type={job['job_type']}, status={job['status']})")
                        future = executor.submit(process_single_job_worker, job_dict)
                        active_futures[future] = job['id']
                        print(f"Submitted job {job['id']} to worker thread pool ({len(active_futures)}/{MAX_CONCURRENT_JOBS} active)")
                
                # Sleep briefly to avoid tight loop
                time.sleep(1)
                
            except Exception as e:
                print(f"ERROR in worker's main loop: {e}")
                traceback.print_exc()
                time.sleep(5)
    
    except KeyboardInterrupt:
        print("\n\nShutting down worker...")
        print("Waiting for active jobs to complete...")
        executor.shutdown(wait=True)
        print("Worker stopped cleanly.")
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        executor.shutdown(wait=False)

if __name__ == "__main__":
    main()

