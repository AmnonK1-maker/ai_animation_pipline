import os
import io
import time
import requests
import replicate
from flask import Flask, render_template, request, redirect, url_for, jsonify
from PIL import Image
import uuid
import shutil
import json
import sqlite3
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
# IMPORTANT: This now securely reads the key from an environment variable.
REPLICATE_API_KEY = os.environ.get("REPLICATE_API_KEY", "YOUR_REPLICATE_API_KEY_HERE")
os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_KEY

# --------------------------------

# --- Folder Paths ---
STATIC_FOLDER = 'static'
UPLOADS_FOLDER = os.path.join(STATIC_FOLDER, 'uploads')
LIBRARY_FOLDER = os.path.join(STATIC_FOLDER, 'library')
ANIMATIONS_FOLDER_GENERATED = os.path.join(STATIC_FOLDER, 'animations', 'generated')
ANIMATIONS_FOLDER_APPROVED = os.path.join(STATIC_FOLDER, 'animations', 'approved')
os.makedirs(UPLOADS_FOLDER, exist_ok=True)
os.makedirs(LIBRARY_FOLDER, exist_ok=True)
os.makedirs(ANIMATIONS_FOLDER_GENERATED, exist_ok=True)
os.makedirs(ANIMATIONS_FOLDER_APPROVED, exist_ok=True)

# --- Database Path ---
DATABASE_PATH = 'jobs.db'

def init_db():
    """Initializes the database and creates the jobs table if it doesn't exist."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                prompt TEXT,
                input_data TEXT,
                result_data TEXT,
                error_message TEXT
            )
        ''')
        conn.commit()

# --- Homepage Route ---
@app.route("/")
def home():
    return render_template("index.html")

# --- Video Tool (from file upload) ---
@app.route("/video-tool")
def video_tool_page():
    return render_template("video_tool.html")

# --- Style Analyzer Tool ---
@app.route("/style-tool", methods=["GET", "POST"])
def style_tool():
    if request.method == "POST":
        image_file = request.files.get("image")
        user_prompt = "Describe the artistic style of this image."

        if not image_file:
            return "Missing image.", 400

        system_prompt = "You are an art history expert. In 2-3 sentences, describe the artistic style of this image. Focus on the technique, mood, and genre. Do not mention the content of the image. Name the art movement the image or the object in the image belongs to."

        filename = f"{uuid.uuid4()}-{image_file.filename}"
        image_path = os.path.join(UPLOADS_FOLDER, filename)
        image_file.save(image_path)

        input_data = json.dumps({
            "image_path": image_path,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        })

        with sqlite3.connect(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
                ('style_analysis', 'queued', datetime.now(), user_prompt, input_data)
            )
            conn.commit()
            
        return jsonify({"success": True, "message": "Job queued."})

    return render_template("style_tool.html")

# --- Image Generation Tool ---
@app.route("/image-tool", methods=["GET", "POST"])
def image_tool():
    style_prompt = request.args.get("style_prompt", "")
    
    if request.method == "POST":
        style_prompt = request.form["style_prompt"]
        object_prompt = request.form["object_prompt"]
        # --- FIX: Get the number of images from the form ---
        num_images = int(request.form.get("num_images", 1))
        
        # We no longer add "transparent background" here
        full_prompt = f"{object_prompt}, in the style of {style_prompt}, centered, professional product shot"
        
        # --- FIX: Save num_images so the worker knows how many to create ---
        input_data = json.dumps({
            "num_images": num_images
        })

        with sqlite3.connect(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
                ('image_generation', 'queued', datetime.now(), full_prompt, input_data)
            )
            conn.commit()
            
        return jsonify({"success": True, "message": "Job queued."})

    return render_template("image_tool.html", style_prompt=style_prompt)

# --- Library Page ---
@app.route("/library")
def library():
    images = [os.path.join('static/library', f) for f in os.listdir(LIBRARY_FOLDER) if f.endswith(('.png', '.jpg', '.jpeg'))]
    images.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return render_template("library.html", images=images)

# --- Animation Workflow ---
@app.route("/animate-image")
def animate_image_page():
    image_url = request.args.get("image_url")
    if not image_url:
        return redirect(url_for('library'))
    return render_template("animation_step.html", image_url=image_url)

@app.route("/generate-animation", methods=["POST"])
def generate_animation():
    image_url = request.form["image_url"]
    prompt = request.form["prompt"]
    aspect_ratio = request.form["aspect_ratio"]
    duration = int(request.form["duration"])
    background_color_name = request.form["background_color"]
    movement = request.form["movement"]
    
    input_data = json.dumps({
        "image_url": image_url,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "background_color": background_color_name,
        "movement": movement
    })

    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO jobs (job_type, status, created_at, prompt, input_data) VALUES (?, ?, ?, ?, ?)",
            ('animation', 'queued', datetime.now(), prompt, input_data)
        )
        conn.commit()
    
    return jsonify({"success": True, "message": "Job queued."})

# --- Job Queue Page ---
@app.route("/queue")
def queue_page():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
    jobs = cursor.fetchall()
    conn.close()
    return render_template("queue.html", jobs=jobs)

# --- API Endpoint to get Job Data ---
@app.route("/api/jobs")
def api_jobs():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
    jobs = cursor.fetchall()
    conn.close()
    
    jobs_list = [dict(job) for job in jobs]
    return jsonify(jobs_list)

# Initialize the database when the app starts
init_db()

if __name__ == "__main__":
    app.run(debug=True, port=8080)


