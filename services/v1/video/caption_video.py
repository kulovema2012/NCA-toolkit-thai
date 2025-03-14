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
    try:
        # Choose model size based on language
        # Use larger models for better multilingual support, especially for Thai
        if language == 'th' or language == 'thai':
            model_size = "medium"  # Better for Thai language
            language = "th"  # Ensure language code is correct
        else:
            model_size = "base"  # Default model for other languages
            
        logger.info(f"Loading Whisper {model_size} model for transcription...")
        model = whisper.load_model(model_size)
        
        transcription_options = {
            'word_timestamps': True,
            'verbose': True,
        }
        
        # If language is specified, use it
        if language != 'auto':
            transcription_options['language'] = language
            logger.info(f"Using specified language: {language}")
        
        logger.info(f"Starting transcription for video: {video_path}")
        result = model.transcribe(video_path, **transcription_options)
        
        # Log some statistics about the transcription
        segment_count = len(result.get('segments', []))
        total_duration = result.get('segments', [])[-1]['end'] if segment_count > 0 else 0
        logger.info(f"Transcription completed with {segment_count} segments over {total_duration:.2f} seconds")
        
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

def process_subtitle_text(text, replace_dict, all_caps, max_words_per_line):
    """Apply text transformations: replacements, all caps, and optional line splitting."""
    for old_word, new_word in replace_dict.items():
        text = re.sub(re.escape(old_word), new_word, text, flags=re.IGNORECASE)
    if all_caps:
        text = text.upper()
    if max_words_per_line > 0:
        words = text.split()
        lines = [' '.join(words[i:i+max_words_per_line]) for i in range(0, len(words), max_words_per_line)]
        text = '\\N'.join(lines)
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
    """Split text into multiple lines if max_words_per_line > 0."""
    if max_words_per_line <= 0:
        return [text]
    words = text.split()
    lines = [' '.join(words[i:i+max_words_per_line]) for i in range(0, len(words), max_words_per_line)]
    return lines

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
            video_path = download_file(video_url, STORAGE_PATH)
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
        subtitle_filename = f"{job_id}.{subtitle_type}"
        subtitle_path = os.path.join(STORAGE_PATH, subtitle_filename)
        try:
            with open(subtitle_path, 'w', encoding='utf-8') as f:
                f.write(subtitle_content)
            logger.info(f"Job {job_id}: Subtitle file saved to {subtitle_path}")
        except Exception as e:
            logger.error(f"Job {job_id}: Failed to save subtitle file: {str(e)}")
            return {"error": f"Failed to save subtitle file: {str(e)}"}

        # Prepare output filename and path
        output_filename = f"{job_id}_captioned.mp4"
        output_path = os.path.join(STORAGE_PATH, output_filename)

        # Process video with subtitles using FFmpeg
        try:
            # Create a more reliable path handling for FFmpeg on Windows
            # Instead of escaping, use a different approach for Windows
            if os.name == 'nt':  # Windows system
                # For Windows, use absolute path with forward slashes
                normalized_subtitle_path = os.path.abspath(subtitle_path).replace('\\', '/')
                
                if subtitle_type == 'ass':
                    # Use the ass filter with normalized path
                    ffmpeg_cmd = (
                        ffmpeg
                        .input(video_path)
                        .output(
                            output_path,
                            vf=f"ass={normalized_subtitle_path}",
                            acodec='copy'
                        )
                    )
                    
                    # Run the command and capture any output
                    logger.info(f"Job {job_id}: Running FFmpeg command with ASS filter using normalized path: {normalized_subtitle_path}")
                    ffmpeg_cmd.run(overwrite_output=True, quiet=False)
                else:
                    # Fallback to subtitles filter for SRT with normalized path
                    ffmpeg_cmd = (
                        ffmpeg
                        .input(video_path)
                        .output(
                            output_path,
                            vf=f"subtitles={normalized_subtitle_path}",
                            acodec='copy'
                        )
                    )
                    
                    logger.info(f"Job {job_id}: Running FFmpeg command with subtitles filter using normalized path: {normalized_subtitle_path}")
                    ffmpeg_cmd.run(overwrite_output=True, quiet=False)
            else:
                # Original code for non-Windows systems
                # Escape special characters in the subtitle path for FFmpeg
                escaped_subtitle_path = subtitle_path.replace('\\', '\\\\').replace(':', '\\:').replace('\'', '\\\'')
                
                if subtitle_type == 'ass':
                    # Use the ass filter which is more reliable for ASS subtitles
                    ffmpeg_cmd = (
                        ffmpeg
                        .input(video_path)
                        .output(
                            output_path,
                            vf=f"ass='{escaped_subtitle_path}'",
                            acodec='copy'
                        )
                    )
                    
                    # Run the command and capture any output
                    logger.info(f"Job {job_id}: Running FFmpeg command with ASS filter")
                    ffmpeg_cmd.run(overwrite_output=True, quiet=False)
                else:
                    # Fallback to subtitles filter for SRT
                    ffmpeg_cmd = (
                        ffmpeg
                        .input(video_path)
                        .output(
                            output_path,
                            vf=f"subtitles='{escaped_subtitle_path}'",
                            acodec='copy'
                        )
                    )
                    
                    logger.info(f"Job {job_id}: Running FFmpeg command with subtitles filter")
                    ffmpeg_cmd.run(overwrite_output=True, quiet=False)
        except ffmpeg.Error as e:
            stderr_output = e.stderr.decode('utf8') if e.stderr else 'Unknown error'
            logger.error(f"Job {job_id}: FFmpeg error: {stderr_output}")
            return {"error": f"FFmpeg error: {stderr_output}"}

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
