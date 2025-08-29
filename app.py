import os
import io
import time
import requests
import replicate
from flask import Flask, render_template, request, redirect, url_for
from PIL import Image
import uuid
import shutil
import json
import cv2
import numpy as np

app = Flask(__name__)

# --- HARDCODE YOUR API KEY HERE ---
# --- ADD YOUR KEYS ENVIRONMENTALLY OR PASTE HERE ---
REPLICATE_API_KEY = os.environ.get("REPLICATE_API_KEY", "YOUR_REPLICATE_API_KEY_HERE")
LEONARDO_API_KEY = os.environ.get("LEONARDO_API_KEY", "YOUR_LEONARDO_API_KEY_HERE")
os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_KEY
# --------------------------------

# --- Folder Paths ---
STATIC_FOLDER = 'static'
LIBRARY_FOLDER = os.path.join(STATIC_FOLDER, 'library')
ANIMATIONS_FOLDER_GENERATED = os.path.join(STATIC_FOLDER, 'animations', 'generated')
ANIMATIONS_FOLDER_APPROVED = os.path.join(STATIC_FOLDER, 'animations', 'approved')
os.makedirs(LIBRARY_FOLDER, exist_ok=True)
os.makedirs(ANIMATIONS_FOLDER_GENERATED, exist_ok=True)
os.makedirs(ANIMATIONS_FOLDER_APPROVED, exist_ok=True)

# --- Homepage Route ---
@app.route("/")
def home():
    return render_template("index.html")

# --- Video Tool (from file upload) ---
@app.route("/video-tool")
def video_tool_page():
    return render_template("video_tool.html")

@app.route("/generate-video", methods=["POST"])
def generate_video():
    start_image_file = request.files["image"]
    prompt = request.form["prompt"]
    aspect_ratio = request.form["aspect_ratio"]
    duration = int(request.form["duration"])
    
    image_mem_file = io.BytesIO()
    start_image_file.save(image_mem_file)
    image_mem_file.seek(0)
    
    api_inputs = { 
        "prompt": prompt, 
        "aspect_ratio": aspect_ratio, 
        "duration": duration,
        "start_image": image_mem_file,
    }
    
    image_mem_file.seek(0)
    api_inputs["end_image"] = image_mem_file

    video_output_url = replicate.run("kwaivgi/kling-v1.6-pro", input=api_inputs)
    video_response = requests.get(video_output_url)
    video_filename = f"{uuid.uuid4()}.mp4"
    video_filepath = os.path.join(ANIMATIONS_FOLDER_GENERATED, video_filename)
    with open(video_filepath, "wb") as f:
        f.write(video_response.content)
    
    hidden_data = {"original_image_url": "", "movement": "none"}
    
    return render_template("result.html", video_path=video_filepath, hidden_data=hidden_data, is_from_upload=True)

# --- Style Analyzer Tool ---
@app.route("/style-tool", methods=["GET", "POST"])
def style_tool():
    analysis_text = None
    if request.method == "POST":
        image_file = request.files["image"]
        prompt = request.form["prompt"]
        in_memory_file = io.BytesIO()
        image_file.save(in_memory_file)
        in_memory_file.seek(0)
        output = replicate.run("yorickvp/llava-13b:2facb4a474a0462c15041b78b1ad70952ea46b5ec6ad29583c0b29dbd4249591", input={"image": in_memory_file, "prompt": prompt})
        analysis_text = "".join(output)
    return render_template("style_tool.html", analysis_text=analysis_text)

# --- Image Generation Tool ---
@app.route("/image-tool", methods=["GET", "POST"])
def image_tool():
    image_urls = None
    style_prompt = request.args.get("style_prompt", "")
    if request.method == "POST":
        style_prompt = request.form["style_prompt"]
        object_prompt = request.form["object_prompt"]
        num_images = int(request.form["num_images"])
        full_prompt = f"{object_prompt}, in the style of {style_prompt}, centered, professional product shot"
        url = "https://cloud.leonardo.ai/api/rest/v1/generations"
        payload = { "prompt": full_prompt, "modelId": "b24e16ff-06e3-43eb-8d33-4416c2d75876", "width": 1024, "height": 1024, "sd_version": "v2", "num_images": num_images, "transparency": "foreground_only" }
        headers = { "accept": "application/json", "content-type": "application/json", "authorization": f"Bearer {LEONARDO_API_KEY}" }
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        generation_id = response_data['sdGenerationJob']['generationId']
        get_url = f"https://cloud.leonardo.ai/api/rest/v1/generations/{generation_id}"
        while True:
            time.sleep(5)
            response = requests.get(get_url, headers=headers)
            response_data = response.json()
            status = response_data['generations_by_pk']['status']
            if status == "COMPLETE":
                temp_urls = [img['url'] for img in response_data['generations_by_pk']['generated_images']]
                saved_image_paths = []
                for url in temp_urls:
                    image_response = requests.get(url)
                    filename = f"{uuid.uuid4()}.png"
                    filepath = os.path.join(LIBRARY_FOLDER, filename)
                    with open(filepath, "wb") as f:
                        f.write(image_response.content)
                    saved_image_paths.append(filepath)
                image_urls = saved_image_paths
                break
            elif status == "FAILED":
                break
    return render_template("image_tool.html", image_urls=image_urls, style_prompt=style_prompt)

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

