import os
import whisper
import srt
import json
import unicodedata
import re
from datetime import timedelta
from whisper.utils import WriteSRT, WriteVTT
from services.file_management import download_file
import logging

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Set the default local storage directory
STORAGE_PATH = "/tmp/"

# Thai language specific constants
THAI_VOWELS = [
    '\u0e30', '\u0e31', '\u0e32', '\u0e33', '\u0e34', '\u0e35', '\u0e36', '\u0e37', '\u0e38', '\u0e39',
    '\u0e47', '\u0e48', '\u0e49', '\u0e4a', '\u0e4b', '\u0e4c', '\u0e4d'
]

THAI_CONSONANTS = [
    '\u0e01', '\u0e02', '\u0e03', '\u0e04', '\u0e05', '\u0e06', '\u0e07', '\u0e08', '\u0e09', '\u0e0a',
    '\u0e0b', '\u0e0c', '\u0e0d', '\u0e0e', '\u0e0f', '\u0e10', '\u0e11', '\u0e12', '\u0e13', '\u0e14',
    '\u0e15', '\u0e16', '\u0e17', '\u0e18', '\u0e19', '\u0e1a', '\u0e1b', '\u0e1c', '\u0e1d', '\u0e1e',
    '\u0e1f', '\u0e20', '\u0e21', '\u0e22', '\u0e23', '\u0e24', '\u0e25', '\u0e26', '\u0e27', '\u0e28',
    '\u0e29', '\u0e2a', '\u0e2b', '\u0e2c', '\u0e2d', '\u0e2e'
]

# Common Thai word corrections (misspelled -> correct)
THAI_WORD_CORRECTIONS = {
    'ครับ': 'ครับ',
    'ค่ะ': 'ค่ะ',
    'นะคะ': 'นะคะ',
    'นะครับ': 'นะครับ',
    # Add more common corrections as needed
}

def clean_thai_text(text):
    """
    Clean and normalize Thai text to ensure proper encoding.
    """
    if not text:
        return text
        
    # Normalize Unicode characters (important for Thai)
    normalized_text = unicodedata.normalize('NFC', text)
    
    # Check if text contains Thai characters
    def contains_thai(s):
        thai_range = range(0x0E00, 0x0E7F)
        return any(ord(c) in thai_range for c in s)
    
    # If text contains Thai, ensure it's properly encoded
    if contains_thai(normalized_text):
        # Keep Thai characters, spaces, and basic punctuation
        thai_range = range(0x0E00, 0x0E7F)
        cleaned_text = ''.join(c for c in normalized_text if ord(c) in thai_range or c.isspace() or c in '.!?,;:')
        
        # Only return cleaned text if we have something left
        if cleaned_text:
            return cleaned_text
    
    # Return normalized text if no Thai characters or cleaning removed everything
    return normalized_text

def preprocess_thai_audio(input_filename):
    """
    Preprocess Thai audio to improve transcription accuracy.
    This function can be extended with audio preprocessing steps.
    """
    logger.info(f"Preprocessing Thai audio: {input_filename}")
    # Currently just returns the original filename
    # Future: Add audio preprocessing like noise reduction, normalization, etc.
    return input_filename

def postprocess_thai_text(text):
    """
    Apply Thai-specific post-processing to improve transcription quality.
    """
    if not text:
        return text
    
    # Normalize Unicode characters
    text = unicodedata.normalize('NFC', text)
    
    # Fix common Thai transcription errors
    for incorrect, correct in THAI_WORD_CORRECTIONS.items():
        text = text.replace(incorrect, correct)
    
    # Fix spacing issues in Thai text
    # Thai doesn't use spaces between words, but Whisper might add them incorrectly
    def fix_thai_spacing(match):
        # Don't add space between Thai consonant and vowel
        if match.group(1)[-1] in THAI_CONSONANTS and match.group(2)[0] in THAI_VOWELS:
            return match.group(1) + match.group(2)
        return match.group(0)  # Keep as is
    
    # Find spaces between Thai characters and fix them if needed
    thai_char_pattern = r'([^\s\u0E00-\u0E7F]+)(\s+)([^\s\u0E00-\u0E7F]+)'
    text = re.sub(thai_char_pattern, fix_thai_spacing, text)
    
    # Fix tone mark positions
    # (This is a simplified approach, a more comprehensive solution would use Thai NLP libraries)
    
    return text

