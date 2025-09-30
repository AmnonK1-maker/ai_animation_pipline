import os
import io
import json
import uuid
import shutil
import sqlite3
import base64
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, json, Response
import cv2
import numpy as np
from dotenv import load_dotenv
from PIL import Image
from video_processor import process_single_frame

app = Flask(__name__)
# Disable template caching for development
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
load_dotenv()

# --- CONFIGURATION & FOLDER PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
UPLOADS_FOLDER = os.path.join(STATIC_FOLDER, 'uploads')
LIBRARY_FOLDER = os.path.join(STATIC_FOLDER, 'library')
ANIMATIONS_FOLDER_GENERATED = os.path.join(STATIC_FOLDER, 'animations', 'generated')
TRANSPARENT_VIDEOS_FOLDER = os.path.join(STATIC_FOLDER, 'library', 'transparent_videos')

os.makedirs(UPLOADS_FOLDER, exist_ok=True)
os.makedirs(LIBRARY_FOLDER, exist_ok=True)
os.makedirs(ANIMATIONS_FOLDER_GENERATED, exist_ok=True)
os.makedirs(TRANSPARENT_VIDEOS_FOLDER, exist_ok=True)

DATABASE_PATH = 'jobs.db'

# --- DATABASE HELPER ---
def get_db_connection():
    """Creates a database connection with WAL mode enabled for high concurrency."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_type TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL, prompt TEXT, input_data TEXT,
                    result_data TEXT, error_message TEXT, keying_settings TEXT,
                    keyed_result_data TEXT, parent_job_id INTEGER
                )
            ''')
            existing_columns = [col[1] for col in cursor.execute("PRAGMA table_info(jobs)").fetchall()]
            columns_to_add = { 'keying_settings': 'TEXT', 'keyed_result_data': 'TEXT', 'parent_job_id': 'INTEGER' }
            for col, col_type in columns_to_add.items():
                if col not in existing_columns:
                    try: 
                        cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
                        print(f"Added missing column: {col}")
                    except sqlite3.OperationalError as e:
                        print(f"Column {col} may already exist or error: {e}")
            conn.commit()
            print("Database initialized successfully.")
    except Exception as e:
        print(f"Database initialization error: {e}")
        raise

@app.cli.command("init-db")
def init_db_command():
    """Clears the existing data and creates new tables."""
    init_db()
    print("Initialized the database.")

@app.cli.command("reset-jobs")
def reset_jobs_command():
    """Clears all jobs from the database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs")
            conn.commit()
            print("All jobs cleared from database.")
    except Exception as e:
        print(f"Error clearing jobs: {e}")

@app.cli.command("clear-failed")
def clear_failed_command():
    """Clears only failed jobs from the database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM jobs WHERE status = 'failed'")
            count = result.rowcount
            conn.commit()
            print(f"Cleared {count} failed jobs from database.")
    except Exception as e:
        print(f"Error clearing failed jobs: {e}")

@app.cli.command("clear-stuck")
def clear_stuck_command():
    """Clears stuck processing jobs from the database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM jobs WHERE status IN ('processing', 'keying_processing')")
            count = result.rowcount
            conn.commit()
            print(f"Cleared {count} stuck processing jobs from database.")
    except Exception as e:
        print(f"Error clearing stuck jobs: {e}")

