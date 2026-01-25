"""
Blender Keying Server - Flask API
Receives keying requests from Render.com, processes with Blender, returns S3 URL

Security Features:
- API key authentication
- IP whitelist
- Rate limiting
- File validation
- Process timeouts
- Disk monitoring
"""

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import subprocess
import requests
import boto3
from botocore.exceptions import ClientError
import json
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv
import logging
from datetime import datetime
import psutil
import shutil

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure logging
LOG_DIR = Path(os.getenv('LOG_DIR', './logs'))
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
BLENDER_PATH = os.getenv('BLENDER_PATH', 'blender')
BLENDER_SCRIPT = Path(__file__).parent / 'blender_keying.py'
TEMP_DIR = Path(os.getenv('TEMP_DIR', './temp'))
TEMP_DIR.mkdir(exist_ok=True)

# AWS S3 Configuration
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_REGION', 'eu-north-1')
S3_BUCKET = os.getenv('S3_BUCKET_NAME')

s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

# Security Configuration
API_KEY = os.getenv('BLENDER_SERVER_API_KEY')
ALLOWED_IPS = os.getenv('ALLOWED_IPS', '').split(',')
MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', 500))
PROCESS_TIMEOUT = int(os.getenv('PROCESS_TIMEOUT', 600))  # 10 minutes

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10 per minute"]
)

# Stats
stats = {
    'total_processed': 0,
    'total_errors': 0,
    'start_time': datetime.now()
}

# Middleware: API Key Authentication
def require_api_key(f):
    """Decorator to require API key"""
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != API_KEY:
            logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# Middleware: IP Whitelist (optional, comment out if not using)
def check_ip_whitelist():
    """Check if request IP is in whitelist"""
    if ALLOWED_IPS and ALLOWED_IPS[0]:  # If whitelist is configured
        if request.remote_addr not in ALLOWED_IPS:
            logger.warning(f"Blocked request from non-whitelisted IP: {request.remote_addr}")
            return jsonify({'error': 'Forbidden'}), 403
    return None

@app.before_request
def before_request():
    """Run before each request"""
    # IP whitelist check (comment out if not using)
    # response = check_ip_whitelist()
    # if response:
    #     return response
    pass

# Helper Functions

def get_disk_space():
    """Get available disk space in GB"""
    disk = psutil.disk_usage(str(TEMP_DIR))
    return disk.free / (1024 ** 3)

def cleanup_temp_files(older_than_hours=1):
    """Clean up old temporary files"""
    try:
        cutoff_time = time.time() - (older_than_hours * 3600)
        for file_path in TEMP_DIR.glob('*'):
            if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                file_path.unlink()
                logger.info(f"Cleaned up old temp file: {file_path.name}")
    except Exception as e:
        logger.error(f"Error cleaning temp files: {e}")

def download_from_s3(video_url, local_path):
    """Download video from S3 URL"""
    try:
        # Parse S3 URL to get bucket and key
        if video_url.startswith('https://'):
            # Format: https://bucket.s3.region.amazonaws.com/key
            parts = video_url.replace('https://', '').split('/', 1)
            if len(parts) == 2:
                s3_key = parts[1]
            else:
                raise ValueError("Invalid S3 URL format")
        else:
            raise ValueError("Only HTTPS S3 URLs accepted")
        
        logger.info(f"Downloading from S3: {s3_key}")
        s3_client.download_file(S3_BUCKET, s3_key, str(local_path))
        
        # Check file size
        file_size_mb = local_path.stat().st_size / (1024 ** 2)
        if file_size_mb > MAX_FILE_SIZE_MB:
            local_path.unlink()
            raise ValueError(f"File too large: {file_size_mb:.1f}MB (max: {MAX_FILE_SIZE_MB}MB)")
        
        logger.info(f"Downloaded {file_size_mb:.1f}MB")
        return True
        
    except ClientError as e:
        logger.error(f"S3 download error: {e}")
        return False
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False

def upload_to_s3(local_path, s3_key):
    """Upload file to S3"""
    try:
        logger.info(f"Uploading to S3: {s3_key}")
        
        extra_args = {
            'ContentType': 'video/webm',
            'ACL': 'public-read'
        }
        
        s3_client.upload_file(
            str(local_path),
            S3_BUCKET,
            s3_key,
            ExtraArgs=extra_args
        )
        
        # Generate public URL
        url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
        logger.info(f"Upload complete: {url}")
        return url
        
    except ClientError as e:
        logger.error(f"S3 upload error: {e}")
        return None
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return None

def run_blender_keying(input_video, output_video, params=None):
    """
    Run Blender keying script
    
    Args:
        input_video: Path to input video
        output_video: Path to output video
        params: Dict of keying parameters
    
    Returns:
        bool: True if successful
    """
    try:
        # Build command
        cmd = [
            BLENDER_PATH,
            '--background',
            '--python', str(BLENDER_SCRIPT),
            '--',
            str(input_video),
            str(output_video)
        ]
        
        if params:
            cmd.append(json.dumps(params))
        
        logger.info(f"Running Blender: {' '.join(cmd)}")
        
        # Run with timeout
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            stdout, stderr = process.communicate(timeout=PROCESS_TIMEOUT)
            
            # Log output
            if stdout:
                for line in stdout.split('\n'):
                    if line.strip():
                        logger.info(f"Blender: {line}")
            
            if process.returncode != 0:
                logger.error(f"Blender failed with code {process.returncode}")
                if stderr:
                    logger.error(f"Blender stderr: {stderr}")
                return False
            
            # Check output file exists
            if not output_video.exists():
                logger.error("Blender completed but output file not found")
                return False
            
            logger.info("Blender keying successful")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error(f"Blender timeout after {PROCESS_TIMEOUT}s")
            process.kill()
            process.communicate()
            return False
            
    except Exception as e:
        logger.error(f"Blender execution error: {e}")
        return False

