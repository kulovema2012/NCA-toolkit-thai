import os
import json
import logging
from flask import Blueprint, request, jsonify
from services.v1.ffmpeg.ffmpeg_compose import process_ffmpeg_compose
from services.v1.video.caption_video import add_padding_to_video
from services.file_management import get_temp_file_path

v1_video_padding_styles_bp = Blueprint('v1_video_padding_styles', __name__)

@v1_video_padding_styles_bp.route('/api/v1/video/padding-styles', methods=['POST'])
def process_video_padding_styles():
    """
    Apply advanced padding styles to a video (gradients, patterns, etc.)
    """
    try:
        data = request.get_json()
        
        # Required parameters
        video_url = data.get('video_url')
        if not video_url:
            return jsonify({"error": "Missing required parameter: video_url"}), 400
            
        # Optional parameters with defaults
        padding_style = data.get('padding_style', 'solid')  # solid, gradient, radial, checkerboard, stripes
        padding_top = data.get('padding_top', 200)
        padding_bottom = data.get('padding_bottom', 0)
        padding_left = data.get('padding_left', 0)
        padding_right = data.get('padding_right', 0)
        
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
        
        # Prepare the FFmpeg compose request
        input_width = 1080  # Default width
        input_height = 1920 - padding_top - padding_bottom  # Default height minus padding
        
        # Create filter based on padding style
        if padding_style == 'gradient':
            if gradient_direction == 'horizontal':
                filter_complex = f"scale={input_width}:{input_height}[video];" + \
                    f"color=s={input_width}x{1920}:c=black,format=rgba," + \
                    f"geq=r='X/{input_width}*255':g='(1-X/{input_width})*255':b='128':a='255'[bg];" + \
                    f"[bg][video]overlay={padding_left}:{padding_top}"
            else:  # vertical
                filter_complex = f"scale={input_width}:{input_height}[video];" + \
                    f"color=s={input_width}x{1920}:c=black,format=rgba," + \
                    f"geq=r='Y/1920*255':g='(1-Y/1920)*255':b='128':a='255'[bg];" + \
                    f"[bg][video]overlay={padding_left}:{padding_top}"
        elif padding_style == 'radial':
            center_x = input_width / 2
            center_y = padding_top / 2
            radius = max(input_width, padding_top) / 2
            
            filter_complex = f"scale={input_width}:{input_height}[video];" + \
                f"color=s={input_width}x{1920}:c=black,format=rgba," + \
                f"geq=r='(1-hypot(X-{center_x},Y-{center_y})/{radius})*255':" + \
                f"g='(1-hypot(X-{center_x},Y-{center_y})/{radius})*200':" + \
                f"b='(1-hypot(X-{center_x},Y-{center_y})/{radius})*255':a='255'[bg];" + \
                f"[bg][video]overlay={padding_left}:{padding_top}"
        elif padding_style == 'checkerboard':
            filter_complex = f"scale={input_width}:{input_height}[video];" + \
                f"color=s={input_width}x{1920}:c={pattern_color1}[bg1];" + \
                f"color=s={input_width}x{1920}:c={pattern_color2}[bg2];" + \
                f"nullsrc=s={input_width}x{1920}," + \
                f"geq=lum='if(mod(floor(X/{pattern_size})+floor(Y/{pattern_size}),2),255,0)':cb=128:cr=128[checkerboard];" + \
                f"[bg1][bg2]blend=all_expr='if(eq(A,0),B,A)'[bg_blend];" + \
                f"[bg_blend][checkerboard]alphamerge[bg];" + \
                f"[bg][video]overlay={padding_left}:{padding_top}"
        elif padding_style == 'stripes':
            filter_complex = f"scale={input_width}:{input_height}[video];" + \
                f"color=s={input_width}x{1920}:c={pattern_color1}[bg1];" + \
                f"color=s={input_width}x{1920}:c={pattern_color2}[bg2];" + \
                f"nullsrc=s={input_width}x{1920}," + \
                f"geq=lum='if(mod(floor(X/{pattern_size}),2),255,0)':cb=128:cr=128[stripes];" + \
                f"[bg1][bg2]blend=all_expr='if(eq(A,0),B,A)'[bg_blend];" + \
                f"[bg_blend][stripes]alphamerge[bg];" + \
                f"[bg][video]overlay={padding_left}:{padding_top}"
        else:  # solid
            filter_complex = f"scale={input_width}:{input_height}," + \
                f"pad={input_width}:{1920}:{padding_left}:{padding_top}:color={padding_color}"
        
        # Add title text if provided
        if title_text:
            # Process title text for better line breaks
            # This would be handled by the JavaScript in the frontend
            # For simplicity, we'll just add the text as-is here
            
            # Determine text style
            if text_style == 'shadow':
                text_effect = f":fontcolor={font_color}:shadowcolor={border_color}:shadowx=2:shadowy=2"
            elif text_style == 'glow':
                text_effect = f":fontcolor={font_color}:bordercolor={border_color}:borderw=3:box=1:boxcolor={border_color}@0.5:boxborderw=1"
            elif text_style == '3d':
                # For 3D effect, we need to add multiple drawtext filters
                position_x = "(w-text_w)/2" if text_position == 'center' else "20" if text_position == 'left' else "w-text_w-20"
                position_y = f"{padding_top/2-font_size}"
                
                filter_complex += f",drawtext=text='{title_text}':" + \
                    f"fontfile=/usr/share/fonts/truetype/thai-tlwg/{font_name}.ttf:" + \
                    f"fontsize={font_size}:fontcolor={border_color}:" + \
                    f"x={position_x}+1:y={position_y}+1"
                
                text_effect = f":fontcolor={font_color}"
            else:  # outline or simple
                text_effect = f":fontcolor={font_color}:bordercolor={border_color}:borderw=2"
            
            # Determine text position
            position_x = "(w-text_w)/2" if text_position == 'center' else "20" if text_position == 'left' else "w-text_w-20"
            position_y = f"{padding_top/2-font_size}"
            
            filter_complex += f",drawtext=text='{title_text}':" + \
                f"fontfile=/usr/share/fonts/truetype/thai-tlwg/{font_name}.ttf:" + \
                f"fontsize={font_size}{text_effect}:" + \
                f"x={position_x}:y={position_y}"
        
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
            "id": f"padding-style-{padding_style}"
        }
        
        # Process the request
        result = process_ffmpeg_compose(ffmpeg_request)
        
        return jsonify(result)
        
    except Exception as e:
        logging.error(f"Error in video padding styles: {str(e)}")
        return jsonify({"error": str(e)}), 500
