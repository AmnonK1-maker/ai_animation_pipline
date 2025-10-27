import os
import sys
import io
import json
import uuid
import shutil
import sqlite3
import base64
import subprocess
import traceback
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, Response
import cv2
import numpy as np
from dotenv import load_dotenv
from PIL import Image
from video_processor import process_single_frame
from s3_storage import storage, upload_file, save_uploaded_file, get_public_url, is_s3_enabled

# ============================================================================
# EMBEDDED API KEYS FOR STANDALONE INSTALLER
# ============================================================================
# These keys are embedded for the standalone installer version.
# They can be overridden by setting environment variables before launch.
# ⚠️ SECURITY NOTE: These keys are recoverable from the binary.
#    Only use for internal prototypes. Rotate keys frequently.
# ============================================================================

# Embed your shared API keys here (will be used if env vars not set)
# For cloud deployment, keys are set via Railway environment variables
# For standalone app, uncomment and add keys here
# os.environ.setdefault("OPENAI_API_KEY",     "your-key-here")
# os.environ.setdefault("OPENAI_ORG_ID",      "your-org-id-here")
# os.environ.setdefault("REPLICATE_API_KEY",  "your-key-here")
# os.environ.setdefault("LEONARDO_API_KEY",   "your-key-here")

# Optional: Disable S3 for standalone (use local storage only)
os.environ.setdefault("USE_S3", "false")
os.environ.setdefault("PRODUCTION_MODE", "false")

# Load environment variables (will use embedded keys if .env not present)
load_dotenv()

# --- CONFIGURATION & FOLDER PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# For standalone app, use user's Documents folder instead of app bundle
# This makes files accessible and prevents DMG from including user data
if getattr(sys, 'frozen', False):
    # Running as standalone app (PyInstaller bundle)
    USER_HOME = os.path.expanduser('~')
    AIAP_DATA_DIR = os.path.join(USER_HOME, 'Documents', 'AIAP')
    STATIC_FOLDER = os.path.join(AIAP_DATA_DIR, 'static')
    DATABASE_PATH = os.path.join(AIAP_DATA_DIR, 'jobs.db')
    print(f"📁 Running as standalone app")
    print(f"📁 Data directory: {AIAP_DATA_DIR}")
    # Templates are bundled in _MEIPASS
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_assets = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_assets)
else:
    # Running in development mode
    STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
    DATABASE_PATH = 'jobs.db'
    print(f"📁 Running in development mode")
    print(f"📁 Data directory: {BASE_DIR}")
    app = Flask(__name__)

UPLOADS_FOLDER = os.path.join(STATIC_FOLDER, 'uploads')
LIBRARY_FOLDER = os.path.join(STATIC_FOLDER, 'library')
ANIMATIONS_FOLDER_GENERATED = os.path.join(STATIC_FOLDER, 'animations', 'generated')
TRANSPARENT_VIDEOS_FOLDER = os.path.join(STATIC_FOLDER, 'library', 'transparent_videos')

# Create all necessary folders
os.makedirs(UPLOADS_FOLDER, exist_ok=True)
os.makedirs(LIBRARY_FOLDER, exist_ok=True)
os.makedirs(ANIMATIONS_FOLDER_GENERATED, exist_ok=True)
os.makedirs(TRANSPARENT_VIDEOS_FOLDER, exist_ok=True)

# Production mode check
PRODUCTION_MODE = os.getenv('PRODUCTION_MODE', 'false').lower() == 'true'

if not PRODUCTION_MODE:
    # Disable template caching for development
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.jinja_env.auto_reload = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    print("🔧 Running in DEVELOPMENT mode")
else:
    print("🚀 Running in PRODUCTION mode")

# --- JINJA2 FILTERS ---
@app.template_filter('smart_url')
def smart_url_filter(url):
    """Handle both local paths and S3/CloudFront URLs"""
    if not url:
        return ''
    # If it's already a full URL, use as-is
    if url.startswith('http://') or url.startswith('https://'):
        return url
    # If it starts with /, use as-is
    if url.startswith('/'):
        return url
    # Otherwise, prepend /
    return '/' + url

