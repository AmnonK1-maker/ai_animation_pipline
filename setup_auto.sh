#!/bin/bash

# 🎬 AI Media Workflow Dashboard - AUTOMATIC One-Click Setup Script
# This script automatically installs ALL dependencies including Python and ffmpeg

set -e  # Exit on any error

echo "🎬 AI Media Workflow Dashboard - AUTOMATIC Setup Script"
echo "========================================================"
echo "This script will automatically install:"
echo "  - Python 3.8+ (if needed)"
echo "  - ffmpeg (if needed)"
echo "  - All Python dependencies"
echo "========================================================"
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

# Detect OS
OS="$(uname -s)"
print_status "Detected OS: $OS"

# Check if we need sudo
NEED_SUDO=false
if [ "$EUID" -ne 0 ] && [ "$OS" = "Linux" ]; then
    NEED_SUDO=true
fi

# ============================================
# STEP 1: Install Package Manager (if needed)
# ============================================

install_homebrew_if_needed() {
    if [ "$OS" = "Darwin" ]; then
        if ! command -v brew &> /dev/null; then
            print_status "Homebrew not found. Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            
            # Add Homebrew to PATH for M1/M2 Macs
            if [ -f "/opt/homebrew/bin/brew" ]; then
                echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi
            
            print_success "Homebrew installed successfully"
        else
            print_success "Homebrew already installed"
        fi
    fi
}

# ============================================
# STEP 2: Install Python 3.8+
# ============================================

install_python() {
    print_status "Checking Python installation..."
    
    PYTHON_CMD=""
    PYTHON_INSTALLED=false
    
    # Check if python3 exists and is version 3.8+
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
        
        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 8 ]; then
            PYTHON_CMD="python3"
            PYTHON_INSTALLED=true
            print_success "Python $PYTHON_VERSION found and is compatible"
        else
            print_warning "Python $PYTHON_VERSION found but version 3.8+ is required"
        fi
    fi
    
    # Install Python if needed
    if [ "$PYTHON_INSTALLED" = false ]; then
        print_status "Installing Python 3..."
        
        if [ "$OS" = "Darwin" ]; then
            # macOS - use Homebrew
            install_homebrew_if_needed
            brew install python@3.11
            PYTHON_CMD="python3"
            print_success "Python 3.11 installed via Homebrew"
            
        elif [ "$OS" = "Linux" ]; then
            # Linux - detect distribution
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                
                if [ "$ID" = "ubuntu" ] || [ "$ID" = "debian" ]; then
                    print_status "Installing Python on Ubuntu/Debian..."
                    if [ "$NEED_SUDO" = true ]; then
                        sudo apt-get update
                        sudo apt-get install -y python3 python3-pip python3-venv
                    else
                        apt-get update
                        apt-get install -y python3 python3-pip python3-venv
                    fi
                    
                elif [ "$ID" = "fedora" ] || [ "$ID" = "rhel" ] || [ "$ID" = "centos" ]; then
                    print_status "Installing Python on Fedora/RHEL/CentOS..."
                    if [ "$NEED_SUDO" = true ]; then
                        sudo dnf install -y python3 python3-pip
                    else
                        dnf install -y python3 python3-pip
                    fi
                    
                elif [ "$ID" = "arch" ] || [ "$ID" = "manjaro" ]; then
                    print_status "Installing Python on Arch Linux..."
                    if [ "$NEED_SUDO" = true ]; then
                        sudo pacman -S --noconfirm python python-pip
                    else
                        pacman -S --noconfirm python python-pip
                    fi
                fi
            fi
            
            PYTHON_CMD="python3"
            print_success "Python 3 installed successfully"
        fi
        
        # Verify installation
        if ! command -v $PYTHON_CMD &> /dev/null; then
            print_error "Python installation failed. Please install manually:"
            echo "  Visit: https://www.python.org/downloads/"
            exit 1
        fi
    fi
    
    export PYTHON_CMD
}

# ============================================
# STEP 3: Install ffmpeg
# ============================================

