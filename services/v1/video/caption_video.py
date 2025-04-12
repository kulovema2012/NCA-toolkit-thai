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
import glob

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

def convert_srt_to_ass_for_thai(srt_path, font_name=None, font_size=24, primary_color="white", outline_color="black", back_color=None, alignment=2, margin_v=30, max_words_per_line=7, max_width=None):
    """
    Convert SRT subtitles to ASS format with special handling for Thai text.
    """
    try:
        logger.info(f"=== STARTING SRT TO ASS CONVERSION FOR THAI ===")
        logger.info(f"Converting SRT to ASS for Thai: {srt_path}")
        logger.debug(f"Parameters: font_name={font_name}, font_size={font_size}, margin_v={margin_v}")
        logger.debug(f"Colors: primary_color={primary_color}, outline_color={outline_color}, back_color={back_color}")
        logger.debug(f"Text formatting: alignment={alignment}, max_words_per_line={max_words_per_line}, max_width={max_width}")
        
        # Get the best available Thai font if none specified
        if not font_name:
            font_name = get_available_thai_font()
            logger.info(f"Using detected Thai font: {font_name}")
        
        # Parse the SRT file
        with open(srt_path, 'r', encoding='utf-8-sig') as f:
            srt_content = f.read()
            logger.debug(f"Read SRT file, content length: {len(srt_content)} bytes")
            subs = list(srt.parse(srt_content))
            logger.info(f"Parsed {len(subs)} subtitle entries from SRT file")
        
        # Create ASS file path
        ass_path = os.path.splitext(srt_path)[0] + '.ass'
        logger.info(f"Will create ASS file at: {ass_path}")
        
        # Write ASS file
        with open(ass_path, 'w', encoding='utf-8') as f:
            logger.debug("Writing ASS file header")
            # Write ASS header
            f.write("[Script Info]\n")
            f.write("Title: Auto-generated Thai subtitles\n")
            f.write("ScriptType: v4.00+\n")
            f.write("WrapStyle: 0\n")
            f.write("ScaledBorderAndShadow: yes\n")
            f.write("YCbCr Matrix: TV.601\n")
            f.write("PlayResX: 1920\n")  # Increased resolution for better scaling
            f.write("PlayResY: 1080\n\n")  # Increased resolution for better scaling
            
            # Convert colors to ASS format if needed
            logger.debug("Converting colors to ASS format")
            if primary_color.startswith('#'):
                primary_color = primary_color.lstrip('#')
                if len(primary_color) == 6:
                    r, g, b = primary_color[0:2], primary_color[2:4], primary_color[4:6]
                    primary_color = f"&H00{b}{g}{r}"
                    logger.debug(f"Converted primary_color to ASS format: {primary_color}")
            else:
                # Handle named colors
                if primary_color.lower() == "white":
                    primary_color = "&H00FFFFFF"
            
            if outline_color.startswith('#'):
                outline_color = outline_color.lstrip('#')
                if len(outline_color) == 6:
                    r, g, b = outline_color[0:2], outline_color[2:4], outline_color[4:6]
                    outline_color = f"&H00{b}{g}{r}"
                    logger.debug(f"Converted outline_color to ASS format: {outline_color}")
            else:
                # Handle named colors
                if outline_color.lower() == "black":
                    outline_color = "&H00000000"
            
            # Set back color to semi-transparent black if not specified
            if not back_color:
                back_color = "&H80000000"  # 50% transparent black
                logger.debug("No back_color specified, using semi-transparent black")
            elif not back_color.startswith("&H"):
                if back_color.startswith('#'):
                    back_color = back_color.lstrip('#')
                    if len(back_color) == 8:  # With alpha
                        a, r, g, b = back_color[0:2], back_color[2:4], back_color[4:6], back_color[6:8]
                        back_color = f"&H{a}{b}{g}{r}"
                    elif len(back_color) == 6:  # Without alpha
                        r, g, b = back_color[0:2], back_color[2:4], back_color[4:6]
                        back_color = f"&H80{b}{g}{r}"  # Add 50% transparency
                    logger.debug(f"Converted back_color to ASS format: {back_color}")
            
            # Determine border style - use 4 for box with background
            border_style = 4  # Box with background for Thai text
            
            # Determine outline size - increase for better visibility
            outline_size = 3.5  # Thicker outline for Thai text
            
            logger.debug("Writing ASS styles section")
            # Write Styles
            f.write("[V4+ Styles]\n")
            f.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
            
            # Always use bold=1 for Thai text to improve readability
            # Use BorderStyle=4 for box with background
            # Explicitly set MarginV to the provided value
            style_line = f"Style: Default,{font_name},{font_size},{primary_color},{primary_color},{outline_color},{back_color},1,0,0,0,100,100,0,0,{border_style},{outline_size},2,{alignment},20,20,{margin_v},1\n\n"
            f.write(style_line)
            logger.debug(f"Wrote style line: {style_line.strip()}")
            
            logger.debug("Writing ASS events section")
            # Write Events
            f.write("[Events]\n")
            f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            
            # Process each subtitle
            processed_count = 0
            for sub in subs:
                # Convert start and end times to ASS format (h:mm:ss.cc)
                start_time = format_time_ass(sub.start.total_seconds())
                end_time = format_time_ass(sub.end.total_seconds())
                
                # Process Thai text with proper word segmentation
                if PYTHAINLP_AVAILABLE:
                    try:
                        from pythainlp.tokenize import word_tokenize
                        
                        logger.debug(f"Processing subtitle text: '{sub.content}'")
                        # Tokenize Thai text
                        words = word_tokenize(sub.content, engine="newmm")
                        logger.debug(f"Tokenized into {len(words)} words using PyThaiNLP")
                        
                        # For Thai, use a more conservative max_width to ensure text fits
                        if not max_width:
                            max_width = 40  # Default max width for Thai
                        
                        # Increase max_words_per_line for Thai to ensure more text is displayed
                        if max_words_per_line < 10:
                            max_words_per_line = 10  # Ensure we show more words per line for Thai
                        
                        # Apply line breaks based on max_words_per_line or max_width
                        lines = []
                        current_line = ""
                        current_word_count = 0
                        
                        for word in words:
                            # Check if adding this word would exceed max width or max words
                            if (max_width and len(current_line) + len(word) > max_width) or \
                               (max_words_per_line and current_word_count >= max_words_per_line):
                                lines.append(current_line)
                                current_line = word
                                current_word_count = 1
                            else:
                                if current_line:
                                    current_line += word
                                else:
                                    current_line = word
                                current_word_count += 1
                        
                        if current_line:
                            lines.append(current_line)
                        
                        # Join lines with ASS line break
                        text = "\\N".join(lines)
                        logger.debug(f"Processed Thai text into {len(lines)} lines")
                        
                    except Exception as e:
                        logger.error(f"Error in Thai word segmentation: {str(e)}")
                        text = sub.content
                        logger.warning(f"Using original text due to segmentation error")
                else:
                    # Fallback if PyThaiNLP is not available
                    text = sub.content
                    logger.warning("PyThaiNLP not available, using original text without word segmentation")
                
                # Add text styling for better visibility
                # Add a border box around the text and make it bold
                styled_text = "{\\bord3.5\\shad2\\b1}" + text
                
                # Write dialogue line with explicit MarginV
                dialogue_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,{margin_v},,{styled_text}\n"
                f.write(dialogue_line)
                processed_count += 1
                
                if processed_count % 10 == 0:
                    logger.debug(f"Processed {processed_count}/{len(subs)} subtitle entries")
        
        logger.info(f"Successfully converted SRT to ASS for Thai at {ass_path}")
        logger.info(f"Total subtitles processed: {processed_count}")
        return ass_path
        
    except Exception as e:
        logger.error(f"Error converting SRT to ASS for Thai: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

def get_available_thai_font():
    """
    Find an available Thai font on the system.
    
    Returns:
        Name of an available Thai font, or a default font if none found
    """
    logger.info("Searching for available Thai fonts")
    
    # Use our new find_thai_fonts function
    thai_fonts = find_thai_fonts()
    
    if thai_fonts:
        # Use the first found Thai font
        font_path = thai_fonts[0]
        logger.info(f"Using Thai font: {font_path}")
        return font_path
    
    # If no fonts found, try common font names that might be available
    common_thai_fonts = [
        "Sarabun", 
        "THSarabun", 
        "TH Sarabun New", 
        "Noto Sans Thai", 
        "Garuda",
        "Norasi",
        "Waree",
        "Loma",
        "Kinnari"
    ]
    
    logger.info(f"No Thai font files found. Trying common Thai font names: {common_thai_fonts}")
    return common_thai_fonts[0]  # Return the first common Thai font name

# Remove the cache_result decorator to ensure parameter changes are recognized
def add_subtitles_to_video(video_path, subtitle_path, output_path=None, font_name="Arial", font_size=24, 
                          position="bottom", margin_v=30, subtitle_style="classic", max_width=None,
                          line_color=None, word_color=None, outline_color=None, all_caps=False,
                          max_words_per_line=7, x=None, y=None, alignment="center", bold=False,
                          italic=False, underline=False, strikeout=False, shadow=None, outline=None,
                          back_color=None, margin_l=None, margin_r=None, encoding=None, job_id=None):
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
        word_color: Color for highlighted words (for karaoke/highlight styles)
        outline_color: Color for text outline
        all_caps: Whether to capitalize all text
        max_words_per_line: Maximum words per line
        x: X position for subtitles (overrides position)
        y: Y position for subtitles (overrides position)
        alignment: Text alignment (left, center, right)
        bold: Whether to use bold text
        italic: Whether to use italic text
        underline: Whether to use underlined text
        strikeout: Whether to use strikeout text
        shadow: Shadow depth for text
        outline: Outline width for text
        back_color: Background color for subtitles
        margin_l: Left margin for subtitles
        margin_r: Right margin for subtitles
        encoding: Encoding for subtitles
        job_id: Unique identifier for the job
    
    Returns:
        Path to the output video with subtitles
    """
    start_time = time.time()
    
    if job_id is None:
        job_id = str(uuid.uuid4())
    
    logger.info(f"Job {job_id}: Starting add_subtitles_to_video process")
    logger.info(f"Job {job_id}: Input video: {video_path}")
    logger.info(f"Job {job_id}: Subtitle file: {subtitle_path}")
    
    # Validate input files
    if not os.path.exists(video_path):
        logger.error(f"Job {job_id}: Video file does not exist: {video_path}")
        return None
    
    if not os.path.exists(subtitle_path):
        logger.error(f"Job {job_id}: Subtitle file does not exist: {subtitle_path}")
        return None
    
    # Set default output path if not provided
    if output_path is None:
        output_dir = os.path.dirname(video_path)
        output_filename = f"captioned_{os.path.basename(video_path)}"
        output_path = os.path.join(output_dir, output_filename)
    
    logger.info(f"Job {job_id}: Output path: {output_path}")
    
    # Process subtitle file to improve formatting
    logger.info(f"Job {job_id}: Processing subtitle file")
    
    # Check if the subtitle file is in Thai
    is_thai = contains_thai(subtitle_path)
    logger.info(f"Job {job_id}: Subtitle file contains Thai text: {is_thai}")
    
    # Process SRT file to improve formatting
    processed_srt_path = process_srt_file(subtitle_path, max_words_per_line=max_words_per_line, is_thai=is_thai)
    logger.info(f"Job {job_id}: Processed SRT file: {processed_srt_path}")
    
    # Set default font for Thai if needed
    if is_thai and font_name in ["Arial", "Helvetica", "Times New Roman"]:
        font_name = get_available_thai_font()
        logger.info(f"Job {job_id}: Using Thai font: {font_name}")
    
    # Set default colors if not provided
    if line_color is None:
        line_color = "white"
    if outline_color is None:
        outline_color = "black"
    
    logger.info(f"Job {job_id}: Font settings - name: {font_name}, size: {font_size}, color: {line_color}")
    logger.info(f"Job {job_id}: Style settings - style: {subtitle_style}, position: {position}, alignment: {alignment}")
    
    # Convert alignment string to number if needed
    if isinstance(alignment, str):
        alignment_map = {
            "left": 1,
            "center": 2,
            "right": 3
        }
        alignment = alignment_map.get(alignment.lower(), 2)
        logger.info(f"Job {job_id}: Converted alignment to: {alignment}")
    
    # Prepare font formatting options
    font_formatting = {
        "bold": bold,
        "italic": italic,
        "underline": underline,
        "strikeout": strikeout
    }
    
    logger.info(f"Job {job_id}: Font formatting: {font_formatting}")
    
    # Convert SRT to ASS for better styling
    ass_path = processed_srt_path.replace(".srt", ".ass")
    
    if is_thai:
        logger.info(f"Job {job_id}: Converting SRT to ASS with Thai text handling")
        convert_srt_to_ass_for_thai(
            processed_srt_path,
            font_name=font_name,
            font_size=font_size,
            primary_color=line_color,
            outline_color=outline_color,
            back_color=back_color,
            alignment=alignment,
            margin_v=margin_v,
            max_words_per_line=max_words_per_line,
            max_width=max_width
        )
    else:
        logger.info(f"Job {job_id}: Converting SRT to ASS with standard text handling")
        convert_srt_to_ass(
            processed_srt_path,
            ass_path,
            font_name=font_name,
            font_size=font_size,
            line_color=line_color,
            outline_color=outline_color,
            word_color=word_color,
            alignment=alignment,
            margin_v=margin_v,
            subtitle_style=subtitle_style,
            max_width=max_width,
            all_caps=all_caps,
            font_formatting=font_formatting
        )
    
    # Ensure ASS file exists
    if not os.path.exists(ass_path):
        logger.error(f"Job {job_id}: Failed to create ASS file")
        return None
    
    logger.info(f"Job {job_id}: ASS file created: {ass_path}")
    
    # Get video info
    video_info = get_video_info(video_path)
    if video_info:
        video_width = video_info.get("width", 1920)
        video_height = video_info.get("height", 1080)
        logger.info(f"Job {job_id}: Video dimensions: {video_width}x{video_height}")
    else:
        logger.warning(f"Job {job_id}: Could not get video info, using default dimensions")
        video_width = 1920
        video_height = 1080
    
    # Calculate subtitle position
    if x is not None and y is not None:
        # Use custom position
        subtitle_position = f"{x}:{y}"
        logger.info(f"Job {job_id}: Using custom subtitle position: {subtitle_position}")
    else:
        # Calculate position based on position parameter
        if position == "top":
            y_pos = margin_v
        elif position == "middle":
            y_pos = video_height // 2
        else:  # bottom
            y_pos = video_height - margin_v
        
        subtitle_position = f"(w-text_w)/2:{y_pos}"
        logger.info(f"Job {job_id}: Using calculated subtitle position: {subtitle_position} (based on '{position}')")
    
    # Prepare FFmpeg command
    ffmpeg_cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        "-y",
        output_path
    ]
    
    logger.info(f"Job {job_id}: FFmpeg command: {' '.join(ffmpeg_cmd)}")
    
    # Execute FFmpeg command
    try:
        logger.info(f"Job {job_id}: Executing FFmpeg command")
        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            logger.error(f"Job {job_id}: FFmpeg error: {stderr.decode('utf-8', errors='ignore')}")
            return None
        
        logger.info(f"Job {job_id}: FFmpeg completed successfully")
        
        # Check if output file exists
        if not os.path.exists(output_path):
            logger.error(f"Job {job_id}: Output file does not exist after FFmpeg: {output_path}")
            return None
        
        # Calculate processing time
        end_time = time.time()
        processing_time = end_time - start_time
        logger.info(f"Job {job_id}: Subtitles added successfully in {processing_time:.2f} seconds")
        
        return output_path
    
    except Exception as e:
        logger.error(f"Job {job_id}: Error adding subtitles to video: {str(e)}")
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
    THAI_VOWELS = 'ะัาำิีึืุูเแโใไ'
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
                            # Text is short enough, no need to split
                            lines = [text]
                        
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
                    logger.warning("ImportError in Thai word segmentation, falling back to character-based splitting")
                    lines = []
                    if len(text) > 25:
                        # Try to split at spaces or punctuation
                        split_points = [m.start() for m in re.finditer(r'[.,!?;: ]', text)]
                        
                        current_pos = 0
                        while current_pos < len(text):
                            # Find the best split point within the character limit
                            end_pos = min(current_pos + 25, len(text))
                            
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
                    else:
                        # Text is short enough, no need to split
                        lines = [text]
                        
                    # Join the lines with newline character
                    text = "\\N".join(lines)
                    logger.info(f"Applied character-based splitting, resulting in {len(lines)} lines")
                except Exception as e:
                    # Catch any other exceptions and log them
                    logger.error(f"Error in Thai word processing: {str(e)}")
                    # Don't modify the text in case of other errors
                    logger.warning("Keeping original text due to processing error")
            else:
                # For non-Thai text, split by words
                words = text.split()
                lines = []
                if len(words) > max_words_per_line:
                    for j in range(0, len(words), max_words_per_line):
                        line = ' '.join(words[j:j+max_words_per_line])
                        lines.append(line)
                    text = "\\N".join(lines)
                else:
                    # Text is short enough, no need to split
                    lines = [text]
            
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
        shadow = settings.get('shadow', None)
        outline = settings.get('outline', None)
        back_color = settings.get('back_color', None)
        
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
            shadow=shadow,
            outline=outline,
            back_color=back_color,
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

def format_time_ass(time_in_seconds):
    """Format time in seconds to ASS format (h:mm:ss.cc)."""
    hours = int(time_in_seconds // 3600)
    minutes = int((time_in_seconds % 3600) // 60)
    seconds = int(time_in_seconds % 60)
    centiseconds = int((time_in_seconds % 1) * 100)
    
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"

def add_subtitles_to_video(video_path, subtitle_path, output_path, font_size=24, font_name="Arial"):
    """
    Add subtitles to a video using FFmpeg.
    
    Args:
        video_path: Path to the video file
        subtitle_path: Path to the subtitle file (SRT or ASS)
        output_path: Path to save the output video
        font_size: Font size for subtitles
        font_name: Font name for subtitles
        
    Returns:
        Path to the output video
    """
    logger.info(f"Adding subtitles to video: {video_path}")
    logger.info(f"Subtitle file: {subtitle_path}")
    logger.info(f"Output path: {output_path}")
    
    # Check if subtitle file exists
    if not os.path.exists(subtitle_path):
        logger.error(f"Subtitle file not found: {subtitle_path}")
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")
            
    # Get subtitle file extension
    _, ext = os.path.splitext(subtitle_path)
    ext = ext.lower()
    
    logger.info(f"Subtitle file extension: {ext}")
    
    # Check file sizes
    video_size = os.path.getsize(video_path)
    subtitle_size = os.path.getsize(subtitle_path)
    logger.info(f"Video file size: {video_size} bytes")
    logger.info(f"Subtitle file size: {subtitle_size} bytes")
    
    # Read first few lines of subtitle file to verify content
    with open(subtitle_path, 'r', encoding='utf-8') as f:
        subtitle_preview = f.read(1000)  # Read first 1000 chars
    logger.info(f"Subtitle file preview: {subtitle_preview[:200]}...")  # Log first 200 chars
    
    # Determine the correct subtitle filter based on file extension
    if ext == '.ass':
        # For ASS files, use the ass filter with explicit file path
        subtitle_path_fixed = subtitle_path.replace('\\', '/')
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"ass='{subtitle_path_fixed}'",
            "-c:v", "libx264", "-crf", "23",
            "-c:a", "copy",
            "-max_muxing_queue_size", "9999",  # Prevent muxing queue errors
            output_path
        ]
        logger.info("Using ASS subtitle filter")
    elif ext == '.srt':
        # For SRT files, use the subtitles filter with styling options
        subtitle_path_fixed = subtitle_path.replace('\\', '/')
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{subtitle_path_fixed}':force_style='FontName={font_name},FontSize={font_size},BackColour=&H80000000,BorderStyle=4,Outline=1,Shadow=0'",
            "-c:v", "libx264", "-crf", "23",
            "-c:a", "copy",
            "-max_muxing_queue_size", "9999",  # Prevent muxing queue errors
            output_path
        ]
        logger.info("Using SRT subtitle filter with styling")
    else:
        logger.warning(f"Unknown subtitle format: {ext}, defaulting to subtitles filter")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{subtitle_path}'",
            "-c:v", "libx264", "-crf", "23",
            "-c:a", "copy",
            "-max_muxing_queue_size", "9999",  # Prevent muxing queue errors
            output_path
        ]
    
    logger.info(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
    
    # Run FFmpeg
    process = subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
    
    # Log FFmpeg output
    if process.stdout:
        logger.info(f"FFmpeg stdout: {process.stdout}")
    if process.stderr:
        logger.info(f"FFmpeg stderr: {process.stderr}")
    
    # Check if output file was created
    if os.path.exists(output_path):
        output_size = os.path.getsize(output_path)
        logger.info(f"Output file created successfully: {output_path} ({output_size} bytes)")
        return output_path
    else:
        logger.error(f"Output file was not created: {output_path}")
        raise FileNotFoundError(f"Output file was not created: {output_path}")
            
def add_subtitles_to_video(video_path, subtitle_path, output_path, font_size=24, font_name="Arial", position="bottom", alignment=2, margin_v=30, subtitle_style="classic", line_color="white", outline_color="black", back_color=None, word_color=None, all_caps=False, outline=True, shadow=True, border_style=1):
    """
    Add subtitles to a video file.
    
    Args:
        video_path: Path to the input video file
        subtitle_path: Path to the subtitle file (SRT or ASS)
        output_path: Path to the output video with subtitles
        font_size: Font size for subtitles
        font_name: Font name to use for subtitles
        position: Position of subtitles (bottom, middle, top)
        alignment: Text alignment (1=left, 2=center, 3=right)
        margin_v: Vertical margin in pixels
        subtitle_style: Style of subtitles (classic, modern)
        line_color: Color of subtitle text
        outline_color: Color of subtitle outline
        back_color: Color of subtitle background
        word_color: Color of highlighted words
        all_caps: Convert subtitles to all caps
        outline: Whether to add outline to text
        shadow: Whether to add shadow to text
        border_style: Border style (1=outline, 4=box)
        
    Returns:
        Path to the output video
    """
    logger.info(f"Adding subtitles to video: {video_path}")
    logger.info(f"Subtitle file: {subtitle_path}")
    logger.info(f"Output path: {output_path}")
    
    # Check if subtitle file exists
    if not os.path.exists(subtitle_path):
        logger.error(f"Subtitle file not found: {subtitle_path}")
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")
            
    # Get subtitle file extension
    _, ext = os.path.splitext(subtitle_path)
    ext = ext.lower()
    
    logger.info(f"Subtitle file extension: {ext}")
    
    # Check file sizes
    video_size = os.path.getsize(video_path)
    subtitle_size = os.path.getsize(subtitle_path)
    logger.info(f"Video file size: {video_size} bytes")
    logger.info(f"Subtitle file size: {subtitle_size} bytes")
    
    # Read first few lines of subtitle file to verify content
    with open(subtitle_path, 'r', encoding='utf-8') as f:
        subtitle_preview = f.read(1000)  # Read first 1000 chars
    logger.info(f"Subtitle file preview: {subtitle_preview[:200]}...")  # Log first 200 chars
    
    # Determine the correct subtitle filter based on file extension
    if ext == '.ass':
        # For ASS files, use the ass filter with explicit file path
        subtitle_path_fixed = subtitle_path.replace('\\', '/')
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"ass='{subtitle_path_fixed}'",
            "-c:v", "libx264", "-crf", "23",
            "-c:a", "copy",
            "-max_muxing_queue_size", "9999",  # Prevent muxing queue errors
            output_path
        ]
        logger.info("Using ASS subtitle filter")
    elif ext == '.srt':
        # For SRT files, use the subtitles filter with styling options
        subtitle_path_fixed = subtitle_path.replace('\\', '/')
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{subtitle_path_fixed}':force_style='FontName={font_name},FontSize={font_size},BackColour=&H80000000,BorderStyle={border_style},Outline={1 if outline else 0},Shadow={1 if shadow else 0}'",
            "-c:v", "libx264", "-crf", "23",
            "-c:a", "copy",
            "-max_muxing_queue_size", "9999",  # Prevent muxing queue errors
            output_path
        ]
        logger.info("Using SRT subtitle filter with styling")
    else:
        logger.warning(f"Unknown subtitle format: {ext}, defaulting to subtitles filter")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{subtitle_path}'",
            "-c:v", "libx264", "-crf", "23",
            "-c:a", "copy",
            "-max_muxing_queue_size", "9999",  # Prevent muxing queue errors
            output_path
        ]
    
    logger.info(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
    
    # Run FFmpeg
    process = subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
    
    # Log FFmpeg output
    if process.stdout:
        logger.info(f"FFmpeg stdout: {process.stdout}")
    if process.stderr:
        logger.info(f"FFmpeg stderr: {process.stderr}")
    
    # Check if output file was created
    if os.path.exists(output_path):
        output_size = os.path.getsize(output_path)
        logger.info(f"Output file created successfully: {output_path} ({output_size} bytes)")
        return output_path
    else:
        logger.error(f"Output file was not created: {output_path}")
        raise FileNotFoundError(f"Output file was not created: {output_path}")

def find_thai_fonts():
    """
    Find available Thai fonts on the system.
    
    Returns:
        List of paths to Thai font files
    """
    # Common paths for Thai fonts
    possible_paths = [
        # Thai-specific fonts
        "/usr/share/fonts/truetype/thai-tlwg/Sarabun*.ttf",
        "/usr/share/fonts/truetype/tlwg/Sarabun*.ttf",
        "/usr/share/fonts/TTF/Sarabun*.ttf",
        "/usr/share/fonts/thai-tlwg/Sarabun*.ttf",
        # General font directories
        "/usr/share/fonts/truetype/*/Sarabun*.ttf",
        "/usr/share/fonts/*/Sarabun*.ttf",
        # Noto Sans Thai (alternative)
        "/usr/share/fonts/truetype/noto/NotoSansThai*.ttf",
        "/usr/share/fonts/noto-cjk/NotoSansThai*.ttf",
        # Fallback to any Thai font
        "/usr/share/fonts/**/Thai*.ttf",
        "/usr/share/fonts/**/*Thai*.ttf"
    ]
    
    found_fonts = []
    
    # Try to find Thai fonts using glob
    for path_pattern in possible_paths:
        try:
            matches = glob.glob(path_pattern, recursive=True)
            found_fonts.extend(matches)
        except Exception as e:
            logger.warning(f"Error checking font path {path_pattern}: {str(e)}")
    
    # If glob doesn't work, try using find command
    if not found_fonts:
        try:
            result = subprocess.run(
                ["find", "/usr/share/fonts", "-name", "*Thai*", "-o", "-name", "*Sarabun*", "-type", "f"],
                capture_output=True, text=True, check=False
            )
            if result.stdout.strip():
                found_fonts.extend(result.stdout.strip().split("\n"))
        except Exception as e:
            logger.warning(f"Error using find command to locate Thai fonts: {str(e)}")
    
    # Last resort - check if we can list any fonts with fc-list
    if not found_fonts:
        try:
            result = subprocess.run(["fc-list"], capture_output=True, text=True, check=False)
            for line in result.stdout.split("\n"):
                if "Thai" in line or "Sarabun" in line:
                    font_path = line.split(":")[0]
                    found_fonts.append(font_path)
        except Exception as e:
            logger.warning(f"Error using fc-list to locate Thai fonts: {str(e)}")
    
    # Log the results
    if found_fonts:
        logger.info(f"Found {len(found_fonts)} Thai fonts: {found_fonts}")
    else:
        logger.warning("No Thai fonts found on the system")
    
    return found_fonts