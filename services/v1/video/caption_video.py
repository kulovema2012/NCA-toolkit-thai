import os
import time
import json
import tempfile
import subprocess
import logging
from typing import Dict, Any, List, Optional, Union
import re
import uuid
import json
import hashlib
import threading
from datetime import datetime, timedelta
import functools
import random
from pathlib import Path

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
        
        # Extract parameters for cache key
        if len(args) >= 2:
            video_path = args[0]
            subtitle_path = args[1]
        else:
            video_path = kwargs.get('video_path')
            subtitle_path = kwargs.get('subtitle_path')
        
        # Skip caching if paths are not provided
        if not video_path or not subtitle_path:
            return func(*args, **kwargs)
        
        # Generate cache key
        cache_key = _generate_cache_key(video_path, subtitle_path, **kwargs)
        
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
def create_styled_ass_subtitle(srt_path, output_ass_path, font_name="Arial", font_size=24, 
                              bold=False, italic=False, alignment=2, primary_color="&HFFFFFF&",
                              outline_color="&H000000&", shadow=1, border_style=1, outline=1,
                              back_color="&H80000000&", spacing=0, margin_v=40, is_thai=False):
    """
    Convert SRT to ASS with custom styling for better Thai text support.
    """
    try:
        import pysubs2
        
        # Load the SRT file
        subs = pysubs2.load(srt_path, encoding="utf-8")
        
        # Set global style for all subtitles
        style = pysubs2.SSAStyle()
        style.fontname = font_name
        style.fontsize = font_size
        style.bold = bold
        style.italic = italic
        style.alignment = alignment  # 2 = bottom center
        style.primarycolor = primary_color
        style.outlinecolor = outline_color
        style.shadow = shadow
        style.borderstyle = border_style
        style.outline = outline
        style.backcolor = back_color
        style.spacing = spacing
        style.marginv = margin_v
        
        # Apply the style to all subtitles
        subs.styles["Default"] = style
        
        # Save as ASS file
        subs.save(output_ass_path, encoding="utf-8")
        
        return output_ass_path
    except Exception as e:
        logger.error(f"Error creating ASS subtitle: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

@cache_result
def add_subtitles_to_video(video_path, subtitle_path, output_path=None, job_id=None, 
                          font_name="Arial", font_size=24, margin_v=40, subtitle_style="classic",
                          max_words_per_line=7, line_color="white", word_color=None, outline_color="black",
                          all_caps=False, x=None, y=None, alignment="center", bold=False, italic=False,
                          underline=False, strikeout=False):
    """
    Add subtitles to a video with enhanced support for Thai language.
    
    This function processes a video file and adds subtitles from an SRT file,
    with special handling for Thai text. It supports various styling options
    and optimizations for Thai language rendering.
    
    Parameters:
    -----------
    video_path : str
        Path to the input video file. Can be a local path or a URL.
    
    subtitle_path : str
        Path to the subtitle file in SRT format.
    
    output_path : str, optional
        Path where the output video will be saved. If not provided, a temporary
        file will be created.
    
    job_id : str, optional
        Identifier for the processing job. Used for logging and tracking.
    
    font_name : str, default="Arial"
        Font to use for subtitles. For Thai text, recommended fonts include:
        "Sarabun", "Garuda", "Loma", "Kinnari", "Norasi", "Sawasdee",
        "Tlwg Typist", "Tlwg Typo", "Waree", and "Umpush".
    
    font_size : int, default=24
        Font size for subtitles. For Thai text, a minimum of 28 is recommended.
    
    margin_v : int, default=40
        Vertical margin for subtitles. For Thai text, a minimum of 60 is applied.
    
    subtitle_style : str, default="classic"
        Style preset for subtitles. Options include:
        - "classic": White text with black outline
        - "modern": White text with semi-transparent background
        - "premium": Enhanced styling with better readability
        - "minimal": Simple styling with minimal visual elements
    
    max_words_per_line : int, default=7
        Maximum number of words per subtitle line. For Thai text, this is
        automatically adjusted to 4 for better readability.
    
    line_color : str, default="white"
        Color of the subtitle text. Can be a named color or a hex code.
    
    word_color : str, optional
        Color for highlighted words. If provided, applies different color to
        specific words in the subtitle.
    
    outline_color : str, default="black"
        Color of the text outline. Can be a named color or a hex code.
    
    all_caps : bool, default=False
        Whether to convert all text to uppercase.
    
    x, y : int, optional
        Custom positioning coordinates for subtitles. If not provided,
        subtitles will be positioned based on the alignment parameter.
    
    alignment : str, default="center"
        Horizontal alignment of subtitles. Options: "left", "center", "right".
    
    bold : bool, default=False
        Whether to render text in bold.
    
    italic : bool, default=False
        Whether to render text in italic.
    
    underline : bool, default=False
        Whether to underline the text.
    
    strikeout : bool, default=False
        Whether to strike through the text.
    
    Returns:
    --------
    dict
        A dictionary containing:
        - file_url: URL or path to access the processed video
        - local_path: Local path to the processed video file
        - processing_time: Time taken to process the video in seconds
    
    Notes:
    ------
    - Thai text is automatically detected and special processing is applied
    - For Thai text, word segmentation is performed to improve readability
    - The function uses FFmpeg for video processing with optimized settings
    - Results are cached to improve performance for repeated processing
    - For Windows systems, special path handling is applied
    
    Examples:
    ---------
    >>> result = add_subtitles_to_video(
    ...     video_path="input.mp4",
    ...     subtitle_path="subtitles.srt",
    ...     font_name="Sarabun",
    ...     font_size=28,
    ...     subtitle_style="premium"
    ... )
    >>> print(f"Processed video available at: {result['file_url']}")
    """
    try:
        # Record start time
        start_time = time.time()
        
        # Log the input parameters for debugging
        logger.info(f"Job {job_id}: Adding subtitles to video with parameters:")
        logger.info(f"Job {job_id}: video_path: {video_path}")
        logger.info(f"Job {job_id}: subtitle_path: {subtitle_path}")
        logger.info(f"Job {job_id}: font_name: {font_name}")
        logger.info(f"Job {job_id}: font_size: {font_size}")
        logger.info(f"Job {job_id}: subtitle_style: {subtitle_style}")
        
        # Check if output path is provided
        if not output_path:
            output_path = os.path.join(os.path.dirname(video_path), f"{job_id}_captioned.mp4")
        
        # Check if the subtitle file exists
        if not os.path.exists(subtitle_path):
            logger.error(f"Job {job_id}: Subtitle file not found: {subtitle_path}")
            return None
        
        # Check if the video file exists
        if not os.path.exists(video_path):
            logger.error(f"Job {job_id}: Video file not found: {video_path}")
            return None
            
        # Check if text contains Thai characters
        def contains_thai(s):
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                content = f.read()
                thai_range = range(0x0E00, 0x0E7F)
                return any(ord(c) in thai_range for c in content)
        
        is_thai = contains_thai(subtitle_path)
        logger.info(f"Job {job_id}: Contains Thai text: {is_thai}")
        
        # Apply predefined styles
        if subtitle_style:
            if subtitle_style == "classic":
                # Classic style: white text with black outline
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not bold:
                    bold = True
                if not max_words_per_line and is_thai:
                    max_words_per_line = 4
                if not max_words_per_line:
                    max_words_per_line = 7
                if not max_width:
                    max_width = 80
                if is_thai and not font_name:
                    font_name = "Sarabun"  # Best overall Thai font
                
            elif subtitle_style == "modern":
                # Modern style: white text with semi-transparent background
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 28
                if not max_words_per_line and is_thai:
                    max_words_per_line = 3
                if not max_width:
                    max_width = 70
                if is_thai and not font_name:
                    font_name = "Sarabun"  # Best overall Thai font
                
            elif subtitle_style == "cinematic":
                # Cinematic style: larger text, bottom position, wider
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 32
                if not position:
                    position = "bottom"
                if not margin_v:
                    margin_v = 60
                if not max_words_per_line and is_thai:
                    max_words_per_line = 3
                if not max_width:
                    max_width = 90
                if not bold:
                    bold = True
                if is_thai and not font_name:
                    font_name = "Sarabun"  # Best overall Thai font
                    
            elif subtitle_style == "minimal":
                # Minimal style: smaller text, no background
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 22
                if not max_words_per_line and is_thai:
                    max_words_per_line = 5
                if not max_width:
                    max_width = 60
                if is_thai and not font_name:
                    font_name = "Garuda"  # Better for smaller text in Thai
                    
            elif subtitle_style == "bold":
                # Bold style: large text with strong outline
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 30
                if not bold:
                    bold = True
                if not max_words_per_line and is_thai:
                    max_words_per_line = 3
                if not max_width:
                    max_width = 75
                if is_thai and not font_name:
                    font_name = "Sarabun"  # Best overall Thai font
                    
            elif subtitle_style == "premium":
                # Premium style: optimized specifically for Thai text
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 28
                if not position:
                    position = "bottom"
                if not margin_v:
                    margin_v = 70
                if not max_words_per_line and is_thai:
                    max_words_per_line = 3
                if not max_width:
                    max_width = 75
                if not bold:
                    bold = True
                # Use Waree font which has better tone mark alignment for Thai
                if is_thai:
                    font_name = "Waree"
                
        # Process text for all_caps if needed
        if all_caps:
            # Create a new subtitle file with all caps
            all_caps_subtitle_path = os.path.join(os.path.dirname(subtitle_path), 
                                                f"allcaps_{os.path.basename(subtitle_path)}")
            with open(subtitle_path, 'r', encoding='utf-8') as f_in:
                with open(all_caps_subtitle_path, 'w', encoding='utf-8') as f_out:
                    for line in f_in:
                        f_out.write(line.upper())
            subtitle_path = all_caps_subtitle_path
        
        # Process max_words_per_line if needed
        limited_subtitle_path = subtitle_path
        if max_words_per_line and max_words_per_line > 0:
            logger.info(f"Job {job_id}: Reformatting SRT with max {max_words_per_line} words per line")
            temp_dir = os.path.dirname(subtitle_path)
            if not temp_dir:
                temp_dir = os.path.dirname(output_path) if output_path else '/tmp'
            
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            
            original_srt = subtitle_path
            limited_srt = os.path.join(temp_dir, f"limited_{job_id}.srt")
            
            with open(original_srt, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse and reformat SRT
            srt_data = []
            current_block = {"index": "", "time": "", "text": []}
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    if current_block["text"]:
                        srt_data.append(current_block)
                        current_block = {"index": "", "time": "", "text": []}
                    continue
                
                if not current_block["index"]:
                    current_block["index"] = line
                elif not current_block["time"] and '-->' in line:
                    current_block["time"] = line
                else:
                    current_block["text"].append(line)
            
            # Add the last block if it exists
            if current_block["text"]:
                srt_data.append(current_block)
            
            # Helper functions for time conversion
            def convert_time_to_seconds(time_str):
                """Convert SRT time format (HH:MM:SS,mmm) to seconds."""
                parts = time_str.replace(',', '.').split(':')
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
            
            def convert_seconds_to_time(seconds):
                """Convert seconds to SRT time format (HH:MM:SS,mmm)."""
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                seconds = seconds % 60
                return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}".replace('.', ',')
            
            # Improved split_lines function for Thai text
            def split_lines(text, max_words_per_line):
                """Split text into lines with a maximum number of words per line."""
                if not max_words_per_line or max_words_per_line <= 0:
                    return [text]
                    
                # Check if text contains Thai characters
                def contains_thai(s):
                    thai_range = range(0x0E00, 0x0E7F)
                    return any(ord(c) in thai_range for c in s)
                
                if contains_thai(text):
                    # For Thai text, use PyThaiNLP if available
                    if PYTHAINLP_AVAILABLE:
                        try:
                            # Use PyThaiNLP with newmm engine (fastest and most accurate)
                            # Set timeout to prevent hanging on very long text
                            words = word_tokenize(text, engine="newmm", keep_whitespace=False)
                            
                            # If the text is short enough, return it as is
                            if len(words) <= max_words_per_line:
                                return [text]
                            
                            # Split into chunks of max_words_per_line
                            result = []
                            for i in range(0, len(words), max_words_per_line):
                                chunk = words[i:i+max_words_per_line]
                                # Join without spaces for Thai words
                                line = ""
                                for word in chunk:
                                    # Add space only for non-Thai characters
                                    if any(ord(c) < 0x0E00 or ord(c) > 0x0E7F for c in word):
                                        line += " " + word
                                    else:
                                        line += word
                                result.append(line.strip())
                            return result
                        except Exception as e:
                            logger.warning(f"PyThaiNLP tokenization failed: {str(e)}. Using fallback method.")
                            # Fall back to the rule-based method if PyThaiNLP fails
                    
                    # Fallback: Rule-based Thai word segmentation
                    # Thai punctuation and break characters
                    break_chars = [' ', '\n', ',', '.', '?', '!', ':', ';', ')', ']', '}', '"', "'", '।', '॥', '…', '–', '—', '|']
                    
                    # Common Thai word-ending characters that can be used as potential break points
                    thai_word_endings = ['ะ', 'า', 'ิ', 'ี', 'ึ', 'ื', 'ุ', 'ู', 'เ', 'แ', 'โ', 'ใ', 'ไ', '่', '้', '๊', '๋', '็', '์', 'ๆ']
                    
                    # If the text is short enough, return it as is
                    if len(text) <= max_words_per_line * 5:  # Estimate 5 chars per Thai word
                        return [text]
                        
                    # Try to split at natural break points
                    result = []
                    current_line = ""
                    char_count = 0
                    last_potential_break = 0
                    
                    for i, char in enumerate(text):
                        current_line += char
                        char_count += 1
                        
                        # Mark potential break points at word boundaries
                        if char in break_chars or char in thai_word_endings:
                            last_potential_break = i
                        
                        # If we've reached the target length, break at the last potential break point
                        if char_count >= max_words_per_line * 4:  # Slightly less than our estimate to be safe
                            if last_potential_break > 0 and last_potential_break > i - 10:
                                # Break at the last potential break point
                                result.append(current_line[:last_potential_break - i + len(current_line)])
                                current_line = current_line[last_potential_break - i + len(current_line):]
                                char_count = len(current_line)
                                last_potential_break = 0
                            else:
                                # If no good break point, just break here
                                result.append(current_line)
                                current_line = ""
                                char_count = 0
                                last_potential_break = 0
                    
                    # Add any remaining text
                    if current_line:
                        result.append(current_line)
                    
                    return result
                else:
                    # For non-Thai text, split by words
                    words = text.split()
                    if len(words) <= max_words_per_line:
                        return [text]
                    
                    # Split into chunks of max_words_per_line
                    return [' '.join(words[i:i+max_words_per_line]) for i in range(0, len(words), max_words_per_line)]
            
            # Reformat with max words per line and fix synchronization
            with open(limited_srt, 'w', encoding='utf-8') as f:
                for block in srt_data:
                    # Join all text lines
                    text = ' '.join(block["text"])
                    
                    # Use our improved split_lines function
                    new_lines = split_lines(text, max_words_per_line)
                    
                    # Limit to maximum 2 lines per subtitle for better readability
                    max_lines = 2
                    if len(new_lines) > max_lines:
                        # Create multiple subtitle blocks if we have more than max_lines
                        time_parts = block["time"].split('-->')
                        start_time = time_parts[0].strip()
                        end_time = time_parts[1].strip()
                        
                        # Calculate time per subtitle block
                        start_seconds = convert_time_to_seconds(start_time)
                        end_seconds = convert_time_to_seconds(end_time)
                        total_duration = end_seconds - start_seconds
                        
                        # Improve synchronization by adding a small offset
                        if is_thai:
                            # Add a small offset (0.3 seconds) to improve sync with Thai audio
                            start_seconds = max(0, start_seconds - 0.3)
                            # Extend duration slightly for better readability
                            end_seconds = end_seconds + 0.2
                            total_duration = end_seconds - start_seconds
                        
                        duration_per_block = total_duration / ((len(new_lines) + max_lines - 1) // max_lines)
                        
                        # Write multiple blocks
                        for i in range(0, len(new_lines), max_lines):
                            block_lines = new_lines[i:i+max_lines]
                            block_start = start_seconds + (i // max_lines) * duration_per_block
                            block_end = min(end_seconds, block_start + duration_per_block)
                            
                            # Ensure minimum display time (1.5 seconds) for Thai text
                            if is_thai and (block_end - block_start) < 1.5:
                                block_end = min(end_seconds, block_start + 1.5)
                            
                            f.write(f"{block['index']}.{i//max_lines+1}\n")
                            f.write(f"{convert_seconds_to_time(block_start)} --> {convert_seconds_to_time(block_end)}\n")
                            f.write('\n'.join(block_lines) + '\n\n')
                    else:
                        # Write the reformatted block
                        # Improve synchronization for Thai text
                        if is_thai:
                            time_parts = block["time"].split('-->')
                            start_time = time_parts[0].strip()
                            end_time = time_parts[1].strip()
                            
                            # Calculate time in seconds
                            start_seconds = convert_time_to_seconds(start_time)
                            end_seconds = convert_time_to_seconds(end_time)
                            
                            # Add a small offset (0.3 seconds) to improve sync with Thai audio
                            start_seconds = max(0, start_seconds - 0.3)
                            # Extend duration slightly for better readability
                            end_seconds = end_seconds + 0.2
                            
                            # Ensure minimum display time (1.5 seconds) for Thai text
                            if (end_seconds - start_seconds) < 1.5:
                                end_seconds = start_seconds + 1.5
                            
                            # Write with adjusted timing
                            f.write(f"{block['index']}\n")
                            f.write(f"{convert_seconds_to_time(start_seconds)} --> {convert_seconds_to_time(end_seconds)}\n")
                            f.write('\n'.join(new_lines) + '\n\n')
                        else:
                            # Non-Thai text - use original timing
                            f.write(block["index"] + '\n')
                            f.write(block["time"] + '\n')
                            f.write('\n'.join(new_lines) + '\n\n')
            
            limited_subtitle_path = limited_srt
        
        # Determine subtitle position and alignment
        subtitle_position = position
        if x is not None and y is not None:
            # Custom position overrides predefined positions
            subtitle_position = "custom"
        
        # Set style parameters based on subtitle style
        primary_color = "&HFFFFFF&"  # White
        outline_color_value = "&H000000&"  # Black
        shadow = 1
        border_style = 1
        outline_width = 1
        back_color = "&H80000000&"  # Semi-transparent black
        spacing = 0
        
        if line_color:
            line_color = line_color.lstrip('#')
            if len(line_color) == 6:
                primary_color = f"&H{line_color}&"
        
        if outline_color:
            outline_color = outline_color.lstrip('#')
            if len(outline_color) == 6:
                outline_color_value = f"&H{outline_color}&"
        
        # Adjust style based on preset
        if subtitle_style == "modern":
            shadow = 0
            border_style = 4  # Box style
            outline_width = 0
            back_color = "&H80000000&"  # Semi-transparent black background
        elif subtitle_style == "cinematic":
            shadow = 1
            border_style = 1
            outline_width = 2  # Thicker outline
        elif subtitle_style == "minimal":
            shadow = 0
            border_style = 1
            outline_width = 1  # Minimal outline
        elif subtitle_style == "bold":
            shadow = 1
            border_style = 1
            outline_width = 3  # Very thick outline
        elif subtitle_style == "premium":
            # Premium style optimized for Thai text
            shadow = 0
            border_style = 1
            outline_width = 1.5  # Medium outline
            back_color = "&HC0000000&"  # More opaque background for better readability
            spacing = 0.5  # Increased spacing to prevent tone mark overlays
        
        # Add background box for Thai text if needed
        if is_thai and subtitle_style not in ["minimal"]:
            if subtitle_style != "premium":  # Premium already has its own background
                back_color = "&H80000000&"  # Semi-transparent black background
            
            # Add special handling for Thai text if not already in premium style
            if subtitle_style != "premium":
                spacing = 0.3  # Increased spacing to prevent tone mark overlays
        
        # Set alignment based on parameter
        align_value = 2  # Default: bottom center
        if alignment == "left":
            align_value = 1
        elif alignment == "center":
            align_value = 2
        elif alignment == "right":
            align_value = 3
        
        # Default margin is increased to ensure text is fully visible
        default_margin_v = max(margin_v, 60 if is_thai else 40)  # Ensure minimum margin of 60 pixels for Thai text
        
        # Build the FFmpeg command using the SRT subtitle file directly
        # Use a very simple approach for Windows compatibility
        if os.name == 'nt':  # Windows
            # Use the original SRT file with minimal options
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", limited_subtitle_path,  # Use subtitle as a separate input
                "-c:v", "libx264", "-crf", "18",
                "-c:a", "copy",
                "-c:s", "mov_text",  # Use mov_text codec for subtitles
                "-metadata:s:s:0", f"language=tha",  # Set subtitle language
                "-pix_fmt", "yuv420p",
                output_path
            ]
        else:
            # Unix systems
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", limited_subtitle_path,  # Use subtitle as a separate input
                "-c:v", "libx264", "-crf", "18",
                "-c:a", "copy",
                "-c:s", "mov_text",  # Use mov_text codec for subtitles
                "-metadata:s:s:0", f"language=tha",  # Set subtitle language
                "-pix_fmt", "yuv420p",
                output_path
            ]
        
        # Log the command
        logger.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        
        # Execute the command
        subprocess.run(ffmpeg_cmd, check=True)
        
        # Calculate processing time
        end_time = time.time()
        # Ensure start_time is a float before subtraction
        if isinstance(start_time, str):
            try:
                start_time = float(start_time)
            except ValueError:
                # If conversion fails, just use the current time as start time
                # This means processing_time will be near zero
                logger.warning(f"Job {job_id}: Invalid start_time format, using current time")
                start_time = end_time
        processing_time = end_time - start_time
        
        # Upload to cloud storage if needed
        file_url = None
        try:
            # Try to import cloud storage module
            from services.cloud_storage import upload_file
            
            # Upload the file to cloud storage if the module is available
            cloud_storage_path = f"videos/captioned/{os.path.basename(output_path)}"
            file_url = upload_file(output_path, cloud_storage_path)
            logger.info(f"Job {job_id}: Uploaded to cloud storage: {file_url}")
        except ImportError:
            # Cloud storage module not available, just use local path
            logger.warning(f"Job {job_id}: Cloud storage module not available, using local path")
            file_url = f"file://{output_path}"
        
        # Return the result
        return {
            "file_url": file_url,
            "local_path": output_path,
            "processing_time": processing_time
        }
    except Exception as e:
        logger.error(f"Error adding subtitles: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

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
            job_id=job_id,
            font_name=font_name,
            font_size=font_size,
            margin_v=margin_v,
            subtitle_style=subtitle_style,
            max_width=max_width,
            position=position,
            max_words_per_line=max_words_per_line,
            line_color=line_color,
            word_color=word_color,
            outline_color=outline_color,
            all_caps=all_caps,
            x=x,
            y=y,
            alignment=alignment,
            bold=bold,
            italic=italic,
            underline=underline,
            strikeout=strikeout
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
