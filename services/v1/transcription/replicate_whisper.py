import os
import logging
import replicate
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

def transcribe_with_replicate(audio_url: str, language: str = "th", batch_size: int = 64) -> List[Dict]:
    """
    Transcribe audio using Replicate's Incredibly Fast Whisper model.
    
    Args:
        audio_url: URL to the audio file
        language: Language code (default: "th" for Thai)
        batch_size: Batch size for processing (default: 64)
        
    Returns:
        List of transcription segments with start, end, and text
    """
    try:
        # Get API key from environment
        api_key = os.environ.get("REPLICATE_API_KEY")
        if not api_key:
            logger.error("REPLICATE_API_KEY not found in environment variables")
            raise ValueError("REPLICATE_API_KEY not set")
            
        # Set up the API key
        os.environ["REPLICATE_API_TOKEN"] = api_key
        
        logger.info(f"Transcribing audio with Replicate Incredibly Fast Whisper: {audio_url}")
        
        # Run the model
        input_params = {
            "audio": audio_url,
            "batch_size": batch_size,
            "language": language
        }
        
        output = replicate.run(
            "vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c",
            input=input_params
        )
        
        logger.info("Transcription completed successfully")
        
        # Process the output into segments
        segments = []
        if "segments" in output:
            segments = output["segments"]
        else:
            # If no segments, create a single segment with the full text
            text = output.get("text", "")
            segments = [{"start": 0, "end": 10, "text": text}]
            
        logger.info(f"Generated {len(segments)} segments")
        return segments
        
    except Exception as e:
        logger.error(f"Error in Replicate transcription: {str(e)}")
        if "quota" in str(e).lower() or "credit" in str(e).lower() or "limit" in str(e).lower():
            logger.error("API credit limit reached for Replicate")
        raise
