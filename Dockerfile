# Use Python 3.10 base image
FROM python:3.10-slim

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

# Create startup script to handle PORT variable
RUN echo '#!/bin/sh\nexec gunicorn --bind 0.0.0.0:${PORT:-8080} --timeout 120 --workers 2 app:app' > /start.sh && chmod +x /start.sh

CMD ["/start.sh"]

