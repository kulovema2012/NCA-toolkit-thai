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
    if not job_id:
        job_id = str(uuid.uuid4())
        
    if not settings:
        settings = {}
        
    logger.info(f"Job {job_id}: Starting script-enhanced auto-caption processing")
    logger.info(f"Job {job_id}: Video URL: {video_url}")
    logger.info(f"Job {job_id}: Script length: {len(script_text)} characters")
    logger.info(f"Job {job_id}: Language: {language}")
    
    # Initialize settings if None
    if settings is None:
        settings = {}
    
    # Create a settings object that combines passed parameters with the settings dict
    settings_obj = settings.copy()
    
    # Add parameters to settings if not already present
    if "min_start_time" not in settings_obj:
        settings_obj["min_start_time"] = min_start_time
    if "subtitle_delay" not in settings_obj:
        settings_obj["subtitle_delay"] = subtitle_delay
    if "max_chars_per_line" not in settings_obj:
        settings_obj["max_chars_per_line"] = max_chars_per_line
    
    # Set default font for Thai language if not specified
    if "font_name" not in settings_obj:
        if language.lower() == "th":
            settings_obj["font_name"] = "Sarabun"  # Default to Sarabun for Thai
        else:
            settings_obj["font_name"] = "Arial"  # Default to Arial for other languages
    
    # Set other default subtitle styling parameters if not specified
    if "font_size" not in settings_obj:
        settings_obj["font_size"] = 24  # Default to 24pt
    if "bold" not in settings_obj:
        settings_obj["bold"] = True  # Default to bold text for better readability
    if "outline" not in settings_obj:
        settings_obj["outline"] = True  # Default to outline for better contrast
    if "shadow" not in settings_obj:
        settings_obj["shadow"] = True  # Default to shadow for better readability
    if "alignment" not in settings_obj:
        settings_obj["alignment"] = "center"  # Default to center alignment
    
    # Get transcription tool from settings
    transcription_tool = settings_obj.get("transcription_tool", transcription_tool)
    allow_fallback = settings_obj.get("allow_fallback", False)  # New parameter to control fallback
    start_time = float(settings_obj.get("start_time", 0))
    subtitle_delay = float(settings_obj.get("subtitle_delay", 0))
    max_chars_per_line = int(settings_obj.get("max_chars_per_line", 30))
    logger.info(f"Using transcription tool: {transcription_tool}")
    logger.info(f"Allow fallback: {allow_fallback}")
    logger.info(f"Using subtitle delay: {subtitle_delay} seconds")
    logger.info(f"Using max characters per line: {max_chars_per_line}")
    
    # Get start time if specified
    logger.info(f"Using start time: {start_time} seconds")
    
    process_start_time = time.time()
    
    # Create a temporary directory for processing
    temp_dir = os.path.join(tempfile.gettempdir(), f"script_enhanced_auto_caption_{job_id}")
    os.makedirs(temp_dir, exist_ok=True)
    
    logger.info(f"Job {job_id}: Created temporary directory: {temp_dir}")
    
    try:
        # Download the video
        logger.info(f"Job {job_id}: Downloading video from {video_url}")
        downloaded_video_path = os.path.join(temp_dir, f"video_{job_id}.mp4")
        download_file(video_url, downloaded_video_path)
        logger.info(f"Job {job_id}: Video downloaded to {downloaded_video_path}")
        
        # Try to import the Replicate Whisper module
        try:
            from services.v1.transcription.replicate_whisper import transcribe_with_replicate
            replicate_available = True
        except ImportError:
            logger.warning("Replicate Whisper module not available")
            replicate_available = False
        
        # Transcribe the video based on selected tool
        transcription_tool_used = transcription_tool  # Default to the selected tool
        try:
            if transcription_tool == "replicate_whisper" and replicate_available:
                try:
                    # Extract audio URL if provided
                    if audio_url:
                        audio_url = audio_url
                    else:
                        # If no audio URL provided, use the video URL
                        audio_url = video_url
                    # Ensure the audio_url is a remote URL (not a local path)
                    if not audio_url.startswith(('http://', 'https://')):
                        logger.warning(f"Audio URL {audio_url} is not a remote URL. Replicate requires a remote URL.")
                        # Fall back to using the video URL if it's remote
                        if video_url.startswith(('http://', 'https://')):
                            logger.info(f"Using video URL instead: {video_url}")
                            audio_url = video_url
                        else:
                            error_msg = "Replicate requires a publicly accessible URL for audio. Please provide a public URL."
                            logger.error(error_msg)
                            raise ValueError(error_msg)
                        
                    # Use Replicate for transcription
                    logger.info(f"Using Replicate Whisper for transcription with URL: {audio_url}")
                    segments = transcribe_with_replicate(
                        audio_url=audio_url,
                        language=language,
                        batch_size=settings_obj.get("batch_size", 64)
                    )
                    transcription_tool_used = "replicate_whisper"
                    logger.info(f"Transcription completed with Replicate Whisper, got {len(segments)} segments")
                except Exception as e:
                    logger.error(f"Error in Replicate transcription: {str(e)}")
                    
                    # Only fall back if allowed
                    if allow_fallback:
                        logger.warning("Replicate transcription failed, trying OpenAI Whisper as fallback...")
                        try:
                            from services.v1.media.transcribe import transcribe_with_whisper
                            segments = transcribe_with_whisper(
                                video_path=downloaded_video_path,
                                language=language
                            )
                            transcription_tool_used = "openai_whisper"
                            logger.info(f"Fallback transcription completed with OpenAI Whisper, got {len(segments)} segments")
                        except Exception as fallback_error:
                            logger.error(f"Fallback transcription also failed: {str(fallback_error)}")
                            raise ValueError(f"Transcription failed with Replicate: {str(e)}\nFallback also failed: {str(fallback_error)}")
                    else:
                        # If fallback is not allowed, raise the original error
                        raise ValueError(f"Replicate transcription failed and fallback is disabled: {str(e)}")
            else:
                # Default to OpenAI Whisper
                try:
                    logger.info("Using OpenAI Whisper for transcription")
                    from services.v1.media.transcribe import transcribe_with_whisper
                    segments = transcribe_with_whisper(
                        video_path=downloaded_video_path,
                        language=language
                    )
                    transcription_tool_used = "openai_whisper"
                    logger.info(f"Transcription completed with OpenAI Whisper, got {len(segments)} segments")
                except Exception as e:
                    logger.error(f"Error in OpenAI transcription: {str(e)}")
                    
                    # Only fall back if allowed
                    if allow_fallback:
                        logger.warning("OpenAI transcription failed, trying Replicate Whisper as fallback...")
                        try:
                            from services.v1.transcription.replicate_whisper import transcribe_with_replicate
                            
                            # Ensure we have a remote URL for Replicate
                            if video_url.startswith(('http://', 'https://')):
                                audio_url = video_url
                                segments = transcribe_with_replicate(
                                    audio_url=audio_url,
                                    language=language,
                                    batch_size=settings_obj.get("batch_size", 64)
                                )
                                transcription_tool_used = "replicate_whisper"
                                logger.info(f"Fallback transcription completed with Replicate Whisper, got {len(segments)} segments")
                            else:
                                logger.error("Cannot fall back to Replicate: video URL is not a remote URL")
                                raise ValueError("OpenAI transcription failed and cannot fall back to Replicate: video URL is not a remote URL")
                        except Exception as fallback_error:
                            logger.error(f"Fallback transcription also failed: {str(fallback_error)}")
                            raise ValueError(f"Transcription failed with OpenAI: {str(e)}\nFallback also failed: {str(fallback_error)}")
                    else:
                        # If fallback is not allowed, raise the original error
                        raise ValueError(f"OpenAI transcription failed and fallback is disabled: {str(e)}")
        except Exception as e:
            logger.error(f"Error in transcription: {str(e)}")
            raise ValueError(f"Transcription error: {str(e)}")
        
        # Adjust segment start times if needed
        if start_time > 0:
            logger.info(f"Adjusting segment start times by {start_time} seconds")
            for segment in segments:
                segment["start"] = segment["start"] + start_time
                segment["end"] = segment["end"] + start_time
        
        # Ensure minimum duration for segments
        min_duration = 1.0  # Minimum duration in seconds
        for segment in segments:
            if segment["end"] - segment["start"] < min_duration:
                segment["end"] = segment["start"] + min_duration
        
        # Align script text with segments
        logger.info(f"Job {job_id}: Aligning script with transcription segments")
        
        try:
            # Use the enhanced subtitles function with the new signature
            from services.v1.media.script_enhanced_subtitles import enhance_subtitles_from_segments
            
            # Get subtitle settings
            subtitle_settings = {
                "font_name": settings_obj.get("font_name", "Arial"),
                "font_size": settings_obj.get("font_size", 24),
                "max_width": settings_obj.get("max_width", 40),
                "margin_v": settings_obj.get("margin_v", 30),  # Add margin_v parameter
                "line_color": settings_obj.get("line_color", "#FFFFFF"),
                "outline_color": settings_obj.get("outline_color", "#000000"),
                "back_color": settings_obj.get("back_color", "&H80000000"),
                "alignment": settings_obj.get("alignment", 2),
                "max_words_per_line": settings_obj.get("max_words_per_line", 15),
                "subtitle_style": settings_obj.get("subtitle_style", "modern")
            }
            
            # Call the enhanced subtitles function with the new signature
            srt_path, ass_path = enhance_subtitles_from_segments(
                segments=segments,
                script_text=script_text,
                language=language,
                settings=subtitle_settings
            )
            
            logger.info(f"Generated subtitle files: SRT={srt_path}, ASS={ass_path}")
            
            # If Thai language and subtitle_delay is specified, create a new SRT file with the delay
            if is_thai_text(script_text) and subtitle_delay > 0:
                logger.info(f"Thai text detected, applying subtitle delay of {subtitle_delay} seconds")
                delayed_srt_path = os.path.join(os.path.dirname(srt_path), f"delayed_{os.path.basename(srt_path)}")
                
                # Parse the original SRT file
                with open(srt_path, 'r', encoding='utf-8') as f:
                    srt_content = f.read()
                
                # Extract segments from SRT content
                import re
                pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:.+\n)+)'
                matches = re.findall(pattern, srt_content, re.MULTILINE)
                
                segments_from_srt = []
                for match in matches:
                    index, start_time_str, end_time_str, text = match
                    
                    # Convert SRT time format to seconds
                    def time_to_seconds(time_str):
                        h, m, s = time_str.replace(',', '.').split(':')
                        return int(h) * 3600 + int(m) * 60 + float(s)
                    
                    start_time = time_to_seconds(start_time_str)
                    end_time = time_to_seconds(end_time_str)
                    
                    segments_from_srt.append({
                        "start": start_time,
                        "end": end_time,
                        "text": text.strip()
                    })
                
                # Create a new SRT file with the delay and improved text wrapping
                delayed_srt_path = create_srt_file(
                    path=delayed_srt_path,
                    segments=segments_from_srt,
                    delay_seconds=subtitle_delay,
                    max_chars_per_line=max_chars_per_line
                )
                
                logger.info(f"Created delayed SRT file with improved Thai text wrapping: {delayed_srt_path}")
                
                # Use the delayed SRT file for captioning
                srt_path = delayed_srt_path
                
                # Convert the delayed SRT to ASS for better styling
                from services.v1.video.caption_video import convert_srt_to_ass_for_thai
                delayed_ass_path = delayed_srt_path.replace('.srt', '.ass')
                convert_srt_to_ass_for_thai(
                    srt_path=delayed_srt_path,
                    font_name=subtitle_settings.get("font_name"),
                    font_size=subtitle_settings.get("font_size"),
                    max_words_per_line=max_chars_per_line
                )
                
                if os.path.exists(delayed_ass_path):
                    logger.info(f"Created delayed ASS file: {delayed_ass_path}")
                    ass_path = delayed_ass_path
            
            # Use the ASS file for captioning
            subtitle_path = ass_path
        except Exception as e:
            logger.error(f"Error in enhanced subtitles generation: {str(e)}")
            raise ValueError(f"Enhanced subtitles generation error: {str(e)}")
        
        # Step 3: Add subtitles to video
        logger.info(f"Job {job_id}: Adding subtitles to video")
        
        # Create the output path
        output_path = os.path.join(temp_dir, f"captioned_{job_id}.mp4")
        
        # Prepare parameters for add_subtitles_to_video
        logger.info(f"Job {job_id}: Calling add_subtitles_to_video with parameters:")
        logger.info(f"Job {job_id}: video_path: {downloaded_video_path}")
        logger.info(f"Job {job_id}: subtitle_path: {subtitle_path}")
        logger.info(f"Job {job_id}: output_path: {output_path}")
        
        # Get font settings
        font_name = settings_obj.get("font_name", "Arial")
        font_size = settings_obj.get("font_size", 24)
        
        logger.info(f"Job {job_id}: font_name: {font_name}")
        logger.info(f"Job {job_id}: font_size: {font_size}")
        
        # Only include the parameters that the function accepts
        add_subtitles_params = {
            "video_path": downloaded_video_path,
            "subtitle_path": subtitle_path,
            "output_path": output_path,
            "font_size": font_size,
            "font_name": font_name
        }
        
        # Add positioning parameters
        if "position" in settings_obj:
            add_subtitles_params["position"] = settings_obj["position"]
            logger.info(f"Job {job_id}: position: {settings_obj['position']}")
            
        # Extract custom positioning parameters before passing to add_subtitles_to_video
        custom_x = None
        custom_y = None
        if "x" in add_subtitles_params:
            custom_x = add_subtitles_params.pop("x")
            logger.info(f"Job {job_id}: Extracted custom x coordinate: {custom_x}")
        if "y" in add_subtitles_params:
            custom_y = add_subtitles_params.pop("y")
            logger.info(f"Job {job_id}: Extracted custom y coordinate: {custom_y}")
            
        # Log the final parameters
        for key, value in add_subtitles_params.items():
            logger.info(f"Job {job_id}: {key}: {value}")
        
        # Call add_subtitles_to_video with filtered parameters
        from services.v1.video.caption_video import add_subtitles_to_video
        caption_result = add_subtitles_to_video(**add_subtitles_params)
        
        # If we have custom coordinates and the caption was successful, modify the subtitle file
        if caption_result and custom_x is not None and custom_y is not None:
            logger.info(f"Job {job_id}: Applying custom coordinates (x={custom_x}, y={custom_y}) to subtitle file")
            try:
                # Check if the output is an ASS file
                if caption_result.lower().endswith('.ass'):
                    # Modify the ASS file to add custom positioning
                    with open(caption_result, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Add positioning tags to dialogue lines
                    if "Dialogue:" in content:
                        # Replace any existing \pos tags or add our own
                        if "\\pos(" in content:
                            logger.debug("Found existing \\pos tag, replacing with custom coordinates")
                            content = re.sub(r'\\pos\([^)]+\)', f"\\pos({custom_x},{custom_y})", content)
                        else:
                            logger.debug("No existing \\pos tag found, adding custom coordinates to dialogue lines")
                            # Add \pos tag to each dialogue line
                            content = re.sub(r'(Dialogue:[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,)', 
                                           f'\\1{{\\an5\\pos({custom_x},{custom_y})}}', content)
                        
                        # Write the modified content back
                        with open(caption_result, 'w', encoding='utf-8') as f:
                            f.write(content)
                        
                        logger.info(f"Job {job_id}: Successfully applied custom coordinates to subtitle file")
                    else:
                        logger.warning(f"Job {job_id}: No dialogue lines found in ASS file, couldn't apply custom coordinates")
                else:
                    logger.warning(f"Job {job_id}: Output is not an ASS file, couldn't apply custom coordinates")
            except Exception as e:
                logger.error(f"Job {job_id}: Error applying custom coordinates: {str(e)}")
                # Continue with the original file if modification fails
        
        # Apply padding if requested
        if "padding" in settings_obj or "padding_top" in settings_obj or "padding_bottom" in settings_obj or "padding_left" in settings_obj or "padding_right" in settings_obj:
            logger.info(f"Job {job_id}: Applying padding to video")
            
            # If padding is specified as a single value, use it for all sides
            if "padding" in settings_obj:
                padding_top = padding_bottom = padding_left = padding_right = int(settings_obj["padding"])
            else:
                padding_top = int(settings_obj.get("padding_top", 0))
                padding_bottom = int(settings_obj.get("padding_bottom", 0))
                padding_left = int(settings_obj.get("padding_left", 0))
                padding_right = int(settings_obj.get("padding_right", 0))
            
            # Create padded video
            padded_video_path = apply_padding_to_video(
                video_path=downloaded_video_path, 
                padding_top=padding_top, 
                padding_bottom=padding_bottom,
                padding_left=padding_left,
                padding_right=padding_right,
                padding_color=settings_obj.get("padding_color", "white"),
                job_id=job_id
            )
            
            logger.info(f"Job {job_id}: Created padded video at {padded_video_path}")
            
            # Use the padded video for subtitling
            downloaded_video_path = padded_video_path
            
            # Adjust y position for top padding if needed
            if padding_top > 0 and custom_y is not None:
                custom_y = int(custom_y) + padding_top
                logger.info(f"Job {job_id}: Adjusted y position to {custom_y} due to top padding")
        
        # Calculate total processing time
        end_time = time.time()
        total_time = end_time - process_start_time
        run_time = total_time
        
        # Prepare response format that matches the original version
        response = {
            "code": 200,
            "id": "script-enhanced-auto-caption",
            "job_id": job_id,
            "message": "success",
            "response": [
                {
                    "file_url": ""
                }
            ],
            "run_time": round(run_time, 3),
            "total_time": round(total_time, 3),
            "transcription_tool": transcription_tool_used
        }
        
        # Handle the caption_result which is a string path, not a dictionary
        if isinstance(caption_result, str) and os.path.exists(caption_result):
            # Always upload the captioned video to cloud storage
            try:
                from services.cloud_storage import upload_to_cloud_storage
                # Use a UUID for the filename to avoid collisions
                import uuid
                file_uuid = str(uuid.uuid4())
                cloud_path = f"captioned_videos/{file_uuid}_{os.path.basename(caption_result)}"
                cloud_url = upload_to_cloud_storage(caption_result, cloud_path)
                
                # Log the upload success
                logger.info(f"Job {job_id}: Successfully uploaded video to cloud storage: {cloud_url}")
                
                # Update the response with the cloud URL
                response["response"][0]["file_url"] = cloud_url
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to upload captioned video to cloud storage: {str(e)}")
                logger.error(traceback.format_exc())
                # Fall back to local file path if upload fails
                response["response"][0]["file_url"] = f"file://{caption_result}"
        elif isinstance(caption_result, dict) and "file_url" in caption_result:
            # Handle if caption_result is already a dictionary with file_url
            response["response"][0]["file_url"] = caption_result["file_url"]
        
        # Add SRT URL to the response only if explicitly requested
        if srt_path and include_srt:
            try:
                from services.cloud_storage import upload_to_cloud_storage
                # Use a UUID for the filename to avoid collisions
                import uuid
                file_uuid = str(uuid.uuid4())
                srt_cloud_path = f"subtitles/{file_uuid}_{os.path.basename(srt_path)}"
                srt_cloud_url = upload_to_cloud_storage(srt_path, srt_cloud_path)
                logger.info(f"Job {job_id}: Successfully uploaded SRT to cloud storage: {srt_cloud_url}")
                response["srt_url"] = srt_cloud_url
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to upload SRT to cloud storage: {str(e)}")
                logger.error(traceback.format_exc())
                # Fall back to local file path if upload fails
                response["srt_url"] = f"file://{srt_path}"
        
        # Add optional metadata if available
        if "metadata" in locals() and 'caption_result' in locals() and isinstance(caption_result, dict) and "metadata" in caption_result:
            metadata = caption_result["metadata"]
            if isinstance(metadata, dict):
                # Extract specific metadata fields to match original format
                if "format" in metadata:
                    format_data = metadata["format"]
                    if isinstance(format_data, dict):
                        if "duration" in format_data:
                            try:
                                response["duration"] = float(format_data["duration"])
                            except (ValueError, TypeError):
                                response["duration"] = 0.0
                        if "bit_rate" in format_data:
                            try:
                                response["bitrate"] = int(format_data["bit_rate"])
                            except (ValueError, TypeError):
                                response["bitrate"] = 0
                        if "size" in format_data:
                            try:
                                response["filesize"] = int(format_data["size"])
                            except (ValueError, TypeError):
                                response["filesize"] = 0
                
                # Add thumbnail URL if available
                if "thumbnail_url" in metadata:
                    response["thumbnail"] = str(metadata["thumbnail_url"])
        
        # Send webhook if provided
        if webhook_url:
            try:
                send_webhook(webhook_url, response)
            except Exception as webhook_error:
                logger.error(f"Job {job_id}: Failed to send webhook: {str(webhook_error)}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error in script-enhanced auto-caption processing: {str(e)}")
        logger.error(traceback.format_exc())
        
        error_response = {
            "code": 500,
            "id": "script-enhanced-auto-caption",
            "job_id": job_id,
            "message": "error",
            "error": str(e)
        }
        
        # Send webhook with error if provided
        if webhook_url:
            try:
                send_webhook(webhook_url, error_response)
            except Exception as webhook_error:
                logger.error(f"Failed to send error webhook: {str(webhook_error)}")
        
        raise ValueError(f"Script-enhanced auto-caption processing error: {str(e)}")
        
    finally:
        # Clean up temporary files
        try:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    os.remove(os.path.join(root, file))
                for dir in dirs:
                    shutil.rmtree(os.path.join(root, dir), ignore_errors=True)
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Job {job_id}: Cleaned up temporary files")
        except Exception as cleanup_error:
            logger.warning(f"Job {job_id}: Error during cleanup: {str(cleanup_error)}")

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