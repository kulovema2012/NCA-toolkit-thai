from flask import Blueprint, request, jsonify
import os
import logging
import json
from datetime import datetime
from services.v1.media.transcribe import transcribe_with_whisper
from services.v1.media.script_enhanced_subtitles import enhance_subtitles_from_segments
from services.v1.video.caption_video import add_subtitles_to_video
from services.v1.transcription.replicate_whisper import transcribe_with_replicate
from services.webhook import send_webhook
from services.file_management import download_file
import time
import threading
import tempfile
import traceback
import shutil
import uuid

# Set up logging
logger = logging.getLogger(__name__)

# Create blueprint
script_enhanced_auto_caption_bp = Blueprint('script_enhanced_auto_caption', __name__, url_prefix='/api/v1/video')

@script_enhanced_auto_caption_bp.route('/script-enhanced-auto-caption', methods=['POST'])
def script_enhanced_auto_caption():
    """
    Auto-caption a video using OpenAI Whisper API for transcription and enhancing with a provided script.
    
    Request JSON:
    {
        "video_url": "URL of the video to caption",
        "script_text": "The voice-over script text",
        "language": "Language code (e.g., 'th' for Thai)",
        "font_name": "Font name for subtitles",
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
        "start_time": "Start time for transcription (in seconds)"
    }
    """
    try:
        # Check if request has JSON data
        if not request.is_json:
            return jsonify({"status": "error", "message": "Request must be JSON"}), 400
        
        # Parse request data
        data = request.get_json()
        
        # Validate required parameters
        required_params = ["video_url", "script_text"]
        for param in required_params:
            if param not in data:
                return jsonify({"status": "error", "message": f"Missing required parameter: {param}"}), 400
        
        # Extract parameters
        video_url = data.get("video_url")
        script_text = data.get("script_text")
        language = data.get("language", "en")  # Default to English
        output_path = data.get("output_path", "")
        webhook_url = data.get("webhook_url", "")
        include_srt = data.get("include_srt", False)
        min_start_time = data.get("min_start_time", 0.0)  # Default to 0.0 seconds
        
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
                min_start_time=min_start_time
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