# --- DATABASE HELPER ---
def get_db_connection():
    """Creates a database connection with WAL mode enabled for high concurrency."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")  # 30 second timeout for busy database
    conn.row_factory = sqlite3.Row
    
    # Lazy initialization: Ensure table exists on every connection
    # This handles Railway's ephemeral filesystem issues
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        if not cursor.fetchone():
            print("⚠️ Table 'jobs' not found, initializing database...")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_type TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL, prompt TEXT, input_data TEXT,
                    result_data TEXT, error_message TEXT, keying_settings TEXT,
                    keyed_result_data TEXT, parent_job_id INTEGER
                )
            ''')
            conn.commit()
            print("✅ Database table created on-demand")
    except Exception as e:
        print(f"⚠️ Error during lazy DB init: {e}")
    
    return conn

def init_db():
    try:
        print(f"📁 Initializing database at: {DATABASE_PATH}")
        print(f"📁 Database exists before init: {os.path.exists(DATABASE_PATH)}")
        
        # Create database directory if it doesn't exist
        db_dir = os.path.dirname(DATABASE_PATH) if os.path.dirname(DATABASE_PATH) else '.'
        if db_dir != '.' and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            print(f"📁 Created database directory: {db_dir}")
        
        # Use direct connection without WAL mode for initialization
        conn = sqlite3.connect(DATABASE_PATH, timeout=30)
        conn.isolation_level = None  # Autocommit mode
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
                    print(f"✅ Added missing column: {col}")
                except sqlite3.OperationalError as e:
                    print(f"⚠️ Column {col} may already exist or error: {e}")
        
        # Verify table was created
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        if cursor.fetchone():
            print("✅ Table 'jobs' verified to exist")
        else:
            raise Exception("Failed to create 'jobs' table")
        
        conn.close()
        print(f"📁 Database exists after init: {os.path.exists(DATABASE_PATH)}")
        print("✅ Database initialized successfully.")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        import traceback
        traceback.print_exc()
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

def preprocess_animation_image(source_image_path, background_color_str, white_outline=False, outline_thickness=3):
    """
    Preprocess image for animation:
    1. Add white outline (if requested)
    2. Place on colored background (if requested)
    
    Order is critical: outline must be applied BEFORE background.
    """
    try:
        # Handle both S3 URLs and local file paths
        temp_file = None
        if source_image_path.startswith('http'):
            # Download from S3 first
            import requests
            print(f"   ...downloading image from S3 for preprocessing: {source_image_path}")
            img_response = requests.get(source_image_path)
            img_response.raise_for_status()
            temp_filename = f"temp_preprocess_{uuid.uuid4()}.png"
            temp_file = os.path.join(UPLOADS_FOLDER, temp_filename)
            with open(temp_file, "wb") as f:
                f.write(img_response.content)
            source_full_path = temp_file
        else:
            # It's a local path
            if source_image_path.startswith('/'):
                source_full_path = os.path.join(BASE_DIR, source_image_path.lstrip('/'))
            else:
                source_full_path = os.path.join(BASE_DIR, source_image_path)
            if not os.path.exists(source_full_path):
                print(f"Preprocessing error: Source file not found at {source_full_path}")
                return source_image_path

        print(f"-> Pre-processing animation input: {source_image_path}")
        fg_image = Image.open(source_full_path).convert("RGBA")
        
        # STEP 1: Add white outline if requested (BEFORE background)
        if white_outline and outline_thickness > 0:
            from PIL import ImageFilter
            print(f"   ...adding {outline_thickness}px white outline")
            
            # Extract alpha channel
            alpha = fg_image.split()[3]
            
            # Create outline by dilating the alpha mask
            outline = alpha.filter(ImageFilter.MaxFilter(outline_thickness * 2 + 1))
            
            # Create white outline layer
            outline_layer = Image.new("RGBA", fg_image.size, (255, 255, 255, 0))
            outline_layer.putalpha(outline)
            
            # Composite: white outline + original image
            fg_image = Image.alpha_composite(outline_layer, fg_image)
            print(f"   ...white outline applied")
        
        # STEP 2: Place on colored background if requested (AFTER outline)
        color_map = {"green": (0, 255, 0), "blue": (0, 0, 255)}
        background_color = color_map.get(background_color_str)
        
        if background_color:
            print(f"   ...placing image on {background_color_str} background")
            bg_image = Image.new("RGBA", fg_image.size, background_color)
            new_size = (int(fg_image.width * 0.85), int(fg_image.height * 0.85))
            fg_image_resized = fg_image.resize(new_size, Image.Resampling.LANCZOS)
            paste_position = ((bg_image.width - fg_image_resized.width) // 2, (bg_image.height - fg_image_resized.height) // 2)
            bg_image.paste(fg_image_resized, paste_position, fg_image_resized)
            fg_image = bg_image.convert("RGB")
        else:
            fg_image = fg_image.convert("RGB")
        
        output_filename = f"preprocessed_{uuid.uuid4()}.png"
        output_full_path = os.path.join(UPLOADS_FOLDER, output_filename)
        fg_image.save(output_full_path, 'PNG')
        print(f"   ...saved pre-processed image to {output_full_path}")
        
        # Clean up temp file if downloaded from S3
        if temp_file:
            try:
                os.remove(temp_file)
                print(f"   ...cleaned up temp file")
            except Exception as e:
                print(f"   ...warning: could not delete temp file: {e}")
        
        # Upload to S3 if enabled
        s3_key = f"uploads/{output_filename}"
        public_url = upload_file(output_full_path, s3_key)
        return public_url
    except Exception as e:
        print(f"Error during image pre-processing: {e}")
        # Clean up temp file on error
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        return source_image_path


# --- Main Routes ---
@app.route("/")
def home():
    # Pass data directory path to template for standalone app
    data_dir = None
    if getattr(sys, 'frozen', False):
        USER_HOME = os.path.expanduser('~')
        data_dir = os.path.join(USER_HOME, 'Documents', 'AIAP')
    return render_template("index_v2.html", data_dir=data_dir)

@app.route("/open-data-folder")
def open_data_folder():
    """Open the data folder in Finder (macOS) or Explorer (Windows)"""
    try:
        if getattr(sys, 'frozen', False):
            USER_HOME = os.path.expanduser('~')
            data_dir = os.path.join(USER_HOME, 'Documents', 'AIAP')
        else:
            data_dir = BASE_DIR
        
        # Ensure directory exists
        os.makedirs(data_dir, exist_ok=True)
        
        # Open in file manager
        if sys.platform == 'darwin':  # macOS
            subprocess.run(['open', data_dir])
        elif sys.platform == 'win32':  # Windows
            subprocess.run(['explorer', data_dir])
        else:  # Linux
            subprocess.run(['xdg-open', data_dir])
        
        return jsonify({"success": True, "message": f"Opened {data_dir}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/fine-tune/<int:job_id>")
def fine_tune_page(job_id):
    with get_db_connection() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    
    if not job: return "Job not found.", 404

    fps = 30 
    video_url = job['result_data']
    
    # Handle both S3 URLs and local file paths
    if video_url.startswith('http'):
        # For S3 URLs, we can't easily get FPS without downloading
        # Default to 30 FPS (standard for most generated videos)
        fps = 30
    else:
        video_path = os.path.join(BASE_DIR, video_url.lstrip('/'))
        if os.path.exists(video_path):
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()

    return render_template("fine_tune.html", job=dict(job), fps=fps)

# --- WORKFLOW ROUTES ---
@app.route("/save-keying-settings/<int:job_id>", methods=["POST"])
def save_keying_settings(job_id):
    try:
        settings = {
            "hue_center": int(request.form.get('hue_center', 60)), 
            "hue_tolerance": int(request.form.get('hue_tolerance', 25)),
            "saturation_min": int(request.form.get('saturation_min', 50)), 
            "value_min": int(request.form.get('value_min', 50)),
            "erode": int(request.form.get('erode', 0)), 
            "dilate": int(request.form.get('dilate', 0)),
            "blur": int(request.form.get('blur', 5)), 
            "spill": int(request.form.get('spill', 2)),
            # Sticker effect parameters
            "sticker_effect": request.form.get('sticker_effect') == 'on',  # Checkbox value
            "displacement_intensity": int(request.form.get('displacement_intensity', 3)),
            "screen_opacity": float(request.form.get('screen_opacity', 0.5))
        }
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Get current job info for logging
            job = cursor.execute("SELECT job_type, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return jsonify({"success": False, "error": f"Job {job_id} not found"}), 404
                
            if job:
                sticker_status = "✅ ENABLED" if settings['sticker_effect'] else "❌ Disabled"
                print(f"-> Saving keying settings for job {job_id} ({job['job_type']}) - was {job['status']}, now pending_process")
                print(f"   🎨 Sticker Effect: {sticker_status} (Displacement: {settings['displacement_intensity']}, Screen: {settings['screen_opacity']})")
            
            cursor.execute("UPDATE jobs SET status = ?, keying_settings = ? WHERE id = ?", ('pending_process', json.dumps(settings), job_id))
            conn.commit()
            
            print(f"   ...settings saved successfully")
        
        return jsonify({"success": True, "message": "Keying settings saved. Click 'Process Pending Jobs' to apply."})
    except Exception as e:
        print(f"Error saving keying settings: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/update-job-input/<int:job_id>", methods=["POST"])
def update_job_input(job_id):
    """Update the input_data field for a job (e.g., to set background color for uploaded videos)"""
    try:
        data = request.get_json()
        input_data = data.get('input_data')
        
        if not input_data:
            return jsonify({"success": False, "error": "No input_data provided"}), 400
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            job = cursor.execute("SELECT id, job_type FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return jsonify({"success": False, "error": f"Job {job_id} not found"}), 404
            
            print(f"-> Updating input_data for job {job_id} ({job['job_type']})")
            cursor.execute("UPDATE jobs SET input_data = ? WHERE id = ?", (json.dumps(input_data), job_id))
            conn.commit()
            print(f"   ...input_data updated: {input_data}")
        
        return jsonify({"success": True, "message": "Job input data updated"})
    except Exception as e:
        print(f"Error updating job input data: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/auto-key-video/<int:job_id>", methods=["POST"])
def auto_key_video(job_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Get job data including input_data
            job = cursor.execute("SELECT job_type, status, input_data FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return jsonify({"success": False, "error": f"Job {job_id} not found"}), 404
            
            # Parse input_data to get background color
            try:
                input_data = json.loads(job['input_data']) if job['input_data'] else {}
                bg_color = input_data.get('background', 'green')  # default to green
            except:
                bg_color = 'green'  # fallback to green if parsing fails
            
            # Set default settings based on background color
            if bg_color == 'blue':
                settings = {
                    "hue_center": 100, "hue_tolerance": 25,
                    "saturation_min": 50, "value_min": 50,
                    "erode": 0, "dilate": 0,
                    "blur": 5, "spill": 2
                }
                bg_display = "Blue Screen"
            elif bg_color == 'unknown':
                # For uploaded videos with unknown background, should have been set by frontend
                return jsonify({"success": False, "error": "Please specify background color (green or blue) for this uploaded video."}), 400
            else:  # 'green', 'as-is', or any other value - default to green screen
                settings = {
                    "hue_center": 60, "hue_tolerance": 25,
                    "saturation_min": 50, "value_min": 50,
                    "erode": 0, "dilate": 0,
                    "blur": 5, "spill": 2
                }
                bg_display = "Green Screen"
                
            print(f"-> Auto-keying {bg_color} background for job {job_id} ({job['job_type']}) - queuing for immediate processing")
            
            # Update with new timestamp to jump to top of queue
            cursor.execute(
                "UPDATE jobs SET status = ?, keying_settings = ?, created_at = ? WHERE id = ?", 
                ('keying_queued', json.dumps(settings), datetime.now(), job_id)
            )
            conn.commit()
            
            print(f"   ...auto-key settings saved and queued (jumped to top of queue): {settings}")
        
        return jsonify({"success": True, "message": f"Auto-key ({bg_display}) queued for processing!"})
    except Exception as e:
        print(f"Error in auto-key: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/upload-video-for-keying", methods=["POST"])
def upload_video_for_keying():
    """Upload a video file directly for keying (creates a placeholder job)"""
    try:
        if 'video' not in request.files:
            return jsonify({"success": False, "error": "No video file provided"}), 400
        
        video_file = request.files['video']
        if video_file.filename == '':
            return jsonify({"success": False, "error": "Empty filename"}), 400
        
        # Save the uploaded video
        filename = f"uploaded_{uuid.uuid4()}.mp4"
        video_path = os.path.join(UPLOADS_FOLDER, filename)
        video_file.save(video_path)
        
        # Upload to S3 if enabled
        s3_key = f"uploads/{filename}"
        video_url = upload_file(video_path, s3_key)
        
        # Create a placeholder job for this uploaded video
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO jobs (job_type, status, prompt, result_data, input_data, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            ''', (
                'video_upload',
                'completed',
                f'Uploaded video: {video_file.filename}',
                video_url,
                json.dumps({'original_filename': video_file.filename})
            ))
            conn.commit()
            job_id = cursor.lastrowid
        
        print(f"✅ Video uploaded for keying: {video_file.filename} -> Job ID: {job_id}")
        return jsonify({"success": True, "job_id": job_id, "video_url": video_url})
    
    except Exception as e:
        print(f"Error uploading video for keying: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/manual-key/<int:job_id>", methods=["POST"])
def manual_key_video(job_id):
    """Apply manual keying settings and immediately queue for processing"""
    try:
        print(f"🎬 /manual-key endpoint called for job #{job_id}")
        keying_settings_json = request.form.get('keying_settings')
        if not keying_settings_json:
            print(f"   ❌ No keying settings provided")
            return jsonify({"success": False, "error": "Missing keying settings"}), 400
        
        # Parse and validate the settings
        try:
            settings = json.loads(keying_settings_json)
            print(f"   ✅ Settings parsed: {settings}")
        except json.JSONDecodeError:
            print(f"   ❌ Invalid JSON in settings")
            return jsonify({"success": False, "error": "Invalid keying settings format"}), 400
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Verify job exists
            job = cursor.execute("SELECT job_type, result_data FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                print(f"   ❌ Job {job_id} not found in database")
                return jsonify({"success": False, "error": f"Job {job_id} not found"}), 404
            
            print(f"   ✅ Job found: type={job['job_type']}, video={job['result_data'][:50]}...")
            
            if not job['result_data']:
                print(f"   ❌ Job has no result_data (video)")
                return jsonify({"success": False, "error": "Job has no video to key"}), 400
            
            # Update job with keying settings and set status to keying_queued
            # Also update timestamp to jump to top of queue
            cursor.execute(
                "UPDATE jobs SET status = ?, keying_settings = ?, created_at = ? WHERE id = ?",
                ('keying_queued', json.dumps(settings), datetime.now(), job_id)
            )
            conn.commit()
            
            print(f"   ✅ Job #{job_id} marked as 'keying_queued' with timestamp={datetime.now()}")
            print(f"   🎯 Worker should pick up this job next!")
        
        return jsonify({"success": True, "message": "Manual keying job queued for processing"})
    except Exception as e:
        print(f"Error in manual-key: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

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
                "erode": 0, "dilate": 0, "blur": 5, "spill": 2
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

@app.route("/process-selected-pending", methods=["POST"])
def process_selected_pending():
    """Process only selected pending jobs for keying"""
    data = request.get_json()
    job_ids = data.get('job_ids', [])
    
    if not job_ids:
        return jsonify({"success": False, "error": "No job IDs provided."}), 400
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Validate and process each job ID
            processed_jobs = []
            placeholders = ','.join('?' for _ in job_ids)
            
            # Get jobs that can be processed for keying
            jobs_query = f"""
                SELECT id, job_type, status, keying_settings FROM jobs 
                WHERE id IN ({placeholders}) 
                AND job_type IN ('animation', 'video_stitching', 'video_upload', 'uploaded_video_keying')
                AND status IN ('pending_review', 'completed', 'pending_process')
            """
            jobs_to_process = cursor.execute(jobs_query, job_ids).fetchall()
            
            if not jobs_to_process:
                return jsonify({"success": False, "error": "No valid jobs found for keying processing."}), 400
            
            for job in jobs_to_process:
                if job['status'] == 'pending_process' or (job['keying_settings'] and job['keying_settings'].strip()):
                    # Job already has custom settings, just queue it
                    cursor.execute("UPDATE jobs SET status = 'keying_queued' WHERE id = ?", (job['id'],))
                    processed_jobs.append(f"#{job['id']} (custom settings)")
                else:
                    # Add default keying settings
                    default_settings = {
                        "hue_center": 60, "hue_tolerance": 25,
                        "saturation_min": 50, "value_min": 50,
                        "erode": 0, "dilate": 0, "blur": 5, "spill": 2
                    }
                    cursor.execute(
                        "UPDATE jobs SET status = 'keying_queued', keying_settings = ? WHERE id = ?",
                        (json.dumps(default_settings), job['id'])
                    )
                    processed_jobs.append(f"#{job['id']} (default settings)")
            
            conn.commit()
            
            message = f"Queued {len(processed_jobs)} selected job(s) for keying: {', '.join(processed_jobs)}"
            print(f"-> {message}")
            
            return jsonify({"success": True, "message": message})
            
    except Exception as e:
        print(f"ERROR in /process-selected-pending: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

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
    s3_key = f"uploads/{filename}"
    
    # Save to S3 or local depending on configuration
    image_url = save_uploaded_file(image_file, s3_key)
    
    return redirect(url_for('animate_image_page', image_url=image_url))

# --- Form Handlers for Job Creation ---
@app.route("/style-tool", methods=["POST"])
def style_tool():
    image_file = request.files.get("image")
    if not image_file: return jsonify({"error": "Missing image."}), 400
    system_prompt = request.form.get("system_prompt", "Default prompt")
    user_prompt = "Analyze image style."
    filename = f"{uuid.uuid4()}-{os.path.basename(image_file.filename)}"
    s3_key = f"uploads/{filename}"
    
    # Save to S3 or local
    image_url = save_uploaded_file(image_file, s3_key)
    input_data = json.dumps({"image_path": image_url, "system_prompt": system_prompt})
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
                ('style_analysis', 'queued', datetime.now(), user_prompt, input_data)
            )
            conn.commit()
    except Exception as e:
        print(f"Error creating style analysis job: {e}")
        return jsonify({"success": False, "error": f"Failed to create job: {str(e)}"}), 500
    return jsonify({"success": True})

@app.route("/palette-tool", methods=["POST"])
def palette_tool():
    image_file = request.files.get("image")
    if not image_file: return jsonify({"error": "Missing image."}), 400
    system_prompt = """Analyze the provided image and identify the 5 most prominent colors of the SUBJECT/FOREGROUND. 

