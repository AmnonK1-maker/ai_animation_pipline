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
from datetime import datetime, timedelta
from replicate.exceptions import ReplicateError
from dotenv import load_dotenv
from openai import OpenAI

from video_processor import process_video_with_opencv, stitch_videos_with_ffmpeg

# --- CONFIGURATION ---
load_dotenv()
LEONARDO_API_KEY = os.environ.get("LEONARDO_API_KEY")
REPLICATE_API_KEY = os.environ.get("REPLICATE_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_KEY

try:
    openai_client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        organization=os.environ.get("OPENAI_ORG_ID"),
    )
    print("Worker: OpenAI client initialized successfully.")
except Exception as e:
    openai_client = None
    print(f"Worker: OpenAI client could not be initialized: {e}")

DATABASE_PATH = 'jobs.db'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
LIBRARY_FOLDER = os.path.join(STATIC_FOLDER, 'library')
ANIMATIONS_FOLDER_GENERATED = os.path.join(STATIC_FOLDER, 'animations', 'generated')
UPLOADS_FOLDER = os.path.join(STATIC_FOLDER, 'uploads')
TRANSPARENT_VIDEOS_FOLDER = os.path.join(STATIC_FOLDER, 'library', 'transparent_videos')
os.makedirs(TRANSPARENT_VIDEOS_FOLDER, exist_ok=True)

# --- IMAGE PREPROCESSING FOR BOOMERANG ---
def preprocess_animation_image_for_boomerang(source_image_path, background_color_str):
    """
    Preprocess images for boomerang automation to ensure consistent backgrounds.
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

        print(f"   ...preprocessing {source_image_path} with {background_color_str} background")
        with Image.open(source_full_path).convert("RGBA") as fg_image:
            bg_image = Image.new("RGBA", fg_image.size, background_color)
            new_size = (int(fg_image.width * 0.9), int(fg_image.height * 0.9))
            fg_image_resized = fg_image.resize(new_size, Image.Resampling.LANCZOS)
            paste_position = ((bg_image.width - fg_image_resized.width) // 2, (bg_image.height - fg_image_resized.height) // 2)
            bg_image.paste(fg_image_resized, paste_position, fg_image_resized)
            
            output_filename = f"boomerang_preprocessed_{uuid.uuid4()}.png"
            output_full_path = os.path.join(LIBRARY_FOLDER, output_filename)
            bg_image.convert("RGB").save(output_full_path, 'PNG')
            print(f"   ...saved preprocessed image to {output_full_path}")
            return os.path.join('static/library', output_filename)
            
    except Exception as e:
        print(f"   ...error during boomerang preprocessing: {e}")
        return source_image_path

# --- DATABASE HELPER ---
def get_db_connection():
    """Creates a database connection with WAL mode enabled for high concurrency."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

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
        
        print(f"   ...preprocessing frames for consistent {background_color} background")
        # Use the same preprocessing logic for both frames to ensure consistency
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
        traceback.print_exc()
        return None, f"A-B-A Loop Automation setup failed: {e}"

