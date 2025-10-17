# ☁️ Cloud Deployment Checklist

## 📋 Pre-Deployment Status

✅ Code committed to Git  
✅ Deployment files present (Procfile, railway.json, nixpacks.toml, s3_storage.py)  
✅ Multi-threaded worker implemented  
✅ UI improvements completed  

---

## 🪣 **STEP 1: AWS S3 Setup** (15 minutes)

### 1.1 Create S3 Bucket

Go to: https://s3.console.aws.amazon.com/

- [ ] Click "Create bucket"
- [ ] Bucket name: `aiap-media-YOUR-NAME` (must be globally unique!)
- [ ] Region: `us-east-1` (or your preferred region)
- [ ] **IMPORTANT:** UNCHECK "Block all public access"
- [ ] Acknowledge warning about public access
- [ ] Click "Create bucket"

**✏️ Write down your bucket name:** _________________________

---

### 1.2 Configure Bucket Policy

- [ ] Go to your bucket → **Permissions** tab
- [ ] Scroll to **Bucket Policy** → Click "Edit"
- [ ] Paste this policy (replace YOUR-BUCKET-NAME):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

- [ ] Click "Save changes"

---

### 1.3 Enable CORS

- [ ] Go to **Permissions** → **Cross-origin resource sharing (CORS)**
- [ ] Click "Edit"
- [ ] Paste this:

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD", "PUT", "POST"],
    "AllowedOrigins": ["*"],
    "ExposeHeaders": ["ETag"]
  }
]
```

- [ ] Click "Save changes"

---

### 1.4 Create IAM User for API Access

Go to: https://console.aws.amazon.com/iam/

- [ ] Click **Users** → **Create user**
- [ ] User name: `aiap-app-user`
- [ ] Click "Next"
- [ ] Select **"Attach policies directly"**
- [ ] Search for and select: **"AmazonS3FullAccess"**
- [ ] Click "Next" → "Create user"
- [ ] Click on the user name you just created
- [ ] Go to **Security credentials** tab
- [ ] Click **"Create access key"**
- [ ] Select "Application running outside AWS"
- [ ] Click "Next" → "Create access key"

**⚠️ CRITICAL: Save these credentials NOW (you can only see them once):**

Access Key ID: _________________________

Secret Access Key: _________________________

---

## 🚂 **STEP 2: Push to GitHub** (2 minutes)

- [ ] Check git remote:
```bash
git remote -v
```

- [ ] If you don't have a remote, create GitHub repo and add it:
```bash
# Create repo on github.com first, then:
git remote add origin https://github.com/YOUR-USERNAME/ai_animation_pipeline.git
```

- [ ] Push your code:
```bash
git push origin main
```

**✏️ Your GitHub repo URL:** _________________________

---

## 🚂 **STEP 3: Railway.app Setup** (10 minutes)

### 3.1 Create Railway Account

Go to: https://railway.app/

- [ ] Sign up using GitHub
- [ ] Verify your email if needed

---

### 3.2 Create New Project

- [ ] Click **"New Project"**
- [ ] Select **"Deploy from GitHub repo"**
- [ ] Authorize Railway to access GitHub (if prompted)
- [ ] Select your repository: `ai_animation_pipeline`
- [ ] Wait for initial deployment to start (this will fail without env vars - that's OK!)

---

### 3.3 Configure Environment Variables

Click on your project → **Variables** tab → **RAW Editor**

Paste this template and fill in YOUR values:

```bash
# AI API Keys (copy from your .env file or use the .railway_env_template)
LEONARDO_API_KEY=your_leonardo_api_key_here
REPLICATE_API_KEY=your_replicate_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_ORG_ID=your_openai_org_id_here

# Production Mode
PRODUCTION_MODE=true

# AWS S3 Configuration (use your values from Step 1)
USE_S3=true
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY_FROM_STEP_1.4
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY_FROM_STEP_1.4
AWS_REGION=us-east-1
S3_BUCKET_NAME=YOUR_BUCKET_NAME_FROM_STEP_1.1