def preprocess_animation_image(source_image_path, background_color_str):
    try:
        # Handle both relative and absolute paths more safely
        if source_image_path.startswith('/'):
            source_full_path = os.path.join(BASE_DIR, source_image_path.lstrip('/'))
        else:
            source_full_path = os.path.join(BASE_DIR, source_image_path)
        if not os.path.exists(source_full_path):
            print(f"Preprocessing error: Source file not found at {source_full_path}")
            return source_image_path

        color_map = {"green": (0, 255, 0), "blue": (0, 0, 255)}
        background_color = color_map.get(background_color_str)
        if not background_color: return source_image_path

        print(f"-> Pre-processing animation input: {source_image_path}")
        with Image.open(source_full_path).convert("RGBA") as fg_image:
            bg_image = Image.new("RGBA", fg_image.size, background_color)
            new_size = (int(fg_image.width * 0.9), int(fg_image.height * 0.9))
            fg_image_resized = fg_image.resize(new_size, Image.Resampling.LANCZOS)
            paste_position = ((bg_image.width - fg_image_resized.width) // 2, (bg_image.height - fg_image_resized.height) // 2)
            bg_image.paste(fg_image_resized, paste_position, fg_image_resized)
            output_filename = f"preprocessed_{uuid.uuid4()}.png"
            output_full_path = os.path.join(UPLOADS_FOLDER, output_filename)
            bg_image.convert("RGB").save(output_full_path, 'PNG')
            print(f"   ...saved pre-processed image to {output_full_path}")
            return os.path.join('static/uploads', output_filename)
    except Exception as e:
        print(f"Error during image pre-processing: {e}")
        return source_image_path


# --- Main Routes ---
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/fine-tune/<int:job_id>")
def fine_tune_page(job_id):
    with get_db_connection() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    
    if not job: return "Job not found.", 404

    fps = 30 
    video_path = os.path.join(BASE_DIR, job['result_data'].lstrip('/'))
    if os.path.exists(video_path):
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()

    return render_template("fine_tune.html", job=dict(job), fps=fps)

# --- WORKFLOW ROUTES ---
@app.route("/save-keying-settings/<int:job_id>", methods=["POST"])
def save_keying_settings(job_id):
    settings = {
        "hue_center": int(request.form.get('hue_center', 60)), "hue_tolerance": int(request.form.get('hue_tolerance', 25)),
        "saturation_min": int(request.form.get('saturation_min', 50)), "value_min": int(request.form.get('value_min', 50)),
        "erode": int(request.form.get('erode', 2)), "dilate": int(request.form.get('dilate', 1)),
        "blur": int(request.form.get('blur', 5)), "spill": int(request.form.get('spill', 2))
    }
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get current job info for logging
        job = cursor.execute("SELECT job_type, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job:
            print(f"-> Saving keying settings for job {job_id} ({job['job_type']}) - was {job['status']}, now pending_process")
        
        cursor.execute("UPDATE jobs SET status = ?, keying_settings = ? WHERE id = ?", ('pending_process', json.dumps(settings), job_id))
        conn.commit()
        
        print(f"   ...settings saved: {settings}")
    
    return redirect(url_for('home'))

@app.route("/process-all-pending", methods=["POST"])
def process_all_pending():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Count jobs that will be processed
        pending_process_count = cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'pending_process'").fetchone()[0]
        print(f"-> Processing pending keys: {pending_process_count} jobs in pending_process status")
        
        # Move pending_process jobs to keying_queued (jobs with custom settings)
        if pending_process_count > 0:
            pending_process_jobs = cursor.execute("SELECT id, job_type FROM jobs WHERE status = 'pending_process'").fetchall()
            for job in pending_process_jobs:
                print(f"   ...queuing job {job['id']} ({job['job_type']}) with custom settings")
            cursor.execute("UPDATE jobs SET status = 'keying_queued' WHERE status = 'pending_process'")
        
        # Also move pending_review jobs to keying_queued (with default settings)
        pending_review_jobs = cursor.execute("SELECT id, job_type FROM jobs WHERE status = 'pending_review' AND job_type IN ('animation', 'video_stitching')").fetchall()
        
        # Handle completed jobs that have custom keying_settings (for re-keying)
        completed_with_settings = cursor.execute("""
            SELECT id, job_type FROM jobs 
            WHERE status = 'completed' 
            AND job_type IN ('animation', 'video_stitching') 
            AND keying_settings IS NOT NULL 
            AND keying_settings != ''
        """).fetchall()
        
        if completed_with_settings:
            print(f"   ...found {len(completed_with_settings)} completed jobs with custom keying settings")
        
        updated_count = pending_process_count
        
        # Process pending_review jobs with default settings
        for job in pending_review_jobs:
            default_settings = {
                "hue_center": 60, "hue_tolerance": 25,
                "saturation_min": 50, "value_min": 50,
                "erode": 2, "dilate": 1, "blur": 5, "spill": 2
            }
            cursor.execute(
                "UPDATE jobs SET status = 'keying_queued', keying_settings = ? WHERE id = ?",
                (json.dumps(default_settings), job['id'])
            )
            updated_count += 1
            
        # Process completed jobs with custom keying settings (re-keying)
        for job in completed_with_settings:
            cursor.execute("UPDATE jobs SET status = 'keying_queued' WHERE id = ?", (job['id'],))
            updated_count += 1
        
        conn.commit()
        
        if updated_count > 0:
            custom_count = pending_process_count + len(completed_with_settings)
            default_count = len(pending_review_jobs)
            
            if custom_count > 0 and default_count > 0:
                message = f"Queued {custom_count} video(s) with custom settings and {default_count} with default settings for keying."
            elif custom_count > 0:
                message = f"Queued {custom_count} video(s) with custom keying settings."
            else:
                message = f"Queued {default_count} video(s) with default keying settings."
                
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": True, "message": "No pending videos found to process."})

@app.route("/animate-image")
def animate_image_page():
    image_url = request.args.get("image_url")
    parent_job_id = request.args.get("parent_job_id")
    return render_template("animation_step.html", image_url=image_url, parent_job_id=parent_job_id)

@app.route("/upload-for-animation", methods=["POST"])
def upload_for_animation():
    if 'image' not in request.files: return "No image file provided.", 400
    image_file = request.files['image']
    if image_file.filename == '': return "No selected file.", 400
    
    filename = f"upload_{uuid.uuid4()}_{os.path.basename(image_file.filename)}"
    save_path = os.path.join(UPLOADS_FOLDER, filename)
    image_file.save(save_path)
    
    image_url = os.path.join('/static/uploads', filename)
    return redirect(url_for('animate_image_page', image_url=image_url))
    
@app.route("/stitch-videos", methods=["POST"])
def stitch_videos():
    data = request.get_json()
    video_paths = data.get('video_paths')
    
    if not video_paths or len(video_paths) != 2:
        return jsonify({"success": False, "error": "Please select exactly two videos to stitch."}), 400

    prompt = f"Stitch {os.path.basename(video_paths[0])} and {os.path.basename(video_paths[1])}"
    input_data = json.dumps({"video_a_path": video_paths[0], "video_b_path": video_paths[1]})

    with get_db_connection() as conn:
        conn.cursor().execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
            ('video_stitching', 'queued', datetime.now(), prompt, input_data)
        )
        conn.commit()
    
    return jsonify({"success": True, "message": "Video stitching job queued."})

# --- Form Handlers for Job Creation ---
@app.route("/style-tool", methods=["POST"])
def style_tool():
    image_file = request.files.get("image")
    if not image_file: return jsonify({"error": "Missing image."}), 400
    system_prompt = request.form.get("system_prompt", "Default prompt")
    user_prompt = "Analyze image style."
    filename = f"{uuid.uuid4()}-{os.path.basename(image_file.filename)}"
    image_path = os.path.join(UPLOADS_FOLDER, filename)
    image_file.save(image_path)
    input_data = json.dumps({"image_path": os.path.join('static/uploads', filename), "system_prompt": system_prompt})
    with get_db_connection() as conn:
        conn.cursor().execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, result_data) VALUES (?, ?, ?, ?, ?, ?)",
            ('style_analysis', 'queued', datetime.now(), user_prompt, input_data, os.path.join('static/uploads', filename))
        )
        conn.commit()
    return jsonify({"success": True})

