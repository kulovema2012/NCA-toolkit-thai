from flask import Blueprint, request, jsonify
import os
import json
import logging
import uuid
from services.v1.media.openai_transcribe import transcribe_with_openai
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
    Transcribe a video using OpenAI's Whisper API without adding subtitles to the video.
    
    Request JSON:
    {
        "video_url": "URL of the video to transcribe",
        "language": "Language code (e.g., 'th' for Thai, optional)"
    }
    
    Returns:
    {
        "status": "success" or "error",
        "transcription": {
            "text": "Full transcription text",
            "segments": [List of transcription segments],
            "language": "Detected or specified language"
        },
        "srt_url": "URL to the SRT file in cloud storage"
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
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        logger.info(f"Starting OpenAI transcription job {job_id} for video: {video_url}")
        
        # Step 1: Transcribe the video using OpenAI Whisper API
        logger.info(f"Transcribing video with OpenAI Whisper API, language: {language}")
        text_path, srt_path, segments_path, media_file_path = transcribe_with_openai(
            video_url, 
            language=language,
            response_format="verbose_json",
            job_id=job_id,
            preserve_media=False  # No need to keep the media file since we're not adding subtitles
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
        
        # Step 2: Upload the SRT file to Google Cloud Storage
        try:
            # Generate a destination path with a unique name
            file_uuid = str(uuid.uuid4())
            srt_filename = os.path.basename(srt_path)
            srt_cloud_path = f"subtitles/{file_uuid}_{srt_filename}"
            
            # Upload the SRT file to cloud storage
            logger.info(f"Uploading SRT file to cloud storage: {srt_cloud_path}")
            srt_cloud_url = upload_to_cloud_storage(srt_path, srt_cloud_path)
            logger.info(f"SRT file uploaded to cloud storage: {srt_cloud_url}")
            
            # Upload the text file to cloud storage as well
            text_filename = os.path.basename(text_path)
            text_cloud_path = f"transcriptions/{file_uuid}_{text_filename}"
            text_cloud_url = upload_to_cloud_storage(text_path, text_cloud_path)
            logger.info(f"Text file uploaded to cloud storage: {text_cloud_url}")
            
            # Upload the segments file to cloud storage as well
            segments_filename = os.path.basename(segments_path)
            segments_cloud_path = f"segments/{file_uuid}_{segments_filename}"
            segments_cloud_url = upload_to_cloud_storage(segments_path, segments_cloud_path)
            logger.info(f"Segments file uploaded to cloud storage: {segments_cloud_url}")
            
            # Load segments data
            with open(segments_path, 'r', encoding='utf-8') as f:
                segments_data = json.load(f)
            
            # Prepare the response with cloud URLs
            response = {
                "status": "success",
                "srt_url": srt_cloud_url,
                "text_url": text_cloud_url,
                "segments_url": segments_cloud_url,
                "transcription": {
                    "text": open(text_path, 'r', encoding='utf-8').read() if os.path.exists(text_path) else "",
                    "segments": segments_data,
                    "language": language
                }
            }
            
        except Exception as e:
            logger.error(f"Error uploading to cloud storage: {str(e)}")
            # Fallback to returning the transcription data without cloud URLs
            with open(segments_path, 'r', encoding='utf-8') as f:
                segments_data = json.load(f)
                
            response = {
                "status": "success",
                "transcription": {
                    "text": open(text_path, 'r', encoding='utf-8').read() if os.path.exists(text_path) else "",
                    "segments": segments_data,
                    "language": language
                },
                "warning": "Failed to upload to cloud storage"
            }
        
        # Clean up temporary files
        try:
            for temp_file in [text_path, srt_path, segments_path, media_file_path]:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.info(f"Removed temporary file: {temp_file}")
        except Exception as e:
            logger.warning(f"Error cleaning up temporary files: {str(e)}")
        
        logger.info(f"OpenAI transcription job {job_id} completed successfully")
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error in OpenAI transcription: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500
