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
        required_params = ["video_url"]
        for param in required_params:
            if param not in data:
                logger.error(f"Missing required parameter: {param}")
                return jsonify({"status": "error", "message": f"Missing required parameter: {param}"}), 400
        
        # Extract parameters
        video_url = data.get("video_url")
        script_text = data.get("script_text") # Make optional using .get()
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
                script_text=script_text, # Pass the value (can be None)
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
    start_time = time.time()
    job_id = job_id or f"script_enhanced_auto_caption_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    logger.info(f"Job {job_id}: Starting script-enhanced auto-captioning")
    
    temp_dir = None
    downloaded_video_path = None
    transcription_time = 0.0  # Initialize
    enhancement_time = 0.0  # Initialize
    upload_time = 0.0      # Initialize

    try:
        # Create a temporary directory for processing
        temp_dir = tempfile.mkdtemp()
        logger.info(f"Job {job_id}: Created temporary directory: {temp_dir}")
        
        # Download the video
        logger.info(f"Job {job_id}: Downloading video from {video_url}")
        downloaded_video_path = download_file(video_url, os.path.join(temp_dir, "input_video.mp4"))
        logger.info(f"Job {job_id}: Video downloaded to {downloaded_video_path}")
        
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
                downloaded_video_path,
                padding_top=padding_top,
                padding_bottom=padding_bottom,
                padding_left=padding_left,
                padding_right=padding_right,
                padding_color=padding_color,
                job_id=job_id
            )
            
            if padded_video_path:
                logger.info(f"Job {job_id}: Padding applied successfully, new video path: {padded_video_path}")
                downloaded_video_path = padded_video_path
            else:
                logger.warning(f"Job {job_id}: Failed to apply padding, using original video")
        
        # Transcribe the video or audio
        logger.info(f"Job {job_id}: Starting transcription with {transcription_tool}")
        
        transcription_start_time = time.time()
        segments = None
        
        if transcription_tool == "replicate_whisper":
            logger.info(f"Job {job_id}: Using Replicate Whisper for transcription")
            source_path = audio_path if audio_path else downloaded_video_path
            segments = transcribe_with_replicate(source_path, language=language)
        else:  # Default to OpenAI Whisper
            logger.info(f"Job {job_id}: Using OpenAI Whisper for transcription")
            source_path = audio_path if audio_path else downloaded_video_path
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
        
        try:
            # Use the enhanced subtitles function with the new signature
            from services.v1.media.script_enhanced_subtitles import enhance_subtitles_from_segments
            
            # Get subtitle settings
            subtitle_settings = {
                "font_name": settings.get("font_name") if settings and "font_name" in settings else ("Sarabun" if is_thai_text(script_text) or language.lower() == "th" else "Arial"),
                "font_size": int(settings.get("font_size", 24)) if settings else 24,
                "max_width": int(settings.get("max_width", 40)) if settings else 40,
                "margin_v": int(settings.get("margin_v", 30)) if settings else 30,
                "line_color": settings.get("line_color", "#FFFFFF") if settings else "#FFFFFF",
                "outline_color": settings.get("outline_color", "#000000") if settings else "#000000",
                "back_color": settings.get("back_color", "&H80000000") if settings else "&H80000000",
                "alignment": int(settings.get("alignment", 2)) if settings else 2,
                "max_words_per_line": int(settings.get("max_words_per_line", 15)) if settings else 15,
                "subtitle_style": settings.get("subtitle_style", "modern") if settings else "modern"
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
            is_thai = language.lower() == "th" or (script_text and is_thai_text(script_text))
            
            if is_thai and subtitle_delay > 0:
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
                    font_name=settings.get("font_name"),
                    font_size=settings.get("font_size"),
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
        
        # Ensure output_path is set, provide default if not
        if not output_path:
            output_filename = f"output_{job_id}.mp4"
            output_path = os.path.join(temp_dir, output_filename)
            logger.info(f"Job {job_id}: No output_path provided, using default: {output_path}")
        else:
            # Ensure the output directory exists if a path is provided
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

        # Add subtitles to video
        logger.info(f"Job {job_id}: Adding subtitles to video")
        
        # Combine all valid parameters for add_subtitles_to_video
        valid_params = {
            "video_path": downloaded_video_path,
            "subtitle_path": ass_path, 
            "output_path": output_path, # Now guaranteed to be non-empty
        }
        logger.info(f"Job {job_id}: Parameters for add_subtitles_to_video: {{'video_path': '{downloaded_video_path}', 'subtitle_path': '{ass_path}', 'output_path': '{output_path}'}}")

        # Add subtitles to video using the generated ASS file
        output_video_path = add_subtitles_to_video(**valid_params)
        
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
            "run_time": {
                "download": round(0, 2),
                "transcription": round(transcription_time, 2),
                "enhancement": round(enhancement_time, 2),
                "upload": round(upload_time, 2),
                "total": round(total_time, 2)
            },
            "total_time": round(total_time, 3), # Keep overall total for compatibility
            "transcription_tool": transcription_tool if not script_text else None # Indicate tool only if used
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
        response["segments_count"] = len(segments)
        response["processing_details"] = {
            "transcription": round(transcription_time, 2),
            "enhancement": round(enhancement_time, 2),
            "captioning": round(total_time - transcription_time - enhancement_time, 2)
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