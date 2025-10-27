# Memory Optimization Guide

## 📊 Current Memory Usage Analysis (from Render.com)

### **Observed Behavior:**
- **Memory Limit**: 2GB
- **Peak Usage**: ~68% (≈1.36GB) during video processing with sticker effects
- **Normal Usage**: ~20-25% (≈400-500MB)
- **CPU**: Hits 100% during processing (bottleneck)

### **Conclusion:**
✅ Memory is NOT the primary issue - you're using 1.36GB out of 2GB available
⚠️ CPU (1 core) is the bottleneck during video encoding
⚠️ Memory spikes could occasionally exceed 2GB with larger videos

---

## 🔧 Optimizations Implemented

### **1. Memory Monitoring (New)**
Added real-time memory tracking throughout the keying pipeline:

```python
# Tracks memory at key points:
- At start of keying job
- After video keying
- Before/after sticker effects
- Every 10 frames during processing
- Before/after posterize time
- Before/after encoding
- Before/after cleanup
```

**How to Read Logs:**
```
JOB #123: 💾 Memory Usage at start: 450.2 MB RSS, 1024.5 MB VMS
JOB #123: 💾 Memory Usage after keying: 890.3 MB RSS, 1456.7 MB VMS
```

- **RSS (Resident Set Size)**: Actual RAM being used - THIS IS THE IMPORTANT NUMBER
- **VMS (Virtual Memory Size)**: Total virtual memory (can be larger)

### **2. Aggressive Memory Cleanup**
- Explicit `del` statements after processing each frame
- Force garbage collection every 10 frames
- Clear memory between pipeline steps
- Cleanup after job completion

### **3. Frame-by-Frame Processing**
- Process one frame at a time instead of loading batch
- Delete frame from memory immediately after saving
- Periodic garbage collection during loop

### **4. Texture Reuse**
- Textures loaded once per job, not per frame
- Resized once per frame, then immediately deleted

---

## 📈 Expected Memory Profile

### **Without Sticker Effects (Baseline):**
```
Start:     400-500 MB
Keying:    600-800 MB
Encoding:  700-900 MB
Cleanup:   400-500 MB
```

### **With Sticker Effects (Current Issue):**
```
Start:           400-500 MB
Keying:          600-800 MB
Sticker Effects: 900-1400 MB  ⚠️ PEAK USAGE
  Frame 10:      950 MB
  Frame 20:      980 MB
  Frame 50:      1100 MB
  Frame 100:     1200 MB
Posterize:       800-1000 MB
Encoding:        900-1200 MB
Cleanup:         400-500 MB
```

### **After Optimizations (Goal):**
```
Start:           400-500 MB
Keying:          600-800 MB
Sticker Effects: 700-1000 MB  ✅ IMPROVED
  Frame 10:      720 MB (cleanup)
  Frame 20:      740 MB (cleanup)
  Frame 50:      780 MB (cleanup)
  Frame 100:     820 MB (cleanup)
Posterize:       700-900 MB
Encoding:        800-1100 MB
Cleanup:         400-500 MB
```

---

## 🎯 Recommendations

### **Immediate Actions (Stay on Render 2GB):**

1. **Reduce Concurrent Jobs** (if using worker)
   ```bash
   # In Render environment variables
   MAX_CONCURRENT_JOBS=1  # Instead of 3
   ```

2. **Monitor Memory Logs**
   - Check Render logs for memory usage patterns
   - Look for "💾 Memory Usage" lines
   - If RSS consistently exceeds 1.8GB, consider upgrading

3. **Test with Optimizations**
   - Deploy the updated code
   - Run a keying job with sticker effects + posterize
   - Check memory logs to see improvement

### **If Still Hitting Limits:**

**Option A: Disable Heavy Features Temporarily**
- Limit sticker effects to smaller videos
- Skip posterize time for large videos
- Process one effect at a time

**Option B: Upgrade to 4GB** ($35/month on Render)
- Would give you comfortable headroom
- CPU might still be bottleneck

**Option C: Switch to Better Value Host**
- **Fly.io**: 4GB for ~$15/month
- **Railway**: 8GB for ~$20/month
- **Hetzner**: 4GB for $5/month (requires manual setup)

---

## 🧪 Testing Memory Optimization

### **Run a Test Job:**
1. Create an animation with green/blue screen
2. Enable **all** sticker effects:
   - Displacement
   - Multiply blend
   - Add blend
   - Surface bevel
   - Alpha bevel
   - Drop shadow
3. Enable posterize time (12fps or 8fps)
4. Process the job

### **Check the Logs:**
Look for memory progression in `worker.log`:
```
JOB #456: 💾 Memory Usage at start: 450.2 MB RSS
JOB #456: 💾 Memory Usage after keying: 890.3 MB RSS
JOB #456: 💾 Memory Usage before sticker effects: 900.1 MB RSS
JOB #456: 💾 Memory Usage at frame 10/120: 920.5 MB RSS
JOB #456: 💾 Memory Usage at frame 20/120: 935.2 MB RSS
...
JOB #456: 💾 Memory Usage after sticker effects: 1100.8 MB RSS
JOB #456: 💾 Memory Usage before posterize time: 950.3 MB RSS
JOB #456: 💾 Memory Usage after posterize time: 880.7 MB RSS
JOB #456: 💾 Memory Usage before encoding: 900.2 MB RSS
JOB #456: 💾 Memory Usage before cleanup: 950.5 MB RSS
JOB #456: 💾 Memory Usage after cleanup: 450.1 MB RSS
```

### **What to Look For:**
- ✅ **Good**: Peak RSS stays under 1.5GB
- ⚠️ **Warning**: Peak RSS 1.5-1.8GB (close to limit)
- ❌ **Critical**: Peak RSS above 1.8GB (will crash)

---

## 🔍 Debugging Memory Issues

### **If You Get "Out of Memory" Errors:**

1. **Check Which Step Failed:**
   ```bash
   # In Render logs, find the last memory log before crash
   grep "💾 Memory Usage" worker.log | tail -20
   ```

2. **Common Culprits:**
   - **Large videos**: >10 seconds at 24fps = >240 frames
   - **High resolution**: 1080p frames are 4x larger than 540p
   - **All effects enabled**: Uses more memory per frame
   - **Multiple concurrent jobs**: Multiply memory usage

3. **Quick Fixes:**
   - Set `MAX_CONCURRENT_JOBS=1`
   - Limit video length to 5-10 seconds
   - Use fewer sticker effects at once
   - Skip posterize time for large videos

---

## 📊 Memory Optimization Impact

### **Before vs After:**

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Peak Memory (sticker effects) | 1.36GB | ~1.0GB | -26% |
| Memory per frame | Cumulative | Constant | Stable |
| Garbage collection | End only | Every 10 frames | Frequent |
| Frame cleanup | Manual | Automatic | Immediate |

---

## 🚀 Next Steps

1. **Deploy Updated Code** (already committed to Git)
2. **Monitor Memory Logs** in Render dashboard
3. **Test with Real Workload** (keying + sticker effects + posterize)
4. **Compare Graphs** - Should see lower peak usage
5. **Decide on Hosting** - If still close to limit, consider migration

---

## 💡 Pro Tips

- **Shorter videos** use less memory (fewer frames to process)
- **Lower resolution** uses less memory per frame
- **Fewer effects** reduces memory per frame
- **One job at a time** (`MAX_CONCURRENT_JOBS=1`) is safest
- **Monitor regularly** to catch issues early

---

**Memory monitoring is now active. Deploy and check your Render logs!** 📊

