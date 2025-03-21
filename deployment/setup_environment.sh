#!/bin/bash
# Setup script for Thai subtitle processing system
# This script helps set up the environment for the Thai subtitle processing system

set -e  # Exit on error

# Text colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Thai Subtitle Processing System - Environment Setup${NC}"
echo "=================================================="

# Detect OS
if [ -f /etc/os-release ]; then
    # freedesktop.org and systemd
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
elif type lsb_release >/dev/null 2>&1; then
    # linuxbase.org
    OS=$(lsb_release -si)
    VER=$(lsb_release -sr)
elif [ -f /etc/lsb-release ]; then
    # For some versions of Debian/Ubuntu without lsb_release command
    . /etc/lsb-release
    OS=$DISTRIB_ID
    VER=$DISTRIB_RELEASE
else
    # Fall back to uname, e.g. "Linux <version>", also works for BSD, etc.
    OS=$(uname -s)
    VER=$(uname -r)
fi

echo -e "Detected OS: ${YELLOW}$OS $VER${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}Warning: Not running as root. Some installation steps may fail.${NC}"
    echo "Consider running this script with sudo."
    read -p "Continue anyway? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Install FFmpeg
echo -e "\n${GREEN}Step 1: Installing FFmpeg${NC}"
echo "------------------------"

if command -v ffmpeg >/dev/null 2>&1; then
    echo -e "${GREEN}✓ FFmpeg is already installed${NC}"
    ffmpeg -version | head -n 1
else
    echo "Installing FFmpeg..."
    
    if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
        apt-get update
        apt-get install -y ffmpeg
    elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
        yum install -y epel-release
        yum install -y ffmpeg
    else
        echo -e "${RED}Unsupported OS for automatic FFmpeg installation.${NC}"
        echo "Please install FFmpeg manually from https://ffmpeg.org/download.html"
        exit 1
    fi
    
    if command -v ffmpeg >/dev/null 2>&1; then
        echo -e "${GREEN}✓ FFmpeg installed successfully${NC}"
        ffmpeg -version | head -n 1
    else
        echo -e "${RED}✗ Failed to install FFmpeg${NC}"
        exit 1
    fi
fi

# Install Thai fonts
echo -e "\n${GREEN}Step 2: Installing Thai fonts${NC}"
echo "------------------------"

if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
    if fc-list | grep -i thai >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Thai fonts are already installed${NC}"
        echo "Available Thai fonts:"
        fc-list | grep -i thai | cut -d: -f2 | sort | uniq
    else
        echo "Installing Thai fonts..."
        apt-get update
        apt-get install -y fonts-thai-tlwg
        
        if fc-list | grep -i thai >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Thai fonts installed successfully${NC}"
            echo "Available Thai fonts:"
            fc-list | grep -i thai | cut -d: -f2 | sort | uniq
        else
            echo -e "${RED}✗ Failed to install Thai fonts${NC}"
            exit 1
        fi
    fi
elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
    if fc-list | grep -i thai >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Thai fonts are already installed${NC}"
        echo "Available Thai fonts:"
        fc-list | grep -i thai | cut -d: -f2 | sort | uniq
    else
        echo "Installing Thai fonts..."
        yum install -y thai-scalable-fonts-common
        
        if fc-list | grep -i thai >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Thai fonts installed successfully${NC}"
            echo "Available Thai fonts:"
            fc-list | grep -i thai | cut -d: -f2 | sort | uniq
        else
            echo -e "${RED}✗ Failed to install Thai fonts${NC}"
            exit 1
        fi
    fi
else
    echo -e "${RED}Unsupported OS for automatic Thai font installation.${NC}"
    echo "Please install Thai fonts manually."
    exit 1
fi

# Set up environment variables
echo -e "\n${GREEN}Step 3: Setting up environment variables${NC}"
echo "------------------------"

ENV_FILE=".env"
echo "Creating $ENV_FILE file..."