def process_transcribe_media(media_url, task, include_text, include_srt, include_segments, word_timestamps, response_type, language, job_id):
    """Transcribe or translate media and return the transcript/translation, SRT or VTT file path."""
    logger.info(f"Starting {task} for media URL: {media_url}")
    input_filename = download_file(media_url, os.path.join(STORAGE_PATH, 'input_media'))
    logger.info(f"Downloaded media to local file: {input_filename}")

    try:
        # Determine the appropriate model size based on language
        # Use medium model for Thai language to improve accuracy
        if language and language.lower() in ['th', 'thai']:
            model_size = "medium"
            language = "th"  # Explicitly set language to Thai
            logger.info(f"Using large model for Thai language transcription")
            
            # Apply Thai-specific audio preprocessing
            input_filename = preprocess_thai_audio(input_filename)
        else:
            # Load a larger model for better translation quality
            model_size = "large" if task == "translate" else "base"
            
        model = whisper.load_model(model_size)
        logger.info(f"Loaded Whisper {model_size} model")

        # Configure transcription/translation options
        options = {
            "task": task,
            "word_timestamps": word_timestamps,
            "verbose": False
        }

        # Add language specification if provided
        if language:
            options["language"] = language
            logger.info(f"Setting language to {language} for {task}")

        result = model.transcribe(input_filename, **options)
        
        # Process Thai text if needed
        is_thai = language and language.lower() in ['th', 'thai']
        if is_thai:
            logger.info("Processing Thai text to ensure proper encoding")
            # Clean the main text
            result['text'] = postprocess_thai_text(result['text'])
            
            # Clean each segment's text
            for segment in result['segments']:
                segment['text'] = postprocess_thai_text(segment['text'])
                
                # Also clean word-level timestamps if present
                if 'words' in segment:
                    for word in segment['words']:
                        if 'word' in word:
                            word['word'] = postprocess_thai_text(word['word'])
        
        # For translation task, the result['text'] will be in English
        text = None
        srt_file = None
        segments_file = None
        
        # Generate output files based on requested formats
        base_output_filename = os.path.join(STORAGE_PATH, f"{job_id}")
        
        # Create text file if requested
        if include_text:
            text = os.path.join(STORAGE_PATH, f"{job_id}.txt")
            with open(text, "w", encoding="utf-8") as f:
                f.write(result['text'])
            logger.info(f"Created text file: {text}")
        
        # Create SRT file if requested
        if include_srt:
            srt_file = os.path.join(STORAGE_PATH, f"{job_id}.srt")
            
            # For Thai language, we need to post-process the SRT content
            if is_thai:
                logger.info("Generating SRT file with Thai-specific processing")
                srt_content = []
                
                for i, segment in enumerate(result['segments']):
                    start_time = timedelta(seconds=segment['start'])
                    end_time = timedelta(seconds=segment['end'])
                    
                    # Apply Thai-specific post-processing to the text
                    processed_text = postprocess_thai_text(segment['text'])
                    
                    # Create SRT subtitle entry
                    srt_content.append(
                        srt.Subtitle(
                            index=i+1,
                            start=start_time,
                            end=end_time,
                            content=processed_text
                        )
                    )
                
                # Write the SRT file with proper encoding
                with open(srt_file, "w", encoding="utf-8") as f:
                    f.write(srt.compose(srt_content))
            else:
                # Use standard Whisper SRT writer for non-Thai languages
                with open(srt_file, "w", encoding="utf-8") as f:
                    writer = WriteSRT(output_dir=None)
                    writer.write_result(result, file=f)
            
            logger.info(f"Created SRT file: {srt_file}")
        
        # Create segments file if requested
        if include_segments:
            segments_file = os.path.join(STORAGE_PATH, f"{job_id}.json")
            with open(segments_file, "w", encoding="utf-8") as f:
                json.dump(result['segments'], f, ensure_ascii=False, indent=2)
            logger.info(f"Created segments file: {segments_file}")
        
        os.remove(input_filename)
        logger.info(f"Removed local file: {input_filename}")
        logger.info(f"{task.capitalize()} successful, output type: {response_type}")

        if response_type == "direct":
            return text, srt_file, segments_file
        else:
            return text, srt_file, segments_file

    except Exception as e:
        logger.error(f"{task.capitalize()} failed: {str(e)}")
        raise

