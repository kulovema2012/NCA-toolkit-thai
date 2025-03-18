import os
import ffmpeg
import logging
import subprocess
import whisper
from datetime import timedelta
import srt
import re
from services.file_management import download_file
from services.cloud_storage import upload_file, upload_to_cloud_storage  # Ensure this import is present
import requests  # Ensure requests is imported for webhook handling
from urllib.parse import urlparse
import tempfile
import datetime
import json
import time

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

STORAGE_PATH = "/tmp/"

POSITION_ALIGNMENT_MAP = {
    "bottom_left": 1,
    "bottom_center": 2,
    "bottom_right": 3,
    "middle_left": 4,
    "middle_center": 5,
    "middle_right": 6,
    "top_left": 7,
    "top_center": 8,
    "top_right": 9
}

def rgb_to_ass_color(rgb_color):
    """Convert RGB hex to ASS (&HAABBGGRR)."""
    if isinstance(rgb_color, str):
        rgb_color = rgb_color.lstrip('#')
        if len(rgb_color) == 6:
            r = int(rgb_color[0:2], 16)
            g = int(rgb_color[2:4], 16)
            b = int(rgb_color[4:6], 16)
            return f"&H00{b:02X}{g:02X}{r:02X}"
    return "&H00FFFFFF"

def generate_transcription(video_path, language='auto'):
    """
    Generate transcription from video using Whisper model.
    Returns a dictionary with segments containing start, end, and text.
    """
    try:
        # Determine the appropriate model size based on language
        # Use medium model for Thai language to improve accuracy
        if language and language.lower() in ['th', 'thai']:
            model_size = "medium"
            language = "th"  # Explicitly set language to Thai
            logger.info(f"Using medium model for Thai language transcription")
        else:
            model_size = "base"
            
        logger.info(f"Loading Whisper {model_size} model for transcription...")
        model = whisper.load_model(model_size)
        logger.info(f"Whisper model loaded successfully")
        
        # Set transcription options
        transcription_options = {
            "word_timestamps": True,  # Enable word-level timestamps
        }
        
        # If language is specified and not 'auto', use it
        if language and language.lower() != 'auto':
            transcription_options["language"] = language
            logger.info(f"Setting language to {language} for transcription")
            
        logger.info(f"Starting transcription with options: {transcription_options}")
        result = model.transcribe(video_path, **transcription_options)
        
        # Ensure proper encoding for Thai text
        if language and language.lower() in ['th', 'thai']:
            for segment in result["segments"]:
                # Ensure text is properly encoded
                if isinstance(segment["text"], str):
                    # Try to fix encoding issues by normalizing the text
                    import unicodedata
                    segment["text"] = unicodedata.normalize('NFC', segment["text"])
                    
                    # Remove any non-Thai characters that might have been incorrectly added
                    thai_range = range(0x0E00, 0x0E7F)
                    cleaned_text = ''.join(c for c in segment["text"] if ord(c) in thai_range or c.isspace() or c in '.!?,;:')
                    if cleaned_text:  # Only replace if we have some text left
                        segment["text"] = cleaned_text
        
        logger.info(f"Transcription completed with {len(result['segments'])} segments")
        logger.info(f"Total duration: {result['segments'][-1]['end'] if result['segments'] else 0} seconds")
        
        return result
    except Exception as e:
        logger.error(f"Error in transcription: {str(e)}")
        raise

def get_video_resolution(video_path):
    try:
        probe = ffmpeg.probe(video_path)
        video_streams = [s for s in probe['streams'] if s['codec_type'] == 'video']
        if video_streams:
            width = int(video_streams[0]['width'])
            height = int(video_streams[0]['height'])
            logger.info(f"Video resolution determined: {width}x{height}")
            return width, height
        else:
            logger.warning(f"No video streams found for {video_path}. Using default resolution 384x288.")
            return 384, 288
    except Exception as e:
        logger.error(f"Error getting video resolution: {str(e)}. Using default resolution 384x288.")
        return 384, 288

def get_available_fonts():
    """Get the list of available fonts on the system."""
    try:
        import matplotlib.font_manager as fm
    except ImportError:
        logger.error("matplotlib not installed. Install via 'pip install matplotlib'.")
        return []
    font_list = fm.findSystemFonts(fontpaths=None, fontext='ttf')
    font_names = set()
    for font in font_list:
        try:
            font_prop = fm.FontProperties(fname=font)
            font_name = font_prop.get_name()
            font_names.add(font_name)
        except Exception:
            continue
    thai_fonts = ["Sarabun", "Garuda", "Loma", "Kinnari", "Norasi", "Sawasdee", 
                 "Tlwg Typist", "Tlwg Typo", "Waree", "Umpush", "Noto Sans Thai"]
    logger.info(f"Available fonts retrieved: {font_names}")
    return list(font_names) + thai_fonts

