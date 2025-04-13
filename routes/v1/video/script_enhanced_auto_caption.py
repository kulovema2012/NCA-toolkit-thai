from flask import Blueprint, request, jsonify
import os
import logging
import json
from datetime import datetime
import time
import threading
import tempfile
import traceback
import shutil
import uuid
import sys
import re
import subprocess

from services.v1.media.transcribe import transcribe_with_whisper
from services.v1.media.script_enhanced_subtitles import enhance_subtitles_from_segments
from services.v1.video.caption_video import add_subtitles_to_video
from services.v1.transcription.replicate_whisper import transcribe_with_replicate
from services.v1.subtitles.thai_text_wrapper import create_srt_file, is_thai_text
from services.webhook import send_webhook
from services.file_management import download_file

# Set up logging
logger = logging.getLogger(__name__)

# Create blueprint
script_enhanced_auto_caption_bp = Blueprint('script_enhanced_auto_caption', __name__, url_prefix='/api/v1/video')

@script_enhanced_auto_caption_bp.route('/debug-env', methods=['GET'])
def debug_environment():
    """
    Debug endpoint to check environment variables and API tokens.
    Only returns masked tokens for security.
    """
    try:
        # Get all environment variable names (sorted)
        env_vars = sorted(os.environ.keys())
        
        # Check for specific API tokens (masked)
        api_tokens = {}
        token_vars = ["REPLICATE_API_TOKEN", "REPLICATE_API_KEY", "REPLICATE_TOKEN", "OPENAI_API_KEY"]
        
        for var in token_vars:
            token = os.environ.get(var)
            if token:
                # Mask the token for security
                masked_token = token[:4] + "..." + token[-4:] if len(token) > 8 else "***"
                api_tokens[var] = f"{masked_token} (length: {len(token)})"
            else:
                api_tokens[var] = "Not set"
        
        # Check if replicate module is properly initialized
        replicate_status = "Available"
        try:
            import replicate
            replicate_token = replicate.api_token
            if replicate_token:
                masked_replicate = replicate_token[:4] + "..." + replicate_token[-4:] if len(replicate_token) > 8 else "***"
                replicate_status = f"Initialized with token: {masked_replicate}"
            else:
                replicate_status = "Available but no token set"
        except ImportError:
            replicate_status = "Module not available"
        except Exception as e:
            replicate_status = f"Error: {str(e)}"
        
        return jsonify({
            "status": "success",
            "environment_variables": env_vars,
            "api_tokens": api_tokens,
            "replicate_status": replicate_status,
            "python_version": sys.version,
            "timestamp": datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error checking environment: {str(e)}"
        }), 500

