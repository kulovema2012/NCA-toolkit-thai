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

def convert_srt_to_ass_for_thai(srt_path, font_name=None, font_size=24, primary_color="white", outline_color="black", back_color=None, alignment=2, margin_v=30, max_words_per_line=7, max_width=None):
    """
    Convert SRT subtitles to ASS format with special handling for Thai text.
    """
    try:
        logger.info(f"Converting SRT to ASS for Thai: {srt_path}")
        
        # Get the best available Thai font if none specified
        if not font_name:
            font_name = get_available_thai_font()
            logger.info(f"Using detected Thai font: {font_name}")
        
        # Parse the SRT file
        with open(srt_path, 'r', encoding='utf-8-sig') as f:
            subs = list(srt.parse(f.read()))
        
        # Create an ASS file
        ass_path = srt_path.replace('.srt', '.ass')
        
        # Write ASS file with Thai-specific settings
        with open(ass_path, 'w', encoding='utf-8') as f:
            # Write header
            f.write("[Script Info]\n")
            f.write("Title: Thai Subtitles\n")
            f.write("ScriptType: v4.00+\n")
            f.write("Collisions: Normal\n")
            f.write("PlayResX: 1920\n")  # Standard HD width
            f.write("PlayResY: 1080\n")  # Standard HD height
            f.write("YCbCr Matrix: None\n\n")
            
            # Write styles
            f.write("[V4+ Styles]\n")
            f.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
            
            # Define a style for Thai text with explicit font settings
            # Convert colors to ASS format (BBGGRR&H)
            # For primary color (text color)
            if primary_color.lower() == "white":
                primary_color_hex = "&H00FFFFFF"  # White
            elif primary_color.lower() == "yellow":
                primary_color_hex = "&H0000FFFF"  # Yellow
            elif primary_color.lower() == "black":
                primary_color_hex = "&H00000000"  # Black
            else:
                primary_color_hex = "&H00FFFFFF"  # Default to white
            
            # For outline color
            if outline_color.lower() == "black":
                outline_color_hex = "&H000000FF"  # Black
            elif outline_color.lower() == "white":
                outline_color_hex = "&H00FFFFFF"  # White
            else:
                outline_color_hex = "&H000000FF"  # Default to black
            
            # CRITICAL FIX: Handle back_color properly
            # Default to semi-transparent black if not specified
            back_color_hex = "&H80000000"  # Default: semi-transparent black (80 = 50% opacity)
            
            # Process back_color parameter
            logger.info(f"Original back_color parameter: '{back_color}'")
            
            if back_color:
                if isinstance(back_color, str):
                    # Handle different formats
                    if back_color.startswith("&H"):
                        # Already in ASS format
                        back_color_hex = back_color
                        logger.info(f"Using ASS format back_color: {back_color_hex}")
                    elif back_color.startswith("H"):
                        # Missing the & prefix, add it
                        back_color_hex = "&" + back_color
                        logger.info(f"Fixed back_color format by adding &: {back_color_hex}")
                    elif back_color.lower() == "black":
                        # Force a higher opacity for black to ensure visibility
                        back_color_hex = "&H80000000"  # Semi-transparent black (80 = 50% opacity)
                        logger.info(f"Using black back_color: {back_color_hex}")
                    elif back_color.lower() == "red":
                        back_color_hex = "&H800000FF"  # Semi-transparent red
                    elif back_color.lower() == "blue":
                        back_color_hex = "&H80FF0000"  # Semi-transparent blue
                    elif back_color.lower() == "green":
                        back_color_hex = "&H8000FF00"  # Semi-transparent green
                    elif back_color.lower() == "transparent":
                        back_color_hex = "&H00000000"  # Fully transparent
                    else:
                        # Try to handle hex color codes like "#000000" for black
                        try:
                            if back_color.startswith("#"):
                                # Convert HTML/CSS hex color to ASS format
                                color = back_color.lstrip("#")
                                if len(color) == 6:
                                    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
                                    # ASS format is &HAABBGGRR (AA=alpha, BB=blue, GG=green, RR=red)
                                    back_color_hex = f"&H80{b:02X}{g:02X}{r:02X}"
                                    logger.info(f"Converted HTML color {back_color} to ASS format: {back_color_hex}")
                        except Exception as e:
                            logger.error(f"Error converting color {back_color}: {str(e)}")
                            # Fall back to default black
                            back_color_hex = "&H80000000"
            
            # FORCE BLACK BACKGROUND - this is critical to prevent red background
            # The original code might be using a different color format, so we'll force black here
            back_color_hex = "&H80000000"  # Semi-transparent black
            logger.warning("Forcing black background color to ensure proper display")
            
            # Log the final back_color_hex for debugging
            logger.info(f"Final back_color_hex: {back_color_hex}")
            
            # Adjust font size based on video dimensions and orientation
            adjusted_font_size = int(font_size * 1.5)
            
            # CRITICAL FIX: Set BorderStyle=4 for opaque box style with specific margins
            # This ensures the background color is properly applied
            border_style = 4  # Use opaque box style with specific margins
            outline_width = 2  # Outline width for better visibility
            
            # Write the style with all parameters explicitly set
            # Note: For Thai subtitles, we're using a more compatible style format
            f.write(f"Style: Default,{font_name},{adjusted_font_size},{primary_color_hex},&H0000FFFF,{outline_color_hex},{back_color_hex},1,0,0,0,100,100,0,0,{border_style},{outline_width},0,{alignment},20,20,{margin_v},1\n\n")
            
            # Write events
            f.write("[Events]\n")
            f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            
            # Process each subtitle
            for i, subtitle in enumerate(subs):
                start_time = subtitle.start.total_seconds()
                end_time = subtitle.end.total_seconds()
                
                # Format the times as ASS format (h:mm:ss.cc)
                start_formatted = format_time_ass(start_time)
                end_formatted = format_time_ass(end_time)
                
                # Process the text with Thai word segmentation
                text = subtitle.content
                
                # Apply max_words_per_line if specified
                if max_words_per_line and max_words_per_line > 0:
                    # Use PyThaiNLP for better word segmentation if available
                    if PYTHAINLP_AVAILABLE:
                        try:
                            # Tokenize the text into words
                            words = word_tokenize(text, engine="newmm")
                            
                            # Log the number of words for debugging
                            logger.info(f"Thai text tokenized into {len(words)} words with max_words_per_line={max_words_per_line}")
                            
                            # Calculate optimal words per line based on video dimensions
                            # For Thai, we'll use a more conservative approach to ensure readability
                            optimal_words_per_line = max(10, min(max_words_per_line, 20))  # Between 10 and 20 words
                            logger.info(f"Using optimal_words_per_line={optimal_words_per_line}")
                            
                            # If the number of words is less than optimal_words_per_line, no need to split
                            if len(words) <= optimal_words_per_line:
                                # Just use the text as is
                                logger.info(f"Text has fewer words ({len(words)}) than optimal_words_per_line ({optimal_words_per_line}), no splitting needed")
                            else:
                                # Group words into lines based on optimal_words_per_line
                                lines = []
                                current_line = []
                                word_count = 0
                                
                                for word in words:
                                    current_line.append(word)
                                    word_count += 1
                                    
                                    if word_count >= optimal_words_per_line:
                                        lines.append("".join(current_line))
                                        current_line = []
                                        word_count = 0
                                
                                # Add any remaining words
                                if current_line:
                                    lines.append("".join(current_line))
                                
                                # Join lines with newline character
                                text = "\\N".join(lines)
                                logger.info(f"Applied optimal_words_per_line={optimal_words_per_line}, resulting in {len(lines)} lines")
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
            
                # Write the event line with explicit background color and style overrides
                # Use specific ASS override tags to ensure proper display
                text_with_style = "{\\bord2\\shad0\\3c&H000000&\\4c&H000000&}" + text
                f.write(f"Dialogue: 0,{start_formatted},{end_formatted},Default,,0,0,0,,{text_with_style}\n")
            
        logger.info(f"Successfully converted SRT to ASS with Thai text handling: {ass_path}")
        return ass_path
    except Exception as e:
        logger.error(f"Error converting SRT to ASS for Thai: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        # Instead of returning None, return the original SRT path
        # This allows the process to continue even if ASS conversion fails
        logger.warning(f"Falling back to original SRT file: {srt_path}")
        return srt_path

def get_available_thai_font():
    """
    Check for available Thai fonts on the system and return the best one.
    """
    # List of Thai fonts to check in order of preference
    # Prioritize fonts that are likely to be available in cloud environments
    thai_fonts = [
        "Sarabun", "Garuda", "Loma", "Kinnari", "Norasi", 
        "Waree", "TH Sarabun New", "Tahoma", "Arial Unicode MS", "DejaVu Sans"
    ]
    
    # Check if we're on Windows (for local development)
    import platform
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes
            
            # Use Windows API to get font directory
            CSIDL_FONTS = 0x0014
            SHGFP_TYPE_CURRENT = 0
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(0, CSIDL_FONTS, 0, SHGFP_TYPE_CURRENT, buf)
            fonts_dir = buf.value
            
            # Check if font files exist
            import os
            for font in thai_fonts:
                # Check common extensions
                for ext in ['.ttf', '.ttc', '.otf']:
                    if os.path.exists(os.path.join(fonts_dir, f"{font}{ext}")):
                        logger.info(f"Found Thai font on Windows: {font}")
                        return font
            
            # If we can't find any specific Thai font, check if Tahoma exists
            # Tahoma has good Thai support and is common on Windows
            if os.path.exists(os.path.join(fonts_dir, "tahoma.ttf")):
                logger.info("Using Tahoma as fallback Thai font")
                return "Tahoma"
                
            # If all else fails, use Arial which should be on all Windows systems
            if os.path.exists(os.path.join(fonts_dir, "arial.ttf")):
                logger.info("Using Arial as fallback Thai font")
                return "Arial"
        except Exception as e:
            logger.warning(f"Error checking for Thai fonts on Windows: {str(e)}")
    else:
        # For Linux/Cloud environments
        # First try fc-list (standard on most Linux distributions)
        try:
            import subprocess
            result = subprocess.run(["fc-list"], capture_output=True, text=True)
            fc_output = result.stdout.lower()
            
            for font in thai_fonts:
                if font.lower() in fc_output:
                    logger.info(f"Found Thai font via fc-list: {font}")
                    return font
                    
            # If no specific Thai font is found, look for common Linux fonts with Thai support
            for fallback in ["DejaVu Sans", "Noto Sans", "FreeSans"]:
                if fallback.lower() in fc_output:
                    logger.info(f"Using fallback font with Thai support: {fallback}")
                    return fallback
        except Exception as e:
            logger.warning(f"Could not check for Thai fonts using fc-list: {str(e)}")
            
        # As a second approach, check common font directories on Linux
        try:
            import os
            linux_font_dirs = [
                "/usr/share/fonts/",
                "/usr/local/share/fonts/",
                "/usr/share/fonts/truetype/",
                "/usr/share/fonts/opentype/"
            ]
            
            for font_dir in linux_font_dirs:
                if os.path.exists(font_dir):
                    # Check for Thai fonts
                    for root, dirs, files in os.walk(font_dir):
                        for font in thai_fonts:
                            for file in files:
                                if font.lower() in file.lower() and file.lower().endswith(('.ttf', '.otf', '.ttc')):
                                    logger.info(f"Found Thai font in {root}: {file}")
                                    return font
        except Exception as e:
            logger.warning(f"Error checking font directories: {str(e)}")
    
    # Default to Sarabun which should be installed in your cloud environment
    # based on your memory about available Thai fonts
    logger.info("Using default Thai font: Sarabun")
    return "Sarabun"

@cache_result
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
    logger.info(f"Adding subtitles to video: {video_path}")
    
    # Determine if subtitles are in Thai
    is_thai = False
    try:
        with open(subtitle_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            # Check for Thai characters
            thai_chars = 'กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮะัาำิีึืุูเแโใไ'
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
                    font_name = get_available_thai_font()  # Get best available Thai font
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
        align_param = 3
    else:  # center (default)
        align_param = 2
    
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
    if is_thai:
        # Create a special ASS file for Thai text
        thai_ass_path = convert_srt_to_ass_for_thai(
            processed_subtitle_path, 
            font_name, 
            adjusted_font_size, 
            line_color, 
            outline_color, 
            max_words_per_line=max_words_per_line,
            alignment=align_param,
            margin_v=margin_v,
            max_width=max_width,
            back_color=back_color
        )
        
        # Properly escape the subtitle path for Windows
        # Handle the case where thai_ass_path might be None (although we fixed that above)
        if thai_ass_path is None:
            logger.error("Thai ASS conversion failed, falling back to original subtitle path")
            thai_ass_path = subtitle_path
            
        escaped_subtitle_path = thai_ass_path.replace('\\', '\\\\')
        
        # Determine the correct subtitle filter based on file extension
        if thai_ass_path.endswith('.ass'):
            # Use ASS filter for ASS files
            subtitle_filter = f"ass={escaped_subtitle_path}"
        else:
            # Use subtitles filter for SRT files
            subtitle_filter = f"subtitles={escaped_subtitle_path}"
        
        logger.info(f"Using subtitle filter: {subtitle_filter}")
        
        # Add voice-over delay of 0.2 seconds for Thai videos to ensure synchronization
        voice_over_delay = 0.2
        logger.info(f"Adding voice-over delay of {voice_over_delay}s for Thai video")
        # Use the adelay filter to delay audio
        audio_filter = f"adelay={int(voice_over_delay*1000)}:all=1"
        
        # For Thai subtitles, use a simpler command that's known to work with Thai text
        # Use -vf instead of -filter_complex for simpler processing
        ffmpeg_cmd = [
            "ffmpeg", "-y", 
            "-i", video_path,
            "-vf", subtitle_filter,
            "-af", audio_filter,
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k",
            output_path
        ]
        
        # Log the full command for debugging
        logger.info(f"Thai subtitle FFmpeg command: {' '.join(ffmpeg_cmd)}")
    else:
        if subtitle_style == "classic":
            # Classic style with simple text - ensure text is visible with proper formatting
            subtitle_filter = f"subtitles='{processed_subtitle_path}':force_style='FontName={font_name},FontSize={adjusted_font_size},PrimaryColour={line_color},OutlineColour={outline_color},BorderStyle=1,Outline=1,Shadow=1,MarginV={margin_v},Alignment={align_param}{font_formatting}'"
        
        elif subtitle_style == "modern":
            # Modern style with background box - ensure text is visible with proper background
            subtitle_filter = f"subtitles='{processed_subtitle_path}':force_style='FontName={font_name},FontSize={adjusted_font_size},PrimaryColour={line_color},OutlineColour={outline_color},BackColour=&H80000000,BorderStyle=3,Outline=1,Shadow=1,MarginV={margin_v},Alignment={align_param}{font_formatting}'"
        
        elif subtitle_style in ["highlight", "karaoke", "word_by_word"]:
            # Convert SRT to ASS first
            ass_subtitle_path = processed_subtitle_path.replace('.srt', '.ass')
            convert_srt_to_ass(processed_subtitle_path, ass_subtitle_path, font_name, adjusted_font_size, 
                             line_color, outline_color, word_color, align_param, margin_v, 
                             subtitle_style, max_width, all_caps, font_formatting)
            subtitle_filter = f"ass='{ass_subtitle_path}'"
        
        elif subtitle_style == "underline":
            # Underlined text - ensure text is visible
            subtitle_filter = f"subtitles='{processed_subtitle_path}':force_style='FontName={font_name},FontSize={adjusted_font_size},PrimaryColour={line_color},OutlineColour={outline_color},BorderStyle=1,Outline=1,Shadow=1,MarginV={margin_v},Alignment={align_param},Underline=1{font_formatting}'"
        
        else:
            # Default to classic if style not recognized
            subtitle_filter = f"subtitles='{processed_subtitle_path}':force_style='FontName={font_name},FontSize={adjusted_font_size},PrimaryColour={line_color},OutlineColour={outline_color},BorderStyle=1,Outline=1,Shadow=1,MarginV={margin_v},Alignment={align_param}{font_formatting}'"
    
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
        
        logger.info(f"FFmpeg stdout: {result.stdout}")
        logger.info(f"FFmpeg stderr: {result.stderr}")
        
        # Check if output file was created
        if os.path.exists(output_path):
            output_size = os.path.getsize(output_path)
            logger.info(f"Output file created successfully: {output_path} ({output_size} bytes)")
            return output_path
        else:
            logger.error(f"Output file was not created: {output_path}")
            raise FileNotFoundError(f"Output file was not created: {output_path}")
            
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr}")
        raise ValueError(f"FFmpeg error: {e.stderr}")
    except Exception as e:
        logger.error(f"Error adding subtitles to video: {str(e)}")
        raise

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
    try:
        logger = logging.getLogger(__name__)
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
            subtitle_filter = f"ass='{subtitle_path}'"
            logger.info("Using ASS subtitle filter")
        elif ext == '.srt':
            # For SRT files, use the subtitles filter with styling options
            subtitle_filter = f"subtitles='{subtitle_path}':force_style='FontName={font_name},FontSize={font_size},BackColour=&H80000000,BorderStyle=4,Outline=1,Shadow=0'"
            logger.info("Using SRT subtitle filter with styling")
        else:
            logger.warning(f"Unknown subtitle format: {ext}, defaulting to subtitles filter")
            subtitle_filter = f"subtitles='{subtitle_path}'"
        
        # Build FFmpeg command with improved options
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", subtitle_filter,
            "-c:v", "libx264", "-crf", "23",
            "-c:a", "copy",
            "-max_muxing_queue_size", "9999",  # Prevent muxing queue errors
            output_path
        ]
        
        logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
        
        # Run FFmpeg
        process = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
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
            
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr}")
        raise ValueError(f"FFmpeg error: {e.stderr}")
    except Exception as e:
        logger.error(f"Error adding subtitles to video: {str(e)}")
        raise
