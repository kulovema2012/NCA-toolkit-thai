from flask import Blueprint, request, jsonify
import os
import json
import logging
import uuid
from services.v1.media.openai_transcribe import transcribe_with_openai
from services.v1.video.caption_video import add_subtitles_to_video

# Set up logging
logger = logging.getLogger(__name__)

# Set the default local storage directory
STORAGE_PATH = "/tmp/"

# Create blueprint
openai_auto_caption_bp = Blueprint('openai_auto_caption', __name__)

@openai_auto_caption_bp.route('/api/v1/video/openai-auto-caption', methods=['POST'])
def openai_auto_caption():
    """
    Auto-caption a video using OpenAI's Whisper API for transcription and FFmpeg for adding subtitles.
    
    Request JSON:
    {
        "video_url": "URL of the video to caption",
        "language": "Language code (e.g., 'th' for Thai, optional)",
        "font": "Font name for subtitles (default: Sarabun)",
        "font_size": "Font size for subtitles (default: 24)",
        "position": "Subtitle position (default: bottom)",
        "style": "Subtitle style (default: classic)",
        "output_path": "Output path for the captioned video (optional)"
    }
    
    Returns:
    {
        "status": "success" or "error",
        "file_url": "URL of the captioned video",
        "transcription": {
            "text": "Full transcription text",
            "segments": [List of transcription segments],
            "language": "Detected or specified language"
        }
    }
    """
    try:
        # Parse request
        data = request.get_json()
        
        if not data:
            return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
        # Get video URL
        video_url = data.get('video_url')
        if not video_url:
            return jsonify({"status": "error", "message": "No video URL provided"}), 400
        
        # Get optional parameters
        language = data.get('language', 'th')  # Default to Thai
        font = data.get('font', 'Sarabun')
        font_size = data.get('font_size', 24)
        position = data.get('position', 'bottom')
        style = data.get('style', 'classic')
        output_path = data.get('output_path')
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        logger.info(f"Starting OpenAI auto-caption job {job_id} for video: {video_url}")
        
        # Step 1: Transcribe the video using OpenAI Whisper API
        logger.info(f"Transcribing video with OpenAI Whisper API, language: {language}")
        text_path, srt_path, segments_path = transcribe_with_openai(
            video_url, 
            language=language,
            response_format="verbose_json",
            job_id=job_id
        )
        
        # Check if transcription was successful
        if not srt_path or not os.path.exists(srt_path):
            logger.error(f"OpenAI transcription failed or did not produce SRT file")
            return jsonify({
                "status": "error", 
                "message": "OpenAI transcription failed or did not produce SRT file"
            }), 500
        
        # Check if SRT file has content
        with open(srt_path, 'r', encoding='utf-8') as f:
            srt_content = f.read().strip()
            if not srt_content:
                logger.error(f"SRT file is empty: {srt_path}")
                return jsonify({
                    "status": "error", 
                    "message": "Transcription produced an empty SRT file"
                }), 500
        
        # Step 2: Add subtitles to the video
        logger.info(f"Adding subtitles to video with font: {font}, position: {position}, style: {style}")
        caption_result = add_subtitles_to_video(
            video_path=video_url,
            subtitle_path=srt_path,
            output_path=output_path,
            job_id=job_id,
            font_name=font,
            font_size=font_size,
            position=position,
            subtitle_style=style
        )
        
        # Check if subtitle addition was successful
        if not caption_result:
            logger.error("Failed to add subtitles to video, caption_result is None")
            return jsonify({
                "status": "error", 
                "message": "Failed to add subtitles to video"
            }), 500
        
        # Prepare the response
        response = {
            "status": "success",
            "file_url": caption_result['file_url'] if isinstance(caption_result, dict) and 'file_url' in caption_result else caption_result,
            "transcription": {
                "text": open(text_path, 'r', encoding='utf-8').read() if os.path.exists(text_path) else "",
                "segments": json.load(open(segments_path, 'r', encoding='utf-8')) if os.path.exists(segments_path) else [],
                "language": language
            }
        }
        
        # Clean up temporary files
        try:
            for temp_file in [text_path, srt_path, segments_path]:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.info(f"Removed temporary file: {temp_file}")
        except Exception as e:
            logger.warning(f"Error cleaning up temporary files: {str(e)}")
        
        logger.info(f"OpenAI auto-caption job {job_id} completed successfully")
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error in OpenAI auto-caption: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500
