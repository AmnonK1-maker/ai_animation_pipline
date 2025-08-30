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
from replicate.exceptions import ReplicateError

# --- CONFIGURATION ---
# IMPORTANT: PASTE YOUR REPLICATE API KEY HERE.
REPLICATE_API_KEY = os.environ.get("REPLICATE_API_KEY", "YOUR_REPLICATE_API_KEY_HERE")
os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_KEY

DATABASE_PATH = 'jobs.db'
STATIC_FOLDER = 'static'
LIBRARY_FOLDER = os.path.join(STATIC_FOLDER, 'library')
ANIMATIONS_FOLDER_GENERATED = os.path.join(STATIC_FOLDER, 'animations', 'generated')
UPLOADS_FOLDER = os.path.join(STATIC_FOLDER, 'uploads')
# -------------------------------------------

def handle_image_generation(job):
    """
    Processes an image generation job in a robust, two-step process:
    1. Generate the image using nano-banana.
    2. Remove the background using the lucataco/remove-bg model.
    """
    try:
        print(f"-> Starting two-step image generation for job {job['id']}...")
        prompt = job['prompt']
        # The 'num_images' from the user is ignored to ensure stability.

        # --- STEP 1: Generate a single base image ---
        print(f"   Step 1: Calling nano-banana to generate 1 image...")
        generated_url = str(replicate.run(
            "google/nano-banana",
            input={
                "prompt": prompt,
                "num_outputs": 1,
                "width": 1024,
                "height": 1024
            }
        ))
        print(f"   Generated 1 base image.")

        # --- STEP 2: Remove background from the image ---
        print("   Downloading base image to memory before background removal...")
        image_response = requests.get(generated_url)
        image_response.raise_for_status() 

        print(f"   Step 2: Removing background by uploading image data...")
        removed_bg_url = str(replicate.run(
            "lucataco/remove-bg",
            input={"image": io.BytesIO(image_response.content)}
        ))

        # Download and save the final transparent image
        final_image_response = requests.get(removed_bg_url)
        final_image_response.raise_for_status()

        filename = f"{uuid.uuid4()}.png"
        filepath = os.path.join(LIBRARY_FOLDER, filename)
        
        with open(filepath, "wb") as f:
            f.write(final_image_response.content)
        
        print(f"   Saved final transparent image to {filepath}")

        return filepath, None

    except ReplicateError as e:
        error_details = f"Replicate API Error: {e}"
        print(f"   {error_details}")
        return None, error_details
    except Exception as e:
        error_details = f"A general error occurred: {e}"
        print(f"   {error_details}")
        return None, error_details

def handle_style_analysis(job):
    """Processes a style analysis job using the correct API format for openai/gpt-4o."""
    try:
        print(f"-> Starting style analysis for job {job['id']}...")
        input_data = json.loads(job['input_data'])
        
        image_path = input_data['image_path']
        system_prompt = input_data['system_prompt']
        user_prompt = input_data['user_prompt']

        print(f"   Analyzing image: {image_path} with GPT-4o...")
        
        with open(image_path, "rb") as image_file:
            output = replicate.run(
                "openai/gpt-4o",
                input={
                    "image": image_file,
                    "prompt": user_prompt,
                    "system_prompt": system_prompt,
                    "max_tokens": 512
                }
            )
            
        analysis_text = "".join(output)
        print("   Analysis complete.")
        
        return analysis_text, None
    except ReplicateError as e:
        error_details = f"Replicate API Error: {e}"
        print(f"   {error_details}")
        return None, error_details
    except Exception as e:
        error_details = f"A general error occurred: {e}"
        print(f"   {error_details}")
        return None, error_details

def handle_animation(job):
    """Processes an animation job."""
    try:
        print(f"-> Starting animation for job {job['id']}...")
        prompt = job['prompt']
        input_data = json.loads(job['input_data'])

        image_url = input_data['image_url']
        aspect_ratio = input_data['aspect_ratio']
        duration = input_data['duration']
        background_color_name = input_data['background_color']
        
        print("   Preparing start image...")
        with open(image_url, "rb") as f:
            foreground = Image.open(f).convert("RGBA")

        colors = {"green": (0, 255, 0), "blue": (0, 0, 255)}
        background = Image.new("RGBA", foreground.size, colors.get(background_color_name, (0, 255, 0)))
        background.paste(foreground, (0, 0), foreground)
        
        final_image_mem_file = io.BytesIO()
        background.convert("RGB").save(final_image_mem_file, format="PNG")
        final_image_mem_file.seek(0)
        print("   Start image is ready.")

        print("   Calling Replicate API (kling)...")
        video_output_url = replicate.run(
            "kwaivgi/kling-v1.6-pro",
            input={
                "prompt": prompt,
                "start_image": final_image_mem_file,
                "aspect_ratio": aspect_ratio,
                "duration": duration
            }
        )
        print("   API call successful. Received video URL.")

        video_response = requests.get(video_output_url)
        video_response.raise_for_status()

        video_filename = f"{uuid.uuid4()}.mp4"
        video_filepath = os.path.join(ANIMATIONS_FOLDER_GENERATED, video_filename)
        
        with open(video_filepath, "wb") as f:
            f.write(video_response.content)
            
        print(f"   Animation saved to {video_filepath}")

        return video_filepath, None
    except ReplicateError as e:
        error_details = f"Replicate API Error: {e}"
        print(f"   {error_details}")
        return None, error_details
    except Exception as e:
        error_details = f"A general error occurred: {e}"
        print(f"   {error_details}")
        return None, error_details

def process_job(job):
    """Router function to call the correct handler based on job type."""
    job_type = job['job_type']
    print(f"Processing job {job['id']} of type '{job_type}'...")
    
    if job_type == 'image_generation':
        return handle_image_generation(job)
    elif job_type == 'animation':
        return handle_animation(job)
    elif job_type == 'style_analysis':
        return handle_style_analysis(job)
    else:
        error_msg = f"Unknown job type: {job_type}"
        print(f"-> {error_msg}")
        return None, error_msg

# --- Main Worker Loop ---
def main():
    print("🚀 Starting worker...")
    while True:
        job = None
        try:
            with sqlite3.connect(DATABASE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1")
                job = cursor.fetchone()

                if job:
                    cursor.execute("UPDATE jobs SET status = 'processing' WHERE id = ?", (job['id'],))
                    conn.commit()

            if job:
                result_data, error_message = process_job(job)
                
                new_status = 'completed' if error_message is None else 'failed'
                with sqlite3.connect(DATABASE_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE jobs SET status = ?, result_data = ?, error_message = ? WHERE id = ?",
                        (new_status, result_data, error_message, job['id'])
                    )
                    conn.commit()
                print(f"✅ Job {job['id']} finished with status: {new_status}")

            else:
                # print("No jobs found. Waiting...")
                time.sleep(5)

        except Exception as e:
            print(f"❌ An error occurred during the main loop: {e}")
            if job:
                with sqlite3.connect(DATABASE_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE jobs SET status = 'failed', error_message = ? WHERE id = ?", (str(e), job['id']))
                    conn.commit()
            time.sleep(10)

if __name__ == "__main__":
    main()
```



