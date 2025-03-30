import os
import json
import requests
import logging
from datetime import timedelta
import srt
from urllib.parse import urlparse
from services.file_management import download_file

# Set up logging
logger = logging.getLogger(__name__)

# Set the default local storage directory
STORAGE_PATH = "/tmp/"

# Function to get OpenAI API key securely
def get_openai_api_key():
    """
    Get the OpenAI API key from environment variable or Google Cloud Secret Manager.
    """
    # First check if API key is in environment variables
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return api_key
    
    # If not in environment, try to get from Google Cloud Secret Manager
    try:
        from google.cloud import secretmanager
        
        # Create the Secret Manager client
        client = secretmanager.SecretManagerServiceClient()
        
        # Build the resource name of the secret
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT environment variable not set")
            return None
            
        name = f"projects/{project_id}/secrets/openai-api-key/versions/latest"
        
        # Access the secret
        response = client.access_secret_version(request={"name": name})
        
        # Return the decoded payload
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.error(f"Error accessing Secret Manager: {str(e)}")
        return None

def transcribe_with_openai(media_url, language="th", response_format="verbose_json", job_id=None, preserve_media=False):
    """
    Transcribe media using OpenAI's Whisper API.
    
    Args:
        media_url: URL or local file path to the media file
        language: Language code (e.g., "th" for Thai)
        response_format: Format of the response from OpenAI API
        job_id: Unique identifier for the job
        preserve_media: If True, don't delete the media file after transcription
        
    Returns:
        tuple: (text_file_path, srt_file_path, segments_file_path, media_file_path)
    """
    # Get API key securely
    api_key = get_openai_api_key()
    if not api_key:
        raise ValueError("OpenAI API key not available. Please set OPENAI_API_KEY environment variable or configure Secret Manager.")
    
    logger.info(f"Starting OpenAI Whisper transcription for media: {media_url}")
    
    # Handle both URLs and local file paths
    if media_url.startswith(('http://', 'https://')):
        # It's a URL, download the file
        # Extract the file extension from the URL
        parsed_url = urlparse(media_url)
        file_path = parsed_url.path
        file_extension = os.path.splitext(file_path)[1]
        
        # If no extension or unrecognized, default to .mp4
        if not file_extension or file_extension.lower() not in ['.flac', '.m4a', '.mp3', '.mp4', '.mpeg', '.mpga', '.oga', '.ogg', '.wav', '.webm']:
            file_extension = '.mp4'
            
        # Create a filename with the proper extension
        input_filename = os.path.join(STORAGE_PATH, f'input_media{file_extension}')
        
        # Download the file
        input_filename = download_file(media_url, input_filename)
        logger.info(f"Downloaded media to local file: {input_filename}")
    else:
        # It's already a local file path
        input_filename = media_url
        logger.info(f"Using local file: {input_filename}")
    
    try:
        # Prepare the API request
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        files = {
            "file": open(input_filename, "rb"),
            "model": (None, "whisper-1"),
            "response_format": (None, response_format),
        }
        
        # Add language if specified
        if language:
            files["language"] = (None, language)
        
        # Make the API request
        logger.info(f"Sending request to OpenAI Whisper API with language: {language}")
        response = requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files)
        
        # Check if the request was successful
        if response.status_code != 200:
            logger.error(f"OpenAI API request failed with status code {response.status_code}: {response.text}")
            raise Exception(f"OpenAI API request failed: {response.text}")
        
        # Parse the response
        result = response.json()
        logger.info("Successfully received response from OpenAI Whisper API")
        
        # Generate output files
        if not job_id:
            job_id = os.path.basename(input_filename).split('.')[0]
        
        # Create text file
        text_file = os.path.join(STORAGE_PATH, f"{job_id}.txt")
        with open(text_file, "w", encoding="utf-8-sig") as f:
            f.write(result["text"])
        logger.info(f"Created text file: {text_file}")
        
        # Create SRT file
        srt_file = os.path.join(STORAGE_PATH, f"{job_id}.srt")
        
        # Generate SRT content from segments
        srt_content = []
        for i, segment in enumerate(result["segments"]):
            start_time = timedelta(seconds=segment["start"])
            end_time = timedelta(seconds=segment["end"])
            
            # Create SRT subtitle entry
            srt_content.append(
                srt.Subtitle(
                    index=i+1,
                    start=start_time,
                    end=end_time,
                    content=segment["text"]
                )
            )
        
        # Write the SRT file
        with open(srt_file, "w", encoding="utf-8-sig") as f:
            f.write(srt.compose(srt_content))
        logger.info(f"Created SRT file: {srt_file}")
        
        # Create segments file
        segments_file = os.path.join(STORAGE_PATH, f"{job_id}.json")
        with open(segments_file, "w", encoding="utf-8") as f:
            json.dump(result["segments"], f, ensure_ascii=False, indent=2)
        logger.info(f"Created segments file: {segments_file}")
        
        # Clean up only if preserve_media is False
        if not preserve_media:
            if not media_url.startswith(('http://', 'https://')):
                os.remove(input_filename)
                logger.info(f"Removed local file: {input_filename}")
        else:
            logger.info(f"Preserving media file for further processing: {input_filename}")
        
        # Return the input_filename as well so it can be used for further processing
        return text_file, srt_file, segments_file, input_filename
        
    except Exception as e:
        logger.error(f"OpenAI transcription failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Clean up only if preserve_media is False
        if not preserve_media:
            if media_url.startswith(('http://', 'https://')) and os.path.exists(input_filename):
                os.remove(input_filename)
                logger.info(f"Removed local file: {input_filename}")
        
        # Raise a more specific exception instead of returning None values
        raise ValueError(f"OpenAI transcription failed: {str(e)}")
