import os
import json
import requests
import logging
from datetime import timedelta
import srt
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

def transcribe_with_openai(media_url, language="th", response_format="verbose_json", job_id=None):
    """
    Transcribe media using OpenAI's Whisper API.
    
    Args:
        media_url: URL to the media file
        language: Language code (e.g., "th" for Thai)
        response_format: Format of the response from OpenAI API
        job_id: Unique identifier for the job
        
    Returns:
        tuple: (text_file_path, srt_file_path, segments_file_path)
    """
    # Get API key securely
    api_key = get_openai_api_key()
    if not api_key:
        raise ValueError("OpenAI API key not available. Please set OPENAI_API_KEY environment variable or configure Secret Manager.")
    
    logger.info(f"Starting OpenAI Whisper transcription for media URL: {media_url}")
    
    # Download the media file
    input_filename = download_file(media_url, os.path.join(STORAGE_PATH, 'input_media'))
    logger.info(f"Downloaded media to local file: {input_filename}")
    
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
        with open(text_file, "w", encoding="utf-8") as f:
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
        with open(srt_file, "w", encoding="utf-8") as f:
            f.write(srt.compose(srt_content))
        logger.info(f"Created SRT file: {srt_file}")
        
        # Create segments file
        segments_file = os.path.join(STORAGE_PATH, f"{job_id}.json")
        with open(segments_file, "w", encoding="utf-8") as f:
            json.dump(result["segments"], f, ensure_ascii=False, indent=2)
        logger.info(f"Created segments file: {segments_file}")
        
        # Clean up
        os.remove(input_filename)
        logger.info(f"Removed local file: {input_filename}")
        
        return text_file, srt_file, segments_file
        
    except Exception as e:
        logger.error(f"OpenAI transcription failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Clean up
        if os.path.exists(input_filename):
            os.remove(input_filename)
            logger.info(f"Removed local file: {input_filename}")
        
        return None, None, None