def process_script_enhanced_auto_caption(video_url, script_text, language="en", settings=None, output_path=None, webhook_url=None, job_id=None, response_type="cloud", include_srt=False, min_start_time=0.0):
    """
    Process script-enhanced auto-captioning.
    
    Args:
        video_url (str): URL or path to the video file
        script_text (str): The script text to align with the audio
        language (str): Language code (e.g., 'th' for Thai)
        settings (dict): Dictionary of subtitle styling parameters
        output_path (str, optional): Path to save the output video
        webhook_url (str, optional): URL to send webhook notifications
        job_id (str, optional): Job ID for tracking
        response_type (str, optional): Type of response ("direct" or "cloud")
        include_srt (bool, optional): Whether to include SRT URL in the response
        min_start_time (float, optional): Minimum start time for subtitles
        
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
    
    # Extract settings
    settings_obj = settings if isinstance(settings, dict) else json.loads(settings)
    
    # Get transcription tool from settings
    transcription_tool = settings_obj.get("transcription_tool", "openai_whisper")
    logger.info(f"Using transcription tool: {transcription_tool}")
    
    # Get start time if specified
    start_time = float(settings_obj.get("start_time", 0.0))
    logger.info(f"Using start time: {start_time} seconds")
    
    start_time = time.time()
    
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
        
        # Transcribe the video based on selected tool
        try:
            if transcription_tool == "replicate_whisper":
                try:
                    # Extract audio URL if provided
                    audio_url = settings_obj.get("audio_url")
                    if not audio_url:
                        # If no audio URL provided, use the video URL
                        audio_url = video_url
                        
                    # Use Replicate for transcription
                    segments = transcribe_with_replicate(
                        audio_url=audio_url,
                        language=language,
                        batch_size=settings_obj.get("batch_size", 64)
                    )
                    logger.info(f"Transcription completed with Replicate Whisper, got {len(segments)} segments")
                except Exception as e:
                    logger.error(f"Error in Replicate transcription: {str(e)}")
                    # If Replicate fails, try OpenAI as fallback
                    logger.warning("Replicate transcription failed, trying OpenAI Whisper as fallback...")
                    try:
                        from services.v1.media.transcribe import transcribe_with_whisper
                        segments = transcribe_with_whisper(
                            video_path=downloaded_video_path,
                            language=language
                        )
                        logger.info(f"Fallback transcription completed with OpenAI Whisper, got {len(segments)} segments")
                    except Exception as fallback_error:
                        logger.error(f"Fallback transcription also failed: {str(fallback_error)}")
                        raise ValueError(f"Transcription failed with both Replicate and OpenAI: {str(e)} and {str(fallback_error)}")
            else:
                # Default to OpenAI Whisper
                try:
                    from services.v1.media.transcribe import transcribe_with_whisper
                    segments = transcribe_with_whisper(
                        video_path=downloaded_video_path,
                        language=language
                    )
                    logger.info(f"Transcription completed with OpenAI Whisper, got {len(segments)} segments")
                except ImportError as ie:
                    # If OpenAI module is not available, try Replicate instead
                    logger.warning(f"OpenAI module not available: {str(ie)}. Trying Replicate Whisper instead...")
                    try:
                        from services.v1.transcription.replicate_whisper import transcribe_with_replicate
                        segments = transcribe_with_replicate(
                            audio_url=video_url,
                            language=language,
                            batch_size=settings_obj.get("batch_size", 64)
                        )
                        logger.info(f"Fallback transcription completed with Replicate Whisper, got {len(segments)} segments")
                    except Exception as fallback_error:
                        logger.error(f"Fallback transcription also failed: {str(fallback_error)}")
                        raise ValueError(f"Transcription failed with both OpenAI and Replicate: {str(ie)} and {str(fallback_error)}")
                except Exception as e:
                    logger.error(f"Error in OpenAI transcription: {str(e)}")
                    # If OpenAI fails for other reasons, try Replicate as fallback
                    logger.warning("OpenAI transcription failed, trying Replicate Whisper as fallback...")
                    try:
                        from services.v1.transcription.replicate_whisper import transcribe_with_replicate
                        segments = transcribe_with_replicate(
                            audio_url=video_url,
                            language=language,
                            batch_size=settings_obj.get("batch_size", 64)
                        )
                        logger.info(f"Fallback transcription completed with Replicate Whisper, got {len(segments)} segments")
                    except Exception as fallback_error:
                        logger.error(f"Fallback transcription also failed: {str(fallback_error)}")
                        raise ValueError(f"Transcription failed with both OpenAI and Replicate: {str(e)} and {str(fallback_error)}")
        except Exception as e:
            logger.error(f"Error in transcription: {str(e)}")
            raise ValueError(f"Transcription error: {str(e)}")
        
        # Adjust segment start times if needed
        if start_time > 0:
            for segment in segments:
                segment["start"] = max(segment["start"] + start_time, start_time)
                segment["end"] = segment["end"] + start_time
            logger.info(f"Adjusted segment timings to start at {start_time} seconds")
        
        # Align script text with segments
        logger.info(f"Job {job_id}: Aligning script with transcription segments")
        
        # Create path for enhanced SRT file
        enhanced_srt_path = os.path.join(temp_dir, f"enhanced_{job_id}.srt")
        
        alignment_result = enhance_subtitles_from_segments(
            script_text=script_text, 
            segments=segments, 
            output_srt_path=enhanced_srt_path, 
            upload_to_cloud=True,
            min_start_time=min_start_time  # Pass the minimum start time parameter
        )
        
        # Check if the result is a dictionary with cloud_url
        srt_cloud_url = None
        if isinstance(alignment_result, dict) and "cloud_url" in alignment_result:
            enhanced_srt_path = alignment_result["local_path"]
            srt_cloud_url = alignment_result["cloud_url"]
            logger.info(f"Job {job_id}: Enhanced SRT uploaded to cloud: {srt_cloud_url}")
        else:
            enhanced_srt_path = alignment_result
            # If the cloud upload failed, try to upload it manually
            try:
                from services.cloud_storage import upload_to_cloud_storage
                import uuid
                filename = os.path.basename(enhanced_srt_path)
                destination_path = f"subtitles/{uuid.uuid4()}_{filename}"
                srt_cloud_url = upload_to_cloud_storage(enhanced_srt_path, destination_path)
                logger.info(f"Job {job_id}: Enhanced SRT uploaded to cloud: {srt_cloud_url}")
            except Exception as e:
                logger.warning(f"Job {job_id}: Failed to upload SRT to cloud storage: {str(e)}")
        
        if not os.path.exists(enhanced_srt_path):
            raise ValueError(f"Enhanced SRT file not created at {enhanced_srt_path}")
        
        # Step 5: Upload the enhanced SRT file to cloud storage
        srt_cloud_url = None
        if os.path.exists(enhanced_srt_path):
            try:
                from services.cloud_storage import upload_to_cloud_storage
                # Use a UUID for the filename to avoid collisions
                import uuid
                file_uuid = str(uuid.uuid4())
                srt_cloud_path = f"subtitles/{file_uuid}_{os.path.basename(enhanced_srt_path)}"
                srt_cloud_url = upload_to_cloud_storage(enhanced_srt_path, srt_cloud_path)
                logger.info(f"Job {job_id}: Enhanced SRT file uploaded to cloud storage: {srt_cloud_url}")
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to upload enhanced SRT file to cloud storage: {str(e)}")
                srt_cloud_url = f"file://{enhanced_srt_path}"
        
        # Step 3: Add subtitles to video
        logger.info(f"Job {job_id}: Adding subtitles to video")
        # Prepare parameters for add_subtitles_to_video
        add_subtitles_params = {
            "video_path": downloaded_video_path,  # Make sure we're using the local path
            "subtitle_path": enhanced_srt_path,
            "output_path": output_path,
            "job_id": job_id
        }
        
        # Add all styling parameters
        supported_params = {
            "font_name": settings.get("font_name", "Sarabun"),
            "font_size": settings.get("font_size", 24),
            "margin_v": settings.get("margin_v", 30),
            "subtitle_style": settings.get("subtitle_style", "classic"),
            "max_width": settings.get("max_width"),
            "position": settings.get("position", "bottom"),
            "line_color": settings.get("line_color"),
            "word_color": settings.get("word_color"),
            "outline_color": settings.get("outline_color"),
            "all_caps": settings.get("all_caps", False),
            "max_words_per_line": settings.get("max_words_per_line"),
            "x": settings.get("x"),
            "y": settings.get("y"),
            "alignment": settings.get("alignment", "center"),
            "bold": settings.get("bold", False),
            "italic": settings.get("italic", False),
            "underline": settings.get("underline", False),
            "strikeout": settings.get("strikeout", False),
            "shadow": settings.get("shadow", False),
            "outline": settings.get("outline", False),
            "back_color": settings.get("back_color"),
            "margin_l": settings.get("margin_l"),
            "margin_r": settings.get("margin_r"),
            "encoding": settings.get("encoding")
        }
        
        # Filter out None values
        supported_params = {k: v for k, v in supported_params.items() if v is not None}
        
        # Update the parameters
        add_subtitles_params.update(supported_params)
        
        # Verify that the files exist before calling add_subtitles_to_video
        if not os.path.exists(downloaded_video_path):
            error_message = f"Video file not found at path: {downloaded_video_path}"
            logger.error(f"Job {job_id}: {error_message}")
            raise ValueError(error_message)
            
        if not os.path.exists(enhanced_srt_path):
            error_message = f"Subtitle file not found at path: {enhanced_srt_path}"
            logger.error(f"Job {job_id}: {error_message}")
            raise ValueError(error_message)
        
        # Log the parameters we're passing to add_subtitles_to_video
        logger.info(f"Job {job_id}: Calling add_subtitles_to_video with parameters:")
        for key, value in add_subtitles_params.items():
            logger.info(f"Job {job_id}: {key}: {value}")
        
        # Call add_subtitles_to_video with all parameters
        from services.v1.video.caption_video import add_subtitles_to_video
        caption_result = add_subtitles_to_video(**add_subtitles_params)
        
        # Check if caption_result is None (error occurred in add_subtitles_to_video)
        if caption_result is None:
            error_message = f"Failed to add subtitles to video. Check logs for details."
            logger.error(f"Job {job_id}: {error_message}")
            raise ValueError(error_message)
        
        # Read the enhanced SRT content
        with open(enhanced_srt_path, 'r', encoding='utf-8') as f:
            enhanced_srt_content = f.read()
        
        # Calculate total processing time
        end_time = time.time()
        total_time = end_time - start_time
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
            "total_time": round(total_time, 3)
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
        if srt_cloud_url and include_srt:
            response["srt_url"] = srt_cloud_url
        
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
