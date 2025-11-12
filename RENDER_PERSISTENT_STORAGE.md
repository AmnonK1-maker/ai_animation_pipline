# Render.com Persistent Storage Setup

## Problem

Your jobs disappear after every deployment because:
- Render.com uses **ephemeral storage** (container is rebuilt fresh each time)
- The SQLite database (`jobs.db`) is stored locally and gets wiped
- Files in `static/` are also lost unless uploaded to S3

## Solution 1: Add Render Persistent Disk (Quick Fix - Recommended)

### Step 1: Create a Persistent Disk

1. Go to your Render Dashboard
2. Navigate to your Web Service
3. Click **"Disks"** in the left sidebar
4. Click **"Add Disk"**
5. Configure:
   - **Name**: `app-data`
   - **Mount Path**: `/opt/render/project/src/data`
   - **Size**: 10 GB (or more if you need it)
6. Click **"Create Disk"**

### Step 2: Update Your Code to Use the Persistent Disk

**Modify `app.py`** (around line 45):

```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Use persistent disk on Render.com
if os.path.exists('/opt/render/project/src/data'):
    # Running on Render with persistent disk
    DATA_DIR = '/opt/render/project/src/data'
    DATABASE_PATH = os.path.join(DATA_DIR, 'jobs.db')
    UPLOAD_FOLDER = os.path.join(DATA_DIR, 'static', 'uploads')
    ANIMATIONS_FOLDER = os.path.join(DATA_DIR, 'static', 'animations', 'generated')
    LIBRARY_FOLDER = os.path.join(DATA_DIR, 'static', 'library')
    # ... other folders
else:
    # Running locally
    DATA_DIR = BASE_DIR
    DATABASE_PATH = os.path.join(BASE_DIR, 'jobs.db')
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    # ... use BASE_DIR as before
```

**Update `get_db_connection()` function** (around line 109):

```python
def get_db_connection():
    # Use DATABASE_PATH instead of hardcoded path
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn
```

### Step 3: Ensure Folders Exist on Startup

Add this to your app initialization (after imports):

```python
# Create necessary folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ANIMATIONS_FOLDER, exist_ok=True)
os.makedirs(LIBRARY_FOLDER, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, 'static', 'library', 'transparent_videos'), exist_ok=True)
```

### Step 4: Initialize Database on First Run

The `init_database()` function should still work, but it will now create the database in the persistent disk.

### Step 5: Deploy

After adding these changes:
```bash
git add app.py
git commit -m "Add persistent disk support for Render.com"
git push origin railway-deployment
```

**Important**: After the first deployment with the disk, your database will persist across all future deployments! 🎉

---

## Solution 2: Migrate to PostgreSQL (Best Long-Term Solution)

### Step 1: Create PostgreSQL Database on Render

1. In Render Dashboard, click **"New +"** → **"PostgreSQL"**
2. Name it (e.g., `ai-animation-db`)
3. Choose the **Free plan** (or paid for better performance)
4. Click **"Create Database"**
5. **Copy the Internal Database URL** from the database info page

### Step 2: Add PostgreSQL to Your Service

1. Go to your Web Service → **"Environment"** tab
2. Add environment variable:
   - **Key**: `DATABASE_URL`
   - **Value**: Paste the Internal Database URL

### Step 3: Update Code to Support PostgreSQL

**Install psycopg2** (add to `requirements.txt`):
```
psycopg2-binary==2.9.9
```

**Modify `app.py`** to support both SQLite and PostgreSQL:

```python
import os
from urllib.parse import urlparse

# Determine database type
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # PostgreSQL (Render.com production)
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    def get_db_connection():
        # Parse DATABASE_URL
        result = urlparse(DATABASE_URL)
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
        return conn
    
    def init_database():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # PostgreSQL schema (use TEXT instead of INTEGER for timestamps)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prompt TEXT,
                    result_data TEXT,
                    keyed_result_data TEXT,
                    keying_settings TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
else:
    # SQLite (local development)
    import sqlite3
    
    DATABASE_PATH = os.path.join(BASE_DIR, 'jobs.db')
    
    def get_db_connection():
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    
    # Keep existing SQLite init_database() function
```

**Update all SQL queries** to be PostgreSQL-compatible:
- Replace `?` placeholders with `%s`
- Use `RETURNING id` instead of `cursor.lastrowid`

### Step 4: Deploy
```bash
git add requirements.txt app.py
git commit -m "Add PostgreSQL support for Render.com"
git push origin railway-deployment
```

---

## Solution 3: Use S3 for All Files (Current Partial Solution)

Your app already uploads to S3, but you still need a persistent database for job metadata.

**Combine**: Use PostgreSQL for the database + S3 for files = best of both worlds!

---

## Quick Test

After setting up persistent storage, test it:

1. Create a new job (e.g., generate an image)
2. Note the job ID
3. Trigger a manual redeploy on Render
4. After redeploy, check if the job still appears in the gallery
5. ✅ If it does, persistent storage is working!

---

## Render Disk Pricing

- **Free**: Not available on free tier
- **Starter** ($7/month for service): 
  - First disk: Free (up to 1 GB)
  - Additional storage: $0.25/GB/month

**Recommendation**: Start with Solution 1 (Persistent Disk) for quick fix, then migrate to PostgreSQL later for better scalability.

