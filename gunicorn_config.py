"""Gunicorn configuration for production deployment"""
import os
import sys

# Ensure the app directory is in the path
sys.path.insert(0, os.path.dirname(__file__))

def on_starting(server):
    """Called just before the master process is initialized."""
    print("=" * 70)
    print("🚀 GUNICORN STARTING - Initializing database...")
    print(f"📁 Working directory: {os.getcwd()}")
    print(f"📁 App directory: {os.path.dirname(__file__)}")
    print("=" * 70)
    
    # Import and initialize database
    try:
        from app import init_db, DATABASE_PATH
        print(f"📁 Database path: {DATABASE_PATH}")
        init_db()
        print("✅ Database initialized successfully!")
        print("=" * 70)
    except Exception as e:
        print(f"❌ CRITICAL: Database initialization failed!")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 70)
        # Don't raise - let Gunicorn start anyway

# Worker configuration
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 2
worker_class = "sync"
timeout = 120
accesslog = "-"
errorlog = "-"
loglevel = "info"

