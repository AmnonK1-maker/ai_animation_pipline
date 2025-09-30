import requests
import time
import os

# --- PASTE YOUR LEONARDO API KEY HERE ---
LEONARDO_API_KEY = os.environ.get("LEONARDO_API_KEY", "")
# -----------------------------------------

def test_leonardo_generation():
    """
    A standalone script to test the Leonardo AI image generation API call.
    """
    if not LEONARDO_API_KEY or LEONARDO_API_KEY == "YOUR_API_KEY_HERE":
        print("❌ Please paste your Leonardo AI API Key into the script.")
        return

    print("🚀 Starting Leonardo AI API test...")
    
    url = "https://cloud.leonardo.ai/api/rest/v1/generations"
    
    # This payload matches the one in your worker.py
    payload = {
        "height": 1024,
        "width": 1024,
        "modelId": "b24e16ff-06e3-43eb-8d33-4416c2d75876", # Leonardo Diffusion XL
        "prompt": "A single, delicious-looking red apple, professional product shot",
        "num_images": 1,
        "presetStyle": "CINEMATIC",
        "transparency": "foreground_only",
        "negative_prompt": "text, watermark, blurry, deformed, distorted, ugly"
    }
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {LEONARDO_API_KEY}"
    }

    try:
        # --- Step 1: Submit the job ---
        print("   -> Sending initial request to Leonardo AI...")
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status() # This will raise an error if the request fails (e.g., 401 Unauthorized)
        
        response_data = response.json()
        generation_id = response_data['sdGenerationJob']['generationId']
        print(f"   ✅ Job submitted successfully! Generation ID: {generation_id}")

        # --- Step 2: Poll for results ---
        get_url = f"https://cloud.leonardo.ai/api/rest/v1/generations/{generation_id}"
        
        while True:
            time.sleep(8) 
            print("   -> Polling for results...")
            response = requests.get(get_url, headers=headers)
            response.raise_for_status()
            
            response_data = response.json()
            status = response_data['generations_by_pk']['status']
            print(f"      Current status: {status}")

            if status == "COMPLETE":
                image_url = response_data['generations_by_pk']['generated_images'][0]['url']
                print("\n🎉 Success! Your image is ready.")
                print(f"   Image URL: {image_url}")
                break
            elif status == "FAILED":
                print("\n❌ Job failed. Please check your Leonardo AI account for more details.")
                break
                
    except requests.exceptions.HTTPError as e:
        print(f"\n❌ An HTTP Error occurred: {e.response.status_code} - {e.response.text}")
        print("   Please check that your API key is correct and has credits.")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    test_leonardo_generation()