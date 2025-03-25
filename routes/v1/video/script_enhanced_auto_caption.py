from flask import Blueprint, request, jsonify
import os
import logging
import json
from datetime import datetime
from services.v1.media.openai_transcribe import transcribe_with_openai
from services.v1.media.script_enhanced_subtitles import enhance_subtitles_from_segments
from services.v1.video.caption_video import add_subtitles_to_video
from services.webhook import send_webhook
from services.file_management import download_file
import time
import threading
import tempfile
import traceback
import shutil

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
        "strikeout": "Whether to use strikeout text"
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
        language = data.get("language", "th")  # Default to Thai
        output_path = data.get("output_path", "")
        webhook_url = data.get("webhook_url", "")
        
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
            "underline", "strikeout"
        ]
        
        for param in optional_params:
            if param in data:
                styling_params[param] = data[param]
        
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
                job_id=job_id
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

def process_script_enhanced_auto_caption(video_url, script_text, language, settings, output_path=None, webhook_url=None, job_id=None):
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
        
    Returns:
        dict: Result dictionary with file URL and other metadata
    """
    # Create a list to track temporary files for cleanup
    temp_files = []
    
    try:
        # Start timing
        start_time = time.time()
        
        # Generate job ID if not provided
        if not job_id:
            job_id = f"script_enhanced_auto_caption_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        logger.info(f"Job {job_id}: Starting script-enhanced auto-caption processing")
        logger.info(f"Job {job_id}: Video URL: {video_url}")
        logger.info(f"Job {job_id}: Language: {language}")
        
        # Create temporary directory for processing
        temp_dir = os.path.join(tempfile.gettempdir(), f"script_enhanced_auto_caption_{job_id}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Step 1: Download video if it's a URL
        local_video_path = None
        if video_url.startswith(('http://', 'https://')):
            logger.info(f"Job {job_id}: Downloading video from URL")
            # Use a consistent filename with .mp4 extension
            video_filename = f"video_{job_id}.mp4"
            local_video_path = os.path.join(temp_dir, video_filename)
            from services.file_management import download_file
            try:
                download_file(video_url, local_video_path)
                # Verify the file was downloaded successfully
                if not os.path.exists(local_video_path) or os.path.getsize(local_video_path) == 0:
                    raise ValueError(f"Failed to download video from {video_url}")
                temp_files.append(local_video_path)
                logger.info(f"Job {job_id}: Video downloaded to {local_video_path}")
            except Exception as e:
                error_message = f"Error downloading video from {video_url}: {str(e)}"
                logger.error(f"Job {job_id}: {error_message}")
                raise ValueError(error_message)
        else:
            local_video_path = video_url
            logger.info(f"Job {job_id}: Using local video path: {local_video_path}")
            # Verify the local file exists
            if not os.path.exists(local_video_path):
                error_message = f"Local video file not found at path: {local_video_path}"
                logger.error(f"Job {job_id}: {error_message}")
                raise ValueError(error_message)
        
        # Determine output path if not provided
        if not output_path:
            output_filename = f"captioned_{os.path.basename(local_video_path)}"
            output_path = os.path.join(temp_dir, output_filename)
            temp_files.append(output_path)
        
        # Step 2: Transcribe the video using OpenAI Whisper API
        logger.info(f"Job {job_id}: Transcribing video with OpenAI Whisper API")
        from services.v1.media.openai_transcribe import transcribe_with_openai
        
        # Paths for transcription outputs
        transcription_dir = os.path.join(temp_dir, "transcription")
        os.makedirs(transcription_dir, exist_ok=True)
        
        text_path = os.path.join(transcription_dir, f"transcription_{job_id}.txt")
        srt_path = os.path.join(transcription_dir, f"transcription_{job_id}.srt")
        segments_path = os.path.join(transcription_dir, f"segments_{job_id}.json")
        enhanced_srt_path = os.path.join(transcription_dir, f"enhanced_{job_id}.srt")
        
        temp_files.extend([text_path, srt_path, segments_path, enhanced_srt_path, transcription_dir])
        
        # Call OpenAI Whisper API for transcription
        text_file, srt_file, segments_file, media_file_path = transcribe_with_openai(
            local_video_path, 
            language=language,
            job_id=job_id,
            preserve_media=True  # Keep the media file for subtitle addition
        )
        
        # Copy the files to our desired locations
        import shutil
        shutil.copy(text_file, text_path)
        shutil.copy(srt_file, srt_path)
        shutil.copy(segments_file, segments_path)
        
        # Update local_video_path if it changed during transcription
        if media_file_path != local_video_path:
            local_video_path = media_file_path
            logger.info(f"Job {job_id}: Updated video path to {local_video_path}")
        
        # Add these files to temp_files for cleanup
        temp_files.extend([text_file, srt_file, segments_file])
        
        if not os.path.exists(srt_path) or os.path.getsize(srt_path) == 0:
            error_message = "Transcription failed: Empty or missing SRT file"
            logger.error(f"Job {job_id}: {error_message}")
            raise ValueError(error_message)
        
        # Load segments from the JSON file
        if not os.path.exists(segments_path):
            raise ValueError(f"Segments file not found at {segments_path}")
            
        with open(segments_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)
        
        # Align script text with segments
        logger.info(f"Job {job_id}: Aligning script with transcription segments")
        from services.v1.media.script_enhanced_subtitles import enhance_subtitles_from_segments
        
        # Use the enhanced_subtitles_from_segments function that uploads to cloud storage
        alignment_result = enhance_subtitles_from_segments(
            script_text=script_text, 
            segments=segments, 
            output_srt_path=enhanced_srt_path, 
            upload_to_cloud=True
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
        
        # Step 3: Add subtitles to video
        logger.info(f"Job {job_id}: Adding subtitles to video")
        # Prepare parameters for add_subtitles_to_video
        add_subtitles_params = {
            "video_path": local_video_path,  # Make sure we're using the local path
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
            "strikeout": settings.get("strikeout", False)
        }
        
        # Filter out None values
        supported_params = {k: v for k, v in supported_params.items() if v is not None}
        
        # Update the parameters
        add_subtitles_params.update(supported_params)
        
        # Verify that the files exist before calling add_subtitles_to_video
        if not os.path.exists(local_video_path):
            error_message = f"Video file not found at path: {local_video_path}"
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
            # Upload the captioned video to cloud storage if requested
            if 'response_type' in data and data['response_type'] == "cloud":
                try:
                    from services.cloud_storage import upload_to_cloud_storage
                    cloud_path = f"captioned_videos/{os.path.basename(caption_result)}"
                    cloud_url = upload_to_cloud_storage(caption_result, cloud_path)
                    response["response"][0]["file_url"] = cloud_url
                except Exception as e:
                    logger.error(f"Job {job_id}: Failed to upload captioned video to cloud storage: {str(e)}")
                    response["response"][0]["file_url"] = f"file://{caption_result}"
            else:
                # Use local file path
                response["response"][0]["file_url"] = f"file://{caption_result}"
        elif isinstance(caption_result, dict) and "file_url" in caption_result:
            # Handle if caption_result is already a dictionary with file_url
            response["response"][0]["file_url"] = caption_result["file_url"]
        
        # Add SRT URL to the response if available
        if srt_cloud_url:
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
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    if os.path.isdir(temp_file):
                        shutil.rmtree(temp_file, ignore_errors=True)
                    else:
                        os.remove(temp_file)
            logger.info(f"Job {job_id}: Cleaned up temporary files")
        except Exception as cleanup_error:
            logger.warning(f"Job {job_id}: Error during cleanup: {str(cleanup_error)}")
