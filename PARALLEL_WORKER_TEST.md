# 🚀 Multi-Threaded Worker - Test Guide

## What's New?

The worker can now **process up to 3 jobs simultaneously** instead of one at a time! This dramatically improves throughput when you have multiple jobs queued.

## Configuration

Set the number of concurrent jobs via environment variable:

```bash
# In your .env file or export in terminal
MAX_CONCURRENT_JOBS=3  # Default is 3
```

You can adjust this based on your system:
- **1-2 jobs**: Low-end systems, limited API rate limits
- **3-5 jobs**: Recommended for most systems
- **5+ jobs**: High-end systems with good API rate limits

## How to Test

### Test 1: Quick Visual Test (Easiest)

1. **Open your browser** to http://localhost:5001

2. **Queue multiple jobs quickly:**
   - Generate 3-5 images using different models
   - Or create 2-3 animations
   - Or mix: 2 images + 2 animations

3. **Watch the job queue:**
   - You should see **multiple jobs go into "processing" status simultaneously**
   - Previously: Only 1 job would process at a time
   - Now: Up to 3 jobs process at once!

4. **Check the terminal logs:**
   ```bash
   tail -f worker_current.log
   ```
   
   You'll see messages like:
   ```
   Submitted job 123 to worker thread pool (1/3 active)
   Submitted job 124 to worker thread pool (2/3 active)
   Submitted job 125 to worker thread pool (3/3 active)
   [Thread-JobWorker-0] Processing job 123...
   [Thread-JobWorker-1] Processing job 124...
   [Thread-JobWorker-2] Processing job 125...
   ```

### Test 2: Database Check

```bash
# While jobs are processing, check the database
sqlite3 jobs.db "SELECT id, job_type, status FROM jobs WHERE status IN ('processing', 'keying_processing') ORDER BY id DESC LIMIT 10;"
```

**Before (single-threaded):** You'd see at most 1 job in "processing" status

**After (multi-threaded):** You'll see up to 3 jobs in "processing" status simultaneously

### Test 3: Performance Test

**Create a batch of image generation jobs:**

1. Generate 5 images with Leonardo AI
2. Note the start time
3. Watch them complete

**Expected Results:**
- **Single-threaded (old):** ~5-10 minutes (sequential)
- **Multi-threaded (new):** ~2-4 minutes (parallel, 3 at a time)

## What Jobs Benefit Most?

### ✅ Perfect for Parallel Processing:
- **Image Generation** (Leonardo, OpenAI, ByteDance) - API calls are I/O-bound
- **Background Removal** (BRIA API) - Pure API call
- **Style/Palette Analysis** (OpenAI Vision) - API-bound
- **Animation Generation** (Kling, Seedance) - Long API waits

### ⚠️ Limited Benefit:
- **Video Keying** - CPU-intensive, but can still run 2-3 in parallel
- **Video Stitching** - FFmpeg is CPU/disk intensive

## Thread Safety

The worker is thread-safe:
- ✅ Each job gets its own database connection
- ✅ SQLite WAL mode handles concurrent writes
- ✅ Each thread logs with `[Thread-JobWorker-N]` prefix
- ✅ Graceful shutdown waits for active jobs to complete

## Monitoring

### Check Active Threads:
```bash
# View worker log with thread names
tail -f worker_current.log | grep "Thread-JobWorker"
```

### Count Active Jobs:
```bash
# Check how many jobs are currently processing
sqlite3 jobs.db "SELECT COUNT(*) FROM jobs WHERE status IN ('processing', 'keying_processing');"
```

### Worker Status:
```bash
# Check if worker is running
ps aux | grep worker.py | grep -v grep
```

## Troubleshooting

### Worker Not Starting:
```bash
cd /Users/amnonk/Documents/kling_app
source venv/bin/activate
python3 worker.py  # Run in foreground to see errors
```

### Too Many Threads:
If your system is overloaded, reduce concurrent jobs:
```bash
export MAX_CONCURRENT_JOBS=2
python3 worker.py
```

### Check Thread Pool Status:
The worker logs show:
```
Submitted job X to worker thread pool (2/3 active)
```
This tells you how many threads are currently busy.

## Performance Tips

1. **API Rate Limits:** Most AI APIs have rate limits. Start with 3 concurrent jobs.

2. **System Resources:** 
   - Each video processing job uses ~500MB RAM
   - Each API call job uses ~100MB RAM
   - Monitor with `htop` or Activity Monitor

3. **Mixed Workload:** The worker handles mixed job types intelligently:
   - Keying jobs get priority (processed first)
   - Then regular queued jobs

## Enjoy Faster Processing! 🚀

Your jobs will now complete much faster when you have multiple items in the queue!

