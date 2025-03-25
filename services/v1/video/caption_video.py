import os
import time
import json
import tempfile
import subprocess
import logging
import re
import uuid
import json
import hashlib
import threading
from datetime import datetime, timedelta
import functools
import random
from pathlib import Path
import srt  # For parsing SRT files
from datetime import timedelta
import unicodedata

# Configure logging
logger = logging.getLogger(__name__)

# Import PyThaiNLP for Thai word segmentation
try:
    from pythainlp.tokenize import word_tokenize
    PYTHAINLP_AVAILABLE = True
except ImportError:
    PYTHAINLP_AVAILABLE = False
    logger.warning("PyThaiNLP not available. Using fallback method for Thai word segmentation.")

# Cache for processed videos to avoid redundant processing
# Structure: {cache_key: {'result': result_dict, 'timestamp': datetime, 'path': file_path}}
_video_cache = {}
_cache_lock = threading.Lock()
_CACHE_EXPIRY = timedelta(hours=24)  # Cache entries expire after 24 hours

def _generate_cache_key(video_path, subtitle_path, **kwargs):
    """Generate a unique cache key based on input parameters and file contents."""
    # Get file modification times
    try:
        video_mtime = os.path.getmtime(video_path) if os.path.exists(video_path) else 0
        subtitle_mtime = os.path.getmtime(subtitle_path) if os.path.exists(subtitle_path) else 0
        
        # Create a string with all parameters and modification times
        param_str = f"{video_path}:{video_mtime}:{subtitle_path}:{subtitle_mtime}"
        
        # Add all other parameters to the string
        for key, value in sorted(kwargs.items()):
            param_str += f":{key}={value}"
            
        # Create a hash of the parameter string
        return hashlib.md5(param_str.encode('utf-8')).hexdigest()
    except Exception as e:
        logger.warning(f"Error generating cache key: {str(e)}")
        # If there's an error, return a unique key to avoid cache conflicts
        return str(uuid.uuid4())

def _clean_expired_cache():
    """Remove expired entries from the cache."""
    now = datetime.now()
    with _cache_lock:
        expired_keys = [k for k, v in _video_cache.items() 
                       if now - v.get('timestamp', datetime.min) > _CACHE_EXPIRY]
        
        for key in expired_keys:
            # Try to remove the cached file if it exists
            try:
                cache_path = _video_cache[key].get('path')
                if cache_path and os.path.exists(cache_path):
                    os.remove(cache_path)
            except Exception as e:
                logger.warning(f"Error removing cached file: {str(e)}")
            
            # Remove the cache entry
            del _video_cache[key]
            
        return len(expired_keys)