@app.route("/palette-tool", methods=["POST"])
def palette_tool():
    image_file = request.files.get("image")
    if not image_file: return jsonify({"error": "Missing image."}), 400
    system_prompt = """Analyze the provided image and identify the 5 most prominent colors. For each color, provide its hexadecimal code and a simple, descriptive name (e.g., 'dark slate blue', 'light coral'). Return the response as a valid JSON object with a single key "palette" which is an array of objects. Each object in the array should have two keys: "hex" and "name". Example: {"palette": [{"hex": "#2F4F4F", "name": "dark slate grey"}, ...]}"""
    user_prompt = "Analyze image palette."
    filename = f"{uuid.uuid4()}-{os.path.basename(image_file.filename)}"
    image_path = os.path.join(UPLOADS_FOLDER, filename)
    image_file.save(image_path)
    input_data = json.dumps({"image_path": os.path.join('static/uploads', filename), "system_prompt": system_prompt})
    with get_db_connection() as conn:
        conn.cursor().execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, result_data) VALUES (?, ?, ?, ?, ?, ?)",
            ('palette_analysis', 'queued', datetime.now(), user_prompt, input_data, os.path.join('static/uploads', filename))
        )
        conn.commit()
    return jsonify({"success": True})

@app.route("/image-tool", methods=["POST"])
def image_tool():
    selected_models = request.form.getlist("modelId")
    if not selected_models: return jsonify({"error": "Please select at least one model."}), 400
    
    parent_job_id = request.form.get("parent_job_id")
    object_prompt = request.form.get("object_prompt")
    style_prompt = request.form.get("style_prompt")
    preset_style = request.form.get("presetStyle")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        for model_id in selected_models:
            prompt = f"{object_prompt}, in the style of {style_prompt}"
            if model_id == "replicate-gpt-image-1":
                prompt = f"{object_prompt} on a transparent background, in the style of {style_prompt}"

            input_data = {
                "object_prompt": object_prompt, "style_prompt": style_prompt, 
                "modelId": model_id, "presetStyle": preset_style
            }
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                ('image_generation', 'queued', datetime.now(), prompt, json.dumps(input_data), parent_job_id)
            )
        conn.commit()
    return jsonify({"success": True})

