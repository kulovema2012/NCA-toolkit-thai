from flask import Blueprint, request, jsonify
import os
import logging
import json
from datetime import datetime
from services.v1.media.openai_transcribe import transcribe_with_openai
from services.v1.media.script_enhanced_subtitles import align_script_with_subtitles
from services.v1.video.caption_video import add_subtitles_to_video
from services.webhook import send_webhook
from services.file_management import download_file
import time
import threading
import tempfile
import traceback

# Set up logging
logger = logging.getLogger(__name__)

# Create blueprint
script_enhanced_auto_caption_bp = Blueprint('script_enhanced_auto_caption', __name__)

@script_enhanced_auto_caption_bp.route('/api/v1/video/script-enhanced-auto-caption', methods=['POST'])
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
        # Start timing
        start_time = time.time()
        
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
        # Extract required parameters
        video_url = data.get('video_url')
        script_text = data.get('script_text')
        
        if not video_url:
            return jsonify({"status": "error", "message": "video_url is required"}), 400
        if not script_text:
            return jsonify({"status": "error", "message": "script_text is required"}), 400
        
        # Extract optional parameters
        language = data.get('language', 'th')  # Default to Thai
        webhook_url = data.get('webhook_url')
        output_path = data.get('output_path')
        
        # Generate a job ID
        job_id = f"script_enhanced_auto_caption_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Extract styling parameters
        settings = {
            'font_name': data.get('font_name', 'Sarabun'),
            'font_size': data.get('font_size', 24),
            'position': data.get('position', 'bottom'),
            'subtitle_style': data.get('subtitle_style', 'classic'),
            'margin_v': data.get('margin_v', 30),
            'max_width': data.get('max_width'),
            'line_color': data.get('line_color'),
            'word_color': data.get('word_color'),
            'outline_color': data.get('outline_color'),
            'all_caps': data.get('all_caps', False),
            'max_words_per_line': data.get('max_words_per_line'),
            'x': data.get('x'),
            'y': data.get('y'),
            'alignment': data.get('alignment', 'center'),
            'bold': data.get('bold', False),
            'italic': data.get('italic', False),
            'underline': data.get('underline', False),
            'strikeout': data.get('strikeout', False)
        }
        
        # If webhook_url is provided, process asynchronously
        if webhook_url:
            # Return a response immediately and continue processing
            threading.Thread(
                target=process_script_enhanced_auto_caption,
                args=(video_url, script_text, language, settings, output_path, webhook_url, job_id)
            ).start()
            
            return jsonify({
                "code": 202,
                "id": "script-enhanced-auto-caption",
                "job_id": job_id,
                "message": "processing",
                "status": "Script-enhanced auto-caption job started"
            })
        
        # Process synchronously
        result = process_script_enhanced_auto_caption(
            video_url, script_text, language, settings, output_path, None, job_id
        )
        
        # Calculate total processing time
        end_time = time.time()
        total_time = end_time - start_time
        run_time = total_time
        
        # Return the result
        return jsonify(result)
    
    except Exception as e:
        error_message = f"Error in script-enhanced auto-caption processing: {str(e)}"
        logger.error(error_message)
        logger.error(traceback.format_exc())
        
        error_response = {
            "code": 500,
            "id": "script-enhanced-auto-caption",
            "job_id": str(job_id),
            "message": "error",
            "error": str(e)
        }
        
        if webhook_url:
            try:
                # Send the webhook with a serializable error response
                send_webhook(webhook_url, error_response)
            except Exception as webhook_error:
                logger.error(f"Failed to send error webhook: {str(webhook_error)}")
                # Create an even more simplified version
                simple_error = {
                    "code": 500,
                    "message": "error",
                    "error": str(e)
                }
                try:
                    send_webhook(webhook_url, simple_error)
                except Exception as final_error:
                    logger.error(f"Failed to send simplified error webhook: {str(final_error)}")
        
        # Return a simple error response
        return jsonify({"message": error_message, "status": "error"}), 500

