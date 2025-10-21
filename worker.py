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

# --- CONFIGURATION ---
load_dotenv()
LEONARDO_API_KEY = os.environ.get("LEONARDO_API_KEY")
REPLICATE_API_KEY = os.environ.get("REPLICATE_API_KEY")
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
            
            # Upload to S3 if enabled
            s3_key = f"library/{output_filename}"
            public_url = upload_file(output_full_path, s3_key)
            return public_url
            
    except Exception as e:
        print(f"   ...error during boomerang preprocessing: {e}")
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
        print(f"Error in boomerang automation setup: {e}")
        traceback.print_exc()
        # Try to rollback the transaction
        try:
            conn.rollback()
        except Exception as rollback_error:
            print(f"Could not rollback transaction: {rollback_error}")
        return None, f"A-B-A Loop Automation setup failed: {e}"

def handle_animation(job):
    try:
        print(f"-> Starting animation generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        video_model = input_data.get("video_model")
        print(f"   ...using model: {video_model}")
        
        # Handle both S3 URLs and local file paths for start image
        image_url = input_data['image_url']
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
        end_file_obj = None
        temp_end_file = None
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
                        api_input["end_image"] = end_file_obj
                    else:
                        # It's a local path
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
            if end_file_obj and not isinstance(end_file_obj, io.BytesIO):
                try:
                    end_file_obj.close()
                except Exception as e:
                    print(f"   ...warning: could not close end_file_obj: {e}")
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
        
        # Upload to S3 if enabled
        s3_key = f"animations/generated/{video_filename}"
        public_url = upload_file(video_filepath, s3_key)
        return public_url, None
    except Exception as e:
        traceback.print_exc()
        return None, f"Animation generation error: {e}"

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
            video_a_path = os.path.join(BASE_DIR, video_a_url.lstrip('/'))
            if not os.path.exists(video_a_path):
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
            video_b_path = os.path.join(BASE_DIR, video_b_url.lstrip('/'))
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
    if not OPENAI_API_KEY: return None, "OpenAI API Key is required for this model but not found in .env file."
    try:
        print(f"-> Starting OpenAI via Replicate generation for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        full_prompt = f"{input_data['object_prompt']}, in the style of {input_data['style_prompt']}, on a transparent background"
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
        
        # Upload to S3 if enabled
        s3_key = f"library/{filename}"
        public_url = upload_file(filepath, s3_key)
        return public_url, None
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
        
        # Upload to S3 if enabled
        s3_key = f"library/{filename}"
        public_url = upload_file(filepath, s3_key)
        return public_url, None
    except Exception as e:
        print(f"   ❌ Bytedance generation error: {e}")
        traceback.print_exc()
        return None, f"Bytedance generation error: {e}"

def handle_background_removal(job):
    try:
        print(f"-> Starting BRIA background removal for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        image_path = input_data.get("image_path")
        if not image_path: return None, "No image path provided for background removal."
        
        # Handle both S3 URLs and local file paths
        if image_path.startswith('http'):
            # It's an S3 URL - download it first
            print(f"   ...downloading image from S3: {image_path}")
            img_response = requests.get(image_path)
            img_response.raise_for_status()
            temp_filename = f"temp_{uuid.uuid4()}.png"
            temp_filepath = os.path.join(LIBRARY_FOLDER, temp_filename)
            with open(temp_filepath, "wb") as f:
                f.write(img_response.content)
            full_image_path = temp_filepath
        else:
            # It's a local path
            if image_path.startswith('/'):
                full_image_path = os.path.join(BASE_DIR, image_path.lstrip('/'))
            else:
                full_image_path = os.path.join(BASE_DIR, image_path)
            if not os.path.exists(full_image_path): 
                return None, f"File not found for background removal: {full_image_path}"
        
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
        
        # Clean up temp file if we downloaded from S3
        if image_path.startswith('http'):
            try:
                os.remove(full_image_path)
                print(f"   ...cleaned up temp file")
            except Exception as e:
                print(f"   ...warning: could not delete temp file: {e}")
        
        # Upload to S3 if enabled
        s3_key = f"library/{filename}"
        public_url = upload_file(filepath, s3_key)
        return public_url, None
    except Exception as e:
        print(f"   ❌ Background removal error: {e}")
        traceback.print_exc()
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
                    
                    # Upload to S3 if enabled
                    s3_key = f"library/{filename}"
                    public_url = upload_file(filepath, s3_key)
                    filepaths.append(public_url)
                return filepaths[0], None
            elif status == "FAILED":
                return None, "Leonardo AI job failed."
    except Exception as e:
        print(f"   ❌ Leonardo generation error: {e}")
        traceback.print_exc()
        return None, f"Image generation error: {e}"

def handle_image_generation(job):
    input_data = json.loads(job['input_data'])
    model_id = input_data.get("modelId")
    if model_id == "bytedance-seedream-4": return handle_bytedance_generation(job)
    elif model_id == "replicate-gpt-image-1": return handle_replicate_openai_generation(job)
    else: return handle_leonardo_generation(job)

def handle_openai_vision_analysis(job):
    if not OPENAI_API_KEY: return None, "OpenAI API key is not initialized. Check API keys."
    try:
        job_type = job['job_type'].replace('_', ' ').capitalize()
        print(f"-> Starting OpenAI GPT-4o Vision Analysis ({job_type}) for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        print(f"   DEBUG: input_data keys: {input_data.keys()}")
        print(f"   DEBUG: image_path from input_data: {input_data.get('image_path', 'NOT FOUND')}")
        system_prompt = input_data.get('system_prompt', 'Analyze this image.')
        image_path = os.path.join(BASE_DIR, input_data['image_path'].lstrip('/'))
        print(f"   DEBUG: Full image path: {image_path}")
        print(f"   DEBUG: Image file exists: {os.path.exists(image_path)}")
        if not os.path.exists(image_path): return None, f"Image file not found at {image_path}"
        
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
            
        return analysis_text if analysis_text else None, None if analysis_text else "Empty response from OpenAI GPT-4o"
    except Exception as e:
        return None, f"OpenAI GPT-4o Vision API error: {e}"

def handle_keying(job):
    try:
        job_id = job['id']
        print(f"-> Starting OpenCV keying for job #{job_id}...")
        print(f"   JOB #{job_id}: Job type: {job['job_type']}")
        print(f"   JOB #{job_id}: Input video: {job['result_data']}")
        
        # Validate input file exists
        greenscreen_video_path = os.path.join(BASE_DIR, job['result_data'].lstrip('/'))
        if not os.path.exists(greenscreen_video_path):
            error_msg = f"Input video file not found: {greenscreen_video_path}"
            print(f"   JOB #{job_id}: ERROR - {error_msg}")
            return None, error_msg
            
        print(f"   JOB #{job_id}: Full input path: {greenscreen_video_path}")
        print(f"   JOB #{job_id}: File exists: {os.path.exists(greenscreen_video_path)}")
        print(f"   JOB #{job_id}: File size: {os.path.getsize(greenscreen_video_path)} bytes")
        
        # Parse keying settings
        settings = json.loads(job['keying_settings'])
        print(f"   JOB #{job_id}: Keying settings: {settings}")
        
        # Generate unique output filename
        output_filename = f"keyed_{job_id}_{uuid.uuid4().hex[:8]}.webm"
        final_output_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, output_filename)
        print(f"   JOB #{job_id}: Output will be: {final_output_path}")
        
        # Prepare keying parameters
        lower_green = [settings['hue_center'] - settings['hue_tolerance'], settings['saturation_min'], settings['value_min']]
        upper_green = [settings['hue_center'] + settings['hue_tolerance'], 255, 255]
        print(f"   JOB #{job_id}: Color range - Lower: {lower_green}, Upper: {upper_green}")
        
        # Process video
        print(f"   JOB #{job_id}: ▶️  Starting video processing...")
        process_video_with_opencv(
            video_path=greenscreen_video_path, 
            output_path=final_output_path, 
            lower_green=lower_green, 
            upper_green=upper_green, 
            erode_amount=settings['erode'], 
            dilate_amount=settings['dilate'], 
            blur_amount=settings['blur'], 
            spill_amount=settings['spill']
        )
        
        # Verify output was created
        if not os.path.exists(final_output_path):
            error_msg = f"Output file was not created: {final_output_path}"
            print(f"   JOB #{job_id}: ERROR - {error_msg}")
            return None, error_msg
            
        output_size = os.path.getsize(final_output_path)
        print(f"   JOB #{job_id}: ✅ Keying completed successfully!")
        print(f"   JOB #{job_id}: Output file: {final_output_path}")
        print(f"   JOB #{job_id}: Output size: {output_size} bytes")
        
        # Upload to S3 if enabled
        s3_key = f"library/transparent_videos/{output_filename}"
        public_url = upload_file(final_output_path, s3_key)
        return public_url, None
    except Exception as e:
        print(f"   JOB #{job.get('id', '???')}: ❌ Keying failed with error: {e}")
        traceback.print_exc()
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
                # Create stitching job with current timestamp
                stitch_timestamp = datetime.now()
                cursor.execute("INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)", ('video_stitching', 'queued', stitch_timestamp, prompt, stitch_input_data, meta_job['id']))
                # Update parent job status and timestamp to be 1 second after stitching job so it appears above in queue
                parent_timestamp = stitch_timestamp + timedelta(seconds=1)
                cursor.execute("UPDATE jobs SET status = 'stitching', created_at = ? WHERE id = ?", (parent_timestamp, meta_job['id']))
                conn.commit()
                print(f"   ...queued stitching job for raw videos: {video_paths}")
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
            
            # Check if all required analysis jobs are completed
            analyses_complete = True
            style_result = None
            color_result = None
            
            if style_job_id:
                style_job = cursor.execute(
                    "SELECT status, result_data FROM jobs WHERE id = ?", (style_job_id,)
                ).fetchone()
                if style_job and style_job['status'] == 'completed':
                    style_result = style_job['result_data']
                else:
                    analyses_complete = False
            
            if color_job_id:
                color_job = cursor.execute(
                    "SELECT status, result_data FROM jobs WHERE id = ?", (color_job_id,)
                ).fetchone()
                if color_job and color_job['status'] == 'completed':
                    color_result = color_job['result_data']
                else:
                    analyses_complete = False
            
            # If all analyses are complete, merge results and queue the job
            if analyses_complete:
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
                
                # Update input_data with merged style
                input_data['style_prompt'] = merged_style
                
                # Update prompt with merged style
                object_prompt = input_data.get('object_prompt', '')
                new_prompt = f"{object_prompt}, in the style of {merged_style}" if merged_style else object_prompt
                
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
                    cursor.execute("UPDATE jobs SET status = ?, error_message = ? WHERE id = ?", (new_status, str(error_message), job_id))
                elif job['status'] in ['keying_queued', 'keying_processing']:
                    # Handle keying completion BEFORE checking job_type
                    new_status = 'completed'
                    cursor.execute("UPDATE jobs SET status = ?, keyed_result_data = ? WHERE id = ?", (new_status, result_data, job_id))
                elif job['job_type'] == 'boomerang_automation':
                    # This is for initial boomerang setup, not keying
                    new_status = result_data # This should be 'waiting_for_children'
                    cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
                elif job['status'] in ['queued', 'processing']:
                    # For animations that are part of boomerang automation, complete them automatically
                    if job['job_type'] == 'animation' and job['parent_job_id']:
                        try:
                            parent_job = cursor.execute("SELECT job_type FROM jobs WHERE id = ?", (job['parent_job_id'],)).fetchone()
                            if parent_job and parent_job['job_type'] == 'boomerang_automation':
                                new_status = 'completed'  # Complete without keying for boomerang automation
                                print(f"   ...auto-completing animation job {job_id} (part of boomerang automation #{job['parent_job_id']})")
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
                        # Mark all jobs as completed (animations no longer need review)
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
                        # Priority: keying jobs first
                        job = cursor.execute("SELECT * FROM jobs WHERE status = 'keying_queued' ORDER BY created_at ASC LIMIT 1").fetchone()
                        if job:
                            cursor.execute("UPDATE jobs SET status = 'keying_processing' WHERE id = ?", (job['id'],))
                            conn.commit()
                            job = cursor.execute("SELECT * FROM jobs WHERE id = ?", (job['id'],)).fetchone()
                        else:
                            # Then regular queued jobs
                            job = cursor.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
                            if job:
                                cursor.execute("UPDATE jobs SET status = 'processing' WHERE id = ?", (job['id'],))
                                conn.commit()
                                job = cursor.execute("SELECT * FROM jobs WHERE id = ?", (job['id'],)).fetchone()
                    
                    if job:
                        # Submit job to thread pool
                        job_dict = dict(job)
                        future = executor.submit(process_single_job_worker, job_dict)
                        active_futures[future] = job['id']
                        print(f"Submitted job {job['id']} to worker thread pool ({len(active_futures)}/{MAX_CONCURRENT_JOBS} active)")
                
                # Show status if no jobs are being processed
                if len(active_futures) == 0:
                    print("No jobs found. Waiting...", end='\r')
                
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