@app.route("/generate-animation", methods=["POST"])
def generate_animation():
    parent_job_id = request.form.get("parent_job_id")
    prompt = request.form.get("prompt")
    
    if request.form.get("boomerang_automation") == "true" and request.form.get("end_image_url"):
        all_input_data = dict(request.form)
        meta_prompt = f"A-B-A Loop Automation: {prompt}"
        with get_db_connection() as conn:
            conn.cursor().execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                ('boomerang_automation', 'queued', datetime.now(), meta_prompt, json.dumps(all_input_data), parent_job_id)
            )
            conn.commit()
        return jsonify({"success": True, "message": "A-B-A loop automation job queued."})

    selected_models = request.form.getlist("video_model")
    if not selected_models: return jsonify({"error": "Please select at least one video model."}), 400
    
    background_option = request.form.get("background", "default")
    image_url = request.form.get("image_url")
    if not image_url or not prompt: return jsonify({"error": "Missing image_url or prompt"}), 400

    processed_image_url = preprocess_animation_image(image_url, background_option)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        for model in selected_models:
            input_data = {
                "image_url": processed_image_url, "end_image_url": request.form.get("end_image_url"),
                "prompt": prompt, "negative_prompt": request.form.get("negative_prompt", ""),
                "seamless_loop": request.form.get("seamless_loop") == "true", "video_model": model,
                "kling_duration": int(request.form.get("kling-duration", 5)), "kling_mode": request.form.get("kling-mode", "pro"),
                "seedance_duration": int(request.form.get("seedance-duration", 5)), "seedance_resolution": request.form.get("seedance-resolution", "1080p"),
                "seedance_aspect_ratio": request.form.get("seedance-aspect-ratio", "1:1")
            }
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                ('animation', 'queued', datetime.now(), prompt, json.dumps(input_data), parent_job_id)
            )
        conn.commit()
    return jsonify({"success": True, "message": f"{len(selected_models)} job(s) queued."})

