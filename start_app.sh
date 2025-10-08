#!/bin/bash

# AI Media Workflow Dashboard - ONE-CLICK Startup Script
# This script starts BOTH Flask web server AND background worker automatically

echo "🎬 Starting AI Media Workflow Dashboard..."
echo "📁 Working directory: $(pwd)"

# Cleanup function to stop both processes on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    if [ ! -z "$FLASK_PID" ] && ps -p $FLASK_PID > /dev/null 2>&1; then
        echo "   Stopping Flask server (PID: $FLASK_PID)..."
        kill $FLASK_PID 2>/dev/null
    fi
    if [ ! -z "$WORKER_PID" ] && ps -p $WORKER_PID > /dev/null 2>&1; then
        echo "   Stopping background worker (PID: $WORKER_PID)..."
        kill $WORKER_PID 2>/dev/null
    fi
    echo "✅ Shutdown complete"
    exit 0
}

# Trap Ctrl+C and other termination signals
trap cleanup SIGINT SIGTERM

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run setup first: ./setup_auto.sh (or ./setup.sh)"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found!"
    echo ""
    echo "Please create .env file with API keys."
    echo "If you're a team member, ask your administrator for the .env file."
    echo ""
    echo "Required format:"
    echo "LEONARDO_API_KEY=your_key_here"
    echo "REPLICATE_API_KEY=your_token_here" 
    echo "OPENAI_API_KEY=your_key_here"
    echo "OPENAI_ORG_ID=your_org_id_here"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate
echo "✅ Virtual environment activated"

# Check if port 5001 is in use
if lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Port 5001 is already in use. Stopping existing process..."
    lsof -ti:5001 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Kill any existing worker processes
pkill -f "python.*worker.py" 2>/dev/null || true
sleep 1

# Start Flask app in background
echo "🚀 Starting Flask web server on http://localhost:5001..."
echo "🔧 Running in DEVELOPMENT mode"
flask run --host=0.0.0.0 --port=5001 > /dev/null 2>&1 &
FLASK_PID=$!

# Wait for Flask to start
sleep 3

# Check if Flask started successfully
if ! ps -p $FLASK_PID > /dev/null 2>&1; then
    echo "❌ Failed to start Flask web server"
    exit 1
fi

echo "✅ Flask web server started (PID: $FLASK_PID)"

# Start background worker
echo "⚙️  Starting background worker..."
python3 worker.py > worker_current.log 2>&1 &
WORKER_PID=$!

# Wait a moment and check if worker started
sleep 2

if ! ps -p $WORKER_PID > /dev/null 2>&1; then
    echo "❌ Failed to start background worker"
    echo "Check worker_current.log for errors"
    kill $FLASK_PID 2>/dev/null
    exit 1
fi

echo "✅ Background worker started (PID: $WORKER_PID)"
echo ""
echo "=========================================="
echo "✅ AI Media Workflow Dashboard is running!"
echo "=========================================="
echo ""
echo "🌐 Open your browser to: http://localhost:5001"
echo ""
echo "📊 Processes running:"
echo "   - Flask Web Server: PID $FLASK_PID"
echo "   - Background Worker: PID $WORKER_PID"
echo ""
echo "📝 Worker logs: worker_current.log"
echo ""
echo "Press Ctrl+C to stop both processes"
echo "=========================================="
echo ""

# Keep script running and monitor both processes
while true; do
    # Check if Flask is still running
    if ! ps -p $FLASK_PID > /dev/null 2>&1; then
        echo "❌ Flask server stopped unexpectedly"
        cleanup
    fi
    
    # Check if worker is still running
    if ! ps -p $WORKER_PID > /dev/null 2>&1; then
        echo "⚠️  Worker stopped unexpectedly. Restarting..."
        python3 worker.py > worker_current.log 2>&1 &
        WORKER_PID=$!
        sleep 2
        if ps -p $WORKER_PID > /dev/null 2>&1; then
            echo "✅ Worker restarted (PID: $WORKER_PID)"
        fi
    fi
    
    sleep 5
done
