import os
import json
import logging
import replicate
import tempfile
import subprocess
import requests
from typing import Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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
        # Get API key from environment
        api_key = os.environ.get("REPLICATE_API_TOKEN")
        if not api_key:
            logger.error("REPLICATE_API_TOKEN not found in environment variables")
            raise ValueError("REPLICATE_API_TOKEN not set")
            
        # Set up the API key
        os.environ["REPLICATE_API_TOKEN"] = api_key
        
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
                cmd = [
                    "ffmpeg", "-y", "-i", video_path, 
                    "-vn", "-acodec", "libmp3lame", "-ar", "44100", "-ac", "2", "-b:a", "192k",
                    audio_file_path
                ]
                logger.info(f"Extracting audio with command: {' '.join(cmd)}")
                subprocess.run(cmd, check=True, capture_output=True)
                
                if not os.path.exists(audio_file_path) or os.path.getsize(audio_file_path) == 0:
                    raise ValueError("Failed to extract audio from video")
                
                logger.info(f"Successfully extracted audio to {audio_file_path}")
                
                # Upload the extracted audio to a temporary storage
                # For simplicity, we'll use the Replicate upload API
                logger.info("Uploading extracted audio to Replicate...")
                with open(audio_file_path, "rb") as f:
                    extracted_audio_url = replicate.upload(f)
                
                logger.info(f"Uploaded audio to {extracted_audio_url}")
                
            except Exception as e:
                logger.error(f"Error extracting audio: {str(e)}")
                raise ValueError(f"Failed to extract audio from video: {str(e)}")
        
        # Use the extracted audio URL if available, otherwise use the original URL
        final_audio_url = extracted_audio_url if extracted_audio_url else audio_url
        logger.info(f"Using audio URL for transcription: {final_audio_url}")
        
        # Run the model
        input_params = {
            "audio": final_audio_url,
            "batch_size": batch_size,
            "language": language,
            "task": "transcribe",
            "timestamp": "chunk",
            "diarise_audio": False
        }
        
        logger.info(f"Calling Replicate with parameters: {input_params}")
        output = replicate.run(
            "vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c",
            input=input_params
        )
        
        logger.info("Transcription completed successfully")
        logger.info(f"Raw output: {output}")
        
        # Process the output into segments
        segments = []
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
        else:
            logger.warning(f"Unexpected output format from Replicate: {output}")
            # Try to extract any text we can find
            if isinstance(output, str):
                segments = [{"start": 0, "end": 10, "text": output.strip()}]
            elif isinstance(output, list) and len(output) > 0:
                segments = [{"start": 0, "end": 10, "text": str(output[0]).strip()}]
            else:
                raise ValueError("Could not extract any text from Replicate output")
            
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
