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
        "font": "Font name for subtitles",
        "font_size": "Font size for subtitles",
        "position": "Subtitle position (top, bottom, middle)",
        "style": "Subtitle style (classic, modern)",
        "output_path": "Output path for the captioned video (optional)",
        "webhook_url": "Webhook URL for async processing (optional)"
    }
    """
    try:
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
        # Get video URL from request
        video_url = data.get('video_url')
        if not video_url:
            return jsonify({"status": "error", "message": "No video URL provided"}), 400
        
        # Get script text from request
        script_text = data.get('script_text')
        if not script_text:
            return jsonify({"status": "error", "message": "No script text provided"}), 400
        
        # Get other parameters from request
        language = data.get('language', 'th')
        font = data.get('font', 'Sarabun')
        font_size = data.get('font_size', 24)
        position = data.get('position', 'bottom')
        style = data.get('style', 'classic')
        output_path = data.get('output_path')
        webhook_url = data.get('webhook_url')
        
        # Generate a unique job ID
        job_id = f"script_enhanced_auto_caption_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Log the request
        logger.info(f"Script-enhanced auto-caption request received for video: {video_url}")
        logger.info(f"Job ID: {job_id}")
        
        # If webhook URL is provided, process asynchronously
        if webhook_url:
            # Send initial webhook notification
            send_webhook(webhook_url, {
                "status": "processing",
                "job_id": job_id,
                "message": "Script-enhanced auto-caption job started"
            })
            
            # Process asynchronously
            import threading
            thread = threading.Thread(
                target=process_script_enhanced_auto_caption,
                args=(video_url, script_text, language, font, font_size, position, style, output_path, webhook_url, job_id)
            )
            thread.start()
            
            return jsonify({
                "status": "processing",
                "job_id": job_id,
                "message": "Script-enhanced auto-caption job started"
            })
        
        # Process synchronously
        result = process_script_enhanced_auto_caption(
            video_url, script_text, language, font, font_size, position, style, output_path, None, job_id
        )
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in script-enhanced auto-caption: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def process_script_enhanced_auto_caption(
    video_url, script_text, language, font, font_size, position, style, output_path, webhook_url, job_id
):
    """
    Process the script-enhanced auto-caption request.
    
    Args:
        video_url: URL of the video to caption
        script_text: The voice-over script text
        language: Language code (e.g., 'th' for Thai)
        font: Font name for subtitles
        font_size: Font size for subtitles
        position: Subtitle position (top, bottom, middle)
        style: Subtitle style (classic, modern)
        output_path: Output path for the captioned video (optional)
        webhook_url: Webhook URL for async processing (optional)
        job_id: Unique job ID
        
    Returns:
        dict: Result of the auto-caption process
    """
    try:
        # Step 1: Transcribe with OpenAI
        text_path, srt_path, segments_path = transcribe_with_openai(
            video_url, language=language, job_id=job_id
        )
        
        # Step 2: Enhance subtitles with the script
        enhanced_srt_path = align_script_with_subtitles(
            script_text, srt_path, srt_path.replace('.srt', '_enhanced.srt')
        )
        
        # Step 3: Add subtitles to video
        caption_result = add_subtitles_to_video(
            video_path=video_url,
            subtitle_path=enhanced_srt_path,
            font=font,
            font_size=font_size,
            position=position,
            style=style,
            output_path=output_path
        )
        
        # Read the transcription text
        with open(text_path, 'r', encoding='utf-8') as f:
            transcription_text = f.read()
        
        # Read the segments data
        with open(segments_path, 'r', encoding='utf-8') as f:
            segments_data = json.load(f)
        
        # Prepare the result
        result = {
            "status": "success",
            "file_url": caption_result.get('file_url'),
            "local_path": caption_result.get('local_path'),
            "transcription": {
                "text": transcription_text,
                "segments": segments_data,
                "language": language
            },
            "script_enhanced": True
        }
        
        # Send webhook notification if provided
        if webhook_url:
            send_webhook(webhook_url, result)
        
        return result
    
    except Exception as e:
        error_message = f"Error in script-enhanced auto-caption processing: {str(e)}"
        logger.error(error_message)
        
        # Send webhook notification if provided
        if webhook_url:
            send_webhook(webhook_url, {
                "status": "error",
                "job_id": job_id,
                "message": error_message
            })
        
        return {
            "status": "error",
            "message": error_message
        }
