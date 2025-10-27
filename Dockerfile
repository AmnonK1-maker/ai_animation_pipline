# Use Python 3.11 base image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopencv-dev \
    python3-opencv \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Railway will set $PORT)
EXPOSE 8080

# Create startup script to run both web server and worker
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "========================================"\n\
echo "🚀 Starting AI Animation Pipeline"\n\
echo "========================================"\n\
\n\
# Start worker in background\n\
echo "📦 Starting worker process..."\n\
python3 worker.py > /app/worker.log 2>&1 &\n\
WORKER_PID=$!\n\
echo "✅ Worker started with PID: $WORKER_PID"\n\
\n\
# Wait a moment for worker to initialize\n\
sleep 2\n\
\n\
# Check if worker is still running\n\
if ps -p $WORKER_PID > /dev/null; then\n\
    echo "✅ Worker is running"\n\
else\n\
    echo "❌ Worker failed to start! Check worker.log"\n\
    cat /app/worker.log\n\
fi\n\
\n\
echo "========================================"\n\
echo "🌐 Starting Gunicorn web server..."\n\
echo "========================================"\n\
exec gunicorn --config gunicorn_config.py app:app' > /start.sh && chmod +x /start.sh

CMD ["/start.sh"]

