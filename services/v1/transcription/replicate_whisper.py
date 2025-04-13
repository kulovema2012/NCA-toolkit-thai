import os
import json
import logging
import tempfile
import subprocess
import requests
import time
import uuid
from typing import Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Updated supported languages list - Replicate Whisper uses full language names
SUPPORTED_LANGUAGES = ["english", "spanish", "french", "german", "italian", "portuguese", "dutch", "russian", "chinese", "japanese", "korean", "arabic", "hebrew", "thai"]

# Language code to full name mapping
LANGUAGE_CODE_MAP = {
    "en": "english",
    "es": "spanish",
    "fr": "french",
    "de": "german",
    "it": "italian",
    "pt": "portuguese",
    "nl": "dutch",
    "ru": "russian",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
    "ar": "arabic",
    "he": "hebrew",
    "th": "thai"
}

def upload_to_cloud_storage(file_path):
    """
    Upload a file to cloud storage and return a publicly accessible URL.
    
    Args:
        file_path (str): Path to the local file
        
    Returns:
        str: Publicly accessible URL to the uploaded file
    """
    try:
        # Check if the cloud storage module is available
        from services.cloud_storage import upload_to_cloud_storage as cloud_upload
        
        # Generate a unique path for the file in cloud storage
        file_name = os.path.basename(file_path)
        unique_id = str(uuid.uuid4())
        cloud_path = f"temp_audio/{unique_id}_{file_name}"
        
        # Upload the file to cloud storage
        logger.info(f"Uploading file to cloud storage: {file_path} -> {cloud_path}")
        cloud_url = cloud_upload(file_path, cloud_path)
        
        logger.info(f"File uploaded successfully: {cloud_url}")
        return cloud_url
    except ImportError:
        logger.error("Cloud storage module not available. Cannot upload local file.")
        raise ValueError("Cloud storage module not available. Cannot process local audio files with Replicate Whisper.")
    except Exception as e:
        logger.error(f"Error uploading file to cloud storage: {str(e)}")
        raise ValueError(f"Error uploading file to cloud storage: {str(e)}")

