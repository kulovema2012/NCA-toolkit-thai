#!/usr/bin/env python3
"""
Dependency checker and installer for Thai subtitle processing system.
This script checks for required system dependencies and helps with installation.
"""

import os
import sys
import subprocess
import platform
import shutil
import logging
from pathlib import Path
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Required system dependencies
DEPENDENCIES = {
    "ffmpeg": {
        "check_cmd": "ffmpeg -version",
        "install_cmd": {
            "debian": "apt-get update && apt-get install -y ffmpeg",
            "rhel": "yum install -y ffmpeg",
            "windows": "echo FFmpeg must be installed manually on Windows. Download from https://ffmpeg.org/download.html"
        }
    },
    "thai_fonts": {
        "check_cmd": {
            "debian": "fc-list | grep -i thai",
            "rhel": "fc-list | grep -i thai",
            "windows": "dir C:\\Windows\\Fonts | findstr /i thai"
        },
        "install_cmd": {
            "debian": "apt-get update && apt-get install -y fonts-thai-tlwg",
            "rhel": "yum install -y thai-scalable-fonts-common",
            "windows": "echo Thai fonts must be installed manually on Windows. Download from https://fonts.google.com/noto/specimen/Noto+Sans+Thai"
        }
    }
}

# Environment variables to check
ENV_VARS = [
    "GOOGLE_APPLICATION_CREDENTIALS",  # For Google Cloud Storage
    "AWS_ACCESS_KEY_ID",               # For AWS S3
    "AWS_SECRET_ACCESS_KEY",           # For AWS S3
    "TEMP_DIR",                        # Custom temp directory
    "LOG_LEVEL"                        # Logging level
]

def get_os_family():
    """Determine the OS family (debian, rhel, or windows)."""
    system = platform.system().lower()
    
    if system == "windows":
        return "windows"
    
    if system == "linux":
        # Check for Debian/Ubuntu
        if os.path.exists("/etc/debian_version"):
            return "debian"
        # Check for RHEL/CentOS
        elif os.path.exists("/etc/redhat-release"):
            return "rhel"
    
    # Default to debian for unknown Linux
    return "debian"

def run_command(command):
    """Run a shell command and return the output and success status."""
    try:
        if platform.system().lower() == "windows":
            # Use shell=True on Windows
            result = subprocess.run(command, shell=True, check=False, 
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                   text=True)
        else:
            # Split command into args on Unix
            result = subprocess.run(command.split(), check=False, 
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                   text=True)
        
        return result.stdout, result.returncode == 0
    except Exception as e:
        logger.error(f"Error running command '{command}': {str(e)}")
        return str(e), False

def check_dependency(name, dependency, os_family):
    """Check if a dependency is installed."""
    logger.info(f"Checking for {name}...")
    
    # Get the appropriate check command
    check_cmd = dependency["check_cmd"]
    if isinstance(check_cmd, dict):
        check_cmd = check_cmd.get(os_family, "echo Not supported on this OS")
    
    # Run the check command
    output, success = run_command(check_cmd)
    
    if success:
        logger.info(f"✅ {name} is installed")
        logger.debug(output)
        return True
    else:
        logger.warning(f"❌ {name} is not installed or not working properly")
        logger.debug(output)
        return False

def install_dependency(name, dependency, os_family):
    """Attempt to install a dependency."""
    logger.info(f"Installing {name}...")
    
    # Get the appropriate install command
    install_cmd = dependency["install_cmd"].get(os_family, "echo Not supported on this OS")
    
    # Check if we need sudo (not on Windows)
    if os_family != "windows" and os.geteuid() != 0:
        logger.warning(f"Need root privileges to install {name}")
        print(f"\nTo install {name}, run the following command with sudo:")
        print(f"sudo {install_cmd}")
        return False
    
    # Run the install command
    output, success = run_command(install_cmd)
    
    if success:
        logger.info(f"✅ {name} installed successfully")
        return True
    else:
        logger.error(f"❌ Failed to install {name}")
        logger.error(output)
        return False