IMPORTANT CHROMA KEY RULE: If both green AND blue colors appear in the image, EXCLUDE the less prominent one from the palette entirely. Skip it and move to the next color to maintain 5 total colors. This is because images will later be animated on green or blue screen backgrounds - we don't want the palette to include the future chroma key background color if it appears minimally in the original image.

Example: If analyzing a tree with green leaves (prominent) that also has a small blue sky area (less prominent), only include the green and skip the blue entirely, as blue will be used as the chroma key background later.

For each color, provide its hexadecimal code and a simple, descriptive name (e.g., 'dark slate blue', 'light coral'). Return the response as a valid JSON object with a single key "palette" which is an array of objects. Each object in the array should have two keys: "hex" and "name". Example: {"palette": [{"hex": "#2F4F4F", "name": "dark slate grey"}, ...]}"""
    user_prompt = "Analyze image palette."
    filename = f"{uuid.uuid4()}-{os.path.basename(image_file.filename)}"
    s3_key = f"uploads/{filename}"
    
    # Save to S3 or local
    image_url = save_uploaded_file(image_file, s3_key)
    input_data = json.dumps({"image_path": image_url, "system_prompt": system_prompt})
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
                ('palette_analysis', 'queued', datetime.now(), user_prompt, input_data)
            )
            conn.commit()
    except Exception as e:
        print(f"Error creating palette analysis job: {e}")
        return jsonify({"success": False, "error": f"Failed to create job: {str(e)}"}), 500
    return jsonify({"success": True})

@app.route("/image-tool", methods=["POST"])
def image_tool():
    """Unified image generation with optional background style/color analysis"""
    selected_models = request.form.getlist("modelId")
    if not selected_models: return jsonify({"error": "Please select at least one model."}), 400
    
    parent_job_id = request.form.get("parent_job_id")
    object_prompt = request.form.get("object_prompt")
    style_prompt = request.form.get("style_prompt", "")
    preset_style = request.form.get("presetStyle")
    aspect_ratio = request.form.get("aspect_ratio", "1:1")
    
    # Check if user uploaded reference images for analysis
    style_ref_image = request.files.get("style_ref_image")
    color_ref_image = request.files.get("color_ref_image")
    
    style_analysis_job_id = None
    color_analysis_job_id = None
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Create internal style analysis job if style ref provided
        if style_ref_image:
            filename = f"{uuid.uuid4()}-style-ref-{os.path.basename(style_ref_image.filename)}"
            s3_key = f"uploads/{filename}"
            style_image_url = save_uploaded_file(style_ref_image, s3_key)
            
            style_system_prompt = """You are the best image describer in the world, known for creating beautiful icon-style images.
Start immediately with the description, as if giving a direct order.

Core Directives:
- Do not literally name or describe what the object is.
- Do not describe any visual data, shape, or outline of the object — only its style and overall feel.
- Do not describe or mention any text, fonts, colors, shadows, glow, or background.


Composition Rules:
- Describe only if the image is transparent or has visible grain or gradient effects.
- If the reference includes elements that break the silhouette (for example, Gothic spikes or rivets), describe them only in stylistic terms that support the aesthetic.
- If the image looks like a one-liner or scribble, say so.
- Do not describe collections as collections — only the style or artistic unity they convey.

Style & Technique Description:
- Focus only on the genre, style, artistic movement, and general visual language.
- Mention grain style and gradient form/style, but never the colors.
- If the image appears pixelated, vectorized, sculpted, hand-drawn, or digital, describe that generally.
- Do not mention any era or year but name the movement/genre (e.g., "Bauhaus modernism," "Gothic revival," "Pop art").
- If the reference image includes outlines, describe them; otherwise, omit.