@app.route("/get-animation-idea", methods=["POST"])
def get_animation_idea():
    image_url = request.form.get("image_url")
    if not image_url: return jsonify({"success": False, "error": "Missing image URL."}), 400

    system_prompt = "You are a creative animator. Look at the provided image. Describe a short, simple, 3-second animation for the main character or object. Be concise and focus on a single, clear action. Do not use punctuation. Your entire response should be a single phrase suitable for a text-to-video prompt."
    user_prompt = "Generate animation idea"
    input_data = json.dumps({"image_path": image_url.lstrip('/'), "system_prompt": system_prompt})
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
            ('animation_prompting', 'queued', datetime.now(), user_prompt, input_data)
        )
        job_id = cursor.lastrowid
        conn.commit()

    return jsonify({"success": True, "job_id": job_id})

@app.route("/remove-background", methods=["POST"])
def remove_background():
    image_url = request.form.get("image_url")
    parent_job_id = request.form.get("parent_job_id")
    if not image_url: return jsonify({"error": "Missing image URL for background removal."}), 400
    
    prompt = f"Remove background from {os.path.basename(image_url)}"
    input_data = json.dumps({"image_path": image_url.lstrip('/')})
    
    with get_db_connection() as conn:
        conn.cursor().execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
            ('background_removal', 'queued', datetime.now(), prompt, input_data, parent_job_id)
        )
        conn.commit()
    return jsonify({"success": True, "message": "Background removal job queued."})

# --- API Endpoints ---
# app.py - Corrected Code

# app.py - New, More Robust Function

# app.py - Final, robust version

@app.route("/api/jobs")
def api_jobs_log():
    try:
        with get_db_connection() as conn:
            query = """
                SELECT j.*, p.id as parent_id, p.result_data as parent_result_data
                FROM jobs j LEFT JOIN jobs p ON j.parent_job_id = p.id
                ORDER BY j.created_at DESC
            """
            jobs_rows = conn.execute(query).fetchall()

        # Convert rows to a list of dictionaries
        job_list = [dict(row) for row in jobs_rows]

        # Use json.dumps with a default handler to convert non-serializable
        # objects (like datetime) to strings. This is a foolproof method.
        json_string = json.dumps(job_list, default=str)

        # Return a manual Response object with the correct content type
        return Response(json_string, content_type='application/json')

    except Exception as e:
        # If anything goes wrong on the server, log it and return a 500 error
        print(f"ERROR in /api/jobs: {e}")
        return jsonify({"error": "Failed to fetch job history from server."}), 500
    
@app.route('/api/extract-frame', methods=['POST'])
def extract_frame():
    data = request.json
    video_path_url = data.get('video_path')
    frame_time = float(data.get('frame_time', 0))
    parent_job_id = data.get('parent_job_id')

    if not video_path_url: return jsonify({"error": "Missing video path"}), 400
    
    video_path = os.path.join(BASE_DIR, video_path_url.lstrip('/'))
    if not os.path.exists(video_path): return jsonify({"error": "Video file not found"}), 404
        
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, frame_time * 1000)
    success, frame = cap.read()
    cap.release()

    if not success: return jsonify({"error": "Could not read frame"}), 500

    frame_filename = f"frame_{uuid.uuid4()}.png"
    frame_filepath = os.path.join(LIBRARY_FOLDER, frame_filename)
    cv2.imwrite(frame_filepath, frame)
    
    result_path = os.path.join('static/library', frame_filename)
    prompt = f"Frame from {os.path.basename(video_path_url)} at {frame_time:.2f}s"
    input_data = json.dumps({"source_video": video_path_url, "time": frame_time})
    
    with get_db_connection() as conn:
        conn.cursor().execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, result_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('frame_extraction', 'completed', datetime.now(), prompt, input_data, result_path, parent_job_id)
        )
        conn.commit()
    
    return jsonify({"success": True, "path": result_path})