# API Endpoints

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    disk_space = get_disk_space()
    
    # Check Blender availability
    try:
        result = subprocess.run(
            [BLENDER_PATH, '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        blender_available = result.returncode == 0
        blender_version = result.stdout.split('\n')[0] if blender_available else 'N/A'
    except:
        blender_available = False
        blender_version = 'N/A'
    
    uptime = (datetime.now() - stats['start_time']).total_seconds()
    
    return jsonify({
        'status': 'healthy' if blender_available else 'degraded',
        'blender_available': blender_available,
        'blender_version': blender_version,
        'disk_space_gb': round(disk_space, 2),
        'total_processed': stats['total_processed'],
        'total_errors': stats['total_errors'],
        'uptime_seconds': int(uptime)
    })

@app.route('/key_video', methods=['POST'])
@require_api_key
@limiter.limit("5 per minute")
def key_video():
    """
    Main keying endpoint
    
    Request JSON:
    {
        "video_url": "https://s3.../video.mp4",
        "job_id": 123,
        "params": {
            "clip_black": 0.0,
            "clip_white": 1.0,
            "despill_factor": 1.0,
            ...
        }
    }
    
    Response JSON:
    {
        "success": true,
        "result_url": "https://s3.../keyed_video.webm",
        "job_id": 123,
        "processing_time": 45.2
    }
    """
    start_time = time.time()
    job_id = None
    temp_input = None
    temp_output = None
    
    try:
        # Parse request
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON'}), 400
        
        video_url = data.get('video_url')
        job_id = data.get('job_id')
        params = data.get('params', {})
        
        if not video_url:
            return jsonify({'error': 'video_url required'}), 400
        
        logger.info(f"Processing job {job_id}: {video_url}")
        
        # Validate URL (only accept S3 URLs from our bucket)
        if not video_url.startswith(f'https://{S3_BUCKET}.s3.'):
            return jsonify({'error': 'Invalid video URL'}), 400
        
        # Check disk space
        if get_disk_space() < 1:  # Less than 1GB free
            cleanup_temp_files(older_than_hours=0.5)
            if get_disk_space() < 0.5:
                logger.error("Insufficient disk space")
                return jsonify({'error': 'Insufficient disk space'}), 507
        
        # Generate unique filenames
        unique_id = str(uuid.uuid4())[:8]
        temp_input = TEMP_DIR / f"input_{unique_id}.mp4"
        temp_output = TEMP_DIR / f"output_{unique_id}.webm"
        
        # Download video from S3
        logger.info("Downloading video...")
        if not download_from_s3(video_url, temp_input):
            return jsonify({'error': 'Failed to download video'}), 500
        
        # Run Blender keying
        logger.info("Running Blender keying...")
        if not run_blender_keying(temp_input, temp_output, params):
            return jsonify({'error': 'Blender keying failed'}), 500
        
        # Upload result to S3
        logger.info("Uploading result...")
        s3_key = f"library/transparent_videos/keyed_{job_id}_{unique_id}.webm"
        result_url = upload_to_s3(temp_output, s3_key)
        
        if not result_url:
            return jsonify({'error': 'Failed to upload result'}), 500
        
        # Success!
        processing_time = time.time() - start_time
        stats['total_processed'] += 1
        
        logger.info(f"Job {job_id} complete in {processing_time:.1f}s: {result_url}")
        
        return jsonify({
            'success': True,
            'result_url': result_url,
            'job_id': job_id,
            'processing_time': round(processing_time, 2)
        })
        
    except Exception as e:
        stats['total_errors'] += 1
        logger.error(f"Error processing job {job_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
        
    finally:
        # Cleanup temp files
        try:
            if temp_input and temp_input.exists():
                temp_input.unlink()
            if temp_output and temp_output.exists():
                temp_output.unlink()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

@app.route('/stats', methods=['GET'])
@require_api_key
def get_stats():
    """Get server statistics"""
    disk = psutil.disk_usage(str(TEMP_DIR))
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=1)
    
    return jsonify({
        'processed': stats['total_processed'],
        'errors': stats['total_errors'],
        'uptime': str(datetime.now() - stats['start_time']),
        'disk': {
            'free_gb': round(disk.free / (1024**3), 2),
            'used_gb': round(disk.used / (1024**3), 2),
            'percent': disk.percent
        },
        'memory': {
            'available_gb': round(memory.available / (1024**3), 2),
            'percent': memory.percent
        },
        'cpu_percent': cpu_percent
    })

# Cleanup old files on startup
cleanup_temp_files(older_than_hours=1)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    
    logger.info("=" * 60)
    logger.info("Blender Keying Server Starting")
    logger.info("=" * 60)
    logger.info(f"Blender path: {BLENDER_PATH}")
    logger.info(f"Temp dir: {TEMP_DIR}")
    logger.info(f"S3 bucket: {S3_BUCKET}")
    logger.info(f"Port: {port}")
    logger.info("=" * 60)
    
    # Run server
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )

