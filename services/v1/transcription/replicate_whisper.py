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
    Transcribe audio using Replicate's Incredibly Fast Whisper model via direct API calls.
    
    Args:
        audio_url: URL to the audio or video file
        language: Language code (default: "th" for Thai)
        batch_size: Batch size for processing (default: 64)
        
    Returns:
        List of transcription segments with start, end, and text
    """
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
        
        # Map language code to full language name if needed
        replicate_language = LANGUAGE_CODE_MAP.get(language.lower(), language.lower())
        if replicate_language not in SUPPORTED_LANGUAGES:
            logger.warning(f"Language '{language}' not directly supported, defaulting to 'thai'")
            replicate_language = "thai"
        
        logger.info(f"Using language for Replicate: {replicate_language}")
        
        # API endpoint
        api_url = "https://api.replicate.com/v1/predictions"
        
        # Headers for the API request
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Prefer": "wait"  # This tells the API to wait for the prediction to complete
        }
        
        # First try with the latest model
        model_version = "vaibhavs10/incredibly-fast-whisper:latest"
        
        # Prepare request data
        request_data = {
            "version": model_version,
            "input": {
                "audio": final_audio_url,
                "language": replicate_language,
                "batch_size": batch_size,
                "task": "transcribe",
                "timestamp": "chunk",
                "diarise_audio": False
            }
        }
        
        logger.info(f"Making direct API call to Replicate with parameters: {request_data}")
        
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
            
            # Process the output to create segments
            segments = []
            
            # Check if output contains 'chunks' (Whisper format)
            if isinstance(output, dict) and "chunks" in output:
                chunks = output["chunks"]
                logger.info(f"Received {len(chunks)} chunks from Replicate")
                
                for chunk in chunks:
                    # Extract the relevant information
                    text = chunk.get("text", "").strip()
                    timestamp = chunk.get("timestamp", [0, 0])
                    
                    # Skip empty chunks
                    if not text:
                        continue
                    
                    # Create a segment
                    segment = {
                        "start": timestamp[0],
                        "end": timestamp[1],
                        "text": text
                    }
                    
                    segments.append(segment)
            else:
                # Handle other output formats
                logger.warning(f"Unexpected output format from Replicate: {type(output)}")
                
                # Try to extract text and timestamps from the output
                if isinstance(output, list):
                    for item in output:
                        if isinstance(item, dict) and "text" in item:
                            # Extract the relevant information
                            text = item.get("text", "").strip()
                            start = item.get("start", 0)
                            end = item.get("end", start + 5)  # Default to 5 seconds if no end time
                            
                            # Skip empty items
                            if not text:
                                continue
                            
                            # Create a segment
                            segment = {
                                "start": start,
                                "end": end,
                                "text": text
                            }
                            
                            segments.append(segment)
            
            logger.info(f"Processed {len(segments)} segments from Replicate output")
            
            # Return the segments
            return segments
            
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error during Replicate API call: {str(e)}")
            
            # Try with an alternative model version if the first attempt failed
            if "version does not exist" in str(e).lower():
                logger.info("Trying with alternative model version...")
                
                # Use an alternative model version
                alt_model_version = "vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c"
                request_data["version"] = alt_model_version
                
                try:
                    # Make the API request with the alternative model
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
                    
                    # Parse the response and continue with the same logic as above
                    result = response.json()
                    logger.info(f"Alternative model API call successful, received response with keys: {result.keys()}")
                    
                    # Continue with the same processing logic as above
                    # ... (same code as above for processing the response)
                    
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
                    
                    # Process the output to create segments
                    segments = []
                    
                    # Check if output contains 'chunks' (Whisper format)
                    if isinstance(output, dict) and "chunks" in output:
                        chunks = output["chunks"]
                        logger.info(f"Received {len(chunks)} chunks from Replicate")
                        
                        for chunk in chunks:
                            # Extract the relevant information
                            text = chunk.get("text", "").strip()
                            timestamp = chunk.get("timestamp", [0, 0])
                            
                            # Skip empty chunks
                            if not text:
                                continue
                            
                            # Create a segment
                            segment = {
                                "start": timestamp[0],
                                "end": timestamp[1],
                                "text": text
                            }
                            
                            segments.append(segment)
                    else:
                        # Handle other output formats
                        logger.warning(f"Unexpected output format from Replicate: {type(output)}")
                        
                        # Try to extract text and timestamps from the output
                        if isinstance(output, list):
                            for item in output:
                                if isinstance(item, dict) and "text" in item:
                                    # Extract the relevant information
                                    text = item.get("text", "").strip()
                                    start = item.get("start", 0)
                                    end = item.get("end", start + 5)  # Default to 5 seconds if no end time
                                    
                                    # Skip empty items
                                    if not text:
                                        continue
                                    
                                    # Create a segment
                                    segment = {
                                        "start": start,
                                        "end": end,
                                        "text": text
                                    }
                                    
                                    segments.append(segment)
                    
                    logger.info(f"Processed {len(segments)} segments from Replicate output")
                    
                    # Return the segments
                    return segments
                    
                except requests.exceptions.RequestException as alt_e:
                    logger.error(f"HTTP error during alternative model API call: {str(alt_e)}")
                    raise ValueError(f"Replicate API error (both model versions failed): {str(e)}, then: {str(alt_e)}")
            
            # If not a version error, just raise the original error
            raise ValueError(f"Replicate API error: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error in Replicate transcription: {str(e)}")
        raise ValueError(f"Replicate API error: {str(e)}")