# Worker Configuration (parallel processing)
MAX_CONCURRENT_JOBS=3
```

- [ ] Replace all `YOUR_` placeholders with actual values
- [ ] Click **"Save"** or **"Deploy"**

---

### 3.4 Add Worker Service

Railway will run the web server automatically, but we need to add the worker:

- [ ] In your project dashboard, click **"+ New"**
- [ ] Select **"Empty Service"**
- [ ] Name it: `worker`
- [ ] Click on the `worker` service
- [ ] Go to **Settings** → **Start Command**
- [ ] Enter: `python worker.py`
- [ ] Go to **Variables** tab
- [ ] Click **"RAW Editor"** and paste the SAME environment variables from step 3.3
- [ ] Click **"Deploy"**

---

### 3.5 Generate Public URL

- [ ] Click on your **web service** (not worker)
- [ ] Go to **Settings** → **Networking**
- [ ] Click **"Generate Domain"**
- [ ] Copy the URL (looks like: `https://your-app.up.railway.app`)

**✏️ Your Railway URL:** _________________________

---

## ✅ **STEP 4: Test Your Deployment** (5 minutes)

- [ ] Open your Railway URL in a browser
- [ ] You should see the AI Media Workflow Dashboard
- [ ] Try generating an image:
  - Click "Image Generator" tool
  - Enter prompt: "a magical cat"
  - Select a model
  - Click "Generate Images"
  - Wait ~30 seconds

- [ ] Check the job queue - job should appear
- [ ] Check Railway logs (web service) - should show job created
- [ ] Check Railway logs (worker service) - should show job processing
- [ ] Image should appear in job queue (hosted on S3!)

---

## 🎉 **SUCCESS!** Your app is live!

### Share with your team:

**App URL:** https://your-app.up.railway.app

Anyone with this URL can now:
- Generate images
- Create animations  
- Process videos
- All without installing anything!

---

## 📊 **Monitoring** (Optional but Recommended)

### Railway Dashboard

Check these regularly:
- [ ] **Deployments** - see build logs if something breaks
- [ ] **Metrics** - CPU/RAM usage
- [ ] **Logs** - real-time application logs

### AWS S3 Dashboard

- [ ] Check **Metrics** tab to see storage growth
- [ ] Monitor costs in **Billing Dashboard**

---

## 🔧 **Troubleshooting**

### Build Failed

**Check:** Railway Deployment Logs
**Solution:** 
- Look for missing dependencies
- Ensure requirements.txt is complete
- Try "Redeploy" button

### Jobs Not Processing

**Check:** Worker service logs
**Solution:**
- Ensure worker service is running
- Check environment variables are set
- Restart worker service

### Images Not Loading

**Check:** S3 bucket policy
**Solution:**
- Verify bucket is public for read
- Check USE_S3=true in env vars
- Verify bucket name matches

### "Database Locked" Errors

**Solution:**
- Edit Procfile: Change `--workers 2` to `--workers 1`
- Commit and push changes
- Railway will auto-redeploy

---

## 💰 **Cost Estimate**

| Service | Monthly Cost |
|---------|--------------|
| Railway Hobby | $10 |
| AWS S3 (100GB) | $2-5 |
| **Total Infrastructure** | **$12-15/month** |

Plus API costs (Leonardo, Replicate, OpenAI) based on usage.

---

## 🎯 **Next Steps After Deployment**

1. [ ] Share URL with your team
2. [ ] Set up billing alerts in Railway
3. [ ] Monitor S3 storage growth
4. [ ] Consider adding authentication for external users
5. [ ] Set up daily S3 backups (optional)

---

## 🆘 **Need Help?**

**Railway Docs:** https://docs.railway.app/  
**AWS S3 Docs:** https://docs.aws.amazon.com/s3/  
**Check Logs:** Railway → Your Service → Logs tab  

---

## 📝 **Deployment Complete Checklist**

- [ ] S3 bucket created and configured
- [ ] IAM user created with credentials saved
- [ ] Code pushed to GitHub
- [ ] Railway project created
- [ ] Environment variables configured
- [ ] Worker service added
- [ ] Public URL generated
- [ ] Tested image generation successfully
- [ ] Shared URL with team

**Date deployed:** _________________________

**Deployed by:** _________________________

---

🎉 **Congratulations! Your AI Media Workflow Dashboard is now running in the cloud!**


