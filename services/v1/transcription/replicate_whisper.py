import os
import json
import logging
import replicate
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
    Transcribe audio using Replicate's Incredibly Fast Whisper model.
    
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
                api_key = token
                logger.info(f"Found Replicate API token in {var_name}")
                break
                
        # Log token status (without revealing the full token)
        if api_key:
            masked_token = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
            logger.info(f"Using Replicate API token: {masked_token}")
        else:
            # List all environment variables (without values) for debugging
            env_vars = sorted(os.environ.keys())
            logger.error(f"Replicate API token not found. Available environment variables: {env_vars}")
            raise ValueError("Replicate API token not found. Please set the REPLICATE_API_TOKEN environment variable.")
        
        # Set the API token for the replicate library
        os.environ["REPLICATE_API_TOKEN"] = api_key
        replicate.api_token = api_key  # Also set it directly on the replicate module
        
        logger.info(f"Processing audio/video for Replicate Incredibly Fast Whisper: {audio_url}")
        
        # Check if the URL is a video file that needs conversion
        parsed_url = urlparse(audio_url)
        file_extension = os.path.splitext(parsed_url.path)[1].lower()
        
        # Create a temporary directory for processing
        temp_dir = tempfile.mkdtemp()
        audio_file_path = None
        extracted_audio_url = None
        
        # If it's a video file or unknown format, download and extract audio
        if file_extension in ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v']:
            logger.info(f"Detected video file format: {file_extension}. Extracting audio...")
            
            # Download the video file
            video_path = os.path.join(temp_dir, f"video{file_extension}")
            try:
                response = requests.get(audio_url, stream=True)
                response.raise_for_status()
                with open(video_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info(f"Downloaded video to {video_path}")
            except Exception as e:
                logger.error(f"Error downloading video: {str(e)}")
                raise ValueError(f"Failed to download video: {str(e)}")
            
            # Extract audio using FFmpeg
            audio_file_path = os.path.join(temp_dir, "extracted_audio.mp3")
            try:
                # Use higher quality settings for better transcription results
                cmd = [
                    "ffmpeg", "-y", "-i", video_path, 
                    "-vn", "-acodec", "libmp3lame", "-ar", "44100", "-ac", "2", "-b:a", "192k",
                    "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",  # Normalize audio levels
                    audio_file_path
                ]
                logger.info(f"Extracting audio with command: {' '.join(cmd)}")
                subprocess.run(cmd, check=True, capture_output=True)
                
                if not os.path.exists(audio_file_path) or os.path.getsize(audio_file_path) == 0:
                    raise ValueError("Failed to extract audio from video")
                
                logger.info(f"Successfully extracted audio to {audio_file_path}")
                
                # Upload the extracted audio to Google Cloud Storage
                try:
                    from services.cloud_storage import upload_to_cloud_storage
                    
                    # Upload the audio file to cloud storage
                    logger.info("Uploading extracted audio to Google Cloud Storage...")
                    cloud_audio_url = upload_to_cloud_storage(audio_file_path, f"audio/extracted_{os.path.basename(audio_file_path)}")
                    
                    if cloud_audio_url:
                        logger.info(f"Successfully uploaded audio to cloud: {cloud_audio_url}")
                        extracted_audio_url = cloud_audio_url
                    else:
                        logger.error("Failed to upload audio to cloud storage")
                        # Fall back to using the original URL if it's remote
                        if audio_url.startswith(('http://', 'https://')):
                            logger.info(f"Using original remote URL: {audio_url}")
                            extracted_audio_url = audio_url
                        else:
                            raise ValueError("Failed to create a publicly accessible URL for the audio")
                except Exception as upload_error:
                    logger.error(f"Error uploading to cloud storage: {str(upload_error)}")
                    # Fall back to using the original URL if it's remote
                    if audio_url.startswith(('http://', 'https://')):
                        logger.info(f"Using original remote URL: {audio_url}")
                        extracted_audio_url = audio_url
                    else:
                        raise ValueError(f"Failed to create a publicly accessible URL for the audio: {str(upload_error)}")
            except Exception as e:
                logger.error(f"Error extracting audio: {str(e)}")
                raise ValueError(f"Failed to extract audio from video: {str(e)}")
        
        # Use the extracted audio URL if available, otherwise use the original URL
        final_audio_url = extracted_audio_url if extracted_audio_url else audio_url
        logger.info(f"Using audio URL for transcription: {final_audio_url}")
        
        # Map language code to full language name if needed
        replicate_language = LANGUAGE_CODE_MAP.get(language.lower(), language.lower())
        if replicate_language not in SUPPORTED_LANGUAGES:
            logger.warning(f"Language '{language}' not directly supported, defaulting to 'thai'")
            replicate_language = "thai"
        
        logger.info(f"Using language for Replicate: {replicate_language}")
        
        # Run the model
        input_params = {
            "audio": final_audio_url,
            "batch_size": batch_size,
            "language": replicate_language,
            "task": "transcribe",
            "timestamp": "chunk",
            "diarise_audio": False
        }
        
        logger.info(f"Calling Replicate with parameters: {input_params}")
        
        try:
            # Create a prediction
            prediction = replicate.predictions.create(
                version="vaibhavs10/incredibly-fast-whisper:d5dfa8cfa4c0a98d0e9f68b0b44cfc143b89231d4dcc1c2e2c0d8d5369f2d2fd",
                input=input_params
            )
            
            # Wait for the prediction to complete
            logger.info(f"Prediction created with ID: {prediction.id}")
            logger.info("Waiting for prediction to complete...")
            
            # Poll for completion
            max_wait_time = 300  # Maximum wait time in seconds
            poll_interval = 5    # Poll interval in seconds
            wait_time = 0
            
            while prediction.status != "succeeded" and wait_time < max_wait_time:
                time.sleep(poll_interval)
                wait_time += poll_interval
                
                # Refresh the prediction status
                prediction = replicate.predictions.get(prediction.id)
                logger.info(f"Prediction status: {prediction.status}, waited {wait_time}s")
                
                if prediction.status == "failed":
                    error_message = prediction.error or "Unknown error"
                    logger.error(f"Prediction failed: {error_message}")
                    raise ValueError(f"Replicate prediction failed: {error_message}")
            
            if wait_time >= max_wait_time and prediction.status != "succeeded":
                logger.error(f"Prediction timed out after {max_wait_time} seconds")
                raise ValueError(f"Replicate prediction timed out after {max_wait_time} seconds")
            
            # Get the output
            output = prediction.output
            
        except Exception as e:
            logger.error(f"Error during Replicate API call: {str(e)}")
            raise ValueError(f"Replicate API error: {str(e)}")
        
        logger.info("Transcription completed successfully")
        logger.info(f"Raw output: {output}")
        
        # Process the output into segments
        segments = []
        
        # Handle different output formats
        if output is None:
            logger.error("Replicate returned None as output")
            raise ValueError("Replicate returned empty output")
            
        if isinstance(output, dict) and "segments" in output:
            raw_segments = output["segments"]
            for segment in raw_segments:
                segments.append({
                    "start": float(segment.get("start", 0)),
                    "end": float(segment.get("end", 0)),
                    "text": segment.get("text", "").strip()
                })
        elif isinstance(output, dict) and "text" in output:
            # If no segments, create a single segment with the full text
            text = output.get("text", "")
            segments = [{"start": 0, "end": 10, "text": text}]
        elif isinstance(output, list) and len(output) > 0:
            # Some versions of the model return a list of segments directly
            for segment in output:
                if isinstance(segment, dict):
                    segments.append({
                        "start": float(segment.get("start", 0)),
                        "end": float(segment.get("end", 0)),
                        "text": segment.get("text", "").strip()
                    })
        elif isinstance(output, str):
            # If the output is just a string, use it as a single segment
            segments = [{"start": 0, "end": 10, "text": output.strip()}]
            
        logger.info(f"Generated {len(segments)} segments")
        
        # Clean up temporary files
        try:
            if audio_file_path and os.path.exists(audio_file_path):
                os.remove(audio_file_path)
            if 'video_path' in locals() and video_path and os.path.exists(video_path):
                os.remove(video_path)
            os.rmdir(temp_dir)
            logger.info("Cleaned up temporary files")
        except Exception as e:
            logger.warning(f"Error cleaning up temporary files: {str(e)}")
        
        return segments
        
    except Exception as e:
        logger.error(f"Error in Replicate transcription: {str(e)}")
        if "quota" in str(e).lower() or "credit" in str(e).lower() or "limit" in str(e).lower():
            logger.error("API credit limit reached for Replicate")
        raise
