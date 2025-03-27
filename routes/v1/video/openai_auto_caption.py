from flask import Blueprint, request, jsonify
import os
import json
import logging
import uuid
from services.v1.media.openai_transcribe import transcribe_with_openai
from services.v1.video.caption_video import add_subtitles_to_video
from services.cloud_storage import upload_to_cloud_storage

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
        "font_name": "Font name for subtitles (default: Sarabun)",
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
        font_name = data.get('font_name', 'Sarabun')
        font_size = data.get('font_size', 24)
        position = data.get('position', 'bottom')
        style = data.get('style', 'classic')
        output_path = data.get('output_path')
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        logger.info(f"Starting OpenAI auto-caption job {job_id} for video: {video_url}")
        
        # Step 1: Transcribe the video using OpenAI Whisper API
        logger.info(f"Transcribing video with OpenAI Whisper API, language: {language}")
        text_path, srt_path, segments_path, media_file_path = transcribe_with_openai(
            video_url, 
            language=language,
            response_format="verbose_json",
            job_id=job_id,
            preserve_media=True  # Keep the media file for subtitle addition
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
        
        # Step 2: Add subtitles to video
        logger.info(f"Adding subtitles to video with font: {font_name}, position: {position}, style: {style}")
        
        # Define local output path if not provided
        if not output_path:
            output_filename = f"subtitled_{os.path.basename(media_file_path)}"
            local_output_path = os.path.join(STORAGE_PATH, output_filename)
        else:
            local_output_path = output_path
        
        caption_result = add_subtitles_to_video(
            video_path=media_file_path,  # Use the media file path returned from transcription
            subtitle_path=srt_path,
            output_path=local_output_path,
            job_id=job_id,
            font_name=font_name,
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
        
        # Step 3: Upload the subtitled video to Google Cloud Storage
        try:
            # Generate a destination path with a unique name
            file_uuid = str(uuid.uuid4())
            output_filename = os.path.basename(local_output_path)
            cloud_destination_path = f"videos/captioned/{file_uuid}_{output_filename}"
            
            # Upload the file to cloud storage
            logger.info(f"Uploading subtitled video to cloud storage: {cloud_destination_path}")
            cloud_url = upload_to_cloud_storage(local_output_path, cloud_destination_path)
            logger.info(f"Subtitled video uploaded to cloud storage: {cloud_url}")
            
            # Upload the SRT file to cloud storage as well
            srt_filename = os.path.basename(srt_path)
            srt_cloud_path = f"subtitles/{file_uuid}_{srt_filename}"
            srt_cloud_url = upload_to_cloud_storage(srt_path, srt_cloud_path)
            logger.info(f"SRT file uploaded to cloud storage: {srt_cloud_url}")
            
            # Prepare the response with cloud URL
            response = {
                "status": "success",
                "file_url": cloud_url,
                "srt_url": srt_cloud_url,
                "transcription": {
                    "text": open(text_path, 'r', encoding='utf-8').read() if os.path.exists(text_path) else "",
                    "segments": json.load(open(segments_path, 'r', encoding='utf-8')) if os.path.exists(segments_path) else [],
                    "language": language
                }
            }
            
        except Exception as e:
            logger.error(f"Error uploading to cloud storage: {str(e)}")
            # Fallback to local path if cloud upload fails
            response = {
                "status": "success",
                "file_url": local_output_path,  # Return local path as fallback
                "transcription": {
                    "text": open(text_path, 'r', encoding='utf-8').read() if os.path.exists(text_path) else "",
                    "segments": json.load(open(segments_path, 'r', encoding='utf-8')) if os.path.exists(segments_path) else [],
                    "language": language
                },
                "warning": "Failed to upload to cloud storage, returning local file path"
            }
        
        # Clean up temporary files
        try:
            for temp_file in [text_path, srt_path, segments_path, media_file_path]:
                if temp_file and os.path.exists(temp_file) and temp_file != local_output_path:
                    os.remove(temp_file)
                    logger.info(f"Removed temporary file: {temp_file}")
            
            # Only remove the output file if it was successfully uploaded to cloud storage
            if 'cloud_url' in locals() and os.path.exists(local_output_path):
                os.remove(local_output_path)
                logger.info(f"Removed local output file: {local_output_path}")
        except Exception as e:
            logger.warning(f"Error cleaning up temporary files: {str(e)}")
        
        logger.info(f"OpenAI auto-caption job {job_id} completed successfully")
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error in OpenAI auto-caption: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500
