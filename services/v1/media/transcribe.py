import os
import json
import logging
import subprocess
import tempfile
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

def transcribe_with_whisper(video_path: str, language: str = "en", job_id: str = None) -> List[Dict]:
    """
    Transcribe a video using OpenAI's Whisper API.
    
    Args:
        video_path: Path to the video file
        language: Language code (default: "en")
        job_id: Job ID for tracking
        
    Returns:
        List of transcription segments with start, end, and text
    """
    try:
        logger.info(f"Transcribing video with OpenAI Whisper: {video_path}")
        
        # Create a temporary directory for outputs
        temp_dir = tempfile.mkdtemp()
        
        # Extract audio from video
        audio_path = os.path.join(temp_dir, "audio.wav")
        extract_cmd = [
            "ffmpeg", "-y", "-i", video_path, 
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", 
            audio_path
        ]
        
        logger.info(f"Extracting audio with command: {' '.join(extract_cmd)}")
        subprocess.run(extract_cmd, check=True)
        
        try:
            # Import OpenAI here to avoid loading it unless needed
            import openai
            
            # Get API key from environment
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                logger.error("OPENAI_API_KEY not found in environment variables")
                raise ValueError("OPENAI_API_KEY not set")
                
            # Set up the API key
            openai.api_key = api_key
            
            # Open the audio file
            with open(audio_path, "rb") as audio_file:
                # Call the OpenAI Whisper API
                logger.info("Calling OpenAI Whisper API")
                response = openai.Audio.transcribe(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                    response_format="verbose_json"
                )
                
            # Process the response to get segments
            segments = []
            if hasattr(response, 'segments'):
                segments = response.segments
            elif isinstance(response, dict) and 'segments' in response:
                segments = response['segments']
                
            # Convert segments to our standard format
            formatted_segments = []
            for segment in segments:
                formatted_segments.append({
                    "start": segment.get("start", 0),
                    "end": segment.get("end", 0),
                    "text": segment.get("text", "").strip()
                })
                
            logger.info(f"Transcription completed with {len(formatted_segments)} segments")
            
            # Clean up temporary files
            os.remove(audio_path)
            os.rmdir(temp_dir)
            
            return formatted_segments
            
        except ImportError:
            # If OpenAI is not installed, try to use Replicate instead
            logger.warning("OpenAI module not installed. Attempting to use Replicate Whisper instead.")
            
            # Import here to avoid circular imports
            from services.v1.transcription.replicate_whisper import transcribe_with_replicate
            
            # Call Replicate Whisper
            segments = transcribe_with_replicate(
                audio_url=audio_path,  # Pass the local file path
                language=language,
                batch_size=64
            )
            
            # Clean up temporary files
            os.remove(audio_path)
            os.rmdir(temp_dir)
            
            return segments
        
    except Exception as e:
        logger.error(f"Error in OpenAI Whisper transcription: {str(e)}")
        if "quota" in str(e).lower() or "credit" in str(e).lower() or "limit" in str(e).lower():
            logger.error("API credit limit reached for OpenAI")
        raise