# --- UPDATED: Generate Animation Route ---
@app.route("/generate-animation", methods=["POST"])
def generate_animation():
    image_url = request.form["image_url"]
    prompt = request.form["prompt"]
    aspect_ratio = request.form["aspect_ratio"]
    duration = int(request.form["duration"])
    background_color_name = request.form["background_color"]
    movement = request.form["movement"]
    
    hidden_data = {"original_image_url": image_url, "movement": movement, "background_color": background_color_name}

    if image_url.startswith(('http://', 'https')):
        response = requests.get(image_url)
        foreground = Image.open(io.BytesIO(response.content)).convert("RGBA")
    else:
        with open(image_url, "rb") as f:
            foreground = Image.open(f).convert("RGBA")

    colors = {"green": (0, 255, 0), "blue": (0, 0, 255)}
    background = Image.new("RGBA", foreground.size, colors.get(background_color_name))
    background.paste(foreground, (0, 0), foreground)
    
    final_image_mem_file = io.BytesIO()
    background.convert("RGB").save(final_image_mem_file, format="PNG")
    final_image_mem_file.seek(0)
    
    video_output_url = replicate.run(
        "kwaivgi/kling-v1.6-pro",
        input={ "prompt": prompt, "start_image": final_image_mem_file, "aspect_ratio": aspect_ratio, "duration": duration }
    )
    
    video_response = requests.get(video_output_url)
    video_filename = f"{uuid.uuid4()}.mp4"
    video_filepath = os.path.join(ANIMATIONS_FOLDER_GENERATED, video_filename)
    with open(video_filepath, "wb") as f:
        f.write(video_response.content)
    
    # FIX: Pass the dictionary directly, not a JSON string
    return render_template("result.html", video_path=video_filepath, hidden_data=hidden_data)

# --- UPDATED: Approval Route ---
@app.route("/approve-animation")
def approve_animation():
    video_path = request.args.get("video_path")
    # FIX: Get the JSON string from the URL and parse it here
    hidden_data_str = request.args.get("hidden_data", "{}")
    hidden_data = json.loads(hidden_data_str)
    
    if video_path and os.path.exists(video_path):
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()
        if ret:
            b, g, r = frame[0, 0]
            key_color = [r / 255.0, g / 255.0, b / 255.0]
        else:
            key_color = [0, 1, 0]

        instruction_data = {
    "keyColor": key_color,
    "movement": hidden_data.get("movement", "none"),
    "background_color": hidden_data.get("background_color", "green") # Defaults to green
}
        json_path = video_path.replace(".mp4", ".json")
        with open(json_path, "w") as f:
            json.dump(instruction_data, f, indent=4)

        filename = os.path.basename(video_path)
        new_video_path = os.path.join(ANIMATIONS_FOLDER_APPROVED, filename)
        shutil.move(video_path, new_video_path)
        
        json_filename = os.path.basename(json_path)
        new_json_path = os.path.join(ANIMATIONS_FOLDER_APPROVED, json_filename)
        shutil.move(json_path, new_json_path)
        
        return render_template("approved.html")
    else:
        return "Error: File not found.", 404

# --- 3D Model Workflow (Placeholder) ---
@app.route("/create-3d")
def create_3d_page():
    image_url = request.args.get("image_url")
    return render_template("threed_step.html", image_url=image_url)

@app.route("/generate-3d", methods=["POST"])
def generate_3d():
    image_url = request.form["image_url"]
    output = replicate.run("stability-ai/triposr:d23a104692a7379d75138a27b82f453c52a0a1a94200e5f75e47c1341c592231", input={ "input_image": image_url, "remove_background": False })
    model_url = output['model']
    return render_template("result_3d.html", model_url=model_url)


if __name__ == "__main__":
    app.run(debug=True)
