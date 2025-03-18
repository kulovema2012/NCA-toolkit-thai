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
        
        # Basic subtitle parameters
        font_name = data.get('font_name', 'Sarabun')
        font_size = data.get('font_size', 24)
        position = data.get('position', 'bottom')
        subtitle_style = data.get('subtitle_style', 'classic')
        margin_v = data.get('margin_v', 30)
        max_width = data.get('max_width')
        output_path = data.get('output_path')
        
        # Advanced styling parameters
        line_color = data.get('line_color')
        word_color = data.get('word_color')
        outline_color = data.get('outline_color')
        all_caps = data.get('all_caps', False)
        max_words_per_line = data.get('max_words_per_line')
        x_pos = data.get('x')
        y_pos = data.get('y')
        alignment = data.get('alignment', 'center')
        bold = data.get('bold', False)
        italic = data.get('italic', False)
        underline = data.get('underline', False)
        strikeout = data.get('strikeout', False)
        
        # Webhook for async processing
        webhook_url = data.get('webhook_url')
        
        # Generate a unique job ID
        job_id = f"script_enhanced_auto_caption_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Log the request
        logger.info(f"Script-enhanced auto-caption request received for video: {video_url}")
        logger.info(f"Job ID: {job_id}")
        
        # Create settings dictionary for all styling parameters
        settings = {
            "font_name": font_name,
            "font_size": font_size,
            "position": position,
            "subtitle_style": subtitle_style,
            "margin_v": margin_v,
            "max_width": max_width,
            "line_color": line_color,
            "word_color": word_color,
            "outline_color": outline_color,
            "all_caps": all_caps,
            "max_words_per_line": max_words_per_line,
            "x": x_pos,
            "y": y_pos,
            "alignment": alignment,
            "bold": bold,
            "italic": italic,
            "underline": underline,
            "strikeout": strikeout
        }
        
        # Filter out None values
        settings = {k: v for k, v in settings.items() if v is not None}
        
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
                args=(video_url, script_text, language, settings, output_path, webhook_url, job_id)
            )
            thread.start()
            
            return jsonify({
                "status": "processing",
                "job_id": job_id,
                "message": "Script-enhanced auto-caption job started"
            })
        
        # Process synchronously
        result = process_script_enhanced_auto_caption(
            video_url, script_text, language, settings, output_path, None, job_id
        )
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in script-enhanced auto-caption: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def process_script_enhanced_auto_caption(
    video_url, script_text, language, settings, output_path, webhook_url, job_id
):
    """
    Process the script-enhanced auto-caption request.
    
    Args:
        video_url: URL of the video to caption
        script_text: The voice-over script text
        language: Language code (e.g., 'th' for Thai)
        settings: Dictionary of subtitle styling settings
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
        # Extract specific parameters needed by add_subtitles_to_video
        add_subtitles_params = {
            "video_path": video_url,
            "subtitle_path": enhanced_srt_path,
            "output_path": output_path,
            "job_id": job_id
        }
        
        # Add all the settings parameters
        add_subtitles_params.update(settings)
        
        # Make sure we're using the right parameter names
        if 'subtitle_style' in add_subtitles_params:
            add_subtitles_params['subtitle_style'] = add_subtitles_params.pop('subtitle_style')
        
        # Call add_subtitles_to_video with all parameters
        caption_result = add_subtitles_to_video(**add_subtitles_params)
        
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
            "script_enhanced": True,
            "settings": settings
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
