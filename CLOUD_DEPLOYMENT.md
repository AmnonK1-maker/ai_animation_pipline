# ☁️ Cloud Deployment Guide - Railway.app + AWS S3

This guide walks you through deploying the AI Media Workflow Dashboard to the cloud using Railway.app and AWS S3.

---

## 📋 **Prerequisites**

Before you start, you'll need:

1. **GitHub account** (to connect your repository)
2. **Railway.app account** (free to sign up)
3. **AWS account** (for S3 storage)
4. **API keys** for Leonardo AI, Replicate, and OpenAI

**Estimated setup time: 30-40 minutes**

---

## 🏗️ **Architecture Overview**

```
┌────────────────────────────────────────┐
│          Railway.app Server            │
│                                        │
│  ┌──────────────┐  ┌───────────────┐ │
│  │  Flask Web   │  │  Background   │ │
│  │  Server      │  │  Worker       │ │
│  │  (Gunicorn)  │  │  (worker.py)  │ │
│  └──────────────┘  └───────────────┘ │
│           │              │            │
│  ┌────────────────────────────────┐  │
│  │   SQLite Database (jobs.db)    │  │
│  └────────────────────────────────┘  │
└────────────────────────────────────────┘
            │                │
            │                ↓
            │    ┌───────────────────────┐
            │    │    AWS S3 Bucket      │
            │    │  (Media Storage)      │
            │    │  - Images: library/   │
            │    │  - Videos: animations/│
            │    └───────────────────────┘
            ↓
    https://your-app.up.railway.app
            ↓
┌──────────┐ ┌──────────┐ ┌──────────┐
│  User 1  │ │  User 2  │ │  User 3  │
│ (Browser)│ │ (Browser)│ │ (Browser)│
└──────────┘ └──────────┘ └──────────┘
```

---

## 🪣 **Step 1: Set Up AWS S3 Storage**

> ℹ️ **S3 Status:** Fully operational and supported! AWS is phasing out legacy ACL features (Email Grantee ACLs), but we're using the modern **bucket policies** approach, which is recommended and future-proof. ✅

### 1.1 Create S3 Bucket

