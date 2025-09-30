#!/bin/bash

# AI Media Workflow Dashboard - Startup Script
# This script helps start both the Flask web server and background worker

echo "🎬 Starting AI Media Workflow Dashboard..."
echo "📁 Working directory: $(pwd)"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    echo "Please create .env with your API keys:"
    echo "LEONARDO_API_KEY=your_key_here"
    echo "REPLICATE_API_TOKEN=your_token_here" 
    echo "OPENAI_API_KEY=your_key_here"
    echo "OPENAI_ORG_ID=your_org_id_here"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

echo "✅ Virtual environment activated"

# Check if port 5001 is in use
if lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port 5001 is already in use. Stopping existing process..."
    lsof -ti:5001 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Start Flask app in background
echo "🚀 Starting Flask web server on http://localhost:5001..."
flask run --host=0.0.0.0 --port=5001 &
FLASK_PID=$!

# Wait for Flask to start
sleep 3

# Check if Flask started successfully
if ps -p $FLASK_PID > /dev/null; then
    echo "✅ Flask web server started (PID: $FLASK_PID)"
    echo "🌐 Access dashboard at: http://localhost:5001"
else
    echo "❌ Failed to start Flask web server"
    exit 1
fi

echo ""
echo "📋 MANUAL STEPS:"
echo "1. 🌐 Open http://localhost:5001 in your browser"
echo "2. ⚙️  Optional: Start background worker in new terminal:"
echo "   cd $(pwd)"
echo "   source venv/bin/activate"
echo "   python worker.py"
echo ""
echo "🛑 To stop the Flask server: kill $FLASK_PID"
echo "Press Ctrl+C to stop monitoring..."

# Keep script running to monitor Flask
while ps -p $FLASK_PID > /dev/null; do
    sleep 5
done

echo "❌ Flask server stopped"
