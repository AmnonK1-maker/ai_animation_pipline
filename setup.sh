#!/bin/bash

# 🎬 AI Media Workflow Dashboard - One-Click Setup Script
# This script sets up the entire application environment automatically

set -e  # Exit on any error

echo "🎬 AI Media Workflow Dashboard - Setup Script"
echo "=============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored messages
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on macOS or Linux
OS="$(uname -s)"
print_status "Detected OS: $OS"

# Step 1: Check Python version
print_status "Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Python $PYTHON_VERSION found"
    
    # Check if version is 3.8 or higher
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
    
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
        print_error "Python 3.8+ is required. You have $PYTHON_VERSION"
        exit 1
    fi
else
    print_error "Python 3 is not installed. Please install Python 3.8 or higher."
    echo "Visit: https://www.python.org/downloads/"
    exit 1
fi

# Step 2: Check for ffmpeg
print_status "Checking ffmpeg installation..."
if command -v ffmpeg &> /dev/null; then
    FFMPEG_VERSION=$(ffmpeg -version | head -n1)
    print_success "ffmpeg found: $FFMPEG_VERSION"
else
    print_warning "ffmpeg not found. Video processing features will not work."
    echo ""
    echo "To install ffmpeg:"
    if [ "$OS" = "Darwin" ]; then
        echo "  macOS: brew install ffmpeg"
    elif [ "$OS" = "Linux" ]; then
        echo "  Ubuntu/Debian: sudo apt-get install ffmpeg"
        echo "  Fedora: sudo dnf install ffmpeg"
    fi
    echo ""
    read -p "Continue without ffmpeg? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Step 3: Create virtual environment
print_status "Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_success "Virtual environment created"
else
    print_warning "Virtual environment already exists, skipping creation"
fi

# Step 4: Activate virtual environment and install dependencies
print_status "Installing Python dependencies (this may take a few minutes)..."
source venv/bin/activate

# Upgrade pip first
pip install --upgrade pip > /dev/null 2>&1

# Install requirements
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    print_success "All Python packages installed successfully"
else
    print_error "requirements.txt not found!"
    exit 1
fi

# Step 5: Setup .env file
print_status "Configuring environment variables..."
if [ ! -f ".env" ]; then
    print_warning ".env file not found. Creating template..."
    cat > .env << 'EOF'
# API Keys - Please fill in your actual keys
LEONARDO_API_KEY="your_leonardo_api_key_here"
REPLICATE_API_KEY="your_replicate_api_key_here"
OPENAI_API_KEY="your_openai_api_key_here"
OPENAI_ORG_ID="your_openai_org_id_here"
EOF
    print_success ".env template created"
    echo ""
    print_warning "⚠️  IMPORTANT: You need to edit .env with your actual API keys!"
    echo ""
    echo "API Key Sources:"
    echo "  - Leonardo AI: https://app.leonardo.ai/settings"
    echo "  - Replicate: https://replicate.com/account/api-tokens"
    echo "  - OpenAI: https://platform.openai.com/api-keys"
    echo ""
    read -p "Press Enter after you've added your API keys to .env (or press Ctrl+C to exit and add them later)..."
else
    print_success ".env file already exists"
    
    # Check if keys are still placeholders
    if grep -q "your_.*_api_key_here" .env; then
        print_warning "⚠️  Your .env file contains placeholder values. Please update with real API keys!"
    fi
fi

# Step 6: Initialize database (if needed)
print_status "Checking database..."
if [ ! -f "jobs.db" ]; then
    print_status "Database not found. It will be created automatically on first run."
else
    print_success "Database exists"
fi

# Step 7: Create necessary directories
print_status "Creating necessary directories..."
mkdir -p static/animations/generated
mkdir -p static/animations/approved/_processed
mkdir -p static/animations/rendered
mkdir -p static/library/transparent_videos
mkdir -p static/uploads
print_success "Directory structure created"

# Step 8: Make startup script executable
if [ -f "start_app.sh" ]; then
    chmod +x start_app.sh
    print_success "start_app.sh is now executable"
fi

# Setup complete!
echo ""
echo "=============================================="
print_success "🎉 Setup Complete!"
echo "=============================================="
echo ""
echo "Next Steps:"
echo ""
echo "1. Verify your API keys in .env file:"
echo "   ${BLUE}nano .env${NC}  or  ${BLUE}open .env${NC}"
echo ""
echo "2. Start the application:"
echo "   ${GREEN}./start_app.sh${NC}"
echo ""
echo "3. Open your browser to:"
echo "   ${BLUE}http://localhost:5001${NC}"
echo ""
echo "For troubleshooting, see ReadMe.md"
echo ""

# Deactivate virtual environment
deactivate 2>/dev/null || true