1. Go to [AWS S3 Console](https://s3.console.aws.amazon.com/)
2. Click **"Create bucket"**
3. Bucket settings:
   - **Bucket name**: `ai-workflow-media` (must be globally unique)
   - **Region**: `us-east-1` (or your preferred region)
   - **Object Ownership**: Keep default "ACLs disabled (recommended)"
   - **Block Public Access**: **UNCHECK** "Block all public access"
   - ⚠️ Acknowledge that objects can be public (needed for browser access)
4. Click **"Create bucket"**

### 1.2 Configure Bucket Policy

1. Go to your bucket → **Permissions** → **Bucket Policy**
2. Add this policy (replace `YOUR-BUCKET-NAME`):

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

3. Click **"Save changes"**

### 1.3 Enable CORS

1. Go to **Permissions** → **Cross-origin resource sharing (CORS)**
2. Add this configuration:

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

### 1.4 Create IAM User for API Access

1. Go to [IAM Console](https://console.aws.amazon.com/iam/)
2. **Users** → **Add users**
3. User name: `ai-workflow-app`
4. Select **"Access key - Programmatic access"**
5. **Permissions**: Attach existing policies → Select **"AmazonS3FullAccess"**
6. Click through to **Create user**
7. **⚠️ SAVE THESE CREDENTIALS** (you'll need them for Railway):
   - Access key ID
   - Secret access key

---

## 🚂 **Step 2: Deploy to Railway.app**

### 2.1 Prepare Your Repository

1. Ensure all changes are committed to Git:
```bash
git add .
git commit -m "Add cloud deployment configuration"
git push origin main
```

### 2.2 Create Railway Project

1. Go to [Railway.app](https://railway.app/) and sign up/login
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Authorize Railway to access your GitHub
5. Select your repository: `ai_animation_pipeline`

### 2.3 Configure Environment Variables

Railway will auto-detect Python and start building. Now add environment variables:

1. Go to your project → **Variables** tab
2. Add these variables:

```bash
# AI API Keys
LEONARDO_API_KEY=your_actual_leonardo_key
REPLICATE_API_KEY=your_actual_replicate_key
OPENAI_API_KEY=your_actual_openai_key
OPENAI_ORG_ID=your_actual_org_id

# Production Mode
PRODUCTION_MODE=true

# AWS S3 Configuration
USE_S3=true
AWS_ACCESS_KEY_ID=your_aws_access_key_from_step_1.4
AWS_SECRET_ACCESS_KEY=your_aws_secret_key_from_step_1.4
AWS_REGION=us-east-1
S3_BUCKET_NAME=ai-workflow-media
```

3. Click **"Save"**

### 2.4 Add Worker Service

By default, Railway only runs the web server. We need to add the background worker:

1. In your project, click **"New Service"**
2. Select **"Empty Service"**
3. Name it: `worker`
4. Go to **Settings** → **Start Command**
5. Enter: `python worker.py`
6. **Variables**: Copy all the same environment variables from the web service

### 2.5 Deploy

1. Railway will automatically deploy both services
2. Wait for build to complete (~3-5 minutes)
3. Once deployed, click on the **web service** → **Settings** → **Networking**
4. Click **"Generate Domain"**
5. Your app will be live at: `https://your-app.up.railway.app` 🎉

---

## ✅ **Step 3: Test Your Deployment**

1. Open your Railway URL in a browser
2. You should see the AI Media Workflow Dashboard
3. Try generating an image to test:
   - Click "Generate Image"
   - Enter a prompt
   - Submit job
   - Wait for processing (worker should pick it up)
   - Image should appear (stored on S3!)

---

## 🔧 **Troubleshooting**

### Build Fails

**Problem**: Railway build fails with dependency errors

**Solution**: Check the **Deploy Logs** in Railway:
- Look for missing packages
- Ensure `requirements.txt` is up to date
- Try redeploying: **Deployments** → **Redeploy**

### Worker Not Processing Jobs

**Problem**: Jobs stay in "queued" status

**Solution**: 
1. Check worker service is running: **worker service** → **Logs**
2. Verify environment variables are set in worker service
3. Restart worker: **Settings** → **Restart**

### Images/Videos Not Loading

**Problem**: Generated media shows broken image icons

**Solution**:
1. Check S3 bucket policy allows public read
2. Verify `USE_S3=true` in environment variables
3. Check S3 bucket name matches `S3_BUCKET_NAME` variable
4. Look at **Logs** for S3 upload errors

### Database Errors

**Problem**: "Database is locked" errors

**Solution**:
1. SQLite can have issues with multiple workers
2. Reduce workers in Procfile: Change `--workers 2` to `--workers 1`
3. Or upgrade to PostgreSQL (see Advanced Configuration below)

---

## 💰 **Cost Breakdown**

| Service | Monthly Cost | Notes |
|---------|--------------|-------|
| **Railway Hobby** | $10 | 1 vCPU, 1GB RAM, enough for 5-10 users |
| **AWS S3** | $2-5 | ~100GB storage + data transfer |
| **Leonardo API** | Pay per use | Image generation costs |
| **Replicate API** | Pay per use | Video animation costs |
| **OpenAI API** | Pay per use | Vision analysis costs |
| **Total Infrastructure** | **$12-15/month** | Fixed costs (excluding API usage) |

---

## 📈 **Scaling Up**

### When to Upgrade

Upgrade Railway plan when you experience:
- Slow job processing
- Timeouts on video operations
- More than 10 concurrent users

### Railway Pro ($20/month)
- 2 vCPU, 2GB RAM
- Better for 10-20 users
- Faster video processing

### Upgrade to PostgreSQL

If you experience database lock errors with multiple users:

1. Add PostgreSQL to Railway: **New** → **Database** → **PostgreSQL**
2. Update `requirements.txt`: Uncomment `psycopg2-binary`
3. Update database connection code in `app.py` and `worker.py`

---

## 🔐 **Security Considerations**

### API Keys
- ✅ Never commit API keys to Git
- ✅ Store in Railway environment variables
- ✅ Rotate keys periodically

### S3 Bucket
- ⚠️ Bucket is public for read access (required for frontend)
- ✅ Only your Railway app can write to bucket (via IAM user)
- ✅ Consider adding CloudFront CDN for DDoS protection

### User Authentication
- ⚠️ Current app has NO login system
- 🔧 Anyone with the URL can use the app
- 💡 Consider adding Flask-Login for production use with external teams

---

## 🎯 **Next Steps**

Once deployed successfully:

1. **Share the URL** with your team
2. **Monitor usage** in Railway dashboard (CPU, memory, bandwidth)
3. **Check S3 storage** growth in AWS console
4. **Set up alerts** in Railway for service failures

---

## 🆘 **Need Help?**

- **Railway Docs**: https://docs.railway.app/
- **AWS S3 Docs**: https://docs.aws.amazon.com/s3/
- **App Issues**: Check worker logs in Railway for detailed error messages

---

## 📝 **Quick Reference: Environment Variables**

Copy this template for your Railway configuration:

```bash
# Required
LEONARDO_API_KEY=
REPLICATE_API_KEY=
OPENAI_API_KEY=
OPENAI_ORG_ID=

# Production
PRODUCTION_MODE=true

# S3 Storage
USE_S3=true
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_BUCKET_NAME=

# Optional CDN
# CLOUDFRONT_URL=
```

---

**Deployment complete!** 🚀 Your AI Media Workflow Dashboard is now running in the cloud!


