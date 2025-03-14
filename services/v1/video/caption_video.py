import os
import ffmpeg
import logging
import subprocess
import whisper
from datetime import timedelta
import srt
import re
from services.file_management import download_file
from services.cloud_storage import upload_file  # Ensure this import is present
import requests  # Ensure requests is imported for webhook handling
from urllib.parse import urlparse

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

def add_subtitles_to_video(video_path, subtitle_path, output_path, job_id=None, 
                          font_name="Sarabun", font_size=24, margin_v=30, 
                          subtitle_style="classic", max_width=None, position="bottom"):
    """
    Add subtitles to a video using FFmpeg.
    
    Args:
        video_path: Path to the input video file
        subtitle_path: Path to the subtitle file (SRT format)
        output_path: Path to save the output video
        job_id: Optional job ID for logging
        font_name: Font name to use for subtitles (default: Sarabun for Thai)
        font_size: Font size for subtitles (default: 24)
        margin_v: Vertical margin from the bottom/top of the frame (default: 30)
        subtitle_style: Style of subtitles - "classic" (with outline) or "modern" (with background)
        max_width: Maximum width of subtitle text (in % of video width, e.g. 80 for 80%)
        position: Position of subtitles - "bottom", "top", or "middle"
        
    Returns:
        Path to the output video file with subtitles
    """
    logger.info(f"Adding subtitles to video with font: {font_name}, size: {font_size}, style: {subtitle_style}, position: {position}")
    
    try:
        # Fix path handling for Windows
        # Replace backslashes with forward slashes for FFmpeg
        video_path_escaped = video_path.replace('\\', '/')
        subtitle_path_escaped = subtitle_path.replace('\\', '/')
        output_path_escaped = output_path.replace('\\', '/')
        
        # Determine position alignment
        alignment = "2"  # Default: bottom-center
        if position == "top":
            alignment = "8"  # top-center
        elif position == "middle":
            alignment = "5"  # middle-center
            
        # Set vertical margin based on position
        margin_v_param = f"MarginV={margin_v}"
        
        # Determine style parameters based on style choice
        if subtitle_style == "modern":
            # Modern style with semi-transparent background
            style_params = f"FontName={font_name},FontSize={font_size},PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=1,Outline=0,Shadow=0,{margin_v_param},Alignment={alignment}"
        else:
            # Classic style with outline
            style_params = f"FontName={font_name},FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H000F0F0F,BackColour=&H80000000,BorderStyle=4,Outline=1,Shadow=1,{margin_v_param},Alignment={alignment}"
        
        # Add max width constraint if specified
        if max_width:
            # Get video dimensions
            ffprobe_cmd = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width",
                "-of", "csv=p=0",
                video_path_escaped
            ]
            
            try:
                video_width = int(subprocess.check_output(ffprobe_cmd, universal_newlines=True).strip())
                # Calculate text width in pixels (approximate)
                text_width = int(video_width * max_width / 100)
                # Add text wrapping parameter
                style_params += f",TextWrapStyle=2,WrapStyle=2,LineSpacing=0.5,MaxWidth={text_width}"
            except Exception as e:
                logger.warning(f"Could not determine video width: {str(e)}. Skipping max width constraint.")
        
        # Construct FFmpeg command with proper path formatting and styling
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", video_path_escaped,
            "-vf", f"subtitles={subtitle_path_escaped}:force_style='{style_params}'",
            "-c:a", "copy",
            "-y",
            output_path_escaped
        ]
        
        logger.info(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
        
        # Run FFmpeg command
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            logger.error(f"FFmpeg error: {stderr}")
            
            # Try alternative method with ASS format for better styling control
            logger.info("Trying alternative method with ASS format")
            
            # Convert SRT to ASS with custom styling
            ass_path = subtitle_path.replace(".srt", ".ass")
            ffmpeg_convert_cmd = [
                "ffmpeg",
                "-i", subtitle_path_escaped,
                ass_path
            ]
            
            subprocess.run(ffmpeg_convert_cmd, check=True)
            
            # Modify the ASS file to add custom styling
            try:
                with open(ass_path, "r", encoding="utf-8") as f:
                    ass_content = f.read()
                
                # Add custom style settings
                style_section = "[V4+ Styles]\n"
                style_section += "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                
                # Create style line based on parameters
                if subtitle_style == "modern":
                    style_line = f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,0,0,{alignment},10,10,{margin_v},1\n\n"
                else:
                    style_line = f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,4,1,1,{alignment},10,10,{margin_v},1\n\n"
                
                style_section += style_line
                
                # Replace the style section if it exists
                if "[V4+ Styles]" in ass_content:
                    import re
                    ass_content = re.sub(r'\[V4\+ Styles\].*?\n\n', style_section, ass_content, flags=re.DOTALL)
                else:
                    # Add it before the events section
                    ass_content = ass_content.replace("[Events]", style_section + "[Events]")
                
                # Add text wrapping for long lines if max_width is specified
                if max_width:
                    try:
                        # Add line breaks to long dialogue lines
                        events_section = ass_content.split("[Events]")[1]
                        dialogue_lines = re.findall(r'(Dialogue:[^\n]+)', events_section)
                        
                        for line in dialogue_lines:
                            # Extract text part
                            text_parts = line.split(',', 9)
                            if len(text_parts) >= 10:
                                text = text_parts[9]
                                # If text is longer than threshold, add line breaks
                                if len(text) > 40:
                                    # Find good breaking points
                                    words = text.split()
                                    new_text = ""
                                    line_length = 0
                                    
                                    for word in words:
                                        if line_length + len(word) > 40:
                                            new_text += "\\N" + word + " "
                                            line_length = len(word) + 1
                                        else:
                                            new_text += word + " "
                                            line_length += len(word) + 1
                                    
                                    # Replace original text with wrapped text
                                    new_line = ','.join(text_parts[:9]) + ',' + new_text.strip()
                                    ass_content = ass_content.replace(line, new_line)
                    except Exception as e:
                        logger.warning(f"Error applying text wrapping: {str(e)}")
                
                with open(ass_path, "w", encoding="utf-8") as f:
                    f.write(ass_content)
            except Exception as e:
                logger.warning(f"Could not modify ASS file: {str(e)}")
            
            # Add ASS subtitles
            ffmpeg_ass_cmd = [
                "ffmpeg",
                "-i", video_path_escaped,
                "-vf", f"ass={ass_path}",
                "-c:a", "copy",
                "-y",
                output_path_escaped
            ]
            
            logger.info(f"Running alternative FFmpeg command: {' '.join(ffmpeg_ass_cmd)}")
            
            process_ass = subprocess.Popen(
                ffmpeg_ass_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            stdout_ass, stderr_ass = process_ass.communicate()
            
            if process_ass.returncode != 0:
                logger.error(f"Alternative FFmpeg error: {stderr_ass}")
                return None
            else:
                logger.info("Alternative method succeeded")
                return output_path
        else:
            logger.info("FFmpeg command succeeded")
            return output_path
    
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
            cloud_url = upload_file(output_path)
            logger.info(f"Job {job_id}: Uploaded captioned video to {cloud_url}")
            return {"file_url": cloud_url}
        except Exception as upload_error:
            logger.error(f"Job {job_id}: Failed to upload captioned video: {str(upload_error)}")
            return {"error": f"Failed to upload captioned video: {str(upload_error)}"}

    except Exception as e:
        logger.error(f"Job {job_id}: Error in process_captioning_v1: {str(e)}", exc_info=True)
        return {"error": str(e)}
