# 🚂 Railway Deployment - Quick Start

## 🚀 Deploy in 10 Minutes

### **Step 1: Deploy Web Service**

1. Go to [railway.app/new](https://railway.app/new)
2. Click **"Deploy from GitHub repo"**
3. Select: `AmnonK1-maker/ai_animation_pipline`
4. Select **Branch**: `railway-deployment`
5. Railway will auto-build with Nixpacks

### **Step 2: Add Environment Variables**

In your service → **Variables** → **Raw Editor**:

```bash
LEONARDO_API_KEY=your_key
REPLICATE_API_KEY=your_key
OPENAI_API_KEY=your_key
OPENAI_ORG_ID=your_org
PRODUCTION_MODE=true
USE_S3=true
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=eu-central-1
S3_BUCKET_NAME=your_bucket
MAX_CONCURRENT_JOBS=2
```

### **Step 3: Generate Domain**

1. Go to **Settings** → **Networking**
2. Click **"Generate Domain"**
3. Your app is live! 🎉

### **Step 4: Add Worker Service**

1. Click **"+ New Service"** in your project
2. Select same repo: `ai_animation_pipline`
3. Select branch: `railway-deployment`
4. In **Settings** → **Start Command**:
   ```bash
   python3 worker.py
   ```
5. Copy environment variables from web service

---

## ✅ What You Get

- **8GB RAM** (vs 2GB on Render)
- **~$20/month** (vs $85 on Render Pro)
- **Separate services** for better scaling
- **All memory optimizations** included

---

## 🔍 Verify It's Working

**Web service logs:**
```
✅ Database initialized successfully!
[INFO] Listening at: http://0.0.0.0:5001
```

**Worker service logs:**
```
Worker: Configured for 2 concurrent jobs
🔍 Worker checking for jobs
💾 Memory: 450.0 MB RSS
```

---

## 💡 Tips

- Both services share the same database automatically
- Worker processes jobs in background
- Web serves the UI
- 8GB RAM is plenty for keying + sticker effects!

**That's it! Your app is deployed on Railway.** 🚂

