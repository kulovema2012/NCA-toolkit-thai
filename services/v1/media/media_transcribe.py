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
        
        # For Thai language, optimize processing to prevent timeouts
        if is_thai:
            logger.info("Thai language detected - using optimized processing settings")
            # Use smaller audio segments for Thai to prevent timeouts
            # Instead of using chunk_size which isn't supported, we'll manually split the audio
            from pydub import AudioSegment
            import tempfile
            
            # Load the audio file
            audio = AudioSegment.from_file(input_filename)
            
            # Split into 5-minute chunks
            chunk_length_ms = 5 * 60 * 1000  # 5 minutes in milliseconds
            
            # Create temporary directory for chunks
            temp_dir = tempfile.mkdtemp()
            chunk_files = []
            
            # Split the audio into chunks
            for i, chunk_start in enumerate(range(0, len(audio), chunk_length_ms)):
                chunk_end = min(chunk_start + chunk_length_ms, len(audio))
                chunk = audio[chunk_start:chunk_end]
                
                # Save the chunk to a temporary file
                chunk_file = os.path.join(temp_dir, f"chunk_{i}.wav")
                chunk.export(chunk_file, format="wav")
                chunk_files.append(chunk_file)
                
                logger.info(f"Created audio chunk {i+1}: {chunk_start/1000}s to {chunk_end/1000}s")
            
            # Process each chunk
            all_segments = []
            full_text = ""
            
            for i, chunk_file in enumerate(chunk_files):
                logger.info(f"Processing chunk {i+1}/{len(chunk_files)}")
                chunk_result = model.transcribe(chunk_file, **options)
                
                # Adjust timestamps for this chunk
                time_offset = i * chunk_length_ms / 1000  # in seconds
                
                for segment in chunk_result['segments']:
                    # Apply a small offset to improve synchronization with voice-over
                    voice_over_offset = -0.2  # 200ms earlier to match voice-over delay in caption_video.py
                    
                    # Apply the offset but ensure we don't go below 0
                    segment['start'] = max(0, segment['start'] + time_offset + voice_over_offset)
                    segment['end'] = max(segment['start'] + 0.8, segment['end'] + time_offset + voice_over_offset)  # Ensure minimum 800ms duration
                    
                    # Ensure maximum duration of 2.0 seconds for better synchronization
                    if segment['end'] - segment['start'] > 2.0:
                        segment['end'] = segment['start'] + 2.0
                    
                    # Adjust word timestamps if present
                    if word_timestamps and 'words' in segment:
                        for word in segment['words']:
                            if 'start' in word:
                                word['start'] = max(0, word['start'] + time_offset + voice_over_offset)
                            if 'end' in word:
                                word['end'] = max(word.get('start', 0) + 0.1, word['end'] + time_offset + voice_over_offset)
                
                # Add segments to the full list
                all_segments.extend(chunk_result['segments'])
                
                # Add text to the full text
                full_text += chunk_result['text'] + " "
            
            # Create a complete result
            result = {
                'text': full_text.strip(),
                'segments': all_segments
            }
            
            # Clean up temporary files
            for chunk_file in chunk_files:
                try:
                    os.remove(chunk_file)
                except Exception as e:
                    logger.warning(f"Failed to remove temporary chunk file {chunk_file}: {str(e)}")
            
            try:
                os.rmdir(temp_dir)
            except Exception as e:
                logger.warning(f"Failed to remove temporary directory {temp_dir}: {str(e)}")
            
        else:
            # For non-Thai languages, use the standard approach
            result = model.transcribe(input_filename, **options)
        
        # Process Thai text to ensure proper encoding and spacing
        if is_thai:
            logger.info("Processing Thai text to ensure proper encoding")
            result['text'] = postprocess_thai_text(result['text'])
            
            # Process segments for Thai text
            for segment in result['segments']:
                if 'text' in segment:
                    segment['text'] = postprocess_thai_text(segment['text'])
                    
                    # Fix common Thai name misspellings
                    segment['text'] = fix_thai_names(segment['text'])
                    
                    # Ensure proper spacing for Thai text
                    segment['text'] = fix_thai_spacing(segment['text'])
        
        # Generate output files
        output_files = {}
        
        if include_text:
            # Generate text file
            text_file = os.path.join(STORAGE_PATH, f"{os.path.splitext(os.path.basename(input_filename))[0]}_{task}.txt")
            with open(text_file, 'w', encoding='utf-8') as f:
                f.write(result['text'])
            output_files['text'] = text_file
        
        if include_srt:
            # Generate SRT file
            srt_file = os.path.join(STORAGE_PATH, f"{os.path.splitext(os.path.basename(input_filename))[0]}_{task}.srt")
            
            # Ensure segments are sorted by start time
            sorted_segments = sorted(result['segments'], key=lambda x: x['start'])
            
            # Add a small gap between segments to prevent blinking
            gap = 0.25  # 250ms gap
            
            # Process segments to ensure proper timing and prevent overlapping
            for i in range(1, len(sorted_segments)):
                prev_segment = sorted_segments[i-1]
                curr_segment = sorted_segments[i]
                
                # If current segment starts before previous ends (plus gap)
                if curr_segment['start'] < prev_segment['end'] + gap:
                    # Adjust current start time to after previous end (plus gap)
                    curr_segment['start'] = prev_segment['end'] + gap
                    
                    # Ensure minimum duration is maintained (800ms)
                    if curr_segment['end'] < curr_segment['start'] + 0.8:
                        curr_segment['end'] = curr_segment['start'] + 0.8
            
            # Generate SRT content
            with open(srt_file, 'w', encoding='utf-8') as f:
                for i, segment in enumerate(sorted_segments, 1):
                    # Format timestamps
                    start_time = format_timestamp(segment['start'])
                    end_time = format_timestamp(segment['end'])
                    
                    # Write SRT entry
                    f.write(f"{i}\n")
                    f.write(f"{start_time} --> {end_time}\n")
                    f.write(f"{segment['text']}\n\n")
            
            output_files['srt'] = srt_file
        
        if include_segments:
            # Generate segments JSON file
            segments_file = os.path.join(STORAGE_PATH, f"{os.path.splitext(os.path.basename(input_filename))[0]}_{task}_segments.json")
            with open(segments_file, 'w', encoding='utf-8') as f:
                json.dump(result['segments'], f, ensure_ascii=False, indent=2)
            output_files['segments'] = segments_file
        
        # Return results based on response_type
        if response_type == 'cloud':
            # Upload files to cloud storage
            cloud_urls = {}
            for file_type, file_path in output_files.items():
                try:
                    from services.cloud_storage import upload_to_cloud_storage
                    cloud_path = f"transcriptions/{os.path.basename(file_path)}"
                    cloud_url = upload_to_cloud_storage(file_path, cloud_path)
                    cloud_urls[file_type] = cloud_url
                except Exception as e:
                    logger.error(f"Failed to upload {file_type} file to cloud storage: {str(e)}")
                    cloud_urls[file_type] = f"file://{file_path}"
            
            return {
                'cloud_urls': cloud_urls,
                'local_paths': output_files,
                'text': result['text'] if include_text else None
            }
        else:
            # Return local file paths
            return {
                'local_paths': output_files,
                'text': result['text'] if include_text else None
            }
    
    except Exception as e:
        logger.error(f"Error in process_transcribe_media: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise

def fix_thai_names(text):
    """Fix common Thai name misspellings"""
    # Common name corrections
    corrections = {
        'แพกซ์ โรมาน่า': 'แพกซ์ โรมานา',
        'แพกซ์โรมาน่า': 'แพกซ์โรมานา',
        'ฮิดเด้น ไทม์ไลน์': 'ฮิดเดน ไทม์ไลน์',
        'ฮิดเด้นไทม์ไลน์': 'ฮิดเดนไทม์ไลน์'
    }
    
    for wrong, correct in corrections.items():
        text = text.replace(wrong, correct)
    
    return text

def fix_thai_spacing(text):
    """Fix spacing issues in Thai text"""
    # Remove spaces between Thai words (but keep spaces between Thai and non-Thai)
    result = ""
    prev_is_thai = False
    
    for char in text:
        is_thai = '\u0E00' <= char <= '\u0E7F'
        
        if char == ' ':
            # Only keep the space if transitioning between Thai and non-Thai
            if not (prev_is_thai and is_thai):
                result += char
        else:
            result += char
            prev_is_thai = is_thai
    
    return result

def format_timestamp(seconds):
    """Format seconds to SRT timestamp format (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"

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