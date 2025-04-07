import os
import json
import logging
import tempfile
import subprocess
import requests
import time
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

def transcribe_with_replicate(audio_url: str, language: str = "th", batch_size: int = 64) -> List[Dict]:
    """
    Transcribe audio using Replicate Whisper API.
    
    Args:
        audio_url (str): URL to the audio file
        language (str, optional): Language code. Defaults to "th".
        batch_size (int, optional): Batch size for processing. Defaults to 64.
        
    Returns:
        list: List of transcription segments with start and end times
    """
    logger.info(f"Starting transcription with Replicate Whisper: {audio_url}")
    
    # Ensure audio_url is a valid URL
    if not audio_url:
        raise ValueError("Audio URL is required")
    
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
            token = os.environ.get(var_name)
            if token:
                # Keep the 'Bearer ' prefix if present (needed for direct API calls)
                api_key = token
                logger.info(f"Found Replicate API token in {var_name}")
                break
                
        # Log token status (without revealing the full token)
        if api_key:
            # For direct API calls, we need the Bearer prefix
            if not api_key.startswith("Bearer "):
                api_key = f"Bearer {api_key}"
                logger.info("Added 'Bearer ' prefix to token for API call")
            
            masked_token = api_key[:10] + "..." + api_key[-5:] if len(api_key) > 15 else "***"
            logger.info(f"Using Replicate API token: {masked_token}")
        else:
            # List all environment variables (without values) for debugging
            env_vars = sorted(os.environ.keys())
            logger.error(f"Replicate API token not found. Available environment variables: {env_vars}")
            raise ValueError("Replicate API token not found. Please set the REPLICATE_API_TOKEN environment variable.")
        
        logger.info(f"Processing audio/video for Replicate Incredibly Fast Whisper: {audio_url}")
        
        # Check if the URL is a local file path or a remote URL
        is_local_file = not audio_url.startswith(('http://', 'https://'))
        extracted_audio_url = None
        
        if is_local_file:
            # For local files, we need to extract the audio and upload it
            logger.info(f"Local file detected. Need to extract audio and upload to cloud storage.")
            
            try:
                # Create a temporary directory for processing
                with tempfile.TemporaryDirectory() as temp_dir:
                    # Extract audio from the video file
                    extracted_audio_path = os.path.join(temp_dir, "extracted_audio.mp3")
                    
                    # Use FFmpeg to extract audio
                    ffmpeg_command = [
                        "ffmpeg", "-y",
                        "-i", audio_url,
                        "-vn", "-acodec", "libmp3lame",
                        "-ar", "44100", "-ac", "2", "-b:a", "192k",
                        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
                        extracted_audio_path
                    ]
                    
                    logger.info(f"Extracting audio with command: {' '.join(ffmpeg_command)}")
                    subprocess.run(ffmpeg_command, check=True, capture_output=True)
                    
                    if os.path.exists(extracted_audio_path):
                        logger.info(f"Successfully extracted audio to {extracted_audio_path}")
                        
                        # Upload the extracted audio to cloud storage
                        try:
                            from services.cloud_storage import upload_file_to_cloud
                            extracted_audio_url = upload_file_to_cloud(
                                file_path=extracted_audio_path,
                                custom_path=f"audio/extracted_{os.path.basename(extracted_audio_path)}"
                            )
                            logger.info(f"Successfully uploaded audio to cloud: {extracted_audio_url}")
                        except Exception as upload_error:
                            logger.error(f"Error uploading audio to cloud: {str(upload_error)}")
                            raise ValueError(f"Failed to create a publicly accessible URL for the audio: {str(upload_error)}")
                    else:
                        logger.error(f"Failed to extract audio: file not found at {extracted_audio_path}")
                        raise ValueError("Failed to extract audio from video")
            except Exception as e:
                logger.error(f"Error extracting audio: {str(e)}")
                raise ValueError(f"Failed to extract audio from video: {str(e)}")
        elif not audio_url.endswith('.mp3') and not audio_url.endswith('.wav') and not audio_url.endswith('.m4a'):
            # For remote video files, we need to download, extract audio, and upload it
            logger.info(f"Remote video file detected. Downloading, extracting audio, and uploading...")
            
            try:
                # Create a temporary directory for processing
                with tempfile.TemporaryDirectory() as temp_dir:
                    # Download the video
                    video_path = os.path.join(temp_dir, "video.mp4")
                    
                    # Download the video file
                    response = requests.get(audio_url, stream=True)
                    response.raise_for_status()
                    
                    with open(video_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    logger.info(f"Downloaded video to {video_path}")
                    
                    # Extract audio from the video file
                    extracted_audio_path = os.path.join(temp_dir, "extracted_audio.mp3")
                    
                    # Use FFmpeg to extract audio
                    ffmpeg_command = [
                        "ffmpeg", "-y",
                        "-i", video_path,
                        "-vn", "-acodec", "libmp3lame",
                        "-ar", "44100", "-ac", "2", "-b:a", "192k",
                        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
                        extracted_audio_path
                    ]
                    
                    logger.info(f"Extracting audio with command: {' '.join(ffmpeg_command)}")
                    subprocess.run(ffmpeg_command, check=True, capture_output=True)
                    
                    if os.path.exists(extracted_audio_path):
                        logger.info(f"Successfully extracted audio to {extracted_audio_path}")
                        
                        # Upload the extracted audio to cloud storage
                        try:
                            from services.cloud_storage import upload_file_to_cloud
                            extracted_audio_url = upload_file_to_cloud(
                                file_path=extracted_audio_path,
                                custom_path=f"audio/extracted_{os.path.basename(extracted_audio_path)}"
                            )
                            logger.info(f"Successfully uploaded audio to cloud: {extracted_audio_url}")
                        except Exception as upload_error:
                            logger.error(f"Error uploading audio to cloud: {str(upload_error)}")
                            # If we can't upload, we'll fall back to the original URL
                            logger.info(f"Falling back to original URL: {audio_url}")
                    else:
                        logger.error(f"Failed to extract audio: file not found at {extracted_audio_path}")
                        # If extraction fails, we'll fall back to the original URL
                        logger.info(f"Falling back to original URL: {audio_url}")
            except Exception as e:
                logger.error(f"Error processing video: {str(e)}")
                logger.info(f"Falling back to original URL: {audio_url}")
        
        # Use the extracted audio URL if available, otherwise use the original URL
        final_audio_url = extracted_audio_url if extracted_audio_url else audio_url
        logger.info(f"Using audio URL for transcription: {final_audio_url}")
        
        # Use the exact model version from the working cURL example
        model_version = "3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c"
        
        # Prepare request data with minimal parameters that match the working example
        request_data = {
            "version": model_version,
            "input": {
                "audio": final_audio_url,
                "batch_size": batch_size
            }
        }
        
        # API endpoint
        api_url = "https://api.replicate.com/v1/predictions"
        
        # Headers for the API request
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Prefer": "wait"  # This tells the API to wait for the prediction to complete
        }
        
        # Log the exact request being sent
        logger.info(f"Making direct API call to Replicate with URL: {api_url}")
        # Don't log the full token, just a masked version
        masked_headers = headers.copy()
        if 'Authorization' in masked_headers:
            auth_value = masked_headers['Authorization']
            if auth_value.startswith('Bearer '):
                masked_headers['Authorization'] = f"Bearer {auth_value[7:12]}...{auth_value[-5:]}"
        logger.info(f"Headers (masked): {masked_headers}")
        logger.info(f"Request data: {json.dumps(request_data, indent=2)}")
        
        try:
            # Make the API request
            response = requests.post(api_url, json=request_data, headers=headers)
            
            # Log the full response for debugging
            try:
                response_json = response.json()
                logger.info(f"Raw API response: {response_json}")
                
                # Check for specific error details
                if 'detail' in response_json:
                    logger.error(f"API error detail: {response_json['detail']}")
                    
                # Check for validation errors
                if 'validation_errors' in response_json:
                    logger.error(f"Validation errors: {response_json['validation_errors']}")
            except Exception as json_error:
                logger.error(f"Could not parse response as JSON: {str(json_error)}")
                logger.error(f"Raw response text: {response.text}")
            
            # Check if the request was successful
            response.raise_for_status()
            
            # Parse the response
            result = response.json()
            logger.info(f"API call successful, received response with keys: {result.keys()}")
            
            # Get the prediction ID
            prediction_id = result.get("id")
            logger.info(f"Prediction ID: {prediction_id}")
            
            # Check if we need to poll for results
            status = result.get("status")
            output = result.get("output")
            
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
                    poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
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
                        result = poll_result
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
        
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error during Replicate API call: {str(e)}")
            
            # No fallback to alternative model - use the same model version that works
            logger.info(f"First attempt failed. Trying with detailed error logging...")
            
            # Make another attempt with the same model but log more details about the error
            try:
                # Make the API request with more detailed error logging
                response = requests.post(api_url, json=request_data, headers=headers)
                
                # Log the full response for debugging
                try:
                    response_json = response.json()
                    logger.error(f"Full API error response: {json.dumps(response_json, indent=2)}")
                    
                    # Check for specific error details
                    if 'detail' in response_json:
                        logger.error(f"API error detail: {response_json['detail']}")
                        
                    # Check for validation errors
                    if 'validation_errors' in response_json:
                        logger.error(f"Validation errors: {response_json['validation_errors']}")
                except Exception as json_error:
                    logger.error(f"Could not parse response as JSON: {str(json_error)}")
                    logger.error(f"Raw response text: {response.text}")
                
                # Raise the error for proper handling
                raise ValueError(f"Replicate API error after multiple attempts: {response.status_code} {response.reason}")
            
            except requests.exceptions.RequestException as alt_e:
                logger.error(f"HTTP error during alternative model API call: {str(alt_e)}")
                raise ValueError(f"Replicate API error (both model versions failed): {str(e)}, then: {str(alt_e)}")
        
        # If not a version error, just raise the original error
        raise ValueError(f"Replicate API error: {str(e)}")
        
    except Exception as e:
        logger.error(f"Error in Replicate transcription: {str(e)}")
        raise ValueError(f"Replicate API error: {str(e)}")