Task:
Create a description focusing entirely on the art style, genre, and aesthetic character — never on the subject itself."""
            
            style_input_data = json.dumps({
                "image_path": style_image_url,
                "system_prompt": style_system_prompt,
                "internal": True  # Hidden from UI
            })
            
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
                ('style_analysis', 'queued', datetime.now(), "Internal style analysis", style_input_data)
            )
            style_analysis_job_id = cursor.lastrowid
            print(f"-> Created internal style analysis job {style_analysis_job_id}")
        
        # Create internal color analysis job if color ref provided
        if color_ref_image:
            filename = f"{uuid.uuid4()}-color-ref-{os.path.basename(color_ref_image.filename)}"
            s3_key = f"uploads/{filename}"
            color_image_url = save_uploaded_file(color_ref_image, s3_key)
            
            color_system_prompt = """Extract the 5 most prominent colors from the SUBJECT/FOREGROUND (ignore backgrounds).

CHROMA KEY RULE: If both green AND blue appear, exclude the less prominent one (it will be the animation background later).

For each color:
- Hex code (e.g., #2F4F4F)
- Simple name (e.g., 'dark slate grey')

REQUIRED FORMAT - Return valid JSON only:
{"palette": [{"hex": "#2F4F4F", "name": "dark slate grey"}, {"hex": "#F08080", "name": "light coral"}, ...]}

No explanation text, just the JSON object."""
            
            color_input_data = json.dumps({
                "image_path": color_image_url,
                "system_prompt": color_system_prompt,
                "internal": True  # Hidden from UI
            })
            
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
                ('palette_analysis', 'queued', datetime.now(), "Internal color analysis", color_input_data)
            )
            color_analysis_job_id = cursor.lastrowid
            print(f"-> Created internal color analysis job {color_analysis_job_id}")
        
        # Create image generation job(s)
        # If analysis jobs exist, create with waiting_for_analysis status
        for model_id in selected_models:
            prompt = f"{object_prompt}, in the style of {style_prompt}" if style_prompt else object_prompt
            if model_id == "replicate-gpt-image-1":
                prompt = f"{object_prompt} on a transparent background, in the style of {style_prompt}" if style_prompt else f"{object_prompt} on a transparent background"

            input_data = {
                "object_prompt": object_prompt, 
                "style_prompt": style_prompt, 
                "modelId": model_id, 
                "presetStyle": preset_style,
                "aspect_ratio": aspect_ratio,
                "style_analysis_job_id": style_analysis_job_id,
                "color_analysis_job_id": color_analysis_job_id
            }
            
            # If analysis jobs exist, wait for them to complete
            status = 'waiting_for_analysis' if (style_analysis_job_id or color_analysis_job_id) else 'queued'
            
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                ('image_generation', status, datetime.now(), prompt, json.dumps(input_data), parent_job_id)
            )
            print(f"-> Created image generation job {cursor.lastrowid} (status: {status})")
        
        conn.commit()
    
    return jsonify({"success": True, "message": f"{len(selected_models)} image generation job(s) created"})

@app.route("/generate-animation", methods=["POST"])
def generate_animation():
    """Generate animation from image - handles both file uploads and URLs"""
    parent_job_id = request.form.get("parent_job_id")
    prompt = request.form.get("prompt")
    
    # Handle start frame - either file upload or URL
    start_frame_file = request.files.get("start_frame")
    image_url = request.form.get("image_url")
    
    if start_frame_file:
        # Upload new file
        filename = f"{uuid.uuid4()}-{os.path.basename(start_frame_file.filename)}"
        s3_key = f"uploads/{filename}"
        image_url = save_uploaded_file(start_frame_file, s3_key)
    elif not image_url:
        return jsonify({"error": "Missing start frame image"}), 400
    
    # Check for boomerang automation (A-B-A loop)
    end_frame_file = request.files.get("end_frame")
    end_image_url = request.form.get("end_image_url")
    
    if end_frame_file:
        filename = f"{uuid.uuid4()}-end-{os.path.basename(end_frame_file.filename)}"
        s3_key = f"uploads/{filename}"
        end_image_url = save_uploaded_file(end_frame_file, s3_key)
    
    if request.form.get("boomerang_automation") == "true" and end_image_url:
        # Create A-B-A loop automation job
        background_option = request.form.get("background", "as-is")
        white_outline = request.form.get("white_outline") == "true"
        outline_thickness = int(request.form.get("outline_thickness", 3))
        
        # Preprocess BOTH start and end images for A-B-A loop
        processed_image_url = preprocess_animation_image(image_url, background_option, white_outline, outline_thickness)
        processed_end_image_url = preprocess_animation_image(end_image_url, background_option, white_outline, outline_thickness)
        
        all_input_data = {
            "image_url": processed_image_url,
            "end_image_url": processed_end_image_url,
            "prompt": prompt,
            "negative_prompt": request.form.get("negative_prompt", ""),
            "background": background_option,
            "white_outline": white_outline,
            "outline_thickness": outline_thickness,
            "video_model": request.form.getlist("video_model")[0] if request.form.getlist("video_model") else "kling-v2.1",
            "seamless_loop": request.form.get("seamless_loop") == "true",
            "kling_duration": int(request.form.get("kling_duration", 5)),
            "kling_mode": request.form.get("kling_mode", "pro")
        }
        
        meta_prompt = f"A-B-A Loop: {prompt}"
        with get_db_connection() as conn:
            conn.cursor().execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                ('boomerang_automation', 'queued', datetime.now(), meta_prompt, json.dumps(all_input_data), parent_job_id)
            )
            conn.commit()
        return jsonify({"success": True, "message": "A-B-A loop automation job queued."})

    # Regular animation generation
    selected_models = request.form.getlist("video_model")
    if not selected_models: 
        return jsonify({"error": "Please select at least one video model."}), 400
    
    if not prompt:
        return jsonify({"error": "Missing animation prompt"}), 400
    
    background_option = request.form.get("background", "as-is")
    white_outline = request.form.get("white_outline") == "true"
    outline_thickness = int(request.form.get("outline_thickness", 3))
    processed_image_url = preprocess_animation_image(image_url, background_option, white_outline, outline_thickness)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        for model in selected_models:
            input_data = {
                "image_url": processed_image_url, 
                "end_image_url": end_image_url if end_image_url else None,
                "prompt": prompt, 
                "negative_prompt": request.form.get("negative_prompt", ""),
                "seamless_loop": request.form.get("seamless_loop") == "true", 
                "white_outline": request.form.get("white_outline") == "true",
                "video_model": model,
                "kling_duration": int(request.form.get("kling_duration", 5)), 
                "kling_mode": request.form.get("kling_mode", "pro"),
                "seedance_duration": int(request.form.get("seedance_duration", 5)), 
                "seedance_resolution": request.form.get("seedance_resolution", "1080p"),
                "seedance_aspect_ratio": request.form.get("seedance_aspect_ratio", "1:1"),
                "background": background_option
            }
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                ('animation', 'queued', datetime.now(), prompt, json.dumps(input_data), parent_job_id)
            )
        conn.commit()
    return jsonify({"success": True, "message": f"{len(selected_models)} animation job(s) queued."})

@app.route("/get-animation-idea", methods=["POST"])
def get_animation_idea():
    """Get animation idea from image - handles both file uploads and URLs"""
    image_file = request.files.get("image")
    image_url = request.form.get("image_url")
    
    if image_file:
        # Upload new file
        filename = f"{uuid.uuid4()}-{os.path.basename(image_file.filename)}"
        s3_key = f"uploads/{filename}"
        image_url = save_uploaded_file(image_file, s3_key)
    elif not image_url:
        return jsonify({"success": False, "error": "Missing image file or URL."}), 400

    system_prompt = """You are an Image-to-Animation Director.
Your task is to look at the uploaded image, analyze it visually, and propose actionable animation ideas that bring its key elements to life.

Rules
Goal: Suggest animation ideas for the image's characters, objects, surfaces, textures, or patterns.

Workflow:
1. Identify Focus Elements: Note the most animation-worthy components (e.g., "character's tail," "fabric texture," "metal surface," "background foliage").
2. Motion Potential: Suggest how each can move, morph, react, loop, or interact (e.g., idle sway, flutter, texture ripple, camera orbit, particle motion).
3. Style Fit: Match the motion language to the visual style (e.g., snappy cartoon rig, smooth painterly drift, mechanical rotation, organic breathing motion).
4. Loop Guidance: If animation needs to loop, describe how to make the last frame flow seamlessly back to the first.

Constraints:
- Keep the background unchanged if it is a green/blue screen intended for later keying.
- Avoid semi-transparent or out-of-frame movements that break clean alpha edges.
- Keep the subject fully within the frame.

Output Format:
Element Focus: (the part to animate)
Suggested Animation: (clear description of motion)
Loop Tip: (only if relevant)
Style Note: (only if the visual style influences the animation approach)

Exclusions:
- Do not describe the subject's identity or give long artistic style descriptions unless it directly affects motion.
- Do not mention colors unless essential to the animation.
- Do not discuss camera gear, lens, or lighting.

Tone: Be concise, creative, and practical — as if briefing an animation team."""
    user_prompt = "Analyze this image and provide animation ideas following the format above."
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
    """Remove background - accepts either image_url or uploaded file"""
    parent_job_id = request.form.get("parent_job_id")
    
    # Check if file upload or URL
    image_file = request.files.get("image")
    image_url = request.form.get("image_url")
    
    if image_file:
        # Handle file upload
        filename = f"{uuid.uuid4()}-{os.path.basename(image_file.filename)}"
        s3_key = f"uploads/{filename}"
        image_url = save_uploaded_file(image_file, s3_key)
        prompt = f"Remove background from {image_file.filename}"
    elif image_url:
        # Handle URL
        prompt = f"Remove background from {os.path.basename(image_url)}"
        image_url = image_url.lstrip('/')
    else:
        return jsonify({"error": "Missing image file or URL for background removal."}), 400
    
    input_data = json.dumps({"image_path": image_url})
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                ('background_removal', 'queued', datetime.now(), prompt, input_data, parent_job_id)
            )
            conn.commit()
    except Exception as e:
        print(f"Error creating background removal job: {e}")
        return jsonify({"success": False, "error": f"Failed to create job: {str(e)}"}), 500
    return jsonify({"success": True, "message": "Background removal job queued."})

@app.route("/upload-video", methods=["POST"])
def upload_video():
    """Handle video uploads for keying and frame extraction"""
    if 'video' not in request.files:
        return jsonify({"error": "No video file provided."}), 400
    
    video_file = request.files['video']
    purpose = request.form.get('purpose', 'general')
    
    if video_file.filename == '':
        return jsonify({"error": "No selected file."}), 400
    
    # Save the uploaded video to S3 or local
    filename = f"upload_{uuid.uuid4()}_{os.path.basename(video_file.filename)}"
    s3_key = f"uploads/{filename}"
    video_url = save_uploaded_file(video_file, s3_key)
    
    if purpose == 'keying':
        # Create a job for video keying with uploaded video
        # Use 'video_upload' job type so it gets the same action buttons as animations
        prompt = f"Uploaded video: {video_file.filename}"
        input_data = json.dumps({
            "uploaded_video": video_url,
            "original_filename": video_file.filename,
            "background": "unknown"  # User will need to specify in keying settings
        })
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, result_data) VALUES (?, ?, ?, ?, ?, ?)",
                ('video_upload', 'pending_review', datetime.now(), prompt, input_data, video_url)
            )
            job_id = cursor.lastrowid
            conn.commit()
        
        print(f"📤 Created video upload job #{job_id} for file: {video_file.filename}")
        return jsonify({"success": True, "video_path": video_url, "job_id": job_id})
    
    elif purpose == 'extract':
        return jsonify({"success": True, "video_path": video_url})
    
    return jsonify({"success": True, "video_path": video_url})

# --- API Endpoints ---

@app.route("/api/jobs")
def api_jobs_log():
    try:
        with get_db_connection() as conn:
            # Count total jobs for debugging
            total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            print(f"📊 API /api/jobs called - Total jobs in database: {total_jobs}")
            
            query = """
                SELECT j.*, p.id as parent_id, p.result_data as parent_result_data
                FROM jobs j LEFT JOIN jobs p ON j.parent_job_id = p.id
                ORDER BY j.created_at DESC, j.id DESC
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
    frame_time = float(request.form.get('frame_time', 0))
    parent_job_id = request.form.get('parent_job_id')
    
    # Handle both uploaded file and existing video path
    temp_video_path = None  # Initialize to avoid NameError
    
    if 'video' in request.files:
        # Handle uploaded file
        video_file = request.files['video']
        if video_file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Save uploaded video temporarily
        temp_video_path = os.path.join(BASE_DIR, 'temp', f"extract_{uuid.uuid4()}_{video_file.filename}")
        os.makedirs(os.path.dirname(temp_video_path), exist_ok=True)
        video_file.save(temp_video_path)
        
        video_path = temp_video_path
        prompt = f"Frame from uploaded video at {frame_time:.2f}s"
        input_data = json.dumps({"uploaded_video": video_file.filename, "time": frame_time})
        
    elif 'video_path' in request.form:
        # Handle existing video path
        video_path_url = request.form.get('video_path')
        video_path = os.path.join(BASE_DIR, video_path_url.lstrip('/'))
        
        if not os.path.exists(video_path):
            return jsonify({"error": "Video file not found"}), 404
        
        prompt = f"Frame from {os.path.basename(video_path_url)} at {frame_time:.2f}s"
        input_data = json.dumps({"source_video": video_path_url, "time": frame_time})
        
    else:
        return jsonify({"error": "Missing video file or path"}), 400
    
    try:
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, frame_time * 1000)
        success, frame = cap.read()
        cap.release()

        if not success:
            return jsonify({"error": "Could not read frame"}), 500

        frame_filename = f"frame_{uuid.uuid4()}.png"
        frame_filepath = os.path.join(LIBRARY_FOLDER, frame_filename)
        cv2.imwrite(frame_filepath, frame)
        
        # Upload to S3 if enabled
        s3_key = f"library/{frame_filename}"
        result_path = upload_file(frame_filepath, s3_key)
        
        with get_db_connection() as conn:
            # Use a future timestamp to ensure it appears at the top of the queue
            # This is safer than manipulating IDs
            future_time = datetime.now() + timedelta(minutes=1)
            
            conn.cursor().execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, result_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('frame_extraction', 'completed', future_time, prompt, input_data, result_path, parent_job_id)
            )
            conn.commit()
        
        # Clean up temp file if it was uploaded
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except:
                pass
                
        return jsonify({"success": True, "path": result_path})
        
    except Exception as e:
        return jsonify({"error": f"Frame extraction failed: {str(e)}"}), 500

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

