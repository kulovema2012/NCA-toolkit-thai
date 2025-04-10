import uuid
import requests
import os
import time
import logging
from urllib.parse import urlparse, parse_qs

# Set up logger
logger = logging.getLogger(__name__)

# Default storage path
STORAGE_PATH = "/tmp"

def download_file(url, target_path):
    """
    Download a file from a URL to a specific target path.
    
    Args:
        url: The URL to download from
        target_path: The full path where the file should be saved or a directory
                    where the file should be saved with its original name
    
    Returns:
        The path to the downloaded file
    """
    logger.info(f"Downloading file from {url}")
    
    # Check if target_path is a directory
    if os.path.isdir(target_path):
        # Extract filename from URL
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        
        # If no filename could be extracted, generate a random one
        if not filename:
            ext = ".mp4"  # Default extension
            filename = f"{uuid.uuid4()}{ext}"
            
        # Combine directory and filename
        full_path = os.path.join(target_path, filename)
        logger.info(f"Target path is a directory, saving file as {full_path}")
    else:
        # Use the provided path as is
        full_path = target_path
        logger.info(f"Saving file to specified path: {full_path}")
    
    # Ensure the target directory exists
    target_dir = os.path.dirname(full_path)
    if not os.path.exists(target_dir):
        logger.info(f"Creating directory: {target_dir}")
        os.makedirs(target_dir, exist_ok=True)
    
    # Download the file
    try:
        logger.info(f"Starting download from {url}")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        file_size = int(response.headers.get('content-length', 0))
        logger.info(f"File size: {file_size} bytes")
        
        with open(full_path, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                
                # Log progress for large files
                if file_size > 1000000 and downloaded % 10000000 == 0:  # Log every 10MB for files > 1MB
                    logger.info(f"Downloaded {downloaded/1000000:.1f}MB of {file_size/1000000:.1f}MB ({downloaded*100/file_size:.1f}%)")
        
        logger.info(f"Download completed: {full_path}")
        return full_path
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        raise

def delete_old_files():
    """
    Delete files older than 1 hour from the storage directory
    """
    logger.info("Checking for old files to delete")
    now = time.time()
    deleted_count = 0
    
    try:
        for filename in os.listdir(STORAGE_PATH):
            file_path = os.path.join(STORAGE_PATH, filename)
            if os.path.isfile(file_path) and os.stat(file_path).st_mtime < now - 3600:
                logger.info(f"Deleting old file: {file_path}")
                os.remove(file_path)
                deleted_count += 1
        
        logger.info(f"Deleted {deleted_count} old files")
    except Exception as e:
        logger.error(f"Error deleting old files: {str(e)}")