def format_ass_time(seconds):
    """Convert float seconds to ASS time format H:MM:SS.cc"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    return f"{hours}:{minutes:02}:{secs:02}.{centiseconds:02}"

def process_thai_text(text, replace_dict=None, all_caps=False):
    """
    Special processing for Thai text to ensure proper rendering.
    Thai doesn't use spaces between words, so we need to handle it differently.
    """
    if not text:
        return text
        
    # Apply replacements if provided
    if replace_dict:
        for find, replace in replace_dict.items():
            text = text.replace(find, replace)
    
    # Apply all caps if requested
    if all_caps:
        text = text.upper()
    
    # Add a small amount of spacing between Thai characters to improve rendering
    # This is a workaround for some font rendering issues with Thai
    processed_text = text
    
    logger.debug(f"Processed Thai text: {processed_text}")
    return processed_text

def process_subtitle_text(text, replace_dict=None, all_caps=False, highlight_index=-1):
    """Process subtitle text with replacements and formatting."""
    # Check if text contains Thai characters
    def contains_thai(s):
        thai_range = range(0x0E00, 0x0E7F)
        return any(ord(c) in thai_range for c in s)
    
    if contains_thai(text):
        return process_thai_text(text, replace_dict, all_caps)
    
    # Original processing for non-Thai text
    if replace_dict:
        for find, replace in replace_dict.items():
            text = text.replace(find, replace)
    
    if all_caps:
        text = text.upper()
    
    return text

def srt_to_transcription_result(srt_content):
    """Convert SRT content into a transcription-like structure for uniform processing."""
    subtitles = list(srt.parse(srt_content))
    segments = []
    for sub in subtitles:
        segments.append({
            'start': sub.start.total_seconds(),
            'end': sub.end.total_seconds(),
            'text': sub.content.strip(),
            'words': []  # SRT does not provide word-level timestamps
        })
    logger.info("Converted SRT content to transcription result.")
    return {'segments': segments}

def split_lines(text, max_words_per_line):
    """Split text into lines with a maximum number of words per line."""
    if not max_words_per_line or max_words_per_line <= 0:
        return [text]
        
    # Check if text contains Thai characters
    def contains_thai(s):
        thai_range = range(0x0E00, 0x0E7F)
        return any(ord(c) in thai_range for c in s)
    
    if contains_thai(text):
        # For Thai text, we need a different approach since Thai doesn't use spaces between words
        # We'll use a simple character count approach instead
        chars_per_line = max_words_per_line * 5  # Rough estimate: 5 chars per word
        if len(text) <= chars_per_line:
            return [text]
        
        # Split by character count
        return [text[i:i+chars_per_line] for i in range(0, len(text), chars_per_line)]
    else:
        # For non-Thai text, split by words
        words = text.split()
        if len(words) <= max_words_per_line:
            return [text]
        
        # Split into chunks of max_words_per_line
        return [' '.join(words[i:i+max_words_per_line]) for i in range(0, len(words), max_words_per_line)]

def is_url(string):
    """Check if the given string is a valid HTTP/HTTPS URL."""
    try:
        result = urlparse(string)
        return result.scheme in ('http', 'https')
    except:
        return False

def download_captions(captions_url):
    """Download captions from the given URL."""
    try:
        logger.info(f"Downloading captions from URL: {captions_url}")
        response = requests.get(captions_url)
        response.raise_for_status()
        logger.info("Captions downloaded successfully.")
        return response.text
    except Exception as e:
        logger.error(f"Error downloading captions: {str(e)}")
        raise

def determine_alignment_code(position_str, alignment_str, x, y, video_width, video_height):
    """
    Determine the final \an alignment code and (x,y) position based on:
    - x,y (if provided)
    - position_str (one of top_left, top_center, ...)
    - alignment_str (left, center, right)
    - If x,y not provided, divide the video into a 3x3 grid and position accordingly.
    """
    logger.info(f"[determine_alignment_code] Inputs: position_str={position_str}, alignment_str={alignment_str}, x={x}, y={y}, video_width={video_width}, video_height={video_height}")

    horizontal_map = {
        'left': 1,
        'center': 2,
        'right': 3
    }

    # If x and y are provided, use them directly and set \an based on alignment_str
    if x is not None and y is not None:
        logger.info("[determine_alignment_code] x and y provided, ignoring position and alignment for grid.")
        vertical_code = 4  # Middle row
        horiz_code = horizontal_map.get(alignment_str, 2)  # Default to center
        an_code = vertical_code + (horiz_code - 1)
        logger.info(f"[determine_alignment_code] Using provided x,y. an_code={an_code}")
        return an_code, True, x, y

    # No x,y provided: determine position and alignment based on grid
    pos_lower = position_str.lower()
    if 'top' in pos_lower:
        vertical_base = 7  # Top row an codes start at 7
        vertical_center = video_height / 6
    elif 'middle' in pos_lower:
        vertical_base = 4  # Middle row an codes start at 4
        vertical_center = video_height / 2
    else:
        vertical_base = 1  # Bottom row an codes start at 1
        vertical_center = (5 * video_height) / 6

    if 'left' in pos_lower:
        left_boundary = 0
        right_boundary = video_width / 3
        center_line = video_width / 6
    elif 'right' in pos_lower:
        left_boundary = (2 * video_width) / 3
        right_boundary = video_width
        center_line = (5 * video_width) / 6
    else:
        # Center column
        left_boundary = video_width / 3
        right_boundary = (2 * video_width) / 3
        center_line = video_width / 2

    # Alignment affects horizontal position within the cell
    if alignment_str == 'left':
        final_x = left_boundary
        horiz_code = 1
    elif alignment_str == 'right':
        final_x = right_boundary
        horiz_code = 3
    else:
        final_x = center_line
        horiz_code = 2

    final_y = vertical_center
    an_code = vertical_base + (horiz_code - 1)

    logger.info(f"[determine_alignment_code] Computed final_x={final_x}, final_y={final_y}, an_code={an_code}")
    return an_code, True, int(final_x), int(final_y)

def generate_ass_style(style_name, style_options):
    """
    Create the style line for ASS subtitles.
    """
    # Get font family or default to Arial
    font_family = style_options.get('font_family', 'Arial')
    
    # Get font size or default to 48
    font_size = style_options.get('font_size', 48)
    
    # Get colors
    primary_color = rgb_to_ass_color(style_options.get('line_color', '#FFFFFF'))
    secondary_color = rgb_to_ass_color(style_options.get('word_color', '#FFFF00'))
    outline_color = rgb_to_ass_color(style_options.get('outline_color', '#000000'))
    
    # Get outline width or default to 2
    outline = style_options.get('outline_width', 2)
    
    # Get shadow offset or default to 1
    shadow = style_options.get('shadow_offset', 1)
    
    # Get bold, italic, underline, strikeout flags
    bold = -1 if style_options.get('bold', False) else 0
    italic = -1 if style_options.get('italic', False) else 0
    underline = -1 if style_options.get('underline', False) else 0
    strikeout = -1 if style_options.get('strikeout', False) else 0
    
    # Add background box by setting the BackColour and BorderStyle
    back_color = "&H80000000"  # Semi-transparent black background
    border_style = 4  # Opaque box
    
    # Create the style line
    style_line = f"Style: {style_name},"\
                f"{font_family},{font_size},"\
                f"{primary_color},{secondary_color},{outline_color},{back_color},"\
                f"{bold},{italic},{underline},{strikeout},"\
                f"{outline},{shadow},{border_style},"\
                f"1,0,0,0,100,100,0,0"
    
    return style_line

def generate_ass_header(style_options, video_resolution):
    """
    Generate the ASS file header with the Default style.
    """
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_resolution[0]}
PlayResY: {video_resolution[1]}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""
    style_line = generate_ass_style('Default', style_options)
    if isinstance(style_line, dict) and 'error' in style_line:
        # Font-related error
        return style_line

    ass_header += style_line + "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    logger.info("Generated ASS header.")
    return ass_header

### STYLE HANDLERS ###

def handle_classic(transcription_result, style_options, replace_dict, video_resolution):
    """
    Classic style handler: Centers the text based on position and alignment.
    """
    max_words_per_line = int(style_options.get('max_words_per_line', 0))
    all_caps = style_options.get('all_caps', False)
    if style_options['font_size'] is None:
        style_options['font_size'] = int(video_resolution[1] * 0.05)

    position_str = style_options.get('position', 'middle_center')
    alignment_str = style_options.get('alignment', 'center')
    x = style_options.get('x')
    y = style_options.get('y')

    an_code, use_pos, final_x, final_y = determine_alignment_code(
        position_str, alignment_str, x, y,
        video_width=video_resolution[0],
        video_height=video_resolution[1]
    )

    logger.info(f"[Classic] position={position_str}, alignment={alignment_str}, x={final_x}, y={final_y}, an_code={an_code}")

    events = []
    for segment in transcription_result['segments']:
        text = segment['text'].strip().replace('\n', ' ')
        lines = split_lines(text, max_words_per_line)
        processed_text = '\\N'.join(process_subtitle_text(line, replace_dict, all_caps, 0) for line in lines)
        start_time = format_ass_time(segment['start'])
        end_time = format_ass_time(segment['end'])
        position_tag = f"{{\\an{an_code}\\pos({final_x},{final_y})}}"
        events.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{position_tag}{processed_text}")
    logger.info(f"Handled {len(events)} dialogues in classic style.")
    return "\n".join(events)

def handle_karaoke(transcription_result, style_options, replace_dict, video_resolution):
    """
    Karaoke style handler: Highlights words as they are spoken.
    """
    max_words_per_line = int(style_options.get('max_words_per_line', 0))
    all_caps = style_options.get('all_caps', False)
    if style_options['font_size'] is None:
        style_options['font_size'] = int(video_resolution[1] * 0.05)

    position_str = style_options.get('position', 'middle_center')
    alignment_str = style_options.get('alignment', 'center')
    x = style_options.get('x')
    y = style_options.get('y')

    an_code, use_pos, final_x, final_y = determine_alignment_code(
        position_str, alignment_str, x, y,
        video_width=video_resolution[0],
        video_height=video_resolution[1]
    )
    word_color = rgb_to_ass_color(style_options.get('word_color', '#FFFF00'))

    logger.info(f"[Karaoke] position={position_str}, alignment={alignment_str}, x={final_x}, y={final_y}, an_code={an_code}")

    events = []
    for segment in transcription_result['segments']:
        words = segment.get('words', [])
        if not words:
            continue

        if max_words_per_line > 0:
            lines_content = []
            current_line = []
            current_line_words = 0
            for w_info in words:
                w = process_subtitle_text(w_info.get('word', ''), replace_dict, all_caps, 0)
                duration_cs = int(round((w_info['end'] - w_info['start']) * 100))
                highlighted_word = f"{{\\k{duration_cs}}}{w} "
                current_line.append(highlighted_word)
                current_line_words += 1
                if current_line_words >= max_words_per_line:
                    lines_content.append(''.join(current_line).strip())
                    current_line = []
                    current_line_words = 0
            if current_line:
                lines_content.append(''.join(current_line).strip())
        else:
            line_content = []
            for w_info in words:
                w = process_subtitle_text(w_info.get('word', ''), replace_dict, all_caps, 0)
                duration_cs = int(round((w_info['end'] - w_info['start']) * 100))
                highlighted_word = f"{{\\k{duration_cs}}}{w} "
                line_content.append(highlighted_word)
            lines_content = [''.join(line_content).strip()]

        dialogue_text = '\\N'.join(lines_content)
        start_time = format_ass_time(words[0]['start'])
        end_time = format_ass_time(words[-1]['end'])
        position_tag = f"{{\\an{an_code}\\pos({final_x},{final_y})}}"
        events.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{position_tag}{{\\c{word_color}}}{dialogue_text}")
    logger.info(f"Handled {len(events)} dialogues in karaoke style.")
    return "\n".join(events)

def handle_highlight(transcription_result, style_options, replace_dict, video_resolution):
    """
    Highlight style handler: Highlights words sequentially.
    """
    max_words_per_line = int(style_options.get('max_words_per_line', 0))
    all_caps = style_options.get('all_caps', False)
    if style_options['font_size'] is None:
        style_options['font_size'] = int(video_resolution[1] * 0.05)

    position_str = style_options.get('position', 'middle_center')
    alignment_str = style_options.get('alignment', 'center')
    x = style_options.get('x')
    y = style_options.get('y')

    an_code, use_pos, final_x, final_y = determine_alignment_code(
        position_str, alignment_str, x, y,
        video_width=video_resolution[0],
        video_height=video_resolution[1]
    )

    word_color = rgb_to_ass_color(style_options.get('word_color', '#FFFF00'))
    line_color = rgb_to_ass_color(style_options.get('line_color', '#FFFFFF'))
    events = []

    logger.info(f"[Highlight] position={position_str}, alignment={alignment_str}, x={final_x}, y={final_y}, an_code={an_code}")

    for segment in transcription_result['segments']:
        words = segment.get('words', [])
        if not words:
            continue
        processed_words = []
        for w_info in words:
            w = process_subtitle_text(w_info.get('word', ''), replace_dict, all_caps, 0)
            if w:
                processed_words.append((w, w_info['start'], w_info['end']))

        if not processed_words:
            continue

        if max_words_per_line > 0:
            line_sets = [processed_words[i:i+max_words_per_line] for i in range(0, len(processed_words), max_words_per_line)]
        else:
            line_sets = [processed_words]

        for line_set in line_sets:
            for idx, (word, w_start, w_end) in enumerate(line_set):
                line_words = []
                for w_idx, (w_text, _, _) in enumerate(line_set):
                    if w_idx == idx:
                        line_words.append(f"{{\\c{word_color}}}{w_text}{{\\c{line_color}}}")
                    else:
                        line_words.append(w_text)
                full_text = ' '.join(line_words)
                start_time = format_ass_time(w_start)
                end_time = format_ass_time(w_end)
                position_tag = f"{{\\an{an_code}\\pos({final_x},{final_y})}}"
                events.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{position_tag}{{\\c{line_color}}}{full_text}")
    logger.info(f"Handled {len(events)} dialogues in highlight style.")
    return "\n".join(events)

def handle_underline(transcription_result, style_options, replace_dict, video_resolution):
    """
    Underline style handler: Underlines the current word.
    """
    max_words_per_line = int(style_options.get('max_words_per_line', 0))
    all_caps = style_options.get('all_caps', False)
    if style_options['font_size'] is None:
        style_options['font_size'] = int(video_resolution[1] * 0.05)

    position_str = style_options.get('position', 'middle_center')
    alignment_str = style_options.get('alignment', 'center')
    x = style_options.get('x')
    y = style_options.get('y')

    an_code, use_pos, final_x, final_y = determine_alignment_code(
        position_str, alignment_str, x, y,
        video_width=video_resolution[0],
        video_height=video_resolution[1]
    )
    line_color = rgb_to_ass_color(style_options.get('line_color', '#FFFFFF'))
    events = []

    logger.info(f"[Underline] position={position_str}, alignment={alignment_str}, x={final_x}, y={final_y}, an_code={an_code}")

    for segment in transcription_result['segments']:
        words = segment.get('words', [])
        if not words:
            continue
        processed_words = []
        for w_info in words:
            w = process_subtitle_text(w_info.get('word', ''), replace_dict, all_caps, 0)
            if w:
                processed_words.append((w, w_info['start'], w_info['end']))

        if not processed_words:
            continue

        if max_words_per_line > 0:
            line_sets = [processed_words[i:i+max_words_per_line] for i in range(0, len(processed_words), max_words_per_line)]
        else:
            line_sets = [processed_words]

        for line_set in line_sets:
            for idx, (word, w_start, w_end) in enumerate(line_set):
                line_words = []
                for w_idx, (w_text, _, _) in enumerate(line_set):
                    if w_idx == idx:
                        line_words.append(f"{{\\u1}}{w_text}{{\\u0}}")
                    else:
                        line_words.append(w_text)
                full_text = ' '.join(line_words)
                start_time = format_ass_time(w_start)
                end_time = format_ass_time(w_end)
                position_tag = f"{{\\an{an_code}\\pos({final_x},{final_y})}}"
                events.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{position_tag}{{\\c{line_color}}}{full_text}")
    logger.info(f"Handled {len(events)} dialogues in underline style.")
    return "\n".join(events)

def handle_word_by_word(transcription_result, style_options, replace_dict, video_resolution):
    """
    Word-by-Word style handler: Displays each word individually.
    """
    max_words_per_line = int(style_options.get('max_words_per_line', 0))
    all_caps = style_options.get('all_caps', False)
    if style_options['font_size'] is None:
        style_options['font_size'] = int(video_resolution[1] * 0.05)

    position_str = style_options.get('position', 'middle_center')
    alignment_str = style_options.get('alignment', 'center')
    x = style_options.get('x')
    y = style_options.get('y')

    an_code, use_pos, final_x, final_y = determine_alignment_code(
        position_str, alignment_str, x, y,
        video_width=video_resolution[0],
        video_height=video_resolution[1]
    )
    word_color = rgb_to_ass_color(style_options.get('word_color', '#FFFF00'))
    events = []

    logger.info(f"[Word-by-Word] position={position_str}, alignment={alignment_str}, x={final_x}, y={final_y}, an_code={an_code}")

    for segment in transcription_result['segments']:
        words = segment.get('words', [])
        if not words:
            continue

        if max_words_per_line > 0:
            grouped_words = [words[i:i+max_words_per_line] for i in range(0, len(words), max_words_per_line)]
        else:
            grouped_words = [words]

        for word_group in grouped_words:
            for w_info in word_group:
                w = process_subtitle_text(w_info.get('word', ''), replace_dict, all_caps, 0)
                if not w:
                    continue
                start_time = format_ass_time(w_info['start'])
                end_time = format_ass_time(w_info['end'])
                position_tag = f"{{\\an{an_code}\\pos({final_x},{final_y})}}"
                events.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{position_tag}{{\\c{word_color}}}{w}")
    logger.info(f"Handled {len(events)} dialogues in word-by-word style.")
    return "\n".join(events)

STYLE_HANDLERS = {
    'classic': handle_classic,
    'karaoke': handle_karaoke,
    'highlight': handle_highlight,
    'underline': handle_underline,
    'word_by_word': handle_word_by_word
}

def srt_to_ass(transcription_result, style_type, settings, replace_dict, video_resolution):
    """
    Convert transcription result to ASS based on the specified style.
    """
    default_style_settings = {
        'line_color': '#FFFFFF',
        'word_color': '#FFFF00',
        'box_color': '#000000',
        'outline_color': '#000000',
        'all_caps': False,
        'max_words_per_line': 0,
        'font_size': None,
        'font_family': 'Arial',
        'bold': False,
        'italic': False,
        'underline': False,
        'strikeout': False,
        'outline_width': 2,
        'shadow_offset': 0,
        'border_style': 1,
        'x': None,
        'y': None,
        'position': 'middle_center',
        'alignment': 'center'  # default alignment
    }
    style_options = {**default_style_settings, **settings}

    if style_options['font_size'] is None:
        style_options['font_size'] = int(video_resolution[1] * 0.05)

    ass_header = generate_ass_header(style_options, video_resolution)
    if isinstance(ass_header, dict) and 'error' in ass_header:
        # Font-related error
        return ass_header

    handler = STYLE_HANDLERS.get(style_type.lower())
    if not handler:
        logger.warning(f"Unknown style '{style_type}', defaulting to 'classic'.")
        handler = handle_classic

    dialogue_lines = handler(transcription_result, style_options, replace_dict, video_resolution)
    logger.info("Converted transcription result to ASS format.")
    return ass_header + dialogue_lines + "\n"

def process_subtitle_events(transcription_result, style_type, settings, replace_dict, video_resolution):
    """
    Process transcription results into ASS subtitle format.
    """
    return srt_to_ass(transcription_result, style_type, settings, replace_dict, video_resolution)

def write_ass_file(ass_content, output_dir, job_id):
    """Write ASS content to a file and return the file path."""
    ass_file = os.path.join(output_dir, f"{job_id}_subtitles.ass")
    
    # Ensure we're writing with UTF-8 encoding to properly handle Thai characters
    with open(ass_file, 'w', encoding='utf-8') as f:
        f.write(ass_content)
    
    logger.info(f"ASS file written to {ass_file}")
    return ass_file

def write_srt_file(srt_content, output_dir, job_id):
    """Write SRT content to a file and return the file path."""
    srt_file = os.path.join(output_dir, f"{job_id}_subtitles.srt")
    
    # Ensure we're writing with UTF-8 encoding to properly handle Thai characters
    with open(srt_file, 'w', encoding='utf-8') as f:
        f.write(srt_content)
    
    logger.info(f"SRT file written to {srt_file}")
    return srt_file

def download_video(url, job_id):
    """
    Download a video from a URL with progress logging.
    """
    try:
        local_filename = os.path.join(STORAGE_PATH, f"{job_id}_input.mp4")
        logger.info(f"Job {job_id}: Downloading video from {url}")
        
        # Stream the download with progress reporting
        response = requests.get(url, stream=True)
        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192
        downloaded = 0
        
        with open(local_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    # Log progress every 10%
                    if total_size > 0 and downloaded % (total_size // 10) < block_size:
                        progress = (downloaded / total_size) * 100
                        logger.info(f"Job {job_id}: Download progress: {progress:.1f}%")
        
        logger.info(f"Job {job_id}: Video downloaded successfully to {local_filename}")
        return local_filename
    except Exception as e:
        logger.error(f"Job {job_id}: Error downloading video: {str(e)}")
        raise

def add_subtitles_to_video(video_path, subtitle_path, output_path=None, job_id=None, 
                          font_name="Sarabun", font_size=24, margin_v=30, 
                          subtitle_style="classic", max_width=None, position="bottom",
                          line_color=None, word_color=None, outline_color=None,
                          all_caps=False, max_words_per_line=None, x=None, y=None,
                          alignment="center", bold=False, italic=False, underline=False,
                          strikeout=False):
    try:
        # Log the input parameters for debugging
        logger.info(f"Job {job_id}: Adding subtitles to video with parameters:")
        logger.info(f"Job {job_id}: video_path: {video_path}")
        logger.info(f"Job {job_id}: subtitle_path: {subtitle_path}")
        logger.info(f"Job {job_id}: output_path: {output_path}")
        logger.info(f"Job {job_id}: job_id: {job_id}")
        logger.info(f"Job {job_id}: font_name: {font_name}")
        logger.info(f"Job {job_id}: font_size: {font_size}")
        logger.info(f"Job {job_id}: margin_v: {margin_v}")
        logger.info(f"Job {job_id}: subtitle_style: {subtitle_style}")
        logger.info(f"Job {job_id}: max_width: {max_width}")
        logger.info(f"Job {job_id}: position: {position}")
        logger.info(f"Job {job_id}: line_color: {line_color}")
        logger.info(f"Job {job_id}: word_color: {word_color}")
        logger.info(f"Job {job_id}: outline_color: {outline_color}")
        logger.info(f"Job {job_id}: all_caps: {all_caps}")
        logger.info(f"Job {job_id}: max_words_per_line: {max_words_per_line}")
        logger.info(f"Job {job_id}: x: {x}")
        logger.info(f"Job {job_id}: y: {y}")
        logger.info(f"Job {job_id}: alignment: {alignment}")
        logger.info(f"Job {job_id}: bold: {bold}")
        logger.info(f"Job {job_id}: italic: {italic}")
        logger.info(f"Job {job_id}: underline: {underline}")
        logger.info(f"Job {job_id}: strikeout: {strikeout}")

        # Generate a job ID if not provided
        if not job_id:
            job_id = f"caption_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Create a temporary directory for processing
        temp_dir = os.path.join(tempfile.gettempdir(), job_id)
        os.makedirs(temp_dir, exist_ok=True)

        # Process SRT file to ensure subtitles don't appear before audio starts
        # This helps with the issue of subtitles appearing at 0.00 seconds
        modified_srt = os.path.join(temp_dir, f"modified_{job_id}.srt")
        with open(subtitle_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse SRT content
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
        
        # Filter out subtitles with no text and ensure proper timing
        filtered_srt_data = []
        min_start_time = 0.8  # Minimum start time in seconds to ensure voice-over has begun
        
        for i, block in enumerate(srt_data):
            # Skip empty subtitles
            if not ''.join(block["text"]).strip():
                continue
                
            # Parse time
            time_parts = block["time"].split('-->')
            start_time_str = time_parts[0].strip()
            end_time_str = time_parts[1].strip()
            
            # Convert start time to seconds for comparison
            h, m, s = start_time_str.split(':')
            s, ms = s.split(',')
            start_time_seconds = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            
            # Ensure first subtitle doesn't start too early
            if i == 0 and start_time_seconds < min_start_time:
                # Format new start time
                total_ms = int(min_start_time * 1000)
                new_h = total_ms // 3600000
                new_m = (total_ms % 3600000) // 60000
                new_s = (total_ms % 60000) // 1000
                new_ms = total_ms % 1000
                
                new_start_time = f"{new_h:02d}:{new_m:02d}:{new_s:02d},{new_ms:03d}"
                block["time"] = f"{new_start_time} --> {end_time_str}"
            
            filtered_srt_data.append(block)
        
        # Write modified SRT
        with open(modified_srt, 'w', encoding='utf-8') as f:
            for i, block in enumerate(filtered_srt_data):
                f.write(f"{i+1}\n")
                f.write(f"{block['time']}\n")
                f.write('\n'.join(block["text"]) + '\n\n')
        
        subtitle_path = modified_srt
        
        # Process text for all_caps if needed
        subtitle_filters = []
        if all_caps:
            # Create a temporary SRT file with uppercase text
            original_srt = subtitle_path
            uppercase_srt = os.path.join(temp_dir, f"uppercase_{job_id}.srt")
            
            with open(original_srt, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Convert text to uppercase while preserving SRT format
            lines = content.split('\n')
            for i in range(len(lines)):
                # Skip timestamp lines and empty lines
                if '-->' in lines[i] or lines[i].strip() == '' or lines[i].strip().isdigit():
                    continue
                lines[i] = lines[i].upper()
            
            with open(uppercase_srt, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            subtitle_path = uppercase_srt
        
        # Process max_words_per_line if needed
        if max_words_per_line:
            # Create a temporary SRT file with limited words per line
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
            
            # Reformat with max words per line
            with open(limited_srt, 'w', encoding='utf-8') as f:
                for block in srt_data:
                    # Join all text lines
                    text = ' '.join(block["text"])
                    words = text.split()
                    
                    # Split into chunks of max_words_per_line
                    new_lines = []
                    for i in range(0, len(words), max_words_per_line):
                        new_lines.append(' '.join(words[i:i+max_words_per_line]))
                    
                    # Write the reformatted block
                    f.write(block["index"] + '\n')
                    f.write(block["time"] + '\n')
                    f.write('\n'.join(new_lines) + '\n\n')
            
            subtitle_path = limited_srt
        
        # Determine subtitle position and alignment
        subtitle_position = position
        if x is not None and y is not None:
            # Custom position overrides predefined positions
            subtitle_position = "custom"
        
        # Base subtitle filter
        subtitle_filter = f"subtitles='{subtitle_path}'"
        
        # Add font settings
        subtitle_filter += f":force_style='FontName={font_name},FontSize={font_size}"
        
        # Add text formatting
        if bold:
            subtitle_filter += ",Bold=1"
        if italic:
            subtitle_filter += ",Italic=1"
        if underline:
            subtitle_filter += ",Underline=1"
        if strikeout:
            subtitle_filter += ",StrikeOut=1"
        
        # Add alignment
        alignment_value = "2"  # Default center
        if alignment == "left":
            alignment_value = "1"
        elif alignment == "right":
            alignment_value = "3"
        subtitle_filter += f",Alignment={alignment_value}"
        
        # Add colors if specified
        if line_color:
            # Remove # if present and ensure it's a valid hex color
            line_color = line_color.lstrip('#')
            if len(line_color) == 6:
                subtitle_filter += f",PrimaryColour=&H{line_color}&"
        
        if outline_color:
            outline_color = outline_color.lstrip('#')
            if len(outline_color) == 6:
                subtitle_filter += f",OutlineColour=&H{outline_color}&"
        
        if word_color and subtitle_style in ["karaoke", "highlight"]:
            word_color = word_color.lstrip('#')
            if len(word_color) == 6:
                subtitle_filter += f",SecondaryColour=&H{word_color}&"
        
        # Add margin based on position - ensure subtitles stay within video frame
        # Default margin is increased to ensure text is fully visible
        default_margin_v = max(margin_v, 40)  # Ensure minimum margin of 40 pixels
        
        if subtitle_position == "bottom":
            subtitle_filter += f",MarginV={default_margin_v}"
        elif subtitle_position == "top":
            subtitle_filter += f",MarginV={default_margin_v}"
        elif subtitle_position == "middle":
            subtitle_filter += f",MarginV=0"
        elif subtitle_position == "custom" and x is not None and y is not None:
            subtitle_filter += f",MarginL={x},MarginR=0,MarginV={y}"
        
        # Add max width if specified
        if max_width:
            # Convert percentage to ASS script units
            subtitle_filter += f",PlayResX=384,PlayResY=288,MarginL={int(384*(100-max_width)/200)},MarginR={int(384*(100-max_width)/200)}"
        
        # Close the force_style parameter
        subtitle_filter += "'"
        
        # Add the subtitle filter to the list
        subtitle_filters.append(subtitle_filter)
        
        # Combine all filters
        filter_complex = ','.join(subtitle_filters)
        
        # Build the FFmpeg command
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-filter_complex", filter_complex,
            "-c:v", "libx264", "-crf", "18",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            output_path
        ]
        
        # Log the command
        logger.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        
        # Execute the command
        subprocess.run(ffmpeg_cmd, check=True)
        
        # Upload to cloud storage if needed
        file_url = None
        upload_to_cloud = is_url(video_path)  # Upload to cloud if input was a URL
        
        if upload_to_cloud:
            # If the input was a URL, upload the output to cloud storage
            from services.cloud_storage import upload_file
            file_url = upload_file(output_path)
            logger.info(f"Uploaded output file to cloud storage: {file_url}")
        else:
            # If the input was a local file, just return the local path
            file_url = f"file://{output_path}"
        
        # Extract metadata using ffprobe
        video_info = {}
        try:
            # Run ffprobe to get video metadata
            ffprobe_cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                output_path
            ]
            
            ffprobe_output = subprocess.check_output(ffprobe_cmd, stderr=subprocess.STDOUT)
            video_info_raw = json.loads(ffprobe_output.decode('utf-8'))
            
            # Process the metadata to ensure it's all serializable
            video_info = {
                "format": {},
                "streams": []
            }
            
            # Process format information
            if "format" in video_info_raw and isinstance(video_info_raw["format"], dict):
                for key, value in video_info_raw["format"].items():
                    # Convert all values to basic Python types
                    if isinstance(value, (int, float, str, bool, type(None))):
                        video_info["format"][key] = value
                    else:
                        video_info["format"][key] = str(value)
            
            # Process stream information
            if "streams" in video_info_raw and isinstance(video_info_raw["streams"], list):
                for stream in video_info_raw["streams"]:
                    if isinstance(stream, dict):
                        stream_info = {}
                        for key, value in stream.items():
                            # Convert all values to basic Python types
                            if isinstance(value, (int, float, str, bool, type(None))):
                                stream_info[key] = value
                            else:
                                stream_info[key] = str(value)
                        video_info["streams"].append(stream_info)
            
            # Generate thumbnail
            thumbnail_path = os.path.join(temp_dir, f"thumbnail_{job_id}.jpg")
            thumbnail_cmd = [
                "ffmpeg",
                "-i", output_path,
                "-ss", "00:00:05",  # Take screenshot at 5 seconds
                "-vframes", "1",
                "-vf", "scale=320:-1",  # Scale to width 320px, maintain aspect ratio
                "-y",
                thumbnail_path
            ]
            
            subprocess.run(thumbnail_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Upload thumbnail if needed
            thumbnail_url = None
            if upload_to_cloud:
                from services.cloud_storage import upload_to_cloud_storage
                thumbnail_url = upload_to_cloud_storage(thumbnail_path, f"thumbnails/{os.path.basename(thumbnail_path)}")
                video_info["thumbnail_url"] = str(thumbnail_url)
            
        except Exception as e:
            logger.warning(f"Error getting video metadata: {str(e)}")
            video_info = {}
        
        # Calculate processing time
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Return the result
        result = {
            "file_url": file_url,
            "local_path": output_path,
            "processing_time": processing_time,
            "metadata": video_info
        }
        
        return result
    except Exception as e:
        logger.error(f"Error adding subtitles: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def process_captioning_v1(video_url, captions, settings, replace, job_id, language='auto'):
    try:
        # Log the input parameters for debugging
        logger.info(f"Job {job_id}: Processing video captioning with parameters:")
        logger.info(f"Job {job_id}: video_url: {video_url}")
        logger.info(f"Job {job_id}: captions provided: {'Yes' if captions else 'No'}")
        logger.info(f"Job {job_id}: settings: {settings}")
        logger.info(f"Job {job_id}: language: {language}")
        
        if not isinstance(settings, dict):
            logger.error(f"Job {job_id}: 'settings' should be a dictionary.")
            return {"error": "'settings' should be a dictionary."}

        # Normalize keys by replacing hyphens with underscores
        style_options = {k.replace('-', '_'): v for k, v in settings.items()}

        if not isinstance(replace, list):
            logger.error(f"Job {job_id}: 'replace' should be a list of objects with 'find' and 'replace' keys.")
            return {"error": "'replace' should be a list of objects with 'find' and 'replace' keys."}

        # Convert 'replace' list to dictionary
        replace_dict = {}
        for item in replace:
            if 'find' in item and 'replace' in item:
                replace_dict[item['find']] = item['replace']
            else:
                logger.warning(f"Job {job_id}: Invalid replace item {item}. Skipping.")

        # Handle deprecated 'highlight_color' by merging it into 'word_color'
        if 'highlight_color' in style_options:
            logger.warning(f"Job {job_id}: 'highlight_color' is deprecated; merging into 'word_color'.")
            style_options['word_color'] = style_options.pop('highlight_color')

        # Check font availability
        font_family = style_options.get('font_family', 'Arial')
        available_fonts = get_available_fonts()
        
        # Case-insensitive font matching
        font_found = False
        for available_font in available_fonts:
            if font_family.lower() == available_font.lower():
                # Use the correctly cased font name
                style_options['font_family'] = available_font
                font_found = True
                break
                
        if not font_found:
            logger.warning(f"Job {job_id}: Font '{font_family}' not found. Falling back to Arial.")
            style_options['font_family'] = 'Arial'

        logger.info(f"Job {job_id}: Using font '{style_options['font_family']}' for captioning.")

        # If no captions provided but we have a video URL, use empty captions rather than failing
        # This ensures we at least process the video even without subtitles
        if captions is None and video_url:
            logger.warning(f"Job {job_id}: No captions provided and auto-transcription not enabled. Processing video without subtitles.")
            captions = ""

        # Determine if captions is a URL or raw content
        if captions and is_url(captions):
            logger.info(f"Job {job_id}: Captions provided as URL. Downloading captions.")
            try:
                captions_content = download_captions(captions)
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to download captions: {str(e)}")
                return {"error": f"Failed to download captions: {str(e)}"}
        elif captions:
            logger.info(f"Job {job_id}: Captions provided as raw content.")
            captions_content = captions
        else:
            captions_content = None

        # Download the video
        try:
            video_path = download_video(video_url, job_id)
            logger.info(f"Job {job_id}: Video downloaded to {video_path}")
        except Exception as e:
            logger.error(f"Job {job_id}: Video download error: {str(e)}")
            return {"error": str(e)}

        # Get video resolution
        video_resolution = get_video_resolution(video_path)
        logger.info(f"Job {job_id}: Video resolution detected = {video_resolution[0]}x{video_resolution[1]}")

        # Determine style type
        style_type = style_options.get('style', 'classic').lower()
        logger.info(f"Job {job_id}: Using style '{style_type}' for captioning.")

        # Determine subtitle content
        if captions_content:
            # Check if it's ASS by looking for '[Script Info]'
            if '[Script Info]' in captions_content:
                # It's ASS directly
                subtitle_content = captions_content
                subtitle_type = 'ass'
                logger.info(f"Job {job_id}: Detected ASS formatted captions.")
            else:
                # Treat as SRT
                logger.info(f"Job {job_id}: Detected SRT formatted captions.")
                # Validate style for SRT
                if style_type != 'classic':
                    error_message = "Only 'classic' style is supported for SRT captions."
                    logger.error(f"Job {job_id}: {error_message}")
                    return {"error": error_message}
                transcription_result = srt_to_transcription_result(captions_content)
                # Generate ASS based on chosen style
                subtitle_content = process_subtitle_events(transcription_result, style_type, style_options, replace_dict, video_resolution)
                subtitle_type = 'ass'
        else:
            # No captions provided, generate transcription
            logger.info(f"Job {job_id}: No captions provided, generating transcription.")
            transcription_result = generate_transcription(video_path, language=language)
            # Generate ASS based on chosen style
            subtitle_content = process_subtitle_events(transcription_result, style_type, style_options, replace_dict, video_resolution)
            subtitle_type = 'ass'

        # Check for subtitle processing errors
        if isinstance(subtitle_content, dict) and 'error' in subtitle_content:
            logger.error(f"Job {job_id}: {subtitle_content['error']}")
            return {"error": subtitle_content['error']}

        # Save the subtitle content
        if subtitle_type == 'ass':
            subtitle_path = write_ass_file(subtitle_content, STORAGE_PATH, job_id)
        else:
            subtitle_path = write_srt_file(subtitle_content, STORAGE_PATH, job_id)
        
        logger.info(f"Job {job_id}: Subtitle file saved to {subtitle_path}")

        # Prepare output filename and path
        output_filename = f"{job_id}_captioned.mp4"
        output_path = os.path.join(STORAGE_PATH, output_filename)

        # Add subtitles to video
        output_path = os.path.join(STORAGE_PATH, output_filename)
        try:
            # Use our improved subtitle addition function
            captioned_video_path = add_subtitles_to_video(video_path, subtitle_path, output_path, job_id)
            
            if not captioned_video_path:
                logger.error(f"Job {job_id}: Failed to add subtitles to video")
                return {"error": "Failed to add subtitles to video"}
                
            logger.info(f"Job {job_id}: Video with captions saved to {captioned_video_path}")
        except Exception as e:
            logger.error(f"Job {job_id}: Error adding subtitles to video: {str(e)}")
            return {"error": f"Error adding subtitles to video: {str(e)}"}

        # Upload the output file to cloud storage
        try:
            file_url = None
            if is_url(video_path):
                # If the input was a URL, upload the output to cloud storage
                from services.cloud_storage import upload_file
                file_url = upload_file(output_path)
                logger.info(f"Uploaded output file to cloud storage: {file_url}")
            else:
                # If the input was a local file, just return the local path
                file_url = f"file://{output_path}"
            return {"file_url": file_url}
        except Exception as upload_error:
            logger.error(f"Job {job_id}: Failed to upload captioned video: {str(upload_error)}")
            return {"error": f"Failed to upload captioned video: {str(upload_error)}"}

    except Exception as e:
        logger.error(f"Job {job_id}: Error in process_captioning_v1: {str(e)}", exc_info=True)
        return {"error": str(e)}