def check_env_vars():
    """Check for required environment variables."""
    logger.info("Checking environment variables...")
    
    missing_vars = []
    for var in ENV_VARS:
        if var not in os.environ:
            missing_vars.append(var)
            logger.warning(f"❌ Environment variable {var} is not set")
        else:
            logger.info(f"✅ Environment variable {var} is set")
    
    return missing_vars

def check_temp_dir():
    """Check if temp directory has sufficient permissions and space."""
    logger.info("Checking temp directory...")
    
    # Get temp directory
    temp_dir = os.environ.get("TEMP_DIR", tempfile.gettempdir())
    
    # Check if directory exists
    if not os.path.exists(temp_dir):
        logger.warning(f"❌ Temp directory {temp_dir} does not exist")
        return False
    
    # Check permissions
    try:
        test_file = os.path.join(temp_dir, f"test_{os.getpid()}.txt")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        logger.info(f"✅ Temp directory {temp_dir} has write permissions")
    except Exception as e:
        logger.error(f"❌ Temp directory {temp_dir} has permission issues: {str(e)}")
        return False
    
    # Check disk space (need at least 1GB free)
    try:
        if platform.system().lower() == "windows":
            # Windows-specific
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(temp_dir), None, None, ctypes.pointer(free_bytes))
            free_gb = free_bytes.value / (1024**3)
        else:
            # Unix-like
            stat = os.statvfs(temp_dir)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        
        if free_gb < 1:
            logger.warning(f"❌ Temp directory {temp_dir} has less than 1GB free space ({free_gb:.2f}GB)")
            return False
        else:
            logger.info(f"✅ Temp directory {temp_dir} has {free_gb:.2f}GB free space")
            return True
    except Exception as e:
        logger.error(f"❌ Could not check disk space in {temp_dir}: {str(e)}")
        return False

def check_python_dependencies():
    """Check if required Python packages are installed."""
    logger.info("Checking Python dependencies...")
    
    try:
        # Check for required packages
        import ffmpeg
        logger.info("✅ ffmpeg-python is installed")
    except ImportError:
        logger.warning("❌ ffmpeg-python is not installed")
    
    try:
        import pythainlp
        logger.info(f"✅ pythainlp is installed (version {pythainlp.__version__})")
    except ImportError:
        logger.warning("❌ pythainlp is not installed")
    
    # Check if we can import our own modules
    try:
        sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        from services.v1.video import caption_video
        logger.info("✅ caption_video module can be imported")
    except ImportError as e:
        logger.warning(f"❌ Cannot import caption_video module: {str(e)}")

def main():
    """Main function to check and install dependencies."""
    logger.info("Starting dependency check for Thai subtitle processing system")
    
    # Determine OS family
    os_family = get_os_family()
    logger.info(f"Detected OS family: {os_family}")
    
    # Check system dependencies
    missing_deps = []
    for name, dependency in DEPENDENCIES.items():
        if not check_dependency(name, dependency, os_family):
            missing_deps.append(name)
    
    # Offer to install missing dependencies
    if missing_deps:
        print("\nThe following dependencies are missing:")
        for dep in missing_deps:
            print(f"- {dep}")
        
        if os_family != "windows" and os.geteuid() != 0:
            print("\nYou need root privileges to install system dependencies.")
            print("Please run this script with sudo or install the dependencies manually.")
        else:
            choice = input("\nDo you want to install the missing dependencies? (y/n): ")
            if choice.lower() == 'y':
                for dep in missing_deps:
                    install_dependency(dep, DEPENDENCIES[dep], os_family)
    
    # Check environment variables
    missing_vars = check_env_vars()
    if missing_vars:
        print("\nThe following environment variables are not set:")
        for var in missing_vars:
            print(f"- {var}")
        print("\nConsider setting these variables for proper functionality.")
    
    # Check temp directory
    check_temp_dir()
    
    # Check Python dependencies
    check_python_dependencies()
    
    logger.info("Dependency check completed")

if __name__ == "__main__":
    main()
