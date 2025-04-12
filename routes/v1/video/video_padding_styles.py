import os
import json
import logging
import re
from flask import Blueprint, request, jsonify
from services.v1.ffmpeg.ffmpeg_compose import process_ffmpeg_compose
from services.file_management import get_temp_file_path
import uuid

logger = logging.getLogger(__name__)

try:
    import pythainlp
    from pythainlp.tokenize import word_tokenize
    PYTHAINLP_AVAILABLE = True
    logger.info("PyThaiNLP is available for Thai word segmentation")
except ImportError:
    PYTHAINLP_AVAILABLE = False
    logger.warning("PyThaiNLP not available. Falling back to basic Thai text splitting.")

v1_video_padding_styles_bp = Blueprint('v1_video_padding_styles', __name__)

def is_thai(text):
    """Check if text contains Thai characters"""
    thai_pattern = re.compile(r'[\u0E00-\u0E7F]')
    thai_chars = thai_pattern.findall(text)
    return len(thai_chars) > len(text) * 0.5

def split_thai_text(text, num_lines):
    """
    Split Thai text into lines with better word boundaries
    
    Args:
        text (str): Thai text to split
        num_lines (int): Number of lines to split into
        
    Returns:
        list: Array of text lines
    """
    # Try to use PyThaiNLP for better word segmentation if available
    if PYTHAINLP_AVAILABLE:
        try:
            # Tokenize the text into words
            words = word_tokenize(text, engine='newmm')
            
            # Calculate words per line
            words_per_line = max(1, len(words) // num_lines)
            
            # Split into lines
            lines = []
            for i in range(0, len(words), words_per_line):
                line = ''.join(words[i:min(i + words_per_line, len(words))])
                lines.append(line)
            
            return lines
        except Exception as e:
            logger.warning(f"Error using PyThaiNLP for word segmentation: {str(e)}")
            # Fall back to basic splitting if PyThaiNLP fails
    
    # Basic Thai text splitting using common prefixes/suffixes
    thai_prefixes = ['การ', 'ความ', 'ใน', 'และ', 'ที่', 'ของ', 'จาก', 'โดย', 'แห่ง', 'เมื่อ']
    thai_suffixes = ['ๆ', 'ไป', 'มา', 'แล้ว', 'ด้วย', 'อยู่', 'ได้', 'ให้']
    
    # Try to find natural break points
    potential_break_points = []
    
    # Check for common break points (after certain words)
    for i in range(2, len(text) - 2):
        # Check if this position follows a common suffix or precedes a common prefix
        for prefix in thai_prefixes:
            if text[i:i+len(prefix)] == prefix:
                potential_break_points.append(i)
                break
        
        for suffix in thai_suffixes:
            if text[i-len(suffix):i] == suffix:
                potential_break_points.append(i)
                break
        
        # Also consider breaks after Thai punctuation
        if text[i-1] in ',.!?;:':
            potential_break_points.append(i)
    
    # If we found enough potential break points, use them
    if len(potential_break_points) >= num_lines - 1:
        # Sort break points by position
        potential_break_points.sort()
        
        # Select evenly distributed break points
        selected_break_points = []
        step = len(potential_break_points) / (num_lines - 1)
        
        for i in range(num_lines - 1):
            index = min(int(i * step), len(potential_break_points) - 1)
            selected_break_points.append(potential_break_points[index])
        
        # Sort the selected break points
        selected_break_points.sort()
        
        # Split text at the selected break points
        lines = []
        start_pos = 0
        
        for break_point in selected_break_points:
            lines.append(text[start_pos:break_point])
            start_pos = break_point
        
        # Add the last segment
        lines.append(text[start_pos:])
        
        return lines
    
    # Fallback: if we couldn't find good break points, split by character count
    chars_per_line = len(text) // num_lines
    lines = []
    
    for i in range(0, len(text), chars_per_line):
        end_pos = min(i + chars_per_line, len(text))
        
        # Try to avoid breaking in the middle of a word if possible
        look_ahead_range = min(10, len(text) - end_pos)
        for j in range(look_ahead_range):
            if any(text[end_pos + j:].startswith(prefix) for prefix in thai_prefixes):
                end_pos = end_pos + j
                break
        
        # Look behind a bit to see if we can find a better break point
        look_behind_range = min(10, end_pos - i)
        for j in range(1, look_behind_range + 1):
            if any(text[end_pos - j - len(suffix):end_pos - j] == suffix for suffix in thai_suffixes):
                end_pos = end_pos - j
                break
        
        lines.append(text[i:end_pos])
        i = end_pos - chars_per_line  # Adjust i since we modified end_pos
    
    return lines

def smart_text_layout(text, max_width, max_height, font_size):
    """
    Create smart text layout with proper line breaks
    
    Args:
        text (str): Text to format
        max_width (int): Maximum width in pixels
        max_height (int): Maximum height in pixels
        font_size (int): Font size
        
    Returns:
        list: Array of lines
    """
    # Handle existing line breaks
    if '\n' in text:
        return text.split('\n')
    
    # Calculate optimal parameters
    char_width = 0.6 if is_thai(text) else 0.55  # Thai characters need slightly more width
    estimated_chars_per_line = int(max_width * 0.8 / (font_size * char_width))
    max_possible_lines = int(max_height / (font_size * 1.2))
    estimated_lines_needed = (len(text) + estimated_chars_per_line - 1) // estimated_chars_per_line
    target_lines = min(max(2, estimated_lines_needed), max_possible_lines)
    
    # Check for title:subtitle format
    if ':' in text and target_lines >= 2:
        parts = text.split(':', 1)
        title = parts[0]
        subtitle = parts[1].strip() if len(parts) > 1 else ""
        
        if not subtitle:
            return [title]
        
        result = [title]
        
        if len(subtitle) > estimated_chars_per_line:
            if is_thai(subtitle):
                result.extend(split_thai_text(subtitle, target_lines - 1))
            else:
                # For non-Thai, split by words
                words = subtitle.split()
                words_per_line = (len(words) + target_lines - 2) // (target_lines - 1)
                
                for i in range(0, len(words), words_per_line):
                    result.append(' '.join(words[i:i + words_per_line]))
        else:
            result.append(subtitle)
        
        return result
    
    # For Thai text, use special handling
    if is_thai(text):
        return split_thai_text(text, target_lines)
    
    # For non-Thai text, split by words
    words = text.split()
    
    # If too few words for requested lines, reduce lines
    actual_lines = min(target_lines, (len(words) + 1) // 2)
    
    # Try to find natural break points for 2-line splits
    if actual_lines == 2:
        break_words = ['of', 'and', 'or', 'but', 'for', 'nor', 'so', 'yet', 'with', 'by', 'to', 'in']
        start_search = len(words) // 3
        end_search = (2 * len(words)) // 3
        
        for i in range(start_search, end_search):
            if words[i].lower() in break_words:
                return [
                    ' '.join(words[:i+1]),
                    ' '.join(words[i+1:])
                ]
    
    # If no natural breaks found or more than 2 lines needed, split evenly
    words_per_line = (len(words) + actual_lines - 1) // actual_lines
    lines = []
    
    for i in range(0, len(words), words_per_line):
        lines.append(' '.join(words[i:min(i + words_per_line, len(words))]))
    
    return lines

@v1_video_padding_styles_bp.route('/api/v1/video/padding-styles', methods=['POST'])
def process_video_padding_styles():
    """
    Apply advanced padding styles to a video (gradients, patterns, etc.)
    """
    job_id = str(uuid.uuid4())
    logger.info(f"Job {job_id}: Starting video padding styles processing")
    
    try:
        data = request.get_json()
        logger.info(f"Job {job_id}: Received request data: {json.dumps(data, indent=2)}")
        
        # Required parameters
        video_url = data.get('video_url')
        if not video_url:
            logger.error(f"Job {job_id}: Missing required parameter: video_url")
            return jsonify({"error": "Missing required parameter: video_url"}), 400
            
        # Optional parameters with defaults
        padding_style = data.get('padding_style', 'solid')  # solid, gradient, radial, checkerboard, stripes
        padding_top = data.get('padding_top', 200)
        padding_bottom = data.get('padding_bottom', 0)
        padding_left = data.get('padding_left', 0)
        padding_right = data.get('padding_right', 0)
        
        logger.info(f"Job {job_id}: Using padding style: {padding_style}, dimensions: top={padding_top}, bottom={padding_bottom}, left={padding_left}, right={padding_right}")
        
        # Style-specific parameters
        padding_color = data.get('padding_color', 'white')
        gradient_start_color = data.get('gradient_start_color', 'white')
        gradient_end_color = data.get('gradient_end_color', 'skyblue')
        gradient_direction = data.get('gradient_direction', 'vertical')  # vertical, horizontal
        pattern_size = data.get('pattern_size', 40)
        pattern_color1 = data.get('pattern_color1', 'white')
        pattern_color2 = data.get('pattern_color2', 'black')
        
        # Text parameters
        title_text = data.get('title_text', '')
        font_name = data.get('font_name', 'Sarabun')
        font_size = data.get('font_size', 50)
        font_color = data.get('font_color', 'black')
        border_color = data.get('border_color', '#ffc8dd')
        text_style = data.get('text_style', 'outline')  # simple, outline, shadow, glow, 3d
        text_position = data.get('text_position', 'center')  # center, left, right, top, bottom
        
        logger.info(f"Job {job_id}: Title text: '{title_text}', font: {font_name}, size: {font_size}, style: {text_style}")
        
        # Prepare the FFmpeg compose request
        input_width = 1080  # Default width
        input_height = 1920 - padding_top - padding_bottom  # Default height minus padding
        
        # Create filter based on padding style
        logger.info(f"Job {job_id}: Creating filter for {padding_style} style")
        if padding_style == 'gradient':
            if gradient_direction == 'horizontal':
                logger.info(f"Job {job_id}: Using horizontal gradient from {gradient_start_color} to {gradient_end_color}")
                filter_complex = f"scale={input_width}:{input_height}[video];" + \
                    f"color=s={input_width}x{1920}:c=black,format=rgba," + \
                    f"geq=r='X/{input_width}*255':g='(1-X/{input_width})*255':b='128':a='255'[bg];" + \
                    f"[bg][video]overlay={padding_left}:{padding_top}"
            else:  # vertical
                logger.info(f"Job {job_id}: Using vertical gradient from {gradient_start_color} to {gradient_end_color}")
                filter_complex = f"scale={input_width}:{input_height}[video];" + \
                    f"color=s={input_width}x{1920}:c=black,format=rgba," + \
                    f"geq=r='Y/1920*255':g='(1-Y/1920)*255':b='128':a='255'[bg];" + \
                    f"[bg][video]overlay={padding_left}:{padding_top}"
        elif padding_style == 'radial':
            center_x = input_width / 2
            center_y = padding_top / 2
            radius = max(input_width, padding_top) / 2
            
            logger.info(f"Job {job_id}: Using radial gradient with center at ({center_x}, {center_y}) and radius {radius}")
            filter_complex = f"scale={input_width}:{input_height}[video];" + \
                f"color=s={input_width}x{1920}:c=black,format=rgba," + \
                f"geq=r='(1-hypot(X-{center_x},Y-{center_y})/{radius})*255':" + \
                f"g='(1-hypot(X-{center_x},Y-{center_y})/{radius})*200':" + \
                f"b='(1-hypot(X-{center_x},Y-{center_y})/{radius})*255':a='255'[bg];" + \
                f"[bg][video]overlay={padding_left}:{padding_top}"
        elif padding_style == 'checkerboard':
            logger.info(f"Job {job_id}: Using checkerboard pattern with size {pattern_size} and colors {pattern_color1}, {pattern_color2}")
            filter_complex = f"scale={input_width}:{input_height}[video];" + \
                f"color=s={input_width}x{1920}:c={pattern_color1}[bg1];" + \
                f"color=s={input_width}x{1920}:c={pattern_color2}[bg2];" + \
                f"nullsrc=s={input_width}x{1920}," + \
                f"geq=lum='if(mod(floor(X/{pattern_size})+floor(Y/{pattern_size}),2),255,0)':cb=128:cr=128[checkerboard];" + \
                f"[bg1][bg2]blend=all_expr='if(eq(A,0),B,A)'[bg_blend];" + \
                f"[bg_blend][checkerboard]alphamerge[bg];" + \
                f"[bg][video]overlay={padding_left}:{padding_top}"
        elif padding_style == 'stripes':
            logger.info(f"Job {job_id}: Using stripes pattern with size {pattern_size} and colors {pattern_color1}, {pattern_color2}")
            filter_complex = f"scale={input_width}:{input_height}[video];" + \
                f"color=s={input_width}x{1920}:c={pattern_color1}[bg1];" + \
                f"color=s={input_width}x{1920}:c={pattern_color2}[bg2];" + \
                f"nullsrc=s={input_width}x{1920}," + \
                f"geq=lum='if(mod(floor(X/{pattern_size}),2),255,0)':cb=128:cr=128[stripes];" + \
                f"[bg1][bg2]blend=all_expr='if(eq(A,0),B,A)'[bg_blend];" + \
                f"[bg_blend][stripes]alphamerge[bg];" + \
                f"[bg][video]overlay={padding_left}:{padding_top}"
        else:  # solid
            logger.info(f"Job {job_id}: Using solid color padding with color {padding_color}")
            filter_complex = f"scale={input_width}:{input_height}," + \
                f"pad={input_width}:{1920}:{padding_left}:{padding_top}:color={padding_color}"
        
        # Add title text if provided
        if title_text:
            logger.info(f"Job {job_id}: Processing title text: '{title_text}'")
            # Process title text for better line breaks using server-side function
            lines = smart_text_layout(title_text, input_width, padding_top, font_size)
            logger.info(f"Job {job_id}: Split title into {len(lines)} lines: {lines}")
            
            # Calculate line height and positioning
            line_height = min(font_size * 1.3, padding_top / (len(lines) + 1))
            border_w = max(1, int(font_size / 25))  # Scale border width with font size
            
            # Calculate total height and starting Y position
            title_height = len(lines) * line_height
            y_start = max(10, (padding_top - title_height) / 2)
            
            logger.info(f"Job {job_id}: Text layout - line height: {line_height}, border width: {border_w}, y start: {y_start}")
            
            # Safety check - ensure text fits in padded area
            if y_start + title_height > padding_top - 10:
                logger.info(f"Job {job_id}: Text too large for padding area, reducing font size")
                font_size = int(font_size * 0.9)
                border_w = max(1, int(font_size / 25))
                line_height = min(font_size * 1.3, padding_top / (len(lines) + 1))
                y_start = max(10, (padding_top - len(lines) * line_height) / 2)
                logger.info(f"Job {job_id}: Adjusted text layout - font size: {font_size}, line height: {line_height}, y start: {y_start}")
            
            # Determine text position
            position_x = "(w-text_w)/2" if text_position == 'center' else "20" if text_position == 'left' else "w-text_w-20"
            logger.info(f"Job {job_id}: Text position: {text_position}, x formula: {position_x}")
            
            # Add each line of text
            for i, line in enumerate(lines):
                # Escape single quotes for FFmpeg
                escaped_line = line.replace("'", "'\\''")
                
                # Determine text style
                if text_style == 'shadow':
                    logger.info(f"Job {job_id}: Using shadow text style for line {i+1}")
                    text_effect = f":fontcolor={font_color}:shadowcolor={border_color}:shadowx=2:shadowy=2"
                elif text_style == 'glow':
                    logger.info(f"Job {job_id}: Using glow text style for line {i+1}")
                    text_effect = f":fontcolor={font_color}:bordercolor={border_color}:borderw=3:box=1:boxcolor={border_color}@0.5:boxborderw=1"
                elif text_style == '3d':
                    # For 3D effect, we need to add multiple drawtext filters
                    logger.info(f"Job {job_id}: Using 3D text style for line {i+1}")
                    filter_complex += f",drawtext=text='{escaped_line}':" + \
                        f"fontfile=/usr/share/fonts/truetype/thai-tlwg/{font_name}.ttf:" + \
                        f"fontsize={font_size}:fontcolor={border_color}:" + \
                        f"x={position_x}+1:y={y_start + i * line_height}+1"
                    
                    text_effect = f":fontcolor={font_color}"
                else:  # outline or simple
                    logger.info(f"Job {job_id}: Using outline text style for line {i+1}")
                    text_effect = f":fontcolor={font_color}:bordercolor={border_color}:borderw={border_w}"
                
                filter_complex += f",drawtext=text='{escaped_line}':" + \
                    f"fontfile=/usr/share/fonts/truetype/thai-tlwg/{font_name}.ttf:" + \
                    f"fontsize={font_size}{text_effect}:" + \
                    f"x={position_x}:y={y_start + i * line_height}"
        
        logger.info(f"Job {job_id}: Final filter complex: {filter_complex}")
        
        # Prepare FFmpeg compose request
        ffmpeg_request = {
            "inputs": [
                {
                    "file_url": video_url
                }
            ],
            "filters": [
                {
                    "filter": filter_complex
                }
            ],
            "outputs": [
                {
                    "options": [
                        {
                            "option": "-c:v",
                            "argument": "libx264"
                        },
                        {
                            "option": "-c:a",
                            "argument": "aac"
                        }
                    ]
                }
            ],
            "metadata": {
                "thumbnail": True,
                "filesize": True,
                "duration": True,
                "bitrate": True,
                "encoder": True
            },
            "id": f"padding-style-{padding_style}-{job_id}"
        }
        
        # Process the request
        logger.info(f"Job {job_id}: Sending request to FFmpeg compose service")
        result = process_ffmpeg_compose(ffmpeg_request)
        logger.info(f"Job {job_id}: FFmpeg compose completed with result: {json.dumps(result, indent=2)}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Job {job_id}: Error in video padding styles: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500
