import os
import subprocess
import json
import logging
import uuid
import glob
from services.file_management import download_file

# Set up logger
logger = logging.getLogger(__name__)

# Define storage path without trailing slash
STORAGE_PATH = "/tmp"

def get_extension_from_format(format_name):
    # Mapping of common format names to file extensions
    format_to_extension = {
        'mp4': 'mp4',
        'mov': 'mov',
        'avi': 'avi',
        'mkv': 'mkv',
        'webm': 'webm',
        'gif': 'gif',
        'apng': 'apng',
        'jpg': 'jpg',
        'jpeg': 'jpg',
        'png': 'png',
        'image2': 'png',  # Assume png for image2 format
        'rawvideo': 'raw',
        'mp3': 'mp3',
        'wav': 'wav',
        'aac': 'aac',
        'flac': 'flac',
        'ogg': 'ogg'
    }
    return format_to_extension.get(format_name.lower(), 'mp4')  # Default to mp4 if unknown

def get_metadata(filename, metadata_requests, job_id):
    metadata = {}
    if metadata_requests.get('thumbnail'):
        thumbnail_filename = f"{os.path.splitext(filename)[0]}_thumbnail.jpg"
        thumbnail_command = [
            'ffmpeg',
            '-i', filename,
            '-vf', 'select=eq(n\,0)',
            '-vframes', '1',
            thumbnail_filename
        ]
        try:
            subprocess.run(thumbnail_command, check=True, capture_output=True, text=True)
            if os.path.exists(thumbnail_filename):
                metadata['thumbnail'] = thumbnail_filename  # Return local path instead of URL
        except subprocess.CalledProcessError as e:
            print(f"Thumbnail generation failed: {e.stderr}")

    if metadata_requests.get('filesize'):
        metadata['filesize'] = os.path.getsize(filename)

    if metadata_requests.get('encoder') or metadata_requests.get('duration') or metadata_requests.get('bitrate'):
        ffprobe_command = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            filename
        ]
        result = subprocess.run(ffprobe_command, capture_output=True, text=True)
        probe_data = json.loads(result.stdout)
        
        if metadata_requests.get('duration'):
            metadata['duration'] = float(probe_data['format']['duration'])
        if metadata_requests.get('bitrate'):
            metadata['bitrate'] = int(probe_data['format']['bit_rate'])
        
        if metadata_requests.get('encoder'):
            metadata['encoder'] = {}
            for stream in probe_data['streams']:
                if stream['codec_type'] == 'video':
                    metadata['encoder']['video'] = stream.get('codec_name', 'unknown')
                elif stream['codec_type'] == 'audio':
                    metadata['encoder']['audio'] = stream.get('codec_name', 'unknown')

    return metadata

def find_thai_font():
    """
    Find an available Thai font on the system.
    Returns the path to the font file if found, or None if not found.
    """
    # Common paths for Thai fonts
    possible_paths = [
        # Thai-specific fonts
        "/usr/share/fonts/truetype/thai-tlwg/Sarabun*.ttf",
        "/usr/share/fonts/truetype/tlwg/Sarabun*.ttf",
        "/usr/share/fonts/TTF/Sarabun*.ttf",
        "/usr/share/fonts/thai-tlwg/Sarabun*.ttf",
        # General font directories
        "/usr/share/fonts/truetype/*/Sarabun*.ttf",
        "/usr/share/fonts/*/Sarabun*.ttf",
        # Noto Sans Thai (alternative)
        "/usr/share/fonts/truetype/noto/NotoSansThai*.ttf",
        "/usr/share/fonts/noto-cjk/NotoSansThai*.ttf",
        # Fallback to any Thai font
        "/usr/share/fonts/**/Thai*.ttf",
        "/usr/share/fonts/**/*Thai*.ttf"
    ]
    
    # Try to find a Thai font
    for path_pattern in possible_paths:
        try:
            matches = glob.glob(path_pattern, recursive=True)
            if matches:
                logger.info(f"Found Thai font: {matches[0]}")
                return matches[0]
        except Exception as e:
            logger.warning(f"Error checking font path {path_pattern}: {str(e)}")
    
    # If glob doesn't work, try using find command
    try:
        result = subprocess.run(
            ["find", "/usr/share/fonts", "-name", "*Thai*", "-o", "-name", "*Sarabun*", "-type", "f"],
            capture_output=True, text=True, check=False
        )
        if result.stdout.strip():
            font_path = result.stdout.strip().split("\n")[0]
            logger.info(f"Found Thai font using find command: {font_path}")
            return font_path
    except Exception as e:
        logger.warning(f"Error using find command to locate Thai font: {str(e)}")
    
    # Last resort - check if we can list any fonts
    try:
        result = subprocess.run(["fc-list"], capture_output=True, text=True, check=False)
        if "Thai" in result.stdout or "Sarabun" in result.stdout:
            for line in result.stdout.split("\n"):
                if "Thai" in line or "Sarabun" in line:
                    font_path = line.split(":")[0]
                    logger.info(f"Found Thai font using fc-list: {font_path}")
                    return font_path
    except Exception as e:
        logger.warning(f"Error using fc-list to locate Thai font: {str(e)}")
    
    logger.error("No Thai font found on the system")
    return None