def cache_result(func):
    """Decorator to cache function results based on input parameters."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Clean expired cache entries periodically
        if random.random() < 0.1:  # 10% chance to clean on each call
            num_cleaned = _clean_expired_cache()
            if num_cleaned > 0:
                logger.info(f"Cleaned {num_cleaned} expired cache entries")
        
        # Extract video_path and subtitle_path from args or kwargs
        if args and len(args) >= 2:
            video_path = args[0]
            subtitle_path = args[1]
        else:
            video_path = kwargs.get('video_path')
            subtitle_path = kwargs.get('subtitle_path')
        
        # Skip caching if paths are not provided
        if not video_path or not subtitle_path:
            return func(*args, **kwargs)
        
        # Create a copy of kwargs without video_path and subtitle_path to avoid duplicate parameters
        cache_kwargs = kwargs.copy()
        cache_kwargs.pop('video_path', None)
        cache_kwargs.pop('subtitle_path', None)
        
        # Generate cache key
        cache_key = _generate_cache_key(video_path, subtitle_path, **cache_kwargs)
        
        # Check if result is in cache
        with _cache_lock:
            if cache_key in _video_cache:
                cache_entry = _video_cache[cache_key]
                cache_path = cache_entry.get('path')
                
                # Verify the cached file still exists
                if cache_path and os.path.exists(cache_path):
                    logger.info(f"Cache hit for {os.path.basename(video_path)} with {os.path.basename(subtitle_path)}")
                    return cache_entry['result']
        
        # Not in cache or cached file missing, call the function
        result = func(*args, **kwargs)
        
        # Store result in cache if successful
        if result and (not isinstance(result, dict) or not result.get('error')):
            with _cache_lock:
                _video_cache[cache_key] = {
                    'result': result,
                    'timestamp': datetime.now(),
                    'path': result.get('local_path') if isinstance(result, dict) else None
                }
                logger.info(f"Cached result for {os.path.basename(video_path)} with {os.path.basename(subtitle_path)}")
        
        return result
    
    return wrapper

@cache_result
def add_subtitles_to_video(video_path, subtitle_path, output_path=None, font_name="Arial", font_size=24, 
                          position="bottom", margin_v=30, subtitle_style="classic", max_width=None,
                          line_color=None, word_color=None, outline_color=None, all_caps=False,
                          max_words_per_line=7, x=None, y=None, alignment="center", bold=False,
                          italic=False, underline=False, strikeout=False, job_id=None):
    """
    Add subtitles to a video using FFmpeg.
    
    Args:
        video_path: Path to the video file
        subtitle_path: Path to the subtitle file (SRT format)
        output_path: Path to save the output video (optional)
        font_name: Font to use for subtitles
        font_size: Font size
        position: Position of subtitles (top, middle, bottom)
        margin_v: Vertical margin from the edge
        subtitle_style: Style of subtitles (classic, modern, karaoke, highlight, underline, word_by_word)
        max_width: Maximum width of subtitle text (in pixels)
        line_color: Color for subtitle text
        word_color: Color for highlighted words
        outline_color: Color for text outline
        all_caps: Whether to capitalize all text
        max_words_per_line: Maximum words per subtitle line
        x: X position for subtitles (overrides position)
        y: Y position for subtitles (overrides position)
        alignment: Text alignment (left, center, right)
        bold: Whether to use bold text
        italic: Whether to use italic text
        underline: Whether to use underlined text
        strikeout: Whether to use strikeout text
        job_id: Job ID for tracking
        
    Returns:
        Path to the output video
    """
    logger.info(f"Adding subtitles to video: {video_path}")
    
    # Determine if subtitles are in Thai
    is_thai = False
    try:
        with open(subtitle_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            # Check for Thai characters
            thai_chars = 'กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮะัาำิีึืุูเแโใไๅ่้๊๋'
            is_thai = any(c in thai_chars for c in content)
            logger.info(f"Detected {'Thai' if is_thai else 'non-Thai'} subtitles")
    except Exception as e:
        logger.warning(f"Error detecting subtitle language: {str(e)}")
    
    # Check if the subtitle file contains Thai text
    try:
        with open(subtitle_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            # Check for Thai characters
            if re.search(r'[ก-๙]', content):
                is_thai = True
                # Use a Thai font if Thai text is detected and no specific font is provided
                if font_name == "Arial":
                    font_name = "Sarabun"  # Default Thai font
                logger.info(f"Thai text detected in subtitles, using font: {font_name}")
    except Exception as e:
        logger.warning(f"Error checking for Thai text: {str(e)}")
    
    # Process the SRT file to improve formatting and prevent overlapping
    processed_subtitle_path = process_srt_file(subtitle_path, max_words_per_line, is_thai)
    
    # Set default output path if not provided
    if not output_path:
        output_path = os.path.splitext(video_path)[0] + "_subtitled" + os.path.splitext(video_path)[1]
    
    # Get video dimensions to calculate proper subtitle positioning and scaling
    video_info = get_video_info(video_path)
    if not video_info:
        logger.error("Failed to get video information")
        return None
    
    video_width = int(video_info.get('width', 1280))
    video_height = int(video_info.get('height', 720))
    
    # Calculate aspect ratio
    aspect_ratio = video_width / video_height
    is_vertical = aspect_ratio < 1.0  # Vertical video like 9:16
    
    # Adjust font size based on video dimensions and orientation
    if is_vertical:
        # For vertical videos (like 9:16), scale font size down
        adjusted_font_size = int(font_size * (video_width / 1080))
        # Increase font size for Thai text to improve readability
        if is_thai:
            adjusted_font_size = int(adjusted_font_size * 1.2)  # 20% larger for Thai
        # Limit maximum width for vertical videos to prevent overflow
        if not max_width:
            max_width = int(video_width * 0.8)  # 80% of video width
    else:
        # For horizontal videos, use standard scaling
        adjusted_font_size = int(font_size * (video_width / 1920))
        # Increase font size for Thai text to improve readability
        if is_thai:
            adjusted_font_size = int(adjusted_font_size * 1.2)  # 20% larger for Thai
        if not max_width:
            max_width = int(video_width * 0.9)  # 90% of video width
    
    logger.info(f"Video dimensions: {video_width}x{video_height}, Adjusted font size: {adjusted_font_size}, Max width: {max_width}")
    
    # Calculate subtitle positioning
    if x is not None and y is not None:
        # Use explicit x,y coordinates if provided
        x_pos = x
        y_pos = y
    else:
        # Calculate based on position parameter
        if position == "top":
            y_pos = margin_v
        elif position == "middle":
            y_pos = video_height // 2
        else:  # bottom (default)
            y_pos = video_height - margin_v
        
        # Center horizontally by default
        x_pos = video_width // 2
    
    # Adjust alignment for FFmpeg
    if alignment == "left":
        align_param = 1
    elif alignment == "right":
        align_param = 2
    else:  # center (default)
        align_param = 0
    
    # Set up font formatting
    font_formatting = ""
    if bold:
        font_formatting += ":fontconfig_pattern=weight=bold"
    if italic:
        font_formatting += ":fontconfig_pattern=slant=italic"
    
    # Set up colors
    if not line_color:
        line_color = "white"
    if not outline_color:
        outline_color = "black"
    if not word_color and subtitle_style in ["highlight", "word_by_word", "karaoke"]:
        word_color = "yellow"
    
    # Set up subtitle filter based on style
    if subtitle_style == "classic":
        # For Thai text, use a different approach to ensure proper rendering
        if is_thai:
            # Use drawtext filter instead of subtitles filter for Thai text
            # First convert SRT to a text file with timecodes
            text_file_path = processed_subtitle_path.replace('.srt', '.txt')
            convert_srt_to_timed_text(processed_subtitle_path, text_file_path)
            
            # Use drawtext filter with the Thai font
            subtitle_filter = f"drawtext=fontfile=/usr/share/fonts/truetype/thai/{font_name}.ttf:fontsize={adjusted_font_size}:fontcolor={line_color}:bordercolor={outline_color}:borderw=2:textfile='{text_file_path}':reload=1:y=h-{margin_v}:x=(w-text_w)/2"
        else:
            # Classic style with simple text - ensure text is visible with proper formatting
            subtitle_filter = f"subtitles='{processed_subtitle_path}':force_style='FontName={font_name},FontSize={adjusted_font_size},PrimaryColour={line_color},OutlineColour={outline_color},BorderStyle=1,Outline=1,Shadow=1,MarginV={margin_v},Alignment={align_param}{font_formatting}'"
    
    elif subtitle_style == "modern":
        # For Thai text, use a different approach to ensure proper rendering
        if is_thai:
            # Use drawtext filter instead of subtitles filter for Thai text
            # First convert SRT to a text file with timecodes
            text_file_path = processed_subtitle_path.replace('.srt', '.txt')
            convert_srt_to_timed_text(processed_subtitle_path, text_file_path)
            
            # Use drawtext filter with the Thai font and a background box
            subtitle_filter = f"drawtext=fontfile=/usr/share/fonts/truetype/thai/{font_name}.ttf:fontsize={adjusted_font_size}:fontcolor={line_color}:bordercolor={outline_color}:borderw=2:box=1:boxcolor=black@0.5:textfile='{text_file_path}':reload=1:y=h-{margin_v}:x=(w-text_w)/2"
        else:
            # Modern style with background box - ensure text is visible with proper background
            subtitle_filter = f"subtitles='{processed_subtitle_path}':force_style='FontName={font_name},FontSize={adjusted_font_size},PrimaryColour={line_color},OutlineColour={outline_color},BackColour=&H80000000,BorderStyle=3,Outline=1,Shadow=1,MarginV={margin_v},Alignment={align_param}{font_formatting}'"
    
    elif subtitle_style in ["highlight", "karaoke", "word_by_word"]:
        # For Thai text with highlight styles, use a different approach
        if is_thai:
            # Use drawtext filter instead of subtitles filter for Thai text
            text_file_path = processed_subtitle_path.replace('.srt', '.txt')
            convert_srt_to_timed_text(processed_subtitle_path, text_file_path)
            
            # For highlight style, use a different color for each word
            if subtitle_style == "highlight":
                subtitle_filter = f"drawtext=fontfile=/usr/share/fonts/truetype/thai/{font_name}.ttf:fontsize={adjusted_font_size}:fontcolor={word_color}:bordercolor={outline_color}:borderw=2:textfile='{text_file_path}':reload=1:y=h-{margin_v}:x=(w-text_w)/2"
            else:
                # For karaoke or word_by_word, use the same approach as classic for now
                subtitle_filter = f"drawtext=fontfile=/usr/share/fonts/truetype/thai/{font_name}.ttf:fontsize={adjusted_font_size}:fontcolor={line_color}:bordercolor={outline_color}:borderw=2:textfile='{text_file_path}':reload=1:y=h-{margin_v}:x=(w-text_w)/2"
        else:
            # For non-Thai text, use the original ASS subtitle approach
            # Convert SRT to ASS first
            ass_subtitle_path = processed_subtitle_path.replace('.srt', '.ass')
            convert_srt_to_ass(processed_subtitle_path, ass_subtitle_path, font_name, adjusted_font_size, 
                             line_color, outline_color, word_color, align_param, margin_v, 
                             subtitle_style, max_width, all_caps, font_formatting)
            subtitle_filter = f"ass='{ass_subtitle_path}'"
    
    elif subtitle_style == "underline":
        # For Thai text with underline style, use drawtext with underline
        if is_thai:
            text_file_path = processed_subtitle_path.replace('.srt', '.txt')
            convert_srt_to_timed_text(processed_subtitle_path, text_file_path)
            
            # Use drawtext filter with underline
            subtitle_filter = f"drawtext=fontfile=/usr/share/fonts/truetype/thai/{font_name}.ttf:fontsize={adjusted_font_size}:fontcolor={line_color}:bordercolor={outline_color}:borderw=2:underline=1:textfile='{text_file_path}':reload=1:y=h-{margin_v}:x=(w-text_w)/2"
        else:
            # Underlined text - ensure text is visible
            subtitle_filter = f"subtitles='{processed_subtitle_path}':force_style='FontName={font_name},FontSize={adjusted_font_size},PrimaryColour={line_color},OutlineColour={outline_color},BorderStyle=1,Outline=1,Shadow=1,MarginV={margin_v},Alignment={align_param},Underline=1{font_formatting}'"
    
    else:
        # Default to classic if style not recognized
        if is_thai:
            # Use drawtext filter for Thai text
            text_file_path = processed_subtitle_path.replace('.srt', '.txt')
            convert_srt_to_timed_text(processed_subtitle_path, text_file_path)
            
            subtitle_filter = f"drawtext=fontfile=/usr/share/fonts/truetype/thai/{font_name}.ttf:fontsize={adjusted_font_size}:fontcolor={line_color}:bordercolor={outline_color}:borderw=2:textfile='{text_file_path}':reload=1:y=h-{margin_v}:x=(w-text_w)/2"
        else:
            # Default to classic if style not recognized - ensure text is visible
            subtitle_filter = f"subtitles='{processed_subtitle_path}':force_style='FontName={font_name},FontSize={adjusted_font_size},PrimaryColour={line_color},OutlineColour={outline_color},BorderStyle=1,Outline=1,Shadow=1,MarginV={margin_v},Alignment={align_param}{font_formatting}'"
    
    # Add voice-over delay of 0.2 seconds for Thai videos to ensure synchronization
    if is_thai:
        voice_over_delay = 0.2
        logger.info(f"Adding voice-over delay of {voice_over_delay}s for Thai video")
        # Use the adelay filter to delay audio
        audio_filter = f"adelay={int(voice_over_delay*1000)}:all=1"
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", video_path, 
            "-filter_complex", f"[0:v]{subtitle_filter}[v];[0:a]{audio_filter}[a]", 
            "-map", "[v]", "-map", "[a]", 
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k",
            output_path
        ]
    else:
        # No audio delay for non-Thai videos
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", video_path, 
            "-vf", subtitle_filter, 
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "copy",
            output_path
        ]
    
    logger.info(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
    
    try:
        # Run FFmpeg
        import subprocess
        result = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return None
        
        logger.info(f"Successfully added subtitles to video: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Error adding subtitles to video: {str(e)}")
        return None

def process_srt_file(subtitle_path, max_words_per_line=7, is_thai=False):
    """
    Process SRT file to improve formatting and prevent overlapping.
    
    Args:
        subtitle_path: Path to the SRT file
        max_words_per_line: Maximum words per line
        is_thai: Whether the subtitles are in Thai
        
    Returns:
        Path to the processed SRT file
    """
    logger.info(f"Processing SRT file: {subtitle_path}")
    
    # Thai language specific constants
    THAI_CONSONANTS = 'กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ'
    THAI_VOWELS = 'ะัาำิีึืุูเแโใไๅ'
    THAI_TONEMARKS = '่้๊๋'
    THAI_CHARS = THAI_CONSONANTS + THAI_VOWELS + THAI_TONEMARKS
    
    # Dictionary of common Thai words that might be incorrectly transcribed
    THAI_WORD_CORRECTIONS = {
        "thaler feet": "ทั้งหมด",
        "stylist": "เรื่องราวของ",
        "Flatast": "ภาพที่น่าสนใจ",
        "pc": "พีซี",
        "Pax Romana": "Pax Romana",
        "Hidden Timelines": "Hidden Timelines"
    }
    
    try:
        # Read the SRT file
        with open(subtitle_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            
        # Parse the SRT content
        subtitles = list(srt.parse(content))
        
        if not subtitles:
            logger.warning("No subtitles found in SRT file")
            return subtitle_path
            
        # Process each subtitle
        processed_subtitles = []
        
        # Maximum characters per line for Thai
        max_thai_chars_per_line = 20  # Further reduced from 25 to prevent horizontal overflow
        
        # Maximum words per line for Thai
        thai_max_words_per_line = 2 if is_thai else max_words_per_line  # Reduced for Thai
        
        # Add a small gap between subtitles to prevent blinking (250ms)
        gap_duration = timedelta(milliseconds=250)  # Increased from 200ms for better separation
        
        # Maximum duration for any subtitle (to ensure voice-over sync)
        max_subtitle_duration = timedelta(seconds=2.0)  # Reduced from 2.5s for tighter sync
        
        # Minimum duration for any subtitle to ensure readability
        min_subtitle_duration = timedelta(milliseconds=800)
        
        # Process subtitles for better synchronization
        for i, subtitle in enumerate(subtitles):
            # Get the text content
            text = subtitle.content
            
            # Replace common incorrect transcriptions with correct Thai words
            if is_thai:
                for incorrect, correct in THAI_WORD_CORRECTIONS.items():
                    text = re.sub(r'\b' + re.escape(incorrect) + r'\b', correct, text, flags=re.IGNORECASE)
            
            # For Thai text, use PyThaiNLP for word segmentation if available
            if is_thai:
                try:
                    from pythainlp.tokenize import word_tokenize
                    
                    # First normalize the text
                    text = unicodedata.normalize('NFC', text)
                    
                    # Detect and process mixed language segments
                    segments = []
                    current_segment = ""
                    current_is_thai = False
                    
                    for char in text:
                        is_thai_char = char in THAI_CHARS
                        
                        # If we're changing language types, process the previous segment
                        if current_segment and is_thai_char != current_is_thai:
                            segments.append(current_segment)
                            current_segment = ""
                        
                        current_segment += char
                        current_is_thai = is_thai_char
                    
                    # Process the last segment
                    if current_segment:
                        segments.append(current_segment)
                    
                    # Process each segment for word tokenization
                    processed_segments = []
                    for segment in segments:
                        if any(c in THAI_CHARS for c in segment):
                            # Thai segment - tokenize and join
                            words = word_tokenize(segment)
                            processed_segments.append(words)
                        else:
                            # Non-Thai segment - split by spaces
                            words = segment.split()
                            processed_segments.append(words)
                    
                    # Flatten the list of words
                    all_words = [word for segment in processed_segments for word in segment]
                    
                    # If we have too many words, create multiple subtitles
                    if len(all_words) > thai_max_words_per_line * 2:
                        # Calculate how many subtitles we need
                        num_subtitles = (len(all_words) + thai_max_words_per_line - 1) // thai_max_words_per_line
                        
                        # Calculate duration for each subtitle
                        total_duration = (subtitle.end - subtitle.start).total_seconds()
                        duration_per_subtitle = total_duration / num_subtitles
                        
                        # Create multiple subtitles
                        for j in range(num_subtitles):
                            start_idx = j * thai_max_words_per_line
                            end_idx = min((j + 1) * thai_max_words_per_line, len(all_words))
                            
                            # Get words for this subtitle
                            subtitle_words = all_words[start_idx:end_idx]
                            
                            # Join Thai words without spaces, but keep spaces for non-Thai
                            subtitle_text = ""
                            for word in subtitle_words:
                                # Add space only for non-Thai characters
                                if any(ord(c) < 0x0E00 or ord(c) > 0x0E7F for c in word):
                                    subtitle_text += " " + word
                                else:
                                    subtitle_text += word
                            
                            # Calculate timing for this subtitle
                            start_time = subtitle.start + timedelta(seconds=j * duration_per_subtitle)
                            end_time = min(subtitle.start + timedelta(seconds=(j + 1) * duration_per_subtitle), subtitle.end)
                            
                            # Ensure we don't exceed max duration
                            if end_time - start_time > max_subtitle_duration:
                                end_time = start_time + max_subtitle_duration
                            
                            # Ensure minimum duration
                            if end_time - start_time < min_subtitle_duration:
                                end_time = start_time + min_subtitle_duration
                            
                            # Add gap if not the last subtitle
                            if j < num_subtitles - 1:
                                end_time = end_time - gap_duration
                            
                            # Create subtitle
                            processed_subtitles.append(
                                srt.Subtitle(
                                    index=len(processed_subtitles) + 1,
                                    start=start_time,
                                    end=end_time,
                                    content=subtitle_text
                                )
                            )
                    else:
                        # Split into lines with max_words_per_line
                        if len(all_words) > thai_max_words_per_line:
                            lines = []
                            for j in range(0, len(all_words), thai_max_words_per_line):
                                line_words = all_words[j:j+thai_max_words_per_line]
                                # Join Thai words without spaces, but keep spaces for non-Thai
                                line = ""
                                for word in line_words:
                                    if any(c in THAI_CHARS for c in word):
                                        line += word
                                    else:
                                        if line and not line.endswith(" "):
                                            line += " "
                                        line += word
                                lines.append(line)
                            text = '\n'.join(lines)
                        else:
                            # Join all words appropriately
                            text = ""
                            for word in all_words:
                                if any(c in THAI_CHARS for c in word):
                                    text += word
                                else:
                                    if text and not text.endswith(" "):
                                        text += " "
                                    text += word
                        
                        # Ensure subtitle duration is not too long
                        end_time = subtitle.end
                        if subtitle.end - subtitle.start > max_subtitle_duration:
                            end_time = subtitle.start + max_subtitle_duration
                        
                        # Ensure minimum duration
                        if end_time - subtitle.start < min_subtitle_duration:
                            end_time = subtitle.start + min_subtitle_duration
                        
                        # Create a single subtitle
                        processed_subtitles.append(
                            srt.Subtitle(
                                index=len(processed_subtitles) + 1,
                                start=subtitle.start,
                                end=end_time,
                                content=text
                            )
                        )
                    
                    logger.info(f"Used PyThaiNLP for word segmentation: {len(all_words)} words")
                    
                    # Skip to the next subtitle since we've already processed this one
                    continue
                except ImportError:
                    # Fallback to character-based splitting
                    if len(text) > max_thai_chars_per_line:
                        lines = []
                        # Try to split at spaces or punctuation
                        split_points = [m.start() for m in re.finditer(r'[.,!?;: ]', text)]
                        
                        current_pos = 0
                        while current_pos < len(text):
                            # Find the best split point within the character limit
                            end_pos = min(current_pos + max_thai_chars_per_line, len(text))
                            
                            # Look for a good split point
                            good_splits = [p for p in split_points if p > current_pos and p < end_pos]
                            
                            if good_splits:
                                # Use the last good split point
                                split_at = max(good_splits)
                                lines.append(text[current_pos:split_at].strip())
                                current_pos = split_at
                            else:
                                # No good split point, just use the max length
                                lines.append(text[current_pos:end_pos].strip())
                                current_pos = end_pos
                        
                        text = '\n'.join(lines)
                except Exception as e:
                    logger.warning(f"Error during Thai word segmentation: {str(e)}")
            else:
                # For non-Thai text, split by words
                words = text.split()
                if len(words) > max_words_per_line:
                    lines = []
                    for j in range(0, len(words), max_words_per_line):
                        line = ' '.join(words[j:j+max_words_per_line])
                        lines.append(line)
                    text = '\n'.join(lines)
            
            # Ensure subtitle duration is not too long
            end_time = subtitle.end
            if subtitle.end - subtitle.start > max_subtitle_duration:
                end_time = subtitle.start + max_subtitle_duration
            
            # Ensure minimum duration
            if end_time - subtitle.start < min_subtitle_duration:
                end_time = subtitle.start + min_subtitle_duration
            
            # Add a gap between this subtitle and the next one
            if i < len(subtitles) - 1:
                next_start = subtitles[i+1].start
                if end_time + gap_duration < next_start:
                    # End this subtitle earlier to create a gap
                    end_time = end_time
                else:
                    # Adjust both this end time and next start time
                    middle_point = end_time + (next_start - end_time) / 2
                    end_time = middle_point - gap_duration / 2
                    # We'll adjust the next subtitle's start time when we process it
            
            # Create a new subtitle with the processed text
            processed_subtitles.append(
                srt.Subtitle(
                    index=len(processed_subtitles) + 1,
                    start=subtitle.start,
                    end=end_time,
                    content=text
                )
            )
            
            # If not the last subtitle, adjust the start time of the next subtitle
            if i < len(subtitles) - 1 and end_time + gap_duration > subtitles[i+1].start:
                subtitles[i+1] = srt.Subtitle(
                    index=subtitles[i+1].index,
                    start=end_time + gap_duration,
                    end=subtitles[i+1].end,
                    content=subtitles[i+1].content
                )
        
        # Sort subtitles by start time to ensure proper ordering
        processed_subtitles.sort(key=lambda x: x.start)
        
        # Renumber subtitles
        for i, sub in enumerate(processed_subtitles):
            processed_subtitles[i] = srt.Subtitle(
                index=i+1,
                start=sub.start,
                end=sub.end,
                content=sub.content
            )
        
        # Write the processed SRT file
        processed_path = subtitle_path.replace('.srt', '_processed.srt')
        with open(processed_path, 'w', encoding='utf-8-sig') as f:
            f.write(srt.compose(processed_subtitles))
            
        logger.info(f"Created processed SRT file: {processed_path}")
        return processed_path
        
    except Exception as e:
        logger.error(f"Error processing SRT file: {str(e)}")
        return subtitle_path

def get_video_info(video_path):
    try:
        import subprocess
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-print_format", "json", video_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"FFprobe error: {result.stderr}")
            return None
        video_info = json.loads(result.stdout)
        for stream in video_info['streams']:
            if stream['codec_type'] == 'video':
                return {
                    'width': stream['width'],
                    'height': stream['height']
                }
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}")
        return None

def convert_srt_to_ass(srt_path, ass_path, font_name, font_size, line_color, outline_color, word_color, alignment, margin_v, subtitle_style, max_width, all_caps, font_formatting):
    try:
        import pysubs2
        subs = pysubs2.load(srt_path, encoding="utf-8")
        
        style = pysubs2.SSAStyle()
        style.fontname = font_name
        style.fontsize = font_size
        style.primarycolor = line_color
        style.outlinecolor = outline_color
        style.backcolor = "&H80000000"  # Semi-transparent black background
        style.bold = False
        style.italic = False
        style.underline = False
        style.strikeout = False
        style.scalex = 100
        style.scaley = 100
        style.spacing = 0
        style.angle = 0
        style.borderstyle = 1
        style.outline = 1
        style.shadow = 0
        style.alignment = alignment
        style.marginl = 10
        style.marginr = 10
        style.marginv = margin_v
        
        subs.styles["Default"] = style
        
        if subtitle_style == "highlight":
            # Highlight style: yellow background for highlighted words
            for line in subs:
                for word in line.text.split():
                    if word.startswith("\\"):
                        # Skip formatting tags
                        continue
                    line.text = line.text.replace(word, f"{{\\1c&H{word_color}&}}{word}{{\\r}}")
        
        elif subtitle_style == "karaoke":
            # Karaoke style: fill in the text as it's sung
            for line in subs:
                words = line.text.split()
                duration = (line.end - line.start).total_seconds()
                word_duration = duration / len(words)
                start_time = line.start
                for word in words:
                    if word.startswith("\\"):
                        # Skip formatting tags
                        continue
                    end_time = start_time + timedelta(seconds=word_duration)
                    line.text = line.text.replace(word, f"{{\\t({start_time.total_seconds()}, {end_time.total_seconds()})\\1c&H{word_color}&}}{word}{{\\r}}")
                    start_time = end_time
        
        elif subtitle_style == "word_by_word":
            # Word by word style: display one word at a time
            for line in subs:
                words = line.text.split()
                duration = (line.end - line.start).total_seconds()
                word_duration = duration / len(words)
                start_time = line.start
                for word in words:
                    if word.startswith("\\"):
                        # Skip formatting tags
                        continue
                    end_time = start_time + timedelta(seconds=word_duration)
                    line.text = line.text.replace(word, f"{{\\t({start_time.total_seconds()}, {end_time.total_seconds()})\\1c&H{word_color}&}}{word}{{\\r}}")
                    start_time = end_time
        
        subs.save(ass_path, encoding="utf-8")
        
    except Exception as e:
        logger.error(f"Error converting SRT to ASS: {str(e)}")

def convert_srt_to_timed_text(srt_path, text_path):
    try:
        with open(srt_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        subs = list(srt.parse(content))
        
        with open(text_path, 'w', encoding='utf-8') as f:
            for sub in subs:
                start_time = sub.start.total_seconds()
                end_time = sub.end.total_seconds()
                text = sub.content
                f.write(f"{start_time}:{end_time}:{text}\n")
        
    except Exception as e:
        logger.error(f"Error converting SRT to timed text: {str(e)}")

def process_captioning_v1(video_url, captions, settings=None, job_id=None, webhook_url=None):
    """
    Process video captioning request with enhanced Thai language support.
    
    Args:
        video_url (str): URL of the video to be captioned
        captions (str): Caption text or path to caption file
        settings (dict): Dictionary of settings for captioning
        job_id (str): Unique identifier for the job
        webhook_url (str): URL to call when processing is complete
        
    Returns:
        dict: Result containing file_url, local_path, and processing_time
    """
    try:
        import tempfile
        import os
        import uuid
        import requests
        from urllib.parse import urlparse
        
        # Create a job ID if not provided
        if job_id is None:
            job_id = str(uuid.uuid4())
            
        logger.info(f"Job {job_id}: Starting caption processing")
        
        # Create temp directory for processing
        temp_dir = tempfile.mkdtemp()
        
        # Initialize settings if not provided
        if not settings:
            settings = {}
            
        # Download video if it's a URL
        video_path = None
        if video_url.startswith(('http://', 'https://')):
            # Extract filename from URL
            parsed_url = urlparse(video_url)
            video_filename = os.path.basename(parsed_url.path)
            if not video_filename:
                video_filename = f"{job_id}_video.mp4"
                
            # Download the video
            video_path = os.path.join(temp_dir, video_filename)
            logger.info(f"Job {job_id}: Downloading video from {video_url}")
            
            response = requests.get(video_url, stream=True)
            if response.status_code == 200:
                with open(video_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info(f"Job {job_id}: Video downloaded to {video_path}")
            else:
                logger.error(f"Job {job_id}: Failed to download video, status code: {response.status_code}")
                return {"error": "Failed to download video"}
        else:
            # Assume video_url is a local path
            video_path = video_url
            
        # Process captions - could be text or a file path
        subtitle_path = None
        if os.path.exists(captions):
            # If captions is a file path, use it directly
            subtitle_path = captions
        else:
            # If captions is text, create an SRT file
            subtitle_path = os.path.join(temp_dir, f"{job_id}_captions.srt")
            
            # Simple conversion of text to SRT format if it's not already in SRT format
            if not captions.strip().startswith('1\n'):
                # Create a basic SRT with one entry
                with open(subtitle_path, 'w', encoding='utf-8') as f:
                    f.write("1\n00:00:00,000 --> 00:05:00,000\n" + captions)
            else:
                # Already in SRT format
                with open(subtitle_path, 'w', encoding='utf-8') as f:
                    f.write(captions)
                    
            logger.info(f"Job {job_id}: Created subtitle file at {subtitle_path}")
            
        # Prepare output path
        output_path = os.path.join(temp_dir, f"{job_id}_captioned.mp4")
        
        # Extract settings
        font_name = settings.get('font_name', 'Arial')
        font_size = settings.get('font_size', 24)
        margin_v = settings.get('margin_v', 40)
        subtitle_style = settings.get('subtitle_style', 'classic')
        max_width = settings.get('max_width', None)
        position = settings.get('position', 'bottom')
        max_words_per_line = settings.get('max_words_per_line', None)
        line_color = settings.get('line_color', None)
        word_color = settings.get('word_color', None)
        outline_color = settings.get('outline_color', None)
        all_caps = settings.get('all_caps', False)
        x = settings.get('x', None)
        y = settings.get('y', None)
        alignment = settings.get('alignment', 'center')
        bold = settings.get('bold', False)
        italic = settings.get('italic', False)
        underline = settings.get('underline', False)
        strikeout = settings.get('strikeout', False)
        
        # Special handling for Thai text
        if contains_thai(subtitle_path):
            logger.info(f"Job {job_id}: Thai text detected, applying Thai-specific settings")
            
            # Use Thai font if not specified
            if 'font_name' not in settings:
                # Check if we're using the premium style
                if subtitle_style == 'premium':
                    font_name = 'Waree'  # Best for tone marks
                else:
                    font_name = 'Sarabun'  # Good general Thai font
                    
            # Adjust words per line for Thai if not specified
            if 'max_words_per_line' not in settings:
                max_words_per_line = 3  # Thai words are often longer
                
            # Add a small delay for better sync with Thai audio if not specified
            if 'delay' not in settings:
                settings['delay'] = -0.3  # 0.3 second earlier
        
        # Add subtitles to video
        result = add_subtitles_to_video(
            video_path=video_path,
            subtitle_path=subtitle_path,
            output_path=output_path,
            font_name=font_name,
            font_size=font_size,
            position=position,
            margin_v=margin_v,
            subtitle_style=subtitle_style,
            max_width=max_width,
            line_color=line_color,
            word_color=word_color,
            outline_color=outline_color,
            all_caps=all_caps,
            max_words_per_line=max_words_per_line,
            x=x,
            y=y,
            alignment=alignment,
            bold=bold,
            italic=italic,
            underline=underline,
            strikeout=strikeout,
            job_id=job_id
        )
        
        if not result:
            logger.error(f"Job {job_id}: Failed to add subtitles to video")
            return {"error": "Failed to add subtitles to video"}
            
        # Call webhook if provided
        if webhook_url:
            try:
                webhook_payload = {
                    "job_id": job_id,
                    "status": "completed",
                    "result": result
                }
                requests.post(webhook_url, json=webhook_payload)
                logger.info(f"Job {job_id}: Webhook called successfully")
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to call webhook: {str(e)}")
        
        return result
        
    except Exception as e:
        logger.error(f"Job {job_id}: Error in process_captioning_v1: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Call webhook with error if provided
        if webhook_url:
            try:
                webhook_payload = {
                    "job_id": job_id,
                    "status": "failed",
                    "error": str(e)
                }
                requests.post(webhook_url, json=webhook_payload)
            except:
                pass
                
        return {"error": str(e)}

def contains_thai(s):
    """Check if a string or file contains Thai characters."""
    if os.path.exists(s):
        try:
            with open(s, 'r', encoding='utf-8') as f:
                content = f.read()
                thai_range = range(0x0E00, 0x0E7F)
                return any(ord(c) in thai_range for c in content)
        except Exception as e:
            logger.warning(f"Error checking Thai content in file: {str(e)}")
            return False
    else:
        thai_range = range(0x0E00, 0x0E7F)
        return any(ord(c) in thai_range for c in s)