@app.route("/api/batch-delete-items", methods=["POST"])
def batch_delete_items():
    data = request.get_json()
    job_ids = data.get('job_ids')
    if not job_ids: return jsonify({"success": False, "error": "No job IDs provided."}), 400
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' for _ in job_ids)
            jobs_to_delete = cursor.execute(f"SELECT result_data, keyed_result_data, input_data FROM jobs WHERE id IN ({placeholders})", job_ids).fetchall()
            
            for job in jobs_to_delete:
                path_sources = [job['result_data'], job['keyed_result_data']]
                try:
                    input_data_dict = json.loads(job['input_data'] or '{}')
                    if 'image_path' in input_data_dict:
                        path_sources.append(input_data_dict['image_path'])
                except (json.JSONDecodeError, TypeError): pass

                for path in path_sources:
                    if not path or not isinstance(path, str): continue
                    try:
                        file_path = os.path.join(BASE_DIR, path.lstrip('/'))
                        if os.path.exists(file_path) and os.path.isfile(file_path):
                            os.remove(file_path)
                            print(f"-> Deleted file: {file_path}")
                    except Exception as e:
                        print(f"Could not delete file {path}. Error: {e}")

            cursor.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)
            conn.commit()
            return jsonify({"success": True, "message": f"{len(job_ids)} items deleted."})
    except Exception as e:
        return jsonify({"success": False, "error": f"A server error occurred: {e}"}), 500

@app.route("/api/video-metadata", methods=['POST'])
def get_video_metadata():
    video_path_url = request.json.get('video_path')
    if not video_path_url: return jsonify({"error": "Missing video path"}), 400
    video_path = os.path.join(BASE_DIR, video_path_url.lstrip('/'))
    if not os.path.exists(video_path): return jsonify({"error": "Video file not found"}), 404
    try:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        return jsonify({"fps": fps if fps > 0 else 30})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/library-images")
def get_library_images():
    images = []
    valid_extensions = ('.png', '.jpg', '.jpeg', '.webp')
    for filename in os.listdir(LIBRARY_FOLDER):
        if filename.lower().endswith(valid_extensions):
            images.append(os.path.join('/static/library', filename))
    return jsonify(sorted(images, reverse=True))
    
@app.route("/api/library-videos")
def get_library_videos():
    videos = []
    valid_extensions = ('.mp4', '.webm')
    folders_to_check = [LIBRARY_FOLDER, ANIMATIONS_FOLDER_GENERATED, TRANSPARENT_VIDEOS_FOLDER]
    for folder in folders_to_check:
        relative_folder = os.path.relpath(folder, STATIC_FOLDER)
        for filename in os.listdir(folder):
            if filename.lower().endswith(valid_extensions):
                videos.append(os.path.join('/static', relative_folder, filename).replace('\\', '/'))
    return jsonify(sorted(list(set(videos)), reverse=True))