@app.route("/api/retry-job", methods=["POST"])
def retry_job():
    """Reset a failed job to 'queued' status so it can be retried"""
    data = request.get_json()
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({"success": False, "error": "No job ID provided."}), 400
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Clear error message and reset to queued
            cursor.execute(
                "UPDATE jobs SET status = 'queued', error_message = NULL WHERE id = ?",
                (job_id,)
            )
            conn.commit()
            return jsonify({"success": True, "message": f"Job {job_id} reset to queued."})
    except Exception as e:
        return jsonify({"success": False, "error": f"Server error: {e}"}), 500

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

@app.route("/api/edit-job/<int:job_id>", methods=["GET"])
def edit_job(job_id):
    """Get job data for editing - returns input_data and prompt to populate the tool"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            job = cursor.execute(
                "SELECT id, job_type, prompt, input_data, result_data FROM jobs WHERE id = ?", 
                (job_id,)
            ).fetchone()
        
            if not job:
                return jsonify({"success": False, "error": "Job not found"}), 404
            
            job_dict = dict(job)
            # Parse input_data JSON string back to dict
            if job_dict.get('input_data'):
                try:
                    job_dict['input_data'] = json.loads(job_dict['input_data'])
                except:
                    pass
            
            # For image_generation jobs, fetch style and color reference images from analysis jobs
            if job_dict['job_type'] == 'image_generation' and job_dict.get('input_data'):
                input_data = job_dict['input_data']
                
                # Get style reference image if style_analysis_job_id exists
                if input_data.get('style_analysis_job_id'):
                    style_job = cursor.execute(
                        "SELECT input_data FROM jobs WHERE id = ?", 
                        (input_data['style_analysis_job_id'],)
                    ).fetchone()
                    if style_job:
                        try:
                            style_input = json.loads(style_job['input_data'])
                            job_dict['input_data']['style_ref_image_path'] = style_input.get('image_path')
                        except:
                            pass
                
                # Get color reference image if color_analysis_job_id exists
                if input_data.get('color_analysis_job_id'):
                    color_job = cursor.execute(
                        "SELECT input_data FROM jobs WHERE id = ?", 
                        (input_data['color_analysis_job_id'],)
                    ).fetchone()
                    if color_job:
                        try:
                            color_input = json.loads(color_job['input_data'])
                            job_dict['input_data']['color_ref_image_path'] = color_input.get('image_path')
                        except:
                            pass
        
        return jsonify({"success": True, "job": job_dict})
        
    except Exception as e:
        print(f"ERROR in /api/edit-job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/regenerate-job/<int:job_id>", methods=["POST"])
def regenerate_job(job_id):
    """Clone a job with same inputs but new random seed"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Get original job
            job = cursor.execute(
                "SELECT job_type, prompt, input_data, parent_job_id FROM jobs WHERE id = ?", 
                (job_id,)
            ).fetchone()
            
            if not job:
                return jsonify({"success": False, "error": "Job not found"}), 404
            
            job_dict = dict(job)
            
            # Create new job with same parameters
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data, parent_job_id) VALUES (?, ?, ?, ?, ?, ?)",
                (job_dict['job_type'], 'queued', datetime.now(), job_dict['prompt'], 
                 job_dict['input_data'], job_dict['parent_job_id'])
            )
            new_job_id = cursor.lastrowid
            conn.commit()
            
            print(f"-> Regenerated job {job_id} as new job {new_job_id} ({job_dict['job_type']})")
            return jsonify({
                "success": True, 
                "message": f"Job regenerated successfully", 
                "new_job_id": new_job_id
            })
            
    except Exception as e:
        print(f"ERROR in /api/regenerate-job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/stitch-videos", methods=["POST"])
