import os
import logging
import re

# Configure logging
logger = logging.getLogger(__name__)

# Import PyThaiNLP for Thai word segmentation if available
try:
    from pythainlp.tokenize import word_tokenize
    PYTHAINLP_AVAILABLE = True
except ImportError:
    PYTHAINLP_AVAILABLE = False
    logger.warning("PyThaiNLP not available. Using fallback method for Thai word segmentation.")

def is_thai_text(text):
    """Check if text contains Thai characters."""
    return any('\u0E00' <= c <= '\u0E7F' for c in text)

def wrap_thai_text(text, max_chars_per_line=30):
    """
    Wrap Thai text to fit within a specified character limit.
    
    Args:
        text (str): The text to wrap
        max_chars_per_line (int): Maximum characters per line
        
    Returns:
        list: List of wrapped text lines
    """
    text = text.strip()
    wrapped_text = []
    
    # Check if text contains Thai characters
    is_thai = is_thai_text(text)
    
    if is_thai:
        # For Thai text, try to wrap at spaces if they exist
        if ' ' in text:
            # Split by spaces first
            parts = text.split(' ')
            current_line = ""
            
            for part in parts:
                # If adding this part would exceed max length, start a new line
                if len(current_line) + len(part) + 1 <= max_chars_per_line:
                    if current_line:
                        current_line += " " + part
                    else:
                        current_line = part
                else:
                    # If current line is not empty, add it to wrapped text
                    if current_line:
                        wrapped_text.append(current_line)
                    
                    # If the part itself is longer than max_chars, we need to split it
                    if len(part) > max_chars_per_line:
                        # Try to use PyThaiNLP for word segmentation if available
                        if PYTHAINLP_AVAILABLE:
                            words = word_tokenize(part, engine="newmm")
                            segment_line = ""
                            
                            for word in words:
                                if len(segment_line) + len(word) <= max_chars_per_line:
                                    segment_line += word
                                else:
                                    if segment_line:
                                        wrapped_text.append(segment_line)
                                    
                                    # If the word itself is too long, split it by characters
                                    if len(word) > max_chars_per_line:
                                        for i in range(0, len(word), max_chars_per_line):
                                            chunk = word[i:i + max_chars_per_line]
                                            if i + max_chars_per_line < len(word):
                                                wrapped_text.append(chunk)
                                            else:
                                                segment_line = chunk
                                    else:
                                        segment_line = word
                            
                            if segment_line:
                                current_line = segment_line
                        else:
                            # Fallback to character-based splitting
                            for i in range(0, len(part), max_chars_per_line):
                                chunk = part[i:i + max_chars_per_line]
                                if i + max_chars_per_line < len(part):
                                    wrapped_text.append(chunk)
                                else:
                                    current_line = chunk
                    else:
                        current_line = part
            
            # Add the last line if not empty
            if current_line:
                wrapped_text.append(current_line)
        else:
            # If PyThaiNLP is available, use it for word segmentation
            if PYTHAINLP_AVAILABLE:
                try:
                    words = word_tokenize(text, engine="newmm")
                    current_line = ""
                    
                    for word in words:
                        if len(current_line) + len(word) <= max_chars_per_line:
                            current_line += word
                        else:
                            wrapped_text.append(current_line)
                            
                            # If the word itself is too long, split it by characters
                            if len(word) > max_chars_per_line:
                                for i in range(0, len(word), max_chars_per_line):
                                    chunk = word[i:i + max_chars_per_line]
                                    if i + max_chars_per_line < len(word):
                                        wrapped_text.append(chunk)
                                    else:
                                        current_line = chunk
                            else:
                                current_line = word
                    
                    # Add the last line if not empty
                    if current_line:
                        wrapped_text.append(current_line)
                except Exception as e:
                    logger.error(f"Error in PyThaiNLP word segmentation: {str(e)}")
                    # Fall back to character-based wrapping
                    for i in range(0, len(text), max_chars_per_line):
                        wrapped_text.append(text[i:i + max_chars_per_line])
            else:
                # No spaces in Thai text and PyThaiNLP not available, use character-based wrapping
                for i in range(0, len(text), max_chars_per_line):
                    wrapped_text.append(text[i:i + max_chars_per_line])
    else:
        # For non-Thai text, use word-based wrapping
        words = text.split()
        current_line = ""
        
        for word in words:
            if len(current_line) + len(word) + 1 <= max_chars_per_line:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
            else:
                wrapped_text.append(current_line)
                current_line = word
        
        # Add the last line if not empty
        if current_line:
            wrapped_text.append(current_line)
    
    # If no wrapped text (rare case), use original text
    if not wrapped_text:
        wrapped_text = [text]
    
    return wrapped_text

def create_srt_file(path, segments, delay_seconds=0, max_chars_per_line=30):
    """
    Create an SRT subtitle file from segments with delay and text wrapping.
    
    Args:
        path: Path to save the SRT file
        segments: List of segments with start, end, and text
        delay_seconds: Number of seconds to delay all subtitles
        max_chars_per_line: Maximum characters per line for text wrapping
    
    Returns:
        str: Path to the created SRT file
    """
    def format_time_srt(seconds):
        """Format time in seconds to SRT format (HH:MM:SS,mmm)."""
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"
    
    with open(path, 'w', encoding='utf-8') as f:
        for i, segment in enumerate(segments):
            # Apply delay to start and end times
            start_time = segment["start"] + delay_seconds
            end_time = segment["end"] + delay_seconds
            
            # Format times for SRT
            start_time_str = format_time_srt(start_time)
            end_time_str = format_time_srt(end_time)
            
            # Wrap text to fit within video frame
            text = segment['text'].strip()
            wrapped_text = wrap_thai_text(text, max_chars_per_line)
            
            # Write SRT entry
            f.write(f"{i+1}\n")
            f.write(f"{start_time_str} --> {end_time_str}\n")
            f.write("\n".join(wrapped_text) + "\n\n")
    
    return path