def process_script_enhanced_auto_caption(video_url, script_text, language, settings, output_path=None, webhook_url=None, job_id=None):
    """
    Process script-enhanced auto-captioning.
    
    Args:
        video_url: URL of the video to caption
        script_text: The voice-over script text
        language: Language code (e.g., 'th' for Thai)
        settings: Dictionary of styling parameters
        output_path: Output path for the captioned video (optional)
        webhook_url: Webhook URL for async processing (optional)
        job_id: Job ID for tracking (optional)
        
    Returns:
        JSON response with the URL to the captioned video and processing information
    """
    try:
        # Start timing
        start_time = time.time()
        
        # Create a temporary directory for processing
        temp_dir = os.path.join(tempfile.gettempdir(), job_id or "script_enhanced_temp")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Step 1: Transcribe the video using OpenAI Whisper API
        logger.info(f"Transcribing video: {video_url}")
        
        # Download the video if it's a URL
        local_video_path = os.path.join(temp_dir, "video.mp4")
        if video_url.startswith(('http://', 'https://')):
            download_file(video_url, local_video_path)
        else:
            local_video_path = video_url
        
        # Transcribe using OpenAI Whisper API
        from services.v1.media.openai_transcribe import transcribe_with_openai
        
        transcription_result = transcribe_with_openai(local_video_path, language, job_id=job_id)
        
        # Validate transcription results
        if not all(transcription_result):
            raise ValueError("OpenAI transcription failed - missing output files")
        
        text_file, srt_file, segments_file = transcription_result
        
        # Verify files exist before accessing
        required_files = {
            "text_file": text_file,
            "segments_file": segments_file
        }
        for name, path in required_files.items():
            if not os.path.exists(path):
                raise FileNotFoundError(f"Transcription {name} not found at: {path}")
        
        # Copy the files to our temp directory
        text_path = os.path.join(temp_dir, "transcription.txt")
        segments_path = os.path.join(temp_dir, "segments.json")
        
        # Copy the text file content
        with open(text_file, 'r', encoding='utf-8') as src:
            text_content = src.read()
            with open(text_path, 'w', encoding='utf-8') as dest:
                dest.write(text_content)
        
        # Copy the segments file content
        with open(segments_file, 'r', encoding='utf-8') as src:
            segments_content = json.load(src)
            with open(segments_path, 'w', encoding='utf-8') as dest:
                json.dump(segments_content, dest, ensure_ascii=False, indent=2)
        
        # Step 2: Align script with transcription timing
        logger.info("Aligning script with transcription timing")
        
        # Create enhanced SRT file using script text and transcription timing
        enhanced_srt_path = os.path.join(temp_dir, "enhanced.srt")
        
        # Load segments data
        with open(segments_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)
        
        # Align script text with segments
        from services.v1.media.media_transcribe import align_script_with_segments
        
        align_script_with_segments(script_text, segments, enhanced_srt_path, language)
        
        # Step 3: Add subtitles to video
        # Extract specific parameters needed by add_subtitles_to_video
        add_subtitles_params = {
            "video_path": video_url,
            "subtitle_path": enhanced_srt_path,
            "output_path": output_path,
            "job_id": job_id
        }
        
        # Add all styling parameters
        supported_params = {
            "font_name": settings.get("font_name"),
            "font_size": settings.get("font_size"),
            "margin_v": settings.get("margin_v"),
            "subtitle_style": settings.get("subtitle_style"),
            "max_width": settings.get("max_width"),
            "position": settings.get("position"),
            "line_color": settings.get("line_color"),
            "word_color": settings.get("word_color"),
            "outline_color": settings.get("outline_color"),
            "all_caps": settings.get("all_caps"),
            "max_words_per_line": settings.get("max_words_per_line"),
            "x": settings.get("x"),
            "y": settings.get("y"),
            "alignment": settings.get("alignment"),
            "bold": settings.get("bold"),
            "italic": settings.get("italic"),
            "underline": settings.get("underline"),
            "strikeout": settings.get("strikeout")
        }
        
        # Filter out None values
        supported_params = {k: v for k, v in supported_params.items() if v is not None}
        
        # Update the parameters
        add_subtitles_params.update(supported_params)
        
        # Call add_subtitles_to_video with all parameters
        caption_result = add_subtitles_to_video(**add_subtitles_params)
        
        # Read the enhanced SRT content
        with open(enhanced_srt_path, 'r', encoding='utf-8') as f:
            enhanced_srt_content = f.read()
        
        # Calculate total processing time
        end_time = time.time()
        total_time = end_time - start_time
        run_time = total_time
        
        # Prepare simplified response format
        response = {
            "code": 200,
            "id": "script-enhanced-auto-caption",
            "job_id": job_id,
            "message": "success",
            "response": [
                {
                    "file_url": caption_result.get("file_url", "")
                }
            ],
            "run_time": round(run_time, 3),
            "total_time": round(total_time, 3)
        }
        
        # Add optional metadata if available
        if "metadata" in caption_result:
            metadata = caption_result["metadata"]
            if isinstance(metadata, dict):
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
        
        # Send webhook notification if provided
        if webhook_url:
            try:
                # Create a copy of the response that's guaranteed to be serializable
                webhook_response = {
                    "code": response.get("code", 200),
                    "id": response.get("id", "script-enhanced-auto-caption"),
                    "job_id": str(response.get("job_id", "")),
                    "message": response.get("message", "success"),
                    "file_url": response.get("response", [{}])[0].get("file_url", ""),
                    "run_time": float(response.get("run_time", 0)),
                    "total_time": float(response.get("total_time", 0))
                }
                
                # Add optional fields if they exist
                if "duration" in response:
                    webhook_response["duration"] = float(response["duration"])
                if "bitrate" in response:
                    webhook_response["bitrate"] = int(response["bitrate"])
                if "filesize" in response:
                    webhook_response["filesize"] = int(response["filesize"])
                if "thumbnail" in response:
                    webhook_response["thumbnail"] = str(response["thumbnail"])
                
                # Send the webhook
                send_webhook(webhook_url, webhook_response)
            except Exception as e:
                logger.error(f"Error sending webhook: {str(e)}")
                # Create a simplified version of the response that should be serializable
                simple_response = {
                    "code": 200,
                    "id": "script-enhanced-auto-caption",
                    "job_id": str(job_id),
                    "message": "success",
                    "file_url": caption_result.get("file_url", ""),
                    "run_time": float(round(run_time, 3)),
                    "total_time": float(round(total_time, 3))
                }
                try:
                    send_webhook(webhook_url, simple_response)
                except Exception as webhook_error:
                    logger.error(f"Failed to send simplified webhook: {str(webhook_error)}")
        
        # Return the result
        return response
    
    except Exception as e:
        error_message = f"Error in script-enhanced auto-caption processing: {str(e)}"
        logger.error(error_message)
        logger.error(traceback.format_exc())
        
        error_response = {
            "code": 500,
            "id": "script-enhanced-auto-caption",
            "job_id": str(job_id),
            "message": "error",
            "error": str(e)
        }
        
        if webhook_url:
            try:
                # Send the webhook with a serializable error response
                send_webhook(webhook_url, error_response)
            except Exception as webhook_error:
                logger.error(f"Failed to send error webhook: {str(webhook_error)}")
                # Create an even more simplified version
                simple_error = {
                    "code": 500,
                    "message": "error",
                    "error": str(e)
                }
                try:
                    send_webhook(webhook_url, simple_error)
                except Exception as final_error:
                    logger.error(f"Failed to send simplified error webhook: {str(final_error)}")
        
        # Return a dictionary error response
        return {"message": error_message, "status": "error"}
