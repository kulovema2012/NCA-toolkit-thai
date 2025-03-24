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
from typing import Dict, List, Optional, Union, Any

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Set the default local storage directory
STORAGE_PATH = "/tmp/"

# Thai language specific constants
THAI_CONSONANTS = 'กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ'
THAI_VOWELS = 'ะัาำิีึืุูเแโใไๅ'
THAI_TONEMARKS = '่้๊๋'
THAI_CHARS = THAI_CONSONANTS + THAI_VOWELS + THAI_TONEMARKS

# Dictionary of common Thai words that might be incorrectly transcribed
THAI_WORD_CORRECTIONS = {
    # Common incorrect transcriptions from Whisper
    "thaler feet": "ทั้งหมด",
    "stylist": "เรื่องราวของ",
    "Flatast": "ภาพที่น่าสนใจ",
    "pc": "พีซี",
    # Add more corrections as needed
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
    
    # Normalize Unicode characters (NFC is better for Thai)
    text = unicodedata.normalize('NFC', text)
    
    # Ensure text is properly encoded as UTF-8
    try:
        # Force re-encoding to ensure proper UTF-8
        text = text.encode('utf-8', errors='ignore').decode('utf-8')
    except Exception as e:
        logger.warning(f"Error during Thai text encoding: {str(e)}")
    
    # Replace common incorrect transcriptions with correct Thai words
    for incorrect, correct in THAI_WORD_CORRECTIONS.items():
        text = re.sub(r'\b' + re.escape(incorrect) + r'\b', correct, text, flags=re.IGNORECASE)
    
    # Try to use PyThaiNLP for more accurate Thai text processing if available
    try:
        from pythainlp import word_tokenize, correct
        
        # First try to correct misspelled Thai words
        text = correct(text)
        
        # Detect mixed language segments and process them separately
        segments = []
        current_segment = ""
        current_is_thai = False
        
        for char in text:
            is_thai_char = char in THAI_CHARS
            
            # If we're changing language types, process the previous segment
            if current_segment and is_thai_char != current_is_thai:
                if current_is_thai:
                    # Process Thai segment with PyThaiNLP
                    tokens = word_tokenize(current_segment)
                    processed_segment = ''.join(tokens)
                    segments.append(processed_segment)
                else:
                    # Keep English segment as is
                    segments.append(current_segment)
                
                # Reset for new segment
                current_segment = ""
            
            current_segment += char
            current_is_thai = is_thai_char
        
        # Process the last segment
        if current_segment:
            if current_is_thai:
                tokens = word_tokenize(current_segment)
                processed_segment = ''.join(tokens)
                segments.append(processed_segment)
            else:
                segments.append(current_segment)
        
        # Join all processed segments
        text = ''.join(segments)
        
        logger.info("Used PyThaiNLP for Thai text processing")
    except ImportError:
        logger.warning("PyThaiNLP not available for Thai text processing")
    except Exception as e:
        logger.warning(f"Error using PyThaiNLP for processing: {str(e)}")
    
    # Fix spacing issues in Thai text
    # Thai doesn't use spaces between words, but Whisper might add them incorrectly
    def fix_thai_spacing(match):
        # Don't add space between Thai characters
        if any(c in THAI_CHARS for c in match.group(1)) and any(c in THAI_CHARS for c in match.group(3)):
            return match.group(1) + match.group(3)
        return match.group(0)  # Keep as is
    
    # Find spaces between Thai characters and fix them if needed
    text = re.sub(r'([^\s]+)(\s+)([^\s]+)', fix_thai_spacing, text)
    
    return text

def process_transcribe_media(media_url, task, include_text, include_srt, include_segments, word_timestamps, response_type, language, job_id):
    """Transcribe or translate media and return the transcript/translation, SRT or VTT file path."""
    logger.info(f"Starting {task} for media URL: {media_url}")
    input_filename = download_file(media_url, os.path.join(STORAGE_PATH, 'input_media'))
    
    if not input_filename:
        raise ValueError("Failed to download media file")
    
    # Determine if the language is Thai
    is_thai = language and language.lower() == 'th'
    
    # For Thai language, optimize processing to prevent timeouts
    if is_thai:
        logger.info("Thai language detected - using optimized processing settings")
        # Use smaller chunk sizes for Thai to prevent timeouts
        chunk_size = 10 * 60  # 10 minute chunks instead of default 30
        logger.info(f"Using smaller chunk size for Thai: {chunk_size} minutes")
    else:
        chunk_size = None  # Use default
    
    try:
        # Load the Whisper model
        model = whisper.load_model("medium")
        
        # Transcribe or translate the audio
        logger.info(f"Running {task} with model: medium")
        
        # Set options based on the task and language
        options = {
            "task": task,
            "language": language,
            "verbose": False,
        }
        
        if word_timestamps:
            options["word_timestamps"] = True
        
        # Add chunk size for Thai to prevent timeouts
        if chunk_size:
            options["chunk_size"] = chunk_size
        
        # Run the transcription/translation
        result = model.transcribe(input_filename, **options)
        
        # Post-process Thai text if needed
        if is_thai:
            logger.info("Processing Thai text to ensure proper encoding")
            result['text'] = postprocess_thai_text(result['text'])
            
            # Also process segment text
            for segment in result['segments']:
                segment['text'] = postprocess_thai_text(segment['text'])
                
                # Process word timestamps if available
                if word_timestamps and 'words' in segment:
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
                
                # Maximum character count per subtitle for Thai (to prevent overlapping)
                max_thai_chars_per_subtitle = 60
                
                for i, segment in enumerate(result['segments']):
                    start_time = timedelta(seconds=segment['start'])
                    end_time = timedelta(seconds=segment['end'])
                    
                    # Apply Thai-specific post-processing to the text
                    processed_text = postprocess_thai_text(segment['text'])
                    
                    # If text is too long, split it into multiple subtitles
                    if len(processed_text) > max_thai_chars_per_subtitle:
                        # Try to find a good breaking point (punctuation or space)
                        break_points = [m.start() for m in re.finditer(r'[.,!?;: ]', processed_text)]
                        
                        # Filter break points to those in the middle section of the text
                        middle_break_points = [p for p in break_points if p > max_thai_chars_per_subtitle/2 and p < max_thai_chars_per_subtitle]
                        
                        if middle_break_points:
                            # Use the break point closest to the max length
                            break_point = min(middle_break_points, key=lambda x: abs(x - max_thai_chars_per_subtitle/2))
                            
                            # Calculate time for the split
                            total_duration = (end_time - start_time).total_seconds()
                            mid_time = start_time + timedelta(seconds=total_duration * (break_point / len(processed_text)))
                            
                            # Create two subtitle entries
                            srt_content.append(
                                srt.Subtitle(
                                    index=i+1,
                                    start=start_time,
                                    end=mid_time,
                                    content=processed_text[:break_point].strip()
                                )
                            )
                            
                            srt_content.append(
                                srt.Subtitle(
                                    index=i+2,
                                    start=mid_time,
                                    end=end_time,
                                    content=processed_text[break_point:].strip()
                                )
                            )
                        else:
                            # If no good break point, just truncate with ellipsis
                            srt_content.append(
                                srt.Subtitle(
                                    index=i+1,
                                    start=start_time,
                                    end=end_time,
                                    content=processed_text[:max_thai_chars_per_subtitle-3] + "..."
                                )
                            )
                    else:
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
                with open(srt_file, "w", encoding="utf-8-sig") as f:
                    f.write(srt.compose(srt_content))
            else:
                # Use standard Whisper SRT writer for non-Thai languages
                with open(srt_file, "w", encoding="utf-8-sig") as f:
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
        
        # Adjust the character rate for Thai language to account for diacritics and tone marks
        if language.lower() in ['th', 'thai']:
            # Thai text needs a much slower rate for better synchronization with voice-over
            chars_per_second = chars_per_second * 0.65  # Slow down the rate by 35%
        
        # Assign timing to each script segment based on its length
        current_time = segments[0]['start']
        
        # Add a small delay at the beginning to ensure subtitles don't start too early
        current_time += 0.3  # 300ms delay
        
        for i, segment in enumerate(script_segments):
            start_time = current_time
            # Calculate duration based on segment length
            segment_duration = len(segment) / chars_per_second
            # Ensure minimum duration
            segment_duration = max(segment_duration, 1.0)
            
            # For Thai language, add extra time for longer segments
            if language.lower() in ['th', 'thai'] and len(segment) > 30:
                # Add 10% more time for each 30 characters over the first 30
                extra_time = (len(segment) - 30) / 30 * 0.1 * segment_duration
                segment_duration += extra_time
            
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
    with open(output_srt_path, "w", encoding="utf-8-sig") as f:
        f.write(srt.compose(srt_content))
    
    logger.info(f"Created aligned SRT file: {output_srt_path}")
    return output_srt_path