def align_script_with_segments(script_text, segments, output_srt_path, language="th"):
    """
    Align a pre-written script with the timing information from transcription segments.
    Optimized for Thai language with character-level alignment.
    
    Args:
        script_text: The pre-written script text
        segments: The transcription segments with timing information
        output_srt_path: Path to save the aligned SRT file
        language: Language code (default: "th" for Thai)
    
    Returns:
        The path to the generated SRT file
    """
    logger.info(f"Aligning script with transcription segments for language: {language}")
    
    # Clean and normalize the script text
    if language.lower() in ['th', 'thai']:
        script_text = postprocess_thai_text(script_text)
    
    # Split the script into sentences or natural segments
    # For Thai, we'll use basic punctuation as segment markers
    if language.lower() in ['th', 'thai']:
        # Thai doesn't use spaces between words, so we split by punctuation
        script_segments = re.split(r'([.!?।॥\n]+)', script_text)
        # Recombine the split segments with their punctuation
        script_segments = [''.join(i) for i in zip(script_segments[::2], script_segments[1::2] + [''])]
        # Remove empty segments
        script_segments = [seg.strip() for seg in script_segments if seg.strip()]
    else:
        # For other languages, split by sentence-ending punctuation
        script_segments = re.split(r'(?<=[.!?])\s+', script_text)
        script_segments = [seg.strip() for seg in script_segments if seg.strip()]
    
    logger.info(f"Split script into {len(script_segments)} segments")
    
    # Prepare the SRT content
    srt_content = []
    
    # If we have very few script segments compared to transcription segments,
    # we might need to further split the script segments
    if len(script_segments) < len(segments) / 2:
        logger.info("Script has fewer segments than transcription, performing character-level alignment")
        # Character-level alignment approach
        
        # Flatten the script into a single string
        flat_script = ''.join(script_segments)
        
        # Calculate total duration of the transcription
        total_duration = segments[-1]['end'] - segments[0]['start']
        
        # Calculate average character duration
        chars_per_second = len(flat_script) / total_duration
        
        # Assign timing to each script segment based on its length
        current_time = segments[0]['start']
        
        for i, segment in enumerate(script_segments):
            start_time = current_time
            # Calculate duration based on segment length
            segment_duration = len(segment) / chars_per_second
            # Ensure minimum duration
            segment_duration = max(segment_duration, 1.0)
            end_time = start_time + segment_duration
            
            # Create SRT subtitle entry
            srt_content.append(
                srt.Subtitle(
                    index=i+1,
                    start=timedelta(seconds=start_time),
                    end=timedelta(seconds=end_time),
                    content=segment
                )
            )
            
            current_time = end_time
    else:
        # If script segments are comparable to transcription segments,
        # use a more direct mapping approach
        logger.info("Using direct mapping between script and transcription segments")
        
        # Calculate how many transcription segments to assign to each script segment
        segments_per_script = max(1, len(segments) // len(script_segments))
        
        for i, script_segment in enumerate(script_segments):
            # Calculate which transcription segments to use for this script segment
            start_idx = i * segments_per_script
            end_idx = min((i + 1) * segments_per_script, len(segments))
            
            # If we're at the last script segment, include all remaining transcription segments
            if i == len(script_segments) - 1:
                end_idx = len(segments)
            
            # Skip if we've run out of transcription segments
            if start_idx >= len(segments):
                break
                
            # Get timing from transcription segments
            start_time = segments[start_idx]['start']
            end_time = segments[end_idx - 1]['end'] if end_idx > 0 and end_idx <= len(segments) else segments[-1]['end']
            
            # Create SRT subtitle entry
            srt_content.append(
                srt.Subtitle(
                    index=i+1,
                    start=timedelta(seconds=start_time),
                    end=timedelta(seconds=end_time),
                    content=script_segment
                )
            )
    
    # Write the SRT file with proper encoding
    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(srt_content))
    
    logger.info(f"Created aligned SRT file: {output_srt_path}")
    return output_srt_path