@script_enhanced_auto_caption_bp.route('/script-enhanced-auto-caption', methods=['POST'])
def script_enhanced_auto_caption():
    """
    Auto-caption a video using OpenAI Whisper API for transcription and enhancing with a provided script.
    
    Request JSON:
    {
        "video_url": "URL of the video to caption",
        "script_text": "The voice-over script text",
        "language": "Language code (e.g., 'th' for Thai)",
        "font_name": "Font name for subtitles (default: 'Sarabun' for Thai, 'Arial' for others)",
        "font_size": "Font size for subtitles",
        "position": "Subtitle position (top, bottom, middle)",
        "subtitle_style": "Subtitle style (classic, modern, karaoke, highlight, underline, word_by_word)",
        "output_path": "Output path for the captioned video (optional)",
        "webhook_url": "Webhook URL for async processing (optional)",
        "margin_v": "Vertical margin from the bottom/top of the frame",
        "max_width": "Maximum width of subtitle text (in % of video width)",
        "line_color": "Color for subtitle text",
        "word_color": "Color for highlighted words",
        "outline_color": "Color for text outline",
        "all_caps": "Whether to capitalize all text",
        "max_words_per_line": "Maximum words per subtitle line",
        "x": "X position for subtitles",
        "y": "Y position for subtitles",
        "alignment": "Text alignment (left, center, right)",
        "bold": "Whether to use bold text",
        "italic": "Whether to use italic text",
        "underline": "Whether to use underlined text",
        "strikeout": "Whether to use strikeout text",
        "shadow": "Whether to use shadow",
        "outline": "Whether to use outline",
        "back_color": "Background color for subtitles",
        "margin_l": "Left margin for subtitles",
        "margin_r": "Right margin for subtitles",
        "encoding": "Encoding for subtitles",
        "min_start_time": "Minimum start time for subtitles",
        "transcription_tool": "Transcription tool to use (replicate_whisper or openai_whisper)",
        "start_time": "Start time for transcription (in seconds)",
        "subtitle_delay": "Subtitle delay in seconds",
        "max_chars_per_line": "Maximum characters per subtitle line",
        "audio_url": "Optional URL to an audio file to use for transcription instead of extracting from video",
        "padding": "Padding value (in pixels)",
        "padding_color": "Color of the padding",
        "padding_top": "Top padding value (in pixels)",
        "padding_bottom": "Bottom padding value (in pixels)",
        "padding_left": "Left padding value (in pixels)",
        "padding_right": "Right padding value (in pixels)"
    }
    """
    try:
        logger.info("=== STARTING SCRIPT-ENHANCED AUTO-CAPTION PROCESS ===")
        # Check if request has JSON data
        if not request.is_json:
            logger.error("Request must be JSON")
            return jsonify({"status": "error", "message": "Request must be JSON"}), 400
        
        # Parse request data
        data = request.get_json()
        logger.debug(f"Received request data: {json.dumps(data, indent=2)}")
        
        # Validate required parameters
        required_params = ["video_url", "script_text"]
        for param in required_params:
            if param not in data:
                logger.error(f"Missing required parameter: {param}")
                return jsonify({"status": "error", "message": f"Missing required parameter: {param}"}), 400
        
        # Extract parameters
        video_url = data.get("video_url")
        script_text = data.get("script_text")
        language = data.get("language", "en")  # Default to English
        output_path = data.get("output_path", "")
        webhook_url = data.get("webhook_url", "")
        include_srt = data.get("include_srt", False)
        min_start_time = data.get("min_start_time", 0.0)  # Default to 0.0 seconds
        subtitle_delay = data.get("subtitle_delay", 0.0)  # Default to 0.0 seconds
        max_chars_per_line = data.get("max_chars_per_line", 30)  # Default to 30 characters per line
        transcription_tool = data.get("transcription_tool", "openai_whisper")  # Default to OpenAI Whisper
        audio_url = data.get("audio_url", "")  # Optional audio URL for transcription
        
        # Set default font based on language
        font_name = data.get("font_name")
        if not font_name:
            if language.lower() == "th":
                font_name = "Sarabun"  # Default to Sarabun for Thai
            else:
                font_name = "Arial"  # Default to Arial for other languages
        
        # Extract other subtitle styling parameters
        font_size = data.get("font_size", 24)  # Default to 24pt
        position = data.get("position", "bottom")  # Default to bottom
        subtitle_style = data.get("subtitle_style", "classic")  # Default to classic
        margin_v = data.get("margin_v", 50)  # Default to 50px vertical margin
        max_width = data.get("max_width", 90)  # Default to 90% of video width
        line_color = data.get("line_color", "white")  # Default to white text
        word_color = data.get("word_color", "#FFFF00")  # Default to yellow for highlighted words
        outline_color = data.get("outline_color", "black")  # Default to black outline
        all_caps = data.get("all_caps", False)  # Default to not all caps
        max_words_per_line = data.get("max_words_per_line", 7)  # Default to 7 words per line
        alignment = data.get("alignment", "center")  # Default to center alignment
        bold = data.get("bold", True)  # Default to bold text for better readability
        outline = data.get("outline", True)  # Default to outline for better contrast
        shadow = data.get("shadow", True)  # Default to shadow for better readability
        border_style = data.get("border_style", 1)  # Default to outline style (1)
        
        # Log the styling parameters for debugging
        logger.info(f"Position: {position}, Outline: {outline}, Shadow: {shadow}, Border Style: {border_style}")
        
        # Validate URLs for template variables that might not have been resolved
        if video_url and (video_url.startswith("{{") or video_url.endswith("}}")):
            logger.error("Invalid video_url: Template variable was not properly resolved")
            return jsonify({"status": "error", "message": "Invalid video_url: Template variable was not properly resolved"}), 400
            
        if audio_url and (audio_url.startswith("{{") or audio_url.endswith("}}")):
            logger.error("Invalid audio_url: Template variable was not properly resolved")
            return jsonify({"status": "error", "message": "Invalid audio_url: Template variable was not properly resolved"}), 400
            
        # Validate script text for template variables
        if script_text and (script_text.startswith("{{") or script_text.endswith("}}")):
            logger.error("Invalid script_text: Template variable was not properly resolved")
            return jsonify({"status": "error", "message": "Invalid script_text: Template variable was not properly resolved"}), 400
        
        # Always use cloud storage for responses
        response_type = "cloud"
        
        # Extract styling parameters - handle nested structure
        styling_params = {}
        settings_obj = data.get("settings", {})
        
        # Handle font settings
        font_settings = settings_obj.get("font", {})
        if font_settings:
            if "name" in font_settings:
                styling_params["font_name"] = font_settings["name"]
            if "size" in font_settings:
                styling_params["font_size"] = font_settings["size"]
        
        # Handle style settings
        style_settings = settings_obj.get("style", {})
        if style_settings:
            for key, value in style_settings.items():
                styling_params[key] = value
        
        # Handle direct settings (for backward compatibility)
        optional_params = [
            "font_name", "font_size", "position", "subtitle_style", "margin_v", 
            "max_width", "line_color", "word_color", "outline_color", "all_caps",
            "max_words_per_line", "x", "y", "alignment", "bold", "italic", 
            "underline", "strikeout", "shadow", "outline", "back_color", 
            "margin_l", "margin_r", "encoding"
        ]
        
        for param in optional_params:
            if param in data:
                styling_params[param] = data[param]
        
        # Special handling for back_color to ensure it's properly passed through
        if "back_color" in styling_params:
            logger.info(f"Found back_color in request: {styling_params['back_color']}")
        elif "style" in settings_obj and "back_color" in settings_obj["style"]:
            styling_params["back_color"] = settings_obj["style"]["back_color"]
            logger.info(f"Found back_color in settings.style: {styling_params['back_color']}")
        else:
            # Default to black background if not specified
            styling_params["back_color"] = "&H80000000"  # Semi-transparent black
            logger.info("No back_color specified, defaulting to semi-transparent black")
        
        # Ensure max_words_per_line is properly passed through
        if "max_words_per_line" in styling_params:
            logger.info(f"Found max_words_per_line in request: {styling_params['max_words_per_line']}")
        elif "style" in settings_obj and "max_words_per_line" in settings_obj["style"]:
            styling_params["max_words_per_line"] = settings_obj["style"]["max_words_per_line"]
            logger.info(f"Found max_words_per_line in settings.style: {styling_params['max_words_per_line']}")
        else:
            # Default to a reasonable value for Thai
            styling_params["max_words_per_line"] = 15
            logger.info("No max_words_per_line specified, defaulting to 15")
        
        # Ensure subtitle_style is properly passed through
        if "subtitle_style" in styling_params:
            logger.info(f"Found subtitle_style in request: {styling_params['subtitle_style']}")
        elif "style" in settings_obj and "subtitle_style" in settings_obj["style"]:
            styling_params["subtitle_style"] = settings_obj["style"]["subtitle_style"]
            logger.info(f"Found subtitle_style in settings.style: {styling_params['subtitle_style']}")
        else:
            # Default to modern style
            styling_params["subtitle_style"] = "modern"
            logger.info("No subtitle_style specified, defaulting to modern")
        
        # Special handling for position to ensure it's properly passed through
        if "position" in styling_params:
            logger.info(f"Found position in request: {styling_params['position']}")
        elif "style" in settings_obj and "position" in settings_obj["style"]:
            styling_params["position"] = settings_obj["style"]["position"]
            logger.info(f"Found position in settings.style: {styling_params['position']}")
        else:
            # Default to bottom if not specified
            styling_params["position"] = "bottom"
            logger.info("No position specified, defaulting to bottom")
            
        # Special handling for outline to ensure it's properly passed through
        if "outline" in styling_params:
            logger.info(f"Found outline in request: {styling_params['outline']}")
        elif "style" in settings_obj and "outline" in settings_obj["style"]:
            styling_params["outline"] = settings_obj["style"]["outline"]
            logger.info(f"Found outline in settings.style: {styling_params['outline']}")
        else:
            # Default to true if not specified
            styling_params["outline"] = True
            logger.info("No outline specified, defaulting to True")
            
        # Special handling for shadow to ensure it's properly passed through
        if "shadow" in styling_params:
            logger.info(f"Found shadow in request: {styling_params['shadow']}")
        elif "style" in settings_obj and "shadow" in settings_obj["style"]:
            styling_params["shadow"] = settings_obj["style"]["shadow"]
            logger.info(f"Found shadow in settings.style: {styling_params['shadow']}")
        else:
            # Default to true if not specified
            styling_params["shadow"] = True
            logger.info("No shadow specified, defaulting to True")
            
        # Special handling for border_style to ensure it's properly passed through
        if "border_style" in styling_params:
            logger.info(f"Found border_style in request: {styling_params['border_style']}")
        elif "style" in settings_obj and "border_style" in settings_obj["style"]:
            styling_params["border_style"] = settings_obj["style"]["border_style"]
            logger.info(f"Found border_style in settings.style: {styling_params['border_style']}")
        else:
            # Default to 1 (outline) if not specified
            styling_params["border_style"] = 1
            logger.info("No border_style specified, defaulting to 1 (outline)")
        
        # Log the extracted styling parameters
        logger.info(f"Extracted styling parameters: {styling_params}")
        
        # Generate a job ID if not provided
        job_id = data.get("job_id", f"script_enhanced_auto_caption_{datetime.now().strftime('%Y%m%d%H%M%S')}")
        
        # Process the request
        try:
            result = process_script_enhanced_auto_caption(
                video_url=video_url,
                script_text=script_text,
                language=language,
                settings=styling_params,
                output_path=output_path,
                webhook_url=webhook_url,
                job_id=job_id,
                response_type=response_type,
                include_srt=include_srt,
                min_start_time=min_start_time,
                subtitle_delay=subtitle_delay,
                max_chars_per_line=max_chars_per_line,
                transcription_tool=transcription_tool,
                audio_url=audio_url
            )
            return jsonify(result)
        except ValueError as e:
            logger.error(f"Error in script-enhanced auto-caption processing: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            logger.error(f"Error in script-enhanced auto-caption processing: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({"status": "error", "message": f"Error in script-enhanced auto-caption processing: {str(e)}"}), 500
    
    except Exception as e:
        logger.error(f"Unexpected error in script-enhanced auto-caption endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Unexpected error: {str(e)}"}), 500