install_ffmpeg() {
    print_status "Checking ffmpeg installation..."
    
    if command -v ffmpeg &> /dev/null; then
        FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -n1)
        print_success "ffmpeg already installed: $FFMPEG_VERSION"
        return
    fi
    
    print_status "Installing ffmpeg..."
    
    if [ "$OS" = "Darwin" ]; then
        # macOS - use Homebrew
        install_homebrew_if_needed
        brew install ffmpeg
        print_success "ffmpeg installed via Homebrew"
        
    elif [ "$OS" = "Linux" ]; then
        # Linux - detect distribution
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            
            if [ "$ID" = "ubuntu" ] || [ "$ID" = "debian" ]; then
                print_status "Installing ffmpeg on Ubuntu/Debian..."
                if [ "$NEED_SUDO" = true ]; then
                    sudo apt-get update
                    sudo apt-get install -y ffmpeg
                else
                    apt-get update
                    apt-get install -y ffmpeg
                fi
                
            elif [ "$ID" = "fedora" ] || [ "$ID" = "rhel" ] || [ "$ID" = "centos" ]; then
                print_status "Installing ffmpeg on Fedora/RHEL/CentOS..."
                # Enable RPM Fusion for ffmpeg
                if [ "$NEED_SUDO" = true ]; then
                    sudo dnf install -y https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm || true
                    sudo dnf install -y ffmpeg
                else
                    dnf install -y https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm || true
                    dnf install -y ffmpeg
                fi
                
            elif [ "$ID" = "arch" ] || [ "$ID" = "manjaro" ]; then
                print_status "Installing ffmpeg on Arch Linux..."
                if [ "$NEED_SUDO" = true ]; then
                    sudo pacman -S --noconfirm ffmpeg
                else
                    pacman -S --noconfirm ffmpeg
                fi
            fi
        fi
        
        print_success "ffmpeg installed successfully"
    fi
    
    # Verify installation
    if ! command -v ffmpeg &> /dev/null; then
        print_warning "ffmpeg installation may have failed. Video features may not work."
        print_warning "You can install manually: https://ffmpeg.org/download.html"
    fi
}

# ============================================
# STEP 4: Run Installation
# ============================================

# Install dependencies
install_python
install_ffmpeg

# ============================================
# STEP 5: Setup Virtual Environment
# ============================================

print_status "Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    $PYTHON_CMD -m venv venv
    print_success "Virtual environment created"
else
    print_warning "Virtual environment already exists, skipping creation"
fi

# Activate virtual environment
source venv/bin/activate

# ============================================
# STEP 6: Install Python Dependencies
# ============================================

print_status "Installing Python dependencies (this may take a few minutes)..."

# Upgrade pip first
pip install --upgrade pip --quiet

# Install requirements
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    print_success "All Python packages installed successfully"
else
    print_error "requirements.txt not found!"
    exit 1
fi

# ============================================
# STEP 7: Setup Environment File
# ============================================

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
else
    print_success ".env file already exists"
    
    # Check if keys are still placeholders
    if grep -q "your_.*_api_key_here" .env; then
        print_warning "⚠️  Your .env file contains placeholder values. Please update with real API keys!"
    fi
fi

# ============================================
# STEP 8: Create Directory Structure
# ============================================

print_status "Creating necessary directories..."
mkdir -p static/animations/generated
mkdir -p static/animations/approved/_processed
mkdir -p static/animations/rendered
mkdir -p static/library/transparent_videos
mkdir -p static/uploads
print_success "Directory structure created"

# ============================================
# STEP 9: Make Scripts Executable
# ============================================

if [ -f "start_app.sh" ]; then
    chmod +x start_app.sh
    print_success "start_app.sh is now executable"
fi

if [ -f "setup.sh" ]; then
    chmod +x setup.sh
fi

# ============================================
# SETUP COMPLETE!
# ============================================

deactivate 2>/dev/null || true

echo ""
echo "=============================================="
print_success "🎉 AUTOMATIC SETUP COMPLETE!"
echo "=============================================="
echo ""
echo "✅ Installed:"
echo "   - Python 3.8+ with pip"
echo "   - ffmpeg for video processing"
echo "   - All Python dependencies"
echo "   - Virtual environment configured"
echo ""
echo "Next Steps:"
echo ""
echo "1. ${YELLOW}Configure your API keys:${NC}"
echo "   ${BLUE}nano .env${NC}  or  ${BLUE}open .env${NC}"
echo ""
echo "2. ${YELLOW}Start the application:${NC}"
echo "   ${GREEN}./start_app.sh${NC}"
echo ""
echo "3. ${YELLOW}Open your browser to:${NC}"
echo "   ${BLUE}http://localhost:5001${NC}"
echo ""
echo "For help, see ReadMe.md or SETUP.md"
echo ""