def process_ffmpeg_compose(data, job_id):
    output_filenames = []
    
    logger.info(f"Job {job_id}: Starting FFmpeg compose process")
    logger.info(f"Job {job_id}: Using storage path: {STORAGE_PATH}")
    
    # Check for Thai font
    thai_font_path = find_thai_font()
    if thai_font_path:
        logger.info(f"Job {job_id}: Found Thai font at {thai_font_path}")
    else:
        logger.warning(f"Job {job_id}: No Thai font found, text rendering may be affected")
    
    # Create temp directory if it doesn't exist
    os.makedirs(STORAGE_PATH, exist_ok=True)
    
    # Build FFmpeg command
    command = ["ffmpeg"]
    
    # Add global options
    for option in data.get("global_options", []):
        command.append(option["option"])
        if "argument" in option and option["argument"] is not None:
            command.append(str(option["argument"]))
    
    # Add inputs
    input_paths = []
    for i, input_data in enumerate(data["inputs"]):
        logger.info(f"Job {job_id}: Processing input {i+1}/{len(data['inputs'])}: {input_data['file_url']}")
        
        if "options" in input_data:
            for option in input_data["options"]:
                command.append(option["option"])
                if "argument" in option and option["argument"] is not None:
                    command.append(str(option["argument"]))
        
        # Generate a unique filename for the downloaded file
        file_ext = os.path.splitext(os.path.basename(input_data["file_url"]))[1]
        if not file_ext:
            file_ext = ".mp4"  # Default extension if none is found
        
        unique_filename = f"{job_id}_input_{i}{file_ext}"
        input_file_path = os.path.join(STORAGE_PATH, unique_filename)
        
        logger.info(f"Job {job_id}: Downloading input file to {input_file_path}")
        try:
            # Download the file to the specific path
            download_file(input_data["file_url"], input_file_path)
            logger.info(f"Job {job_id}: Successfully downloaded input file to {input_file_path}")
            
            # Verify the file exists
            if not os.path.exists(input_file_path):
                raise FileNotFoundError(f"Downloaded file not found at {input_file_path}")
            
            input_paths.append(input_file_path)
            command.extend(["-i", input_file_path])
        except Exception as e:
            logger.error(f"Job {job_id}: Error downloading input file: {str(e)}")
            raise
    
    # Add filters
    if data.get("filters"):
        filter_complex = ";".join(filter_obj["filter"] for filter_obj in data["filters"])
        
        # Replace font path if Thai font was found
        if thai_font_path and "fontfile=" in filter_complex:
            # Extract the original fontfile path
            original_paths = []
            import re
            for match in re.finditer(r'fontfile=([^:]+)', filter_complex):
                original_paths.append(match.group(1))
            
            # Replace with the found Thai font path if it contains Thai or Sarabun
            for path in original_paths:
                if "Thai" in path or "Sarabun" in path or "thai" in path:
                    filter_complex = filter_complex.replace(f"fontfile={path}", f"fontfile={thai_font_path}")
                    logger.info(f"Job {job_id}: Replaced font path {path} with {thai_font_path}")
        
        logger.info(f"Job {job_id}: Using filter_complex: {filter_complex}")
        command.extend(["-filter_complex", filter_complex])
    
    # Add outputs
    for i, output in enumerate(data["outputs"]):
        format_name = None
        for option in output["options"]:
            if option["option"] == "-f":
                format_name = option.get("argument")
                break
        
        extension = get_extension_from_format(format_name) if format_name else 'mp4'
        output_filename = os.path.join(STORAGE_PATH, f"{job_id}_output_{i}.{extension}")
        logger.info(f"Job {job_id}: Setting output {i+1} to {output_filename}")
        output_filenames.append(output_filename)
        
        for option in output["options"]:
            command.append(option["option"])
            if "argument" in option and option["argument"] is not None:
                command.append(str(option["argument"]))
        command.append(output_filename)
    
    # Execute FFmpeg command
    logger.info(f"Job {job_id}: Executing FFmpeg command: {' '.join(command)}")
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info(f"Job {job_id}: FFmpeg command completed successfully")
        logger.debug(f"Job {job_id}: FFmpeg stdout: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Job {job_id}: FFmpeg command failed: {e.stderr}")
        raise Exception(f"FFmpeg command failed: {e.stderr}")
    
    # Clean up input files
    logger.info(f"Job {job_id}: Cleaning up input files")
    for input_path in input_paths:
        if os.path.exists(input_path):
            try:
                os.remove(input_path)
                logger.info(f"Job {job_id}: Removed input file: {input_path}")
            except Exception as e:
                logger.warning(f"Job {job_id}: Failed to remove input file {input_path}: {str(e)}")
    
    # Get metadata if requested
    metadata = []
    if data.get("metadata"):
        logger.info(f"Job {job_id}: Collecting metadata for outputs")
        for i, output_filename in enumerate(output_filenames):
            logger.info(f"Job {job_id}: Getting metadata for output {i+1}: {output_filename}")
            metadata.append(get_metadata(output_filename, data["metadata"], job_id))
    
    logger.info(f"Job {job_id}: FFmpeg compose process completed successfully")
    return output_filenames, metadata