def stitch_videos():
    """Create a manual video stitching job"""
    try:
        video_a_url = request.form.get('video_a_url')
        video_b_url = request.form.get('video_b_url')
        prompt = request.form.get('prompt', 'Manual Video Stitch')
        
        if not video_a_url or not video_b_url:
            return jsonify({"success": False, "error": "Both video URLs are required"}), 400
        
        # Convert URLs to local paths
        video_a_path = video_a_url.replace(request.host_url.rstrip('/'), '')
        video_b_path = video_b_url.replace(request.host_url.rstrip('/'), '')
        
        input_data = {
            "video_a_path": video_a_path,
            "video_b_path": video_b_path
        }
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
                ('video_stitching', 'queued', datetime.now(), prompt, json.dumps(input_data))
            )
            job_id = cursor.lastrowid
            conn.commit()
            
        print(f"-> Manual stitch job created: {job_id}")
        return jsonify({
            "success": True,
            "message": "Video stitching job queued",
            "job_id": job_id
        })
        
    except Exception as e:
        print(f"ERROR in /api/stitch-videos: {e}")
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

@app.route("/api/trim-video", methods=["POST"])
def trim_video():
    """Trim a video to specified in/out points"""
    try:
        job_id = int(request.form.get('job_id'))
        in_point = float(request.form.get('in_point'))
        out_point = float(request.form.get('out_point'))
        
        if out_point <= in_point:
            return jsonify({"success": False, "error": "Out point must be after in point"}), 400
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            job = cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            
            if not job:
                return jsonify({"success": False, "error": "Job not found"}), 404
            
            # Get the video URL to trim
            video_url = None
            if job['keyed_result_data']:
                try:
                    keyed_data = json.loads(job['keyed_result_data'])
                    video_url = keyed_data.get('webm') or job['keyed_result_data']
                except:
                    video_url = job['keyed_result_data']
            elif job['result_data']:
                video_url = job['result_data']
            else:
                return jsonify({"success": False, "error": "No video found for this job"}), 404
            
            # Handle S3 URLs or local paths
            if video_url.startswith('http'):
                # Download from S3 first
                import requests
                print(f"-> Downloading video from S3 for trimming: {video_url}")
                response = requests.get(video_url)
                response.raise_for_status()
                temp_input = f"temp_trim_input_{uuid.uuid4().hex[:8]}.webm"
                input_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, temp_input)
                with open(input_path, 'wb') as f:
                    f.write(response.content)
            else:
                input_path = os.path.join(BASE_DIR, video_url.lstrip('/'))
                if not os.path.exists(input_path):
                    return jsonify({"success": False, "error": "Video file not found"}), 404
            
            # Create output filename
            output_filename = f"trimmed_{job_id}_{uuid.uuid4().hex[:8]}.webm"
            output_path = os.path.join(TRANSPARENT_VIDEOS_FOLDER, output_filename)
            
            # Trim video using ffmpeg
            duration = out_point - in_point
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-i', input_path,
                '-ss', str(in_point),
                '-t', str(duration),
                '-c', 'copy',  # Copy codec for fast trimming
                output_path
            ]
            
            print(f"-> Trimming video: {in_point}s to {out_point}s (duration: {duration}s)")
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"   ❌ FFmpeg trim error: {result.stderr}")
                return jsonify({"success": False, "error": "FFmpeg trimming failed"}), 500
            
            # Upload trimmed video to S3 if enabled
            s3_key = f"library/transparent_videos/{output_filename}"
            trimmed_url = upload_file(output_path, s3_key)
            
            # Update the job's result_data with trimmed video
            cursor.execute(
                "UPDATE jobs SET result_data = ?, prompt = ? WHERE id = ?",
                (trimmed_url, f"{job['prompt']} [Trimmed {in_point:.1f}s-{out_point:.1f}s]", job_id)
            )
            conn.commit()
            
            # Clean up temp input file if we downloaded from S3
            if video_url.startswith('http') and os.path.exists(input_path):
                try:
                    os.remove(input_path)
                except:
                    pass
            
            print(f"   ✅ Video trimmed successfully: {trimmed_url}")
            return jsonify({"success": True, "video_url": trimmed_url})
            
    except Exception as e:
        print(f"ERROR in /api/trim-video: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/preview-frame', methods=['POST'])
def preview_frame():
    video_path_url = request.form.get('video_path')
    frame_time = float(request.form.get('frame_time', 0))
    if not video_path_url: return "Missing video path", 400
    
    # Remove cache-busting query parameters (e.g., ?t=1234567890)
    video_path_url = video_path_url.split('?')[0]
    
    video_path = os.path.join(BASE_DIR, video_path_url.lstrip('/'))
    print(f"🔍 Preview frame request: video_path_url={video_path_url}, frame_time={frame_time}")
    print(f"   Full path: {video_path}")
    print(f"   File exists: {os.path.exists(video_path)}")
    
    if not os.path.exists(video_path): return "Video file not found", 404
        
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, frame_time * 1000)
    success, frame = cap.read()
    cap.release()
    if not success: return "Could not read frame from video", 500

    settings = {
        "hue_center": int(request.form.get('hue_center', 60)), "hue_tolerance": int(request.form.get('hue_tolerance', 25)),
        "saturation_min": int(request.form.get('saturation_min', 50)), "value_min": int(request.form.get('value_min', 50)),
        "erode": int(request.form.get('erode', 0)), "dilate": int(request.form.get('dilate', 0)),
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

# Initialize database when app is imported (for Gunicorn/production)
# --- STICKER EFFECT TEST PAGE ---
@app.route("/sticker-test")
def sticker_test_page():
    """Test page for single-frame sticker effect"""
    return render_template("sticker_test.html")

@app.route("/test-sticker-effect", methods=["POST"])
def test_sticker_effect():
    """Apply sticker effect to a single image for testing"""
    try:
        from PIL import Image, ImageFilter, ImageChops, ImageEnhance
        import cv2
        import numpy as np
        
        # Get uploaded image
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "No image uploaded"}), 400
        
        image_file = request.files['image']
        hue_center = int(request.form.get('hue_center', 60))
        hue_tolerance = int(request.form.get('hue_tolerance', 25))
        displacement_intensity = int(request.form.get('displacement_intensity', 50))
        darker_opacity = float(request.form.get('darker_opacity', 1.0))
        screen_opacity = float(request.form.get('screen_opacity', 0.7))
        
        # Drop shadow parameters
        enable_shadow = request.form.get('enable_shadow') == 'true'
        shadow_blur = int(request.form.get('shadow_blur', 0))
        shadow_x = int(request.form.get('shadow_x', 1))
        shadow_y = int(request.form.get('shadow_y', 1))
        shadow_opacity = float(request.form.get('shadow_opacity', 1.0))
        
        # Bevel & emboss parameters
        enable_bevel = request.form.get('enable_bevel') == 'true'
        bevel_depth = int(request.form.get('bevel_depth', 3))
        bevel_highlight = float(request.form.get('bevel_highlight', 0.5))
        bevel_shadow = float(request.form.get('bevel_shadow', 0.5))
        
        # Alpha bevel parameters
        enable_alpha_bevel = request.form.get('enable_alpha_bevel') == 'true'
        alpha_bevel_size = int(request.form.get('alpha_bevel_size', 15))
        alpha_bevel_blur = int(request.form.get('alpha_bevel_blur', 2))
        alpha_bevel_angle = float(request.form.get('alpha_bevel_angle', 70))
        alpha_bevel_highlight = float(request.form.get('alpha_bevel_highlight', 0.6))
        alpha_bevel_shadow = float(request.form.get('alpha_bevel_shadow', 0.6))
        
        # Save uploaded image
        temp_input_path = os.path.join(LIBRARY_FOLDER, f"test_input_{uuid.uuid4().hex[:8]}.png")
        image_file.save(temp_input_path)
        
        # Step 1: Apply chroma keying
        img = cv2.imread(temp_input_path)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Create mask
        lower_bound = np.array([max(0, hue_center - hue_tolerance), 50, 50])
        upper_bound = np.array([min(180, hue_center + hue_tolerance), 255, 255])
        mask = cv2.inRange(hsv, lower_bound, upper_bound)
        mask_inv = cv2.bitwise_not(mask)
        
        # Apply mask to create transparent image
        b, g, r = cv2.split(img)
        rgba = cv2.merge((b, g, r, mask_inv))
        
        # Save keyed image
        keyed_path = os.path.join(LIBRARY_FOLDER, f"test_keyed_{uuid.uuid4().hex[:8]}.png")
        cv2.imwrite(keyed_path, rgba)
        
        # Step 2: Apply sticker effect
        keyed_pil = Image.open(keyed_path).convert('RGBA')
        
        # Load textures
        disp_folder = os.path.join(STATIC_FOLDER, 'textures', 'displacement')
        screen_folder = os.path.join(STATIC_FOLDER, 'textures', 'screen')
        
        disp_files = sorted([f for f in os.listdir(disp_folder) if f.endswith('.png')])
        screen_files = sorted([f for f in os.listdir(screen_folder) if f.endswith('.png')])
        
        if not disp_files or not screen_files:
            return jsonify({"success": False, "error": "Texture files not found"}), 500
        
        # Use first frame of each texture
        disp_texture = Image.open(os.path.join(disp_folder, disp_files[0])).convert('RGBA')
        screen_texture = Image.open(os.path.join(screen_folder, screen_files[0])).convert('RGBA')
        
        # Apply displacement
        if displacement_intensity > 0:
            img_array = np.array(keyed_pil)
            h, w = img_array.shape[:2]
            disp_map = disp_texture.resize((w, h), Image.Resampling.BILINEAR).convert('L')
            disp_array = np.array(disp_map).astype(float) / 255.0
            
            disp_x = (disp_array - 0.5) * displacement_intensity
            disp_y = (disp_array - 0.5) * displacement_intensity
            
            map_x, map_y = np.meshgrid(np.arange(w), np.arange(h))
            map_x = (map_x + disp_x).astype(np.float32)
            map_y = (map_y + disp_y).astype(np.float32)
            
            warped = cv2.remap(img_array, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            keyed_pil = Image.fromarray(warped, 'RGBA')
        
        # Resize textures to match image
        disp_texture = disp_texture.resize(keyed_pil.size, Image.Resampling.BILINEAR)
        screen_texture = screen_texture.resize(keyed_pil.size, Image.Resampling.BILINEAR)
        
        # Store original alpha for later use with bevel
        original_alpha = keyed_pil.split()[3]
        
        # Apply Multiply blend mode (displacement texture) with opacity
        if darker_opacity > 0:
            base_rgb = np.array(keyed_pil.convert('RGB')).astype(float) / 255.0
            overlay_rgb = np.array(disp_texture.convert('RGB')).astype(float) / 255.0
            
            # Multiply blend mode: result = base * overlay
            result_rgb = base_rgb * overlay_rgb
            result_rgb = (result_rgb * 255).astype(np.uint8)
            
            # Blend with original based on opacity
            if darker_opacity < 1.0:
                base_rgb_uint = (base_rgb * 255).astype(np.uint8)
                result_rgb = (result_rgb * darker_opacity + base_rgb_uint * (1 - darker_opacity)).astype(np.uint8)
            
            result = Image.fromarray(result_rgb, 'RGB').convert('RGBA')
            result.putalpha(keyed_pil.split()[3])  # Keep original alpha
            keyed_pil = result
        
        # Apply Add (Linear Dodge) blend mode (screen texture)
        base_rgb = np.array(keyed_pil.convert('RGB')).astype(float) / 255.0
        overlay_rgb = np.array(screen_texture.convert('RGB')).astype(float) / 255.0
        
        # Add blend mode: result = base + overlay (clamped to 1.0)
        result_rgb = np.clip(base_rgb + overlay_rgb, 0, 1.0)
        result_rgb = (result_rgb * 255).astype(np.uint8)
        
        # Blend with original based on opacity
        if screen_opacity < 1.0:
            base_rgb_uint = (base_rgb * 255).astype(np.uint8)
            result_rgb = (result_rgb * screen_opacity + base_rgb_uint * (1 - screen_opacity)).astype(np.uint8)
        
        result = Image.fromarray(result_rgb, 'RGB').convert('RGBA')
        result.putalpha(keyed_pil.split()[3])  # Keep original alpha
        
        # Apply bevel & emboss AFTER blend modes (using After Effects style)
        if enable_bevel:
            # Create a grayscale embossed/relief map
            grey = result.convert('L')  # Convert to greyscale
            grey_array = np.array(grey).astype(float)
            
            # Create emboss kernel (like After Effects)
            emboss_strength = bevel_depth * 0.5
            
            # Shift image to create relief effect
            shifted_right = np.roll(grey_array, bevel_depth, axis=1)
            shifted_down = np.roll(grey_array, bevel_depth, axis=0)
            shifted_left = np.roll(grey_array, -bevel_depth, axis=1)
            shifted_up = np.roll(grey_array, -bevel_depth, axis=0)
            
            # Calculate relief (differences create the 3D effect)
            relief_x = (shifted_right - shifted_left) * bevel_highlight
            relief_y = (shifted_down - shifted_up) * bevel_shadow
            relief = relief_x + relief_y
            
            # Normalize to 0-255 range and center at 128 (middle grey)
            relief = relief + 128
            relief = np.clip(relief, 0, 255).astype(np.uint8)
            
            # Create RGB emboss map (grey image)
            emboss_map = Image.fromarray(relief, 'L').convert('RGB')
            
            # Apply Overlay blend mode (like After Effects)
            base_rgb = np.array(result.convert('RGB')).astype(float) / 255.0
            overlay_rgb = np.array(emboss_map).astype(float) / 255.0
            
            # Overlay blend mode: 
            # if base < 0.5: result = 2 * base * overlay
            # else: result = 1 - 2 * (1 - base) * (1 - overlay)
            mask = base_rgb < 0.5
            result_rgb = np.where(
                mask,
                2 * base_rgb * overlay_rgb,
                1 - 2 * (1 - base_rgb) * (1 - overlay_rgb)
            )
            result_rgb = (result_rgb * 255).astype(np.uint8)
            
            result = Image.fromarray(result_rgb, 'RGB').convert('RGBA')
            result.putalpha(original_alpha)  # Keep original alpha
        
        # Apply alpha bevel (like After Effects - gradient-based with light angle)
        if enable_alpha_bevel:
            # Get the current alpha channel
            alpha = result.split()[3]
            alpha_array = np.array(alpha, dtype=np.float32)
            
            # Calculate gradients (edge normals) of the alpha channel
            # Use larger kernel for deeper bevels
            kernel_size = min(alpha_bevel_size, 31)
            if kernel_size % 2 == 0:
                kernel_size += 1  # Must be odd
            gradient_x = cv2.Sobel(alpha_array, cv2.CV_32F, 1, 0, ksize=min(kernel_size, 31))
            gradient_y = cv2.Sobel(alpha_array, cv2.CV_32F, 0, 1, ksize=min(kernel_size, 31))
            
            # Calculate the angle of each edge normal (in radians)
            edge_angles = np.arctan2(gradient_y, gradient_x)
            
            # Convert light angle from degrees to radians
            light_angle_rad = np.deg2rad(alpha_bevel_angle)
            
            # Calculate how aligned each edge is with the light direction
            # Dot product between edge normal and light direction
            # cos(angle_difference) tells us if edge faces light (positive) or away (negative)
            angle_diff = edge_angles - light_angle_rad
            alignment = np.cos(angle_diff)
            
            # Calculate edge magnitude (strength)
            edge_magnitude = np.sqrt(gradient_x**2 + gradient_y**2)
            edge_magnitude = edge_magnitude / (edge_magnitude.max() + 1e-8)  # Normalize
            
            # Separate highlights and shadows with different intensities
            # Positive alignment = highlight, negative = shadow
            highlight_mask = np.maximum(0, alignment) * edge_magnitude * alpha_bevel_highlight
            shadow_mask = np.maximum(0, -alignment) * edge_magnitude * alpha_bevel_shadow
            
            # Blur the effect to create smooth bevels (separate control from depth)
            if alpha_bevel_blur > 0:
                blur_kernel = alpha_bevel_blur * 2 + 1
                if blur_kernel % 2 == 0:
                    blur_kernel += 1
                highlight_mask = cv2.GaussianBlur(highlight_mask, (blur_kernel, blur_kernel), 0)
                shadow_mask = cv2.GaussianBlur(shadow_mask, (blur_kernel, blur_kernel), 0)
            
            # Apply the bevel effect to the image
            result_array = np.array(result)
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
            
            result = Image.fromarray(result_array, 'RGBA')
        
        # Apply drop shadow (create a composite with shadow layer)
        if enable_shadow:
            # Get the alpha channel
            alpha = result.split()[3]
            
            # Create shadow layer (black image with alpha)
            shadow_layer = Image.new('RGBA', result.size, (0, 0, 0, 0))
            shadow_color = (0, 0, 0, int(255 * shadow_opacity))
            
            # Fill shadow with black where there's alpha
            shadow_array = np.array(shadow_layer)
            alpha_array = np.array(alpha)
            shadow_array[:, :, 0] = 0  # R
            shadow_array[:, :, 1] = 0  # G
            shadow_array[:, :, 2] = 0  # B
            shadow_array[:, :, 3] = (alpha_array * shadow_opacity).astype(np.uint8)  # A
            shadow_layer = Image.fromarray(shadow_array, 'RGBA')
            
            # Blur the shadow
            if shadow_blur > 0:
                from PIL import ImageFilter
                shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
            
            # Create canvas with shadow offset
            max_offset = max(abs(shadow_x), abs(shadow_y)) + shadow_blur
            canvas_size = (result.width + max_offset * 2, result.height + max_offset * 2)
            canvas = Image.new('RGBA', canvas_size, (0, 0, 0, 0))
            
            # Paste shadow with offset
            shadow_pos = (max_offset + shadow_x, max_offset + shadow_y)
            canvas.paste(shadow_layer, shadow_pos, shadow_layer)
            
            # Paste original image on top
            image_pos = (max_offset, max_offset)
            canvas.paste(result, image_pos, result)
            
            result = canvas
        
        # Save final result
        sticker_path = os.path.join(LIBRARY_FOLDER, f"test_sticker_{uuid.uuid4().hex[:8]}.png")
        result.save(sticker_path, 'PNG')
        
        # Clean up temp file
        os.remove(temp_input_path)
        
        # Return URLs
        keyed_url = keyed_path.replace(STATIC_FOLDER, '/static')
        sticker_url = sticker_path.replace(STATIC_FOLDER, '/static')
        
        return jsonify({
            "success": True,
            "keyed_url": keyed_url,
            "sticker_url": sticker_url
        })
        
    except Exception as e:
        print(f"Sticker test error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

print("=" * 50)
print("🔧 INITIALIZING DATABASE...")
print(f"📁 Database path: {DATABASE_PATH}")
print(f"📁 Current directory: {os.getcwd()}")
print("=" * 50)
try:
    init_db()
    print("✅ Database initialization completed successfully!")
except Exception as e:
    print(f"❌ CRITICAL: Database initialization failed: {e}")
    import traceback
    traceback.print_exc()
    # Don't raise - let the app start anyway and show better errors

@app.route("/sticker-debug")
def sticker_debug_page():
    """Debug page for sticker effect step-by-step analysis"""
    return render_template("sticker_debug.html")

@app.route("/debug-sticker-effect", methods=["POST"])
def debug_sticker_effect():
    """Process a single frame through each sticker effect step and return intermediate results"""
    try:
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "No image uploaded"}), 400
        
        image_file = request.files['image']
        
        # Create debug output folder
        debug_folder = os.path.join(LIBRARY_FOLDER, "debug_steps")
        os.makedirs(debug_folder, exist_ok=True)
        
        # Import worker functions
        from worker import (
            load_texture_sequence, apply_displacement, blend_multiply, blend_add,
            apply_surface_bevel, apply_alpha_bevel, apply_drop_shadow,
            TEXTURE_DISPLACEMENT_FOLDER, TEXTURE_SCREEN_FOLDER
        )
        
        # Save and load the uploaded image directly
        temp_image_path = os.path.join(debug_folder, f"uploaded_{uuid.uuid4().hex[:8]}.png")
        image_file.save(temp_image_path)
        
        # Load the frame
        frame_pil = Image.open(temp_image_path).convert('RGBA')
        original_alpha = frame_pil.split()[3]
        
        # Debug: Check alpha channel
        alpha_array = np.array(original_alpha)
        alpha_stats = {
            'min': int(alpha_array.min()),
            'max': int(alpha_array.max()),
            'transparent_pixels': int(np.sum(alpha_array == 0)),
            'total_pixels': int(alpha_array.size)
        }
        print(f"Alpha channel stats: {alpha_stats}")
        
        # Load textures
        disp_textures = load_texture_sequence(TEXTURE_DISPLACEMENT_FOLDER)
        screen_textures = load_texture_sequence(TEXTURE_SCREEN_FOLDER)
        
        if not disp_textures or not screen_textures:
            return jsonify({"success": False, "error": "Textures not found"}), 500
        
        # Get textures for this frame (use first texture for single frame test)
        disp_texture = disp_textures[0].resize(frame_pil.size, Image.LANCZOS)
        screen_texture = screen_textures[0].resize(frame_pil.size, Image.LANCZOS)
        
        # Step-by-step processing with intermediate saves
        steps = {}
        session_id = uuid.uuid4().hex[:8]
        
        # Step 1: Original
        original_path = f"/static/library/debug_steps/{session_id}_1_original.png"
        frame_pil.save(os.path.join(BASE_DIR, original_path.lstrip('/')), 'PNG')
        steps['original'] = original_path
        
        # Step 2: After Displacement
        frame_pil = apply_displacement(frame_pil, disp_texture, intensity=50)
        displaced_path = f"/static/library/debug_steps/{session_id}_2_displacement.png"
        frame_pil.save(os.path.join(BASE_DIR, displaced_path.lstrip('/')), 'PNG')
        steps['after_displacement'] = displaced_path
        
        # Step 3: After Multiply Blend
        frame_pil = blend_multiply(frame_pil, disp_texture, opacity=1.0)
        multiply_path = f"/static/library/debug_steps/{session_id}_3_multiply.png"
        frame_pil.save(os.path.join(BASE_DIR, multiply_path.lstrip('/')), 'PNG')
        steps['after_multiply'] = multiply_path
        
        # Step 4: After Add Blend
        frame_pil = blend_add(frame_pil, screen_texture, opacity=0.7)
        add_path = f"/static/library/debug_steps/{session_id}_4_add.png"
        frame_pil.save(os.path.join(BASE_DIR, add_path.lstrip('/')), 'PNG')
        steps['after_add'] = add_path
        
        # Step 5: After Surface Bevel
        frame_pil = apply_surface_bevel(frame_pil, depth=3, highlight=0.5, shadow=0.5)
        bevel_path = f"/static/library/debug_steps/{session_id}_5_surface_bevel.png"
        frame_pil.save(os.path.join(BASE_DIR, bevel_path.lstrip('/')), 'PNG')
        steps['after_surface_bevel'] = bevel_path
        
        # Step 6: After Alpha Bevel
        frame_pil = apply_alpha_bevel(frame_pil, size=15, blur=2, angle=70, 
                                      highlight_intensity=0.6, shadow_intensity=0.6)
        alpha_bevel_path = f"/static/library/debug_steps/{session_id}_6_alpha_bevel.png"
        frame_pil.save(os.path.join(BASE_DIR, alpha_bevel_path.lstrip('/')), 'PNG')
        steps['after_alpha_bevel'] = alpha_bevel_path
        
        # Step 7: After Drop Shadow
        frame_pil = apply_drop_shadow(frame_pil, blur=0, offset_x=1, offset_y=1, opacity=1.0)
        shadow_path = f"/static/library/debug_steps/{session_id}_7_drop_shadow.png"
        frame_pil.save(os.path.join(BASE_DIR, shadow_path.lstrip('/')), 'PNG')
        steps['after_drop_shadow'] = shadow_path
        
        # Step 8: Final - Restore original alpha and zero out transparent RGB
        frame_pil.putalpha(original_alpha)
        frame_array = np.array(frame_pil)
        alpha_array = np.array(original_alpha)
        mask = (alpha_array == 0)
        frame_array[:, :, 0] = np.where(mask, 0, frame_array[:, :, 0])
        frame_array[:, :, 1] = np.where(mask, 0, frame_array[:, :, 1])
        frame_array[:, :, 2] = np.where(mask, 0, frame_array[:, :, 2])
        frame_pil = Image.fromarray(frame_array, 'RGBA')
        
        final_path = f"/static/library/debug_steps/{session_id}_8_final.png"
        frame_pil.save(os.path.join(BASE_DIR, final_path.lstrip('/')), 'PNG')
        steps['final'] = final_path
        
        # Cleanup temp image
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
        
        return jsonify({
            "success": True, 
            "steps": steps,
            "alpha_stats": alpha_stats,
            "message": f"Analyzed frame - {alpha_stats['transparent_pixels']}/{alpha_stats['total_pixels']} pixels are transparent ({100*alpha_stats['transparent_pixels']/alpha_stats['total_pixels']:.1f}%)"
        })
        
    except Exception as e:
        print(f"Debug sticker effect error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    # Initialize database on startup (for direct execution)
    init_db()
    # Start the Flask development server
    app.run(debug=True, host='0.0.0.0', port=5001)