def process_script_enhanced_auto_caption(video_url, script_text, language="en", settings=None, output_path=None, webhook_url=None, job_id=None, response_type="cloud", include_srt=False, min_start_time=0.0, subtitle_delay=0.0, max_chars_per_line=30, transcription_tool="openai_whisper", audio_url=""):
    """
    Process script-enhanced auto-captioning.
    
    Args:
        video_url (str): URL of the video to caption
        script_text (str): The voice-over script text
        language (str, optional): Language code. Defaults to "en".
        settings (dict, optional): Additional settings for captioning. Defaults to None.
        output_path (str, optional): Output path for the captioned video. Defaults to None.
        webhook_url (str, optional): Webhook URL for async processing. Defaults to None.
        job_id (str, optional): Job ID for tracking. Defaults to None.
        response_type (str, optional): Response type (local or cloud). Defaults to "cloud".
        include_srt (bool, optional): Whether to include SRT file in response. Defaults to False.
        min_start_time (float, optional): Minimum start time for subtitles
        subtitle_delay (float, optional): Subtitle delay in seconds
        max_chars_per_line (int, optional): Maximum characters per subtitle line
        transcription_tool (str, optional): Transcription tool to use (replicate_whisper or openai_whisper)
        audio_url (str, optional): Optional URL to an audio file to use for transcription instead of extracting from video
        
    Returns:
        dict: Response with captioned video URL and metadata
    """
    start_time = time.time()
    
    if job_id is None:
        job_id = str(uuid.uuid4())
    
    logger.info(f"Job {job_id}: Starting script-enhanced auto-captioning process")
    logger.info(f"Job {job_id}: Parameters - language: {language}, transcription_tool: {transcription_tool}")
    logger.info(f"Job {job_id}: Script text length: {len(script_text)} characters")
    
    if settings is None:
        settings = {}
    
    # Create a temporary directory for processing
    temp_dir = tempfile.mkdtemp()
    logger.info(f"Job {job_id}: Created temporary directory: {temp_dir}")
    
    try:
        # Download the video
        logger.info(f"Job {job_id}: Downloading video from {video_url}")
        video_path = download_file(video_url, os.path.join(temp_dir, "input_video.mp4"))
        logger.info(f"Job {job_id}: Video downloaded to {video_path}")
        
        # Check if we need to use a separate audio file for transcription
        audio_path = None
        if audio_url:
            logger.info(f"Job {job_id}: Downloading separate audio file from {audio_url}")
            audio_path = download_file(audio_url, os.path.join(temp_dir, "input_audio.mp3"))
            logger.info(f"Job {job_id}: Audio downloaded to {audio_path}")
        
        # Apply padding if specified
        padding = settings.get("padding", 0)
        padding_top = settings.get("padding_top", padding)
        padding_bottom = settings.get("padding_bottom", padding)
        padding_left = settings.get("padding_left", padding)
        padding_right = settings.get("padding_right", padding)
        padding_color = settings.get("padding_color", "white")
        
        if padding_top > 0 or padding_bottom > 0 or padding_left > 0 or padding_right > 0:
            logger.info(f"Job {job_id}: Applying padding - top: {padding_top}, bottom: {padding_bottom}, left: {padding_left}, right: {padding_right}, color: {padding_color}")
            padded_video_path = apply_padding_to_video(
                video_path,
                padding_top=padding_top,
                padding_bottom=padding_bottom,
                padding_left=padding_left,
                padding_right=padding_right,
                padding_color=padding_color,
                job_id=job_id
            )
            
            if padded_video_path:
                logger.info(f"Job {job_id}: Padding applied successfully, new video path: {padded_video_path}")
                video_path = padded_video_path
            else:
                logger.warning(f"Job {job_id}: Failed to apply padding, using original video")
        
        # Transcribe the video or audio
        logger.info(f"Job {job_id}: Starting transcription with {transcription_tool}")
        
        transcription_start_time = time.time()
        segments = None
        
        if transcription_tool == "replicate_whisper":
            logger.info(f"Job {job_id}: Using Replicate Whisper for transcription")
            source_path = audio_path if audio_path else video_path
            segments = transcribe_with_replicate(source_path, language=language)
        else:  # Default to OpenAI Whisper
            logger.info(f"Job {job_id}: Using OpenAI Whisper for transcription")
            source_path = audio_path if audio_path else video_path
            segments = transcribe_with_whisper(source_path, language=language)
        
        transcription_time = time.time() - transcription_start_time
        logger.info(f"Job {job_id}: Transcription completed in {transcription_time:.2f} seconds")
        
        if not segments:
            logger.error(f"Job {job_id}: Transcription failed, no segments returned")
            return {"error": "Transcription failed"}
        
        logger.info(f"Job {job_id}: Transcription returned {len(segments)} segments")
        
        # Enhance subtitles with script
        logger.info(f"Job {job_id}: Enhancing subtitles with script text")
        enhancement_start_time = time.time()
        
        # Apply subtitle delay if specified
        if subtitle_delay > 0:
            logger.info(f"Job {job_id}: Applying subtitle delay of {subtitle_delay} seconds")
            for segment in segments:
                segment["start"] += subtitle_delay
                segment["end"] += subtitle_delay
        
        # Apply minimum start time if specified
        if min_start_time > 0:
            logger.info(f"Job {job_id}: Applying minimum start time of {min_start_time} seconds")
            segments = [s for s in segments if s["end"] >= min_start_time]
            for segment in segments:
                if segment["start"] < min_start_time:
                    segment["start"] = min_start_time
        
        enhanced_segments = enhance_subtitles_from_segments(segments, script_text, language)
        
        if not enhanced_segments:
            logger.error(f"Job {job_id}: Script alignment failed, no enhanced segments returned")
            return {"error": "Script alignment failed"}
        
        enhancement_time = time.time() - enhancement_start_time
        logger.info(f"Job {job_id}: Subtitle enhancement completed in {enhancement_time:.2f} seconds")
        logger.info(f"Job {job_id}: Enhanced subtitles have {len(enhanced_segments)} segments")
        
        # Create SRT file
        srt_path = os.path.join(temp_dir, "subtitles.srt")
        logger.info(f"Job {job_id}: Creating SRT file at {srt_path}")
        
        is_thai = is_thai_text(script_text) or language == "th"
        logger.info(f"Job {job_id}: Text detected as Thai: {is_thai}")
        
        create_srt_file(enhanced_segments, srt_path, max_chars_per_line=max_chars_per_line, is_thai=is_thai)
        logger.info(f"Job {job_id}: SRT file created successfully")
        
        # Add subtitles to video
        logger.info(f"Job {job_id}: Adding subtitles to video")
        
        # Extract subtitle styling parameters from settings
        font_name = settings.get("font_name", "Sarabun" if is_thai else "Arial")
        font_size = settings.get("font_size", 24)
        position = settings.get("position", "bottom")
        margin_v = settings.get("margin_v", 30)
        subtitle_style = settings.get("subtitle_style", "modern")
        max_width = settings.get("max_width", None)
        line_color = settings.get("line_color", "white")
        word_color = settings.get("word_color", None)
        outline_color = settings.get("outline_color", "black")
        all_caps = settings.get("all_caps", False)
        x = settings.get("x", None)
        y = settings.get("y", None)
        alignment = settings.get("alignment", "center")
        bold = settings.get("bold", False)
        italic = settings.get("italic", False)
        underline = settings.get("underline", False)
        strikeout = settings.get("strikeout", False)
        shadow = settings.get("shadow", None)
        outline = settings.get("outline", None)
        back_color = settings.get("back_color", None)
        margin_l = settings.get("margin_l", None)
        margin_r = settings.get("margin_r", None)
        encoding = settings.get("encoding", None)
        
        # Adjust Y position if padding_top is applied
        custom_y = y
        if padding_top > 0 and custom_y is not None:
            custom_y = int(custom_y) + padding_top
            logger.info(f"Job {job_id}: Adjusted Y position to {custom_y} due to top padding")
        
        logger.info(f"Job {job_id}: Subtitle styling - font: {font_name}, size: {font_size}, position: {position}, style: {subtitle_style}")
        
        # Set output path
        if output_path is None:
            output_path = os.path.join(temp_dir, "output_video.mp4")
        
        logger.info(f"Job {job_id}: Adding subtitles to video with output path: {output_path}")
        
        captioning_start_time = time.time()
        output_video_path = add_subtitles_to_video(
            video_path,
            srt_path,
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
            max_words_per_line=max_chars_per_line,
            x=x,
            y=custom_y,
            alignment=alignment,
            bold=bold,
            italic=italic,
            underline=underline,
            strikeout=strikeout,
            shadow=shadow,
            outline=outline,
            back_color=back_color,
            margin_l=margin_l,
            margin_r=margin_r,
            encoding=encoding,
            job_id=job_id
        )
        
        captioning_time = time.time() - captioning_start_time
        
        if not output_video_path or not os.path.exists(output_video_path):
            logger.error(f"Job {job_id}: Failed to add subtitles to video")
            return {"error": "Failed to add subtitles to video"}
        
        logger.info(f"Job {job_id}: Subtitles added successfully in {captioning_time:.2f} seconds")
        
        # Get file size
        file_size = os.path.getsize(output_video_path)
        
        # Prepare response
        total_time = time.time() - start_time
        
        # Format the response to match the previous version
        response = {
            "code": 200,
            "id": "script-enhanced-auto-caption",
            "job_id": job_id,
            "message": "success",
            "response": [
                {
                    "file_url": output_video_path if response_type == "local" else f"/static/temp/{os.path.basename(output_video_path)}"
                }
            ],
            "run_time": round(total_time, 3),
            "total_time": round(total_time, 3),
            "transcription_tool": transcription_tool
        }
        
        # If we need to upload to cloud storage
        try:
            from services.cloud_storage import upload_to_cloud_storage
            # Use a UUID for the filename to avoid collisions
            file_uuid = str(uuid.uuid4())
            cloud_path = f"captioned_videos/{file_uuid}_{os.path.basename(output_video_path)}"
            cloud_url = upload_to_cloud_storage(output_video_path, cloud_path)
            
            # Log the upload success
            logger.info(f"Job {job_id}: Successfully uploaded video to cloud storage: {cloud_url}")
            
            # Update the response with the cloud URL
            response["response"][0]["file_url"] = cloud_url
        except Exception as e:
            logger.error(f"Job {job_id}: Failed to upload captioned video to cloud storage: {str(e)}")
            logger.error(f"Job {job_id}: {traceback.format_exc()}")
            # Fall back to local file path if upload fails
            if response_type != "local":
                response["response"][0]["file_url"] = f"file://{output_video_path}"
        
        # Add SRT URL to the response only if explicitly requested
        if srt_path and include_srt:
            try:
                from services.cloud_storage import upload_to_cloud_storage
                # Use a UUID for the filename to avoid collisions
                file_uuid = str(uuid.uuid4())
                srt_cloud_path = f"subtitles/{file_uuid}_{os.path.basename(srt_path)}"
                srt_cloud_url = upload_to_cloud_storage(srt_path, srt_cloud_path)
                logger.info(f"Job {job_id}: Successfully uploaded SRT to cloud storage: {srt_cloud_url}")
                response["srt_url"] = srt_cloud_url
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to upload SRT to cloud storage: {str(e)}")
                logger.error(f"Job {job_id}: {traceback.format_exc()}")
                # Fall back to local file path if upload fails
                response["srt_url"] = f"file://{srt_path}"
        
        # Add additional metadata
        response["file_size"] = file_size
        response["segments_count"] = len(enhanced_segments)
        response["processing_details"] = {
            "transcription": round(transcription_time, 2),
            "enhancement": round(enhancement_time, 2),
            "captioning": round(captioning_time, 2)
        }
        
        logger.info(f"Job {job_id}: Script-enhanced auto-captioning completed successfully in {total_time:.2f} seconds")
        logger.info(f"Job {job_id}: Output video size: {file_size} bytes")
        
        return response

    except Exception as e:
        logger.error(f"Job {job_id}: Error in script-enhanced auto-captioning: {str(e)}")
        logger.error(f"Job {job_id}: {traceback.format_exc()}")
        return {"error": str(e)}
    
    finally:
        # Clean up temporary directory
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Job {job_id}: Cleaned up temporary directory {temp_dir}")
            except Exception as e:
                logger.warning(f"Job {job_id}: Failed to clean up temporary directory: {str(e)}")