@app.route("/api/job-status/<int:job_id>")
def get_job_status(job_id):
    with get_db_connection() as conn:
        job = conn.execute("SELECT status, result_data, error_message FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job: return jsonify({"status": "not_found"}), 404
    return jsonify(dict(job))

@app.route("/api/reset-job", methods=["POST"])
def reset_job():
    """Reset a job to a different status for retry/re-processing"""
    try:
        data = request.get_json()
        job_id = data.get('job_id')
        new_status = data.get('new_status')
        
        if not job_id or not new_status:
            return jsonify({"success": False, "error": "Missing job_id or new_status"}), 400
        
        # Validate new_status
        valid_statuses = ['queued', 'pending_review', 'failed', 'completed']
        if new_status not in valid_statuses:
            return jsonify({"success": False, "error": f"Invalid status. Must be one of: {valid_statuses}"}), 400
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Check if job exists
            job = cursor.execute("SELECT id, job_type, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return jsonify({"success": False, "error": "Job not found"}), 404
            
            # Clear error message when resetting
            cursor.execute(
                "UPDATE jobs SET status = ?, error_message = NULL WHERE id = ?",
                (new_status, job_id)
            )
            conn.commit()
            
            print(f"-> Reset job {job_id} ({job['job_type']}) from '{job['status']}' to '{new_status}'")
            return jsonify({"success": True, "message": f"Job {job_id} reset to {new_status}"})
            
    except Exception as e:
        print(f"ERROR in /api/reset-job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/clear-all-jobs", methods=["POST"])
def clear_all_jobs():
    """Clear all jobs from the database via API"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM jobs")
            count = result.rowcount
            conn.commit()
            print(f"-> Cleared {count} jobs via API")
            return jsonify({"success": True, "message": f"Cleared {count} jobs from database."})
    except Exception as e:
        print(f"ERROR in /api/clear-all-jobs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/clear-failed-jobs", methods=["POST"])
def clear_failed_jobs():
    """Clear only failed jobs from the database via API"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM jobs WHERE status = 'failed'")
            count = result.rowcount
            conn.commit()
            print(f"-> Cleared {count} failed jobs via API")
            return jsonify({"success": True, "message": f"Cleared {count} failed jobs from database."})
    except Exception as e:
        print(f"ERROR in /api/clear-failed-jobs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/clear-stuck-jobs", methods=["POST"])
def clear_stuck_jobs():
    """Clear stuck processing jobs from the database via API"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM jobs WHERE status IN ('processing', 'keying_processing', 'stitching')")
            count = result.rowcount
            conn.commit()
            print(f"-> Cleared {count} stuck jobs via API")
            return jsonify({"success": True, "message": f"Cleared {count} stuck processing jobs from database."})
    except Exception as e:
        print(f"ERROR in /api/clear-stuck-jobs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/cancel-job/<int:job_id>", methods=["POST"])
def cancel_job(job_id):
    """Cancel a specific job by ID"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Check if job exists and is cancellable
            job = cursor.execute("SELECT id, job_type, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return jsonify({"success": False, "error": "Job not found"}), 404
            
            cancellable_statuses = ['processing', 'keying_processing', 'stitching', 'queued', 'keying_queued']
            if job['status'] not in cancellable_statuses:
                return jsonify({"success": False, "error": f"Cannot cancel job with status '{job['status']}'"}), 400
            
            # Cancel the job
            cursor.execute("UPDATE jobs SET status = 'failed', error_message = ? WHERE id = ?", 
                         (f"Job cancelled by user at {datetime.now()}", job_id))
            conn.commit()
            
            print(f"-> Cancelled job {job_id} ({job['job_type']}) from status '{job['status']}'")
            return jsonify({"success": True, "message": f"Job {job_id} cancelled successfully"})
            
    except Exception as e:
        print(f"ERROR in /api/cancel-job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/preview-frame', methods=['POST'])
def preview_frame():
    video_path_url = request.form.get('video_path')
    frame_time = float(request.form.get('frame_time', 0))
    if not video_path_url: return "Missing video path", 400
    video_path = os.path.join(BASE_DIR, video_path_url.lstrip('/'))
    if not os.path.exists(video_path): return "Video file not found", 404
        
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, frame_time * 1000)
    success, frame = cap.read()
    cap.release()
    if not success: return "Could not read frame from video", 500

    settings = {
        "hue_center": int(request.form.get('hue_center', 60)), "hue_tolerance": int(request.form.get('hue_tolerance', 25)),
        "saturation_min": int(request.form.get('saturation_min', 50)), "value_min": int(request.form.get('value_min', 50)),
        "erode": int(request.form.get('erode', 2)), "dilate": int(request.form.get('dilate', 1)),
        "blur": int(request.form.get('blur', 5)), "spill": int(request.form.get('spill', 2))
    }
    lower_green = [settings['hue_center'] - settings['hue_tolerance'], settings['saturation_min'], settings['value_min']]
    upper_green = [settings['hue_center'] + settings['hue_tolerance'], 255, 255]
    bgra_frame = process_single_frame(
        frame, lower_green, upper_green,
        settings['erode'], settings['dilate'], settings['blur'], settings['spill']
    )
    _, img_encoded = cv2.imencode('.png', bgra_frame)
    return send_file(io.BytesIO(img_encoded.tobytes()), mimetype='image/png')


if __name__ == '__main__':
    # Initialize database on startup
    init_db()
    # Start the Flask development server
    app.run(debug=True, host='0.0.0.0', port=5001)

