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
RUN echo '#!/bin/sh\n\
echo "Starting worker in background..."\n\
python worker.py &\n\
WORKER_PID=$!\n\
echo "Worker started with PID: $WORKER_PID"\n\
\n\
echo "Starting Gunicorn web server..."\n\
exec gunicorn --config gunicorn_config.py app:app' > /start.sh && chmod +x /start.sh

CMD ["/start.sh"]