def transcribe_with_replicate(audio_url: str, language: str = "th", batch_size: int = 64) -> List[Dict]:
    """
    Transcribe audio using Replicate Whisper API.
    
    Args:
        audio_url (str): URL or local path to the audio file
        language (str, optional): Language code. Defaults to "th".
        batch_size (int, optional): Batch size for processing. Defaults to 64.
        
    Returns:
        list: List of transcription segments with start and end times
    """
    logger.info(f"Starting transcription with Replicate Whisper: {audio_url}")
    
    # Ensure audio_url is provided
    if not audio_url:
        raise ValueError("Audio URL or path is required")
    
    # Check if audio_url is a local file path
    if os.path.exists(audio_url) and os.path.isfile(audio_url):
        logger.info(f"Local file detected: {audio_url}. Uploading to cloud storage...")
        audio_url = upload_to_cloud_storage(audio_url)
        logger.info(f"Using cloud URL for transcription: {audio_url}")
    
    # Validate the audio URL format
    if not audio_url.startswith(('http://', 'https://')):
        raise ValueError(f"Invalid audio URL format: {audio_url}. Must start with http:// or https://")
    
    # Check if the URL is accessible
    try:
        head_response = requests.head(audio_url, timeout=10)
        head_response.raise_for_status()
        logger.info(f"Audio URL is accessible: {audio_url}")
    except Exception as e:
        logger.error(f"Audio URL is not accessible: {audio_url}. Error: {str(e)}")
        raise ValueError(f"Audio URL is not accessible: {str(e)}")
    
    try:
        # Try multiple possible environment variable names for the Replicate API token
        api_token_vars = ["REPLICATE_API_TOKEN", "REPLICATE_API_KEY", "REPLICATE_TOKEN"]
        api_key = None
        
        # Check each possible environment variable
        for var_name in api_token_vars:
            api_key = os.environ.get(var_name)
            if api_key:
                logger.info(f"Found Replicate API token in {var_name}")
                break
        
        if not api_key:
            logger.error("Replicate API token not found in environment variables")
            raise ValueError("Replicate API token not found. Please set REPLICATE_API_TOKEN environment variable.")
        
        # Map language code to full language name if needed
        if language in LANGUAGE_CODE_MAP:
            language_name = LANGUAGE_CODE_MAP[language]
        else:
            # If not in map, use as is (might be full name already)
            language_name = language
        
        logger.info(f"Using language: {language_name}")
        
        # Prepare the API request to Replicate
        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json"
        }
        
        # Define the model and version
        model = "openai/whisper"
        version = "e39e354773466b955265e969568deb7da217804d8e771ea8c9cd0cef6591f8bc"
        
        # Prepare the API endpoint
        api_url = "https://api.replicate.com/v1/predictions"
        
        # Prepare the request payload
        payload = {
            "version": version,
            "input": {
                "audio": audio_url,
                "model": "large-v2",
                "transcription": "srt",
                "translate": False,
                "language": language_name,
                "temperature": 0,
                "patience": 1,
                "suppress_tokens": "-1",
                "condition_on_previous_text": True,
                "temperature_increment_on_fallback": 0.2,
                "compression_ratio_threshold": 2.4,
                "logprob_threshold": -1.0,
                "no_speech_threshold": 0.6
            }
        }
        
        logger.info(f"Sending request to Replicate API: {json.dumps(payload, indent=2)}")
        
        # Send the request to start the transcription
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        prediction = response.json()
        
        logger.info(f"Prediction started: {prediction['id']}")
        
        # Poll for the prediction result
        prediction_id = prediction["id"]
        prediction_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
        
        # Initialize polling variables
        max_attempts = 60  # Maximum number of polling attempts
        attempt = 0
        poll_interval = 5  # Initial polling interval in seconds
        
        while attempt < max_attempts:
            attempt += 1
            
            # Get the prediction status
            response = requests.get(prediction_url, headers=headers)
            response.raise_for_status()
            prediction = response.json()
            
            # Check if the prediction is complete
            if prediction["status"] == "succeeded":
                logger.info(f"Prediction succeeded after {attempt} attempts")
                break
            elif prediction["status"] == "failed":
                logger.error(f"Prediction failed: {prediction.get('error', 'Unknown error')}")
                raise ValueError(f"Replicate prediction failed: {prediction.get('error', 'Unknown error')}")
            
            # If still processing, wait and try again
            logger.info(f"Prediction status: {prediction['status']}. Polling again in {poll_interval} seconds...")
            time.sleep(poll_interval)
            
            # Increase polling interval for later attempts (up to 20 seconds)
            poll_interval = min(poll_interval * 1.5, 20)
        
        # Check if we exceeded the maximum number of attempts
        if attempt >= max_attempts:
            logger.error("Exceeded maximum polling attempts")
            raise ValueError("Exceeded maximum polling attempts for Replicate prediction")
        
        # Extract the SRT content from the prediction output
        srt_content = prediction["output"]
        
        if not srt_content:
            logger.error("No transcription output received from Replicate")
            raise ValueError("No transcription output received from Replicate")
        
        logger.info(f"Received SRT content from Replicate: {len(srt_content)} characters")
        
        # Parse the SRT content into segments
        segments = parse_srt_content(srt_content)
        
        logger.info(f"Parsed {len(segments)} segments from SRT content")
        
        return segments
    
    except Exception as e:
        logger.error(f"Error in Replicate Whisper transcription: {str(e)}")
        raise ValueError(f"Error in Replicate Whisper transcription: {str(e)}")

def parse_srt_content(srt_content):
    """
    Parse SRT content into a list of segments.
    
    Args:
        srt_content (str): SRT content as a string
        
    Returns:
        list: List of segments with start and end times
    """
    segments = []
    
    # Split the SRT content into blocks
    blocks = srt_content.strip().split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        
        # Skip invalid blocks
        if len(lines) < 3:
            continue
        
        # Parse the timestamp line
        timestamp_line = lines[1]
        try:
            timestamps = timestamp_line.split(' --> ')
            start_time = parse_timestamp(timestamps[0])
            end_time = parse_timestamp(timestamps[1])
            
            # Join the text lines
            text = ' '.join(lines[2:])
            
            # Add the segment
            segments.append({
                'start': start_time,
                'end': end_time,
                'text': text
            })
        except Exception as e:
            logger.warning(f"Error parsing SRT block: {str(e)}")
            continue
    
    return segments

def parse_timestamp(timestamp):
    """
    Parse an SRT timestamp into seconds.
    
    Args:
        timestamp (str): SRT timestamp in format HH:MM:SS,mmm
        
    Returns:
        float: Time in seconds
    """
    # Replace comma with period for milliseconds
    timestamp = timestamp.replace(',', '.')
    
    # Split into hours, minutes, seconds
    parts = timestamp.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    
    # Convert to seconds
    return hours * 3600 + minutes * 60 + seconds