def handle_animation(job):
    try:
        print(f"-> Starting animation generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        video_model = input_data.get("video_model")
        print(f"   ...using model: {video_model}")
        start_image_path = os.path.join(BASE_DIR, input_data['image_url'].lstrip('/'))
        if not os.path.exists(start_image_path):
            raise FileNotFoundError(f"Start image not found at {start_image_path}")
        user_negative_prompt = input_data.get("negative_prompt", "").strip()
        additional_instructions = "contact shadow, drop shadow, change background color"
        final_negative_prompt = f"{user_negative_prompt}, {additional_instructions}" if user_negative_prompt else additional_instructions
        api_input = {"prompt": input_data.get('prompt'), "negative_prompt": final_negative_prompt}
        if 'kling' in video_model:
            api_input["duration"] = input_data.get('kling_duration', 5)
            if 'v2.1' in video_model: api_input["mode"] = input_data.get("kling_mode", "pro")
        elif 'seedance' in video_model:
            api_input["duration"] = input_data.get('seedance_duration', 5)
            api_input["resolution"] = input_data.get('seedance_resolution', '1080p')
            api_input["aspect_ratio"] = input_data.get('seedance_aspect_ratio', '1:1')
        with open(start_image_path, "rb") as start_file:
            if 'seedance' in video_model: api_input["image"] = start_file
            else: api_input["start_image"] = start_file
            end_image_url = input_data.get("end_image_url")
            end_file_obj = None
            try:
                if end_image_url and isinstance(end_image_url, str) and end_image_url.strip():
                    end_image_path = os.path.join(BASE_DIR, end_image_url.lstrip('/'))
                    if os.path.exists(end_image_path):
                        print(f"   ...using end frame from {end_image_path}")
                        end_file_obj = open(end_image_path, "rb")
                        api_input["end_image"] = end_file_obj
                if input_data.get("seamless_loop", False):
                    print("   ...using start frame as end frame for seamless loop.")
                    start_file.seek(0)
                    api_input["end_image"] = io.BytesIO(start_file.read())
                if "end_image" in api_input and 'kling-v2.1' in video_model:
                    api_input["mode"] = "pro"
                    print("   ...forcing 'pro' mode for Kling because end_image is present.")
                loggable_input = {k: v for k, v in api_input.items() if not isinstance(v, io.IOBase)}
                if "start_image" in api_input or "image" in api_input: loggable_input['start_image_provided'] = True
                if "end_image" in api_input: loggable_input['end_image_provided'] = True
                print(f"   ...calling Replicate with parameters: {loggable_input}")
                video_output_url = replicate.run(video_model, input=api_input)
            finally:
                if end_file_obj: end_file_obj.close()
        video_response = requests.get(video_output_url)
        video_response.raise_for_status()
        video_filename = f"{uuid.uuid4()}.mp4"
        video_filepath = os.path.join(ANIMATIONS_FOLDER_GENERATED, video_filename)
        with open(video_filepath, "wb") as f: f.write(video_response.content)
        return os.path.join('static/animations/generated', video_filename), None
    except Exception as e:
        traceback.print_exc()
        return None, f"Animation generation error: {e}"

def handle_video_stitching(job):
    try:
        print(f"-> Starting video stitching for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        video_a_path = os.path.join(BASE_DIR, input_data['video_a_path'].lstrip('/'))
        video_b_path = os.path.join(BASE_DIR, input_data['video_b_path'].lstrip('/'))
        
        # Validate input files exist
        if not os.path.exists(video_a_path):
            return None, f"Source video A not found: {video_a_path}"
        if not os.path.exists(video_b_path):
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
        return os.path.join('static/library', output_filename), None
        
    except Exception as e:
        print(f"   ...ERROR in video stitching: {e}")
        traceback.print_exc()
        return None, f"Video stitching error: {e}"

def handle_replicate_openai_generation(job):
    if not OPENAI_API_KEY: return None, "OpenAI API Key is required for this model but not found in .env file."
    try:
        print(f"-> Starting OpenAI via Replicate generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        full_prompt = f"{input_data['object_prompt']}, in the style of {input_data['style_prompt']}"
        api_input = {"prompt": full_prompt, "openai_api_key": OPENAI_API_KEY, "background": "transparent", "quality": "high", "output_format": "png", "aspect_ratio": "1:1"}
        print("   ...calling openai/gpt-image-1 on Replicate.")
        output = replicate.run("openai/gpt-image-1", input=api_input)
        output_url = output[0] if isinstance(output, list) and output else output if isinstance(output, str) else None
        if not output_url: return None, "Replicate OpenAI model did not return an image URL."
        print(f"   ...downloading image from Replicate: {output_url}")
        image_res = requests.get(output_url)
        image_res.raise_for_status()
        filename = f"{uuid.uuid4()}.png"
        filepath = os.path.join(LIBRARY_FOLDER, filename)
        with open(filepath, "wb") as f: f.write(image_res.content)
        return os.path.join('static/library', filename), None
    except Exception as e:
        return None, f"Replicate OpenAI generation error: {e}"

def handle_bytedance_generation(job):
    try:
        print(f"-> Starting Bytedance Seedream-4 generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        engineered_prompt = (f"professional product shot of a {input_data['object_prompt']}, " f"in the style of {input_data['style_prompt']}, centered, " f"on a solid bright green flat neutral background, no shadows")
        print(f"   ...calling bytedance/seedream-4")
        greenscreen_output = replicate.run("bytedance/seedream-4", input={"prompt": engineered_prompt, "size": "1K", "aspect_ratio": "1:1"})
        greenscreen_url = greenscreen_output[0] if greenscreen_output else None
        if not greenscreen_url: return None, "Bytedance model did not return an image URL."
        print(f"   ...downloading greenscreen image.")
        img_res = requests.get(greenscreen_url)
        img_res.raise_for_status()
        filename = f"{uuid.uuid4()}.png"
        filepath = os.path.join(LIBRARY_FOLDER, filename)
        with open(filepath, "wb") as f: f.write(img_res.content)
        return os.path.join('static/library', filename), None
    except Exception as e:
        return None, f"Bytedance generation error: {e}"

def handle_background_removal(job):
    try:
        print(f"-> Starting BRIA background removal for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        relative_image_path = input_data.get("image_path")
        if not relative_image_path: return None, "No image path provided for background removal."
        # Handle both relative and absolute paths more safely
        if relative_image_path.startswith('/'):
            full_image_path = os.path.join(BASE_DIR, relative_image_path.lstrip('/'))
        else:
            full_image_path = os.path.join(BASE_DIR, relative_image_path)
        if not os.path.exists(full_image_path): return None, f"File not found for background removal: {full_image_path}"
        print(f"   ...uploading {full_image_path} to bria/remove-background")
        with open(full_image_path, "rb") as f:
            transparent_output_url = replicate.run("bria/remove-background", input={"image": f})
        if not transparent_output_url: return None, "BRIA model did not return an image URL."
        print(f"   ...downloading final transparent image.")
        img_res = requests.get(transparent_output_url)
        img_res.raise_for_status()
        filename = f"{uuid.uuid4()}.png"
        filepath = os.path.join(LIBRARY_FOLDER, filename)
        with open(filepath, "wb") as f: f.write(img_res.content)
        print(f"   ...kept original image: {full_image_path}")
        return os.path.join('static/library', filename), None
    except Exception as e:
        return None, f"BRIA background removal error: {e}"

def handle_leonardo_generation(job):
    try:
        print(f"-> Starting Leonardo AI image generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        model_id = input_data.get("modelId", "b24e16ff-06e3-43eb-8d33-4416c2d75876")
        preset_style = input_data.get("presetStyle", "NONE")
        full_prompt = f"{input_data['object_prompt']}, in the style of {input_data['style_prompt']}, centered, professional product shot"
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
                    filename = f"{uuid.uuid4()}.png"
                    filepath = os.path.join(LIBRARY_FOLDER, filename)
                    with open(filepath, "wb") as f: f.write(img_res.content)
                    filepaths.append(os.path.join('static/library', filename))
                return filepaths[0], None
            elif status == "FAILED":
                return None, "Leonardo AI job failed."
    except Exception as e:
        return None, f"Image generation error: {e}"

def handle_image_generation(job):
    input_data = json.loads(job['input_data'])
    model_id = input_data.get("modelId")
    if model_id == "bytedance-seedream-4": return handle_bytedance_generation(job)
    elif model_id == "replicate-gpt-image-1": return handle_replicate_openai_generation(job)
    else: return handle_leonardo_generation(job)

def handle_openai_vision_analysis(job):
    if not openai_client: return None, "OpenAI client is not initialized. Check API keys."
    try:
        job_type = job['job_type'].replace('_', ' ').capitalize()
        print(f"-> Starting OpenAI Vision Analysis ({job_type}) for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        system_prompt = input_data.get('system_prompt', 'Analyze this image.')
        image_path = os.path.join(BASE_DIR, input_data['image_path'].lstrip('/'))
        if not os.path.exists(image_path): return None, f"Image file not found at {image_path}"
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        response_format = "json_object" if "json" in system_prompt.lower() else "text"
        response = openai_client.chat.completions.create(model="gpt-4-turbo", response_format={"type": response_format}, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}]}], max_tokens=500)
        analysis_text = response.choices[0].message.content
        print(f"   ...OpenAI analysis complete.")
        return analysis_text, None
    except Exception as e:
        return None, f"OpenAI Vision API error: {e}"

def handle_keying(job):
    try:
        print(f"-> Starting OpenCV keying for job {job['id']}...")
        print(f"   DEBUG: Job type: {job['job_type']}, Input file: {job['result_data']}")
        greenscreen_video_path = os.path.join(BASE_DIR, job['result_data'].lstrip('/'))
        print(f"   DEBUG: Full path: {greenscreen_video_path}")
        settings = json.loads(job['keying_settings'])
        output_filename = f"keyed_{uuid.uuid4()}.webm"
        final_output_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, output_filename)
        print(f"   DEBUG: Output path: {final_output_path}")
        lower_green = [settings['hue_center'] - settings['hue_tolerance'], settings['saturation_min'], settings['value_min']]
        upper_green = [settings['hue_center'] + settings['hue_tolerance'], 255, 255]
        process_video_with_opencv(video_path=greenscreen_video_path, output_path=final_output_path, lower_green=lower_green, upper_green=upper_green, erode_amount=settings['erode'], dilate_amount=settings['dilate'], blur_amount=settings['blur'], spill_amount=settings['spill'])
        print(f"   DEBUG: Keying completed successfully")
        return os.path.join('static/library/transparent_videos', output_filename), None
    except Exception as e:
        print(f"   DEBUG: Keying failed with error: {e}")
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
        
        # Check for completed children (either completed status or completed with keyed_result_data)
        completed_children = [c for c in children if c['status'] == 'completed' and (c['keyed_result_data'] or c['result_data'])]
        failed_children = [c for c in children if c['status'] == 'failed']
        
        print(f"Checking automation job #{meta_job['id']}: {len(children)} children, {len(completed_children)} completed, {len(failed_children)} failed")
        
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
            
            # For boomerang automation, always use raw video results (not keyed) for stitching
            # Sort to ensure consistent A->B, B->A order (first created, then second created)
            children_sorted = sorted(completed_children, key=lambda x: x['id'])
            video_paths = []
            for c in children_sorted:
                # Use raw result_data for boomerang automation stitching
                video_path = c['result_data']
                if not video_path:
                    print(f"   ...warning: child job {c['id']} has no result_data")
                    continue
                video_paths.append(video_path)
            
            if len(video_paths) == 2:
                prompt = f"Stitched Loop: {meta_job['prompt']}"
                stitch_input_data = json.dumps({"video_a_path": video_paths[0], "video_b_path": video_paths[1]})
                cursor.execute("INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)", ('video_stitching', 'queued', datetime.now(), prompt, stitch_input_data, meta_job['id']))
                cursor.execute("UPDATE jobs SET status = 'stitching' WHERE id = ?", (meta_job['id'],))
                conn.commit()
                print(f"   ...queued stitching job for raw videos: {video_paths}")
            else:
                print(f"   ...error: not enough valid video paths for stitching: {video_paths}")
        else:
            print(f"   ...waiting for more children to complete: {len(completed_children)}/2")

def process_job(job, conn):
    job_type = job['job_type']
    status = job['status']
    print(f"Processing job {job['id']} of type '{job_type}' with status '{status}'...")
    
    # Status-based routing takes precedence (for keying, etc.)
    if status in ['keying_queued', 'keying_processing']: 
        print(f"   DEBUG: Job {job['id']} going to handle_keying() - type: {job_type}, status: {status}")
        return handle_keying(job)  # Any job type can be keyed
    
    # Job-type based routing for normal processing
    elif job_type == 'image_generation': return handle_image_generation(job)
    elif job_type == 'background_removal': return handle_background_removal(job)
    elif job_type in ['style_analysis', 'palette_analysis', 'animation_prompting']: return handle_openai_vision_analysis(job)
    elif job_type == 'video_stitching': return handle_video_stitching(job)
    elif job_type == 'boomerang_automation': return handle_boomerang_automation(job, conn)
    elif job_type == 'animation' and status in ['queued', 'processing']: return handle_animation(job)
    else: return None, f"Unknown job type/status: {job_type}/{status}"

def main():
    print("Starting worker...")
    last_cleanup = time.time()
    
    while True:
        job = None
        try:
            # Kill stuck ffmpeg processes every 30 seconds
            current_time = time.time()
            if current_time - last_cleanup > 30:
                kill_stuck_ffmpeg_processes()
                last_cleanup = current_time
            
            with get_db_connection() as conn:
                check_for_completed_automations(conn)
                cursor = conn.cursor()
                job = cursor.execute("SELECT * FROM jobs WHERE status = 'keying_queued' ORDER BY created_at ASC LIMIT 1").fetchone()
                if job:
                    cursor.execute("UPDATE jobs SET status = 'keying_processing' WHERE id = ?", (job['id'],))
                    conn.commit()
                    # Fetch the job again with updated status
                    job = cursor.execute("SELECT * FROM jobs WHERE id = ?", (job['id'],)).fetchone()
                else:
                    job = cursor.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
                    if job:
                        cursor.execute("UPDATE jobs SET status = 'processing' WHERE id = ?", (job['id'],))
                        conn.commit()
                        # Fetch the job again with updated status
                        job = cursor.execute("SELECT * FROM jobs WHERE id = ?", (job['id'],)).fetchone()

            if job:
                result_data, error_message = None, None
                try:
                    with get_db_connection() as conn:
                        result_data, error_message = process_job(dict(job), conn)
                except Exception as e:
                    print(f"Unhandled exception during job {job['id']} processing: {e}")
                    traceback.print_exc()
                    error_message = f"Unhandled worker exception: {e}"

                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    if error_message is not None:
                        new_status = 'failed'
                        cursor.execute("UPDATE jobs SET status = ?, error_message = ? WHERE id = ?", (new_status, str(error_message), job['id']))
                    elif job['job_type'] == 'boomerang_automation':
                        new_status = result_data # This should be 'waiting_for_children'
                        cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job['id']))
                    elif job['status'] in ['keying_queued', 'keying_processing']:
                        new_status = 'completed'
                        cursor.execute("UPDATE jobs SET status = ?, keyed_result_data = ? WHERE id = ?", (new_status, result_data, job['id']))
                    elif job['status'] in ['queued', 'processing']:
                        # For animations that are part of boomerang automation, complete them automatically
                        if job['job_type'] == 'animation' and job['parent_job_id']:
                            try:
                                parent_job = cursor.execute("SELECT job_type FROM jobs WHERE id = ?", (job['parent_job_id'],)).fetchone()
                                if parent_job and parent_job['job_type'] == 'boomerang_automation':
                                    new_status = 'completed'  # Complete without keying for boomerang automation
                                    print(f"   ...auto-completing animation job {job['id']} (part of boomerang automation #{job['parent_job_id']})")
                                    cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job['id']))
                                else:
                                    new_status = 'pending_review'  # Regular workflow needs review
                                    print(f"   ...setting animation job {job['id']} to pending_review (parent type: {parent_job['job_type'] if parent_job else 'None'})")
                                    cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job['id']))
                            except Exception as e:
                                print(f"   ...error checking parent job for {job['id']}: {e}, defaulting to completed")
                                new_status = 'completed'  # Safe default for boomerang children
                                cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job['id']))
                        else:
                            new_status = 'pending_review' if job['job_type'] in ['animation', 'video_stitching'] else 'completed'
                            cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job['id']))
                    else: # Default case for completion
                        new_status = 'completed'
                        cursor.execute("UPDATE jobs SET status = ?, result_data = ? WHERE id = ?", (new_status, result_data, job['id']))

                    conn.commit()
                    print(f"Job {job['id']} finished.")
            else:
                print("No jobs found. Waiting...", end='\r')
                time.sleep(5)
        except Exception as e:
            print(f"FATAL ERROR in worker's main loop: {e}")
            traceback.print_exc()
            if job:
                try:
                    with get_db_connection() as conn:
                        conn.cursor().execute("UPDATE jobs SET status = 'failed', error_message = ? WHERE id = ?", (f"Fatal worker error: {e}", job['id']))
                        conn.commit()
                except Exception as db_e:
                    print(f"   ...could not even update DB for failed job: {db_e}")
            time.sleep(10)

if __name__ == "__main__":
    main()

