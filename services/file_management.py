import os
import uuid
import requests
from urllib.parse import urlparse, parse_qs

def download_file(url, target_path):
    """
    Download a file from a URL to a specific target path.
    
    Args:
        url: The URL to download from
        target_path: The full path where the file should be saved
    
    Returns:
        The path to the downloaded file
    """
    # Ensure the target directory exists
    target_dir = os.path.dirname(target_path)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
    
    # Download the file
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    with open(target_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    return target_path


def delete_old_files():
    now = time.time()
    for filename in os.listdir(STORAGE_PATH):
        file_path = os.path.join(STORAGE_PATH, filename)
        if os.path.isfile(file_path) and os.stat(file_path).st_mtime < now - 3600:
            os.remove(file_path)