cat > $ENV_FILE << EOL
# Thai Subtitle Processing System Environment Variables
# Generated on $(date)

# Cloud Storage Configuration
# Uncomment and set these variables for cloud storage integration

# Google Cloud Storage
#GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
#GCS_BUCKET_NAME=your-bucket-name

# AWS S3
#AWS_ACCESS_KEY_ID=your-access-key
#AWS_SECRET_ACCESS_KEY=your-secret-key
#AWS_REGION=your-region
#S3_BUCKET_NAME=your-bucket-name

# Temporary Directory
# Uncomment and set this to use a custom temp directory
#TEMP_DIR=/path/to/temp/directory

# Logging Configuration
LOG_LEVEL=INFO

# Queue Configuration
MAX_WORKERS=4
MAX_QUEUE_SIZE=100
MAX_RETRIES=3
EOL

echo -e "${GREEN}✓ Environment variables template created: $ENV_FILE${NC}"
echo "Please edit this file to set your actual values."

# Check temp directory
echo -e "\n${GREEN}Step 4: Checking temporary directory${NC}"
echo "------------------------"

TEMP_DIR=${TEMP_DIR:-/tmp}
echo "Using temporary directory: $TEMP_DIR"

if [ -d "$TEMP_DIR" ]; then
    if [ -w "$TEMP_DIR" ]; then
        echo -e "${GREEN}✓ Temporary directory is writable${NC}"
        
        # Check disk space
        SPACE=$(df -h "$TEMP_DIR" | awk 'NR==2 {print $4}')
        echo "Available space: $SPACE"
        
        # Create a test file
        TEST_FILE="$TEMP_DIR/test_$(date +%s).txt"
        if echo "test" > "$TEST_FILE" && rm "$TEST_FILE"; then
            echo -e "${GREEN}✓ Write test successful${NC}"
        else
            echo -e "${RED}✗ Failed to write to temporary directory${NC}"
        fi
    else
        echo -e "${RED}✗ Temporary directory is not writable${NC}"
        echo "Please ensure the application has write permissions to $TEMP_DIR"
    fi
else
    echo -e "${RED}✗ Temporary directory does not exist${NC}"
    echo "Creating directory: $TEMP_DIR"
    mkdir -p "$TEMP_DIR"
    if [ -d "$TEMP_DIR" ]; then
        echo -e "${GREEN}✓ Temporary directory created${NC}"
    else
        echo -e "${RED}✗ Failed to create temporary directory${NC}"
    fi
fi

# Configure logging
echo -e "\n${GREEN}Step 5: Configuring logging${NC}"
echo "------------------------"

LOG_DIR="logs"
if [ ! -d "$LOG_DIR" ]; then
    echo "Creating log directory: $LOG_DIR"
    mkdir -p "$LOG_DIR"
fi

if [ -d "$LOG_DIR" ] && [ -w "$LOG_DIR" ]; then
    echo -e "${GREEN}✓ Log directory is ready${NC}"
else
    echo -e "${RED}✗ Log directory is not writable${NC}"
    echo "Please ensure the application has write permissions to $LOG_DIR"
fi

# Summary
echo -e "\n${GREEN}Setup Complete!${NC}"
echo "=================================================="
echo -e "FFmpeg: ${GREEN}✓${NC}"
echo -e "Thai Fonts: ${GREEN}✓${NC}"
echo -e "Environment Variables: ${YELLOW}⚠ Review $ENV_FILE${NC}"
echo -e "Temporary Directory: ${GREEN}✓ $TEMP_DIR${NC}"
echo -e "Logging: ${GREEN}✓ $LOG_DIR${NC}"
echo
echo "Next steps:"
echo "1. Edit the $ENV_FILE file to set your actual environment variables"
echo "2. Install Python dependencies: pip install -r requirements.txt"
echo "3. Run the application!"
echo
echo -e "${GREEN}Thank you for using the Thai Subtitle Processing System!${NC}"
