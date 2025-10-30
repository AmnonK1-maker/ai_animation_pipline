# 🚀 Deploy to Render.com

## Quick Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/AmnonK1-maker/ai_animation_pipline)

---

## Manual Deployment Steps

### 1️⃣ Connect Repository

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **"New +"** → **"Blueprint"**
3. Connect your GitHub account if not already connected
4. Select repository: **`ai_animation_pipline`**
5. Branch: **`railway-deployment`**
6. Render will detect `render.yaml` automatically

### 2️⃣ Configure Environment Variables

Add these in the Render dashboard when prompted:

**Required API Keys:**
```
OPENAI_API_KEY=sk-...
OPENAI_ORG_ID=org-...
REPLICATE_API_KEY=r8_...
LEONARDO_API_KEY=...
```

**Production Settings:**
```
PRODUCTION_MODE=true
MAX_CONCURRENT_JOBS=3
```

**AWS S3 (Optional - leave USE_S3=false initially):**
```
USE_S3=false
AWS_ACCESS_KEY_ID=(leave empty)
AWS_SECRET_ACCESS_KEY=(leave empty)
AWS_REGION=us-east-1
S3_BUCKET_NAME=(leave empty)
```

### 3️⃣ Deploy

1. Click **"Apply"** to create the service
2. Render will:
   - Build Docker container (~5-10 minutes)
   - Start web server + worker
   - Provide a public URL: `https://your-app.onrender.com`

### 4️⃣ Verify Deployment

Once deployed, check:
- ✅ Web interface loads at your Render URL
- ✅ Can create image generation jobs
- ✅ Worker processes jobs (check logs)

---

## 📋 Deployment Checklist

- [ ] GitHub repository connected to Render
- [ ] Branch set to `railway-deployment`
- [ ] All API keys added to environment variables
- [ ] `PRODUCTION_MODE=true` set
- [ ] Docker build completed successfully
- [ ] Web service is running
- [ ] Worker is processing jobs (check logs)
- [ ] Can access app at Render URL
- [ ] Test image generation workflow
- [ ] Test animation workflow
- [ ] Test keying workflow

---

## 🔧 Troubleshooting

### Build fails with "requirements.txt not found"
- Make sure you're on the `railway-deployment` branch
- Check that `requirements.txt` exists in root directory

### Worker not processing jobs
- Check Render logs: Dashboard → Your Service → Logs
- Verify worker started: Look for "Worker started with PID"
- Check API keys are correctly set

### Database errors
- Render provides ephemeral filesystem on free tier
- Database resets on each deploy
- Consider upgrading to paid plan for persistent disk

### FFmpeg errors
- FFmpeg is installed via Dockerfile
- Check build logs to ensure apt-get installed ffmpeg

---

## 📊 Monitor Your App

**View Logs:**
- Render Dashboard → Your Service → Logs
- Filter by "worker.py" to see job processing
- Filter by "gunicorn" to see web requests

**Check Metrics:**
- Render Dashboard → Metrics
- CPU, Memory, Request count

**Restart Service:**
- Render Dashboard → Manual Deploy → "Clear build cache & deploy"

---

## 🔄 Update Deployment

When you push new code:

```bash
git add .
git commit -m "Your update message"
git push origin railway-deployment
```

Render will automatically detect the push and redeploy! 🎉

---

## 💰 Pricing Notes

**Free Tier:**
- Web service sleeps after 15 min inactivity
- 750 hours/month free
- Ephemeral filesystem (database resets on deploy)

**Paid Tier ($7/month):**
- Always-on service
- Persistent disk (database survives deploys)
- Faster builds

---

## 📚 Additional Resources

- [Render Documentation](https://render.com/docs)
- [Blueprint Spec](https://render.com/docs/blueprint-spec)
- [Environment Variables](https://render.com/docs/environment-variables)