def apply_padding_to_video(video_path, padding_top=0, padding_bottom=0, padding_left=0, padding_right=0, padding_color="white", job_id=None):
    """
    Apply padding to a video.
    
    Args:
        video_path: Path to the video file
        padding_top: Top padding in pixels
        padding_bottom: Bottom padding in pixels
        padding_left: Left padding in pixels
        padding_right: Right padding in pixels
        padding_color: Color of the padding
        job_id: Unique identifier for the job
        
    Returns:
        Path to the padded video
    """
    logger.info(f"Job {job_id}: Applying padding to video: {video_path}")
    logger.info(f"Job {job_id}: Padding values: Top={padding_top}, Bottom={padding_bottom}, Left={padding_left}, Right={padding_right}")
    logger.info(f"Job {job_id}: Padding color: {padding_color}")
    
    # Create output path
    output_path = f"/tmp/{uuid.uuid4()}_padded.mp4"
    logger.info(f"Job {job_id}: Output path: {output_path}")
    
    # Get video dimensions
    video_info = get_video_info(video_path)
    width = int(video_info.get("width", 1280))
    height = int(video_info.get("height", 720))
    logger.info(f"Job {job_id}: Original video dimensions: {width}x{height}")
    
    # Calculate new dimensions
    new_width = width + padding_left + padding_right
    new_height = height + padding_top + padding_bottom
    logger.info(f"Job {job_id}: New video dimensions: {new_width}x{new_height}")
    
    # Create FFmpeg command
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"pad={new_width}:{new_height}:{padding_left}:{padding_top}:color={padding_color}",
        "-c:v", "libx264", "-crf", "18",
        "-c:a", "copy",
        output_path
    ]
    
    # Execute FFmpeg command
    logger.info(f"Job {job_id}: Executing FFmpeg command: {' '.join(ffmpeg_cmd)}")
    try:
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True)
        logger.info(f"Job {job_id}: FFmpeg command executed successfully")
        logger.debug(f"Job {job_id}: FFmpeg stdout: {result.stdout}")
        
        # Check if output file exists
        if os.path.exists(output_path):
            logger.info(f"Job {job_id}: Padded video created successfully: {output_path}")
            return output_path
        else:
            logger.error(f"Job {job_id}: Padded video was not created: {output_path}")
            raise FileNotFoundError(f"Padded video was not created: {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Job {job_id}: Error executing FFmpeg command: {e}")
        logger.error(f"Job {job_id}: FFmpeg stderr: {e.stderr}")
        raise Exception(f"Error applying padding to video: {e.stderr}")