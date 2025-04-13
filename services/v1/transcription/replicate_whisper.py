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
        
        # Ensure the token has the correct format (Bearer prefix if needed)
        if not api_key.startswith("Bearer "):
            api_key = f"Bearer {api_key}"
        
        # Use the correct model version from the curl example
        model_version = "3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c"
        
        # Prepare the API request to Replicate
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Prefer": "wait"  # This tells the API to wait for the prediction to complete
        }
        
        # Prepare the API endpoint
        api_url = "https://api.replicate.com/v1/predictions"
        
        # Prepare the request payload - using the exact format from the curl example
        payload = {
            "version": model_version,
            "input": {
                "audio": audio_url,
                "batch_size": batch_size
            }
        }
        
        logger.info(f"Sending request to Replicate API: {json.dumps(payload, indent=2)}")
        
        # Send the request to start the transcription
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        prediction = response.json()
        
        logger.info(f"Prediction started: {prediction.get('id', 'unknown')}")
        
        # Check if we need to poll for results
        status = prediction.get("status")
        output = prediction.get("output")
        
        # If the prediction is still processing, poll for results
        if status == "processing" or output is None:
            logger.info("Prediction is still processing, polling for results...")
            
            # Set up polling parameters
            max_polls = 60  # Maximum number of polling attempts
            poll_interval = 5  # Seconds between polls
            polls = 0
            
            # Poll for results
            while polls < max_polls:
                # Wait before polling
                time.sleep(poll_interval)
                polls += 1
                
                # Make a GET request to check the status
                poll_url = f"https://api.replicate.com/v1/predictions/{prediction['id']}"
                poll_response = requests.get(poll_url, headers=headers)
                
                # Check if the request was successful
                poll_response.raise_for_status()
                
                # Parse the response
                poll_result = poll_response.json()
                status = poll_result.get("status")
                output = poll_result.get("output")
                
                logger.info(f"Poll {polls}/{max_polls}: Status = {status}")
                
                # If the prediction is complete, break the loop
                if status == "succeeded" and output is not None:
                    logger.info("Prediction completed successfully")
                    prediction = poll_result
                    break
                
                # If the prediction failed, raise an error
                if status == "failed":
                    error = poll_result.get("error")
                    logger.error(f"Prediction failed: {error}")
                    raise ValueError(f"Replicate prediction failed: {error}")
            
            # If we've exhausted our polling attempts, raise an error
            if polls >= max_polls and (status != "succeeded" or output is None):
                logger.error("Exceeded maximum polling attempts")
                raise ValueError("Exceeded maximum polling attempts for Replicate prediction")
        
        # Process the output
        if output is None:
            logger.error("No output received from Replicate API")
            raise ValueError("No output received from Replicate API")
        
        # Log the output structure to help with debugging
        logger.info(f"Output type: {type(output)}")
        if isinstance(output, dict):
            logger.info(f"Output keys: {output.keys()}")
        elif isinstance(output, list):
            logger.info(f"Output is a list with {len(output)} items")
            if output and isinstance(output[0], dict):
                logger.info(f"First item keys: {output[0].keys()}")
        
        # Process the output to create segments
        segments = []
        
        # Handle the Incredibly Fast Whisper output format
        # The model returns a list of segments with text and timestamps
        if isinstance(output, list):
            logger.info(f"Processing list output with {len(output)} items")
            
            for item in output:
                if isinstance(item, dict):
                    # Extract the relevant information
                    text = item.get("text", "").strip()
                    start = item.get("start", 0)
                    end = item.get("end", 0)
                    
                    # Skip empty segments
                    if not text:
                        continue
                    
                    # Create a segment
                    segment = {
                        "start": start,
                        "end": end,
                        "text": text
                    }
                    
                    segments.append(segment)
        
        # Handle the case where output is a dictionary with 'segments'
        elif isinstance(output, dict) and "segments" in output:
            logger.info(f"Processing dictionary output with 'segments' key")
            
            for segment in output["segments"]:
                if isinstance(segment, dict):
                    # Extract the relevant information
                    text = segment.get("text", "").strip()
                    start = segment.get("start", 0)
                    end = segment.get("end", 0)
                    
                    # Skip empty segments
                    if not text:
                        continue
                    
                    # Create a segment
                    segment_data = {
                        "start": start,
                        "end": end,
                        "text": text
                    }
                    
                    segments.append(segment_data)
        
        # Handle the case where output is a dictionary with 'chunks'
        elif isinstance(output, dict) and "chunks" in output:
            logger.info(f"Processing dictionary output with 'chunks' key")
            
            for chunk in output["chunks"]:
                if isinstance(chunk, dict):
                    # Extract the relevant information
                    text = chunk.get("text", "").strip()
                    timestamp = chunk.get("timestamp", [0, 0])
                    
                    # Skip empty chunks
                    if not text:
                        continue
                    
                    # Create a segment
                    segment = {
                        "start": timestamp[0] if isinstance(timestamp, list) and len(timestamp) > 0 else 0,
                        "end": timestamp[1] if isinstance(timestamp, list) and len(timestamp) > 1 else 0,
                        "text": text
                    }
                    
                    segments.append(segment)
        
        # Handle the case where output is a string (full transcription without timestamps)
        elif isinstance(output, str):
            logger.info(f"Processing string output (length: {len(output)})")
            
            # Check if it's an SRT format
            if "\n\n" in output and "-->" in output:
                logger.info("Detected SRT format in output string")
                segments = parse_srt_content(output)
            else:
                # Create a single segment with the full text
                segment = {
                    "start": 0,
                    "end": 60,  # Default to 60 seconds if no timing information
                    "text": output.strip()
                }
                
                segments.append(segment)
        
        else:
            logger.error(f"Unexpected output format: {output}")
            raise ValueError(f"Unexpected output format from Replicate: {type(output)}")
        
        logger.info(f"Processed {len(segments)} segments from Replicate output")
        
        # Return the segments
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
