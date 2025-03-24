from flask import Blueprint
from app_utils import *
import logging
import os
from services.v1.media.media_transcribe import process_transcribe_media
from services.authentication import authenticate
from services.cloud_storage import upload_file

v1_media_transcribe_bp = Blueprint('v1_media_transcribe', __name__)
logger = logging.getLogger(__name__)

@v1_media_transcribe_bp.route('/v1/media/transcribe', methods=['POST'])
@authenticate
@validate_payload({
    "type": "object",
    "properties": {
        "media_url": {"type": "string", "format": "uri"},
        "task": {"type": "string", "enum": ["transcribe", "translate"]},
        "include_text": {"type": "boolean"},
        "include_srt": {"type": "boolean"},
        "include_segments": {"type": "boolean"},
        "word_timestamps": {"type": "boolean"},
        "response_type": {"type": "string", "enum": ["direct", "cloud"]},
        "language": {"type": "string"},
        "webhook_url": {"type": "string", "format": "uri"},
        "id": {"type": "string"}
    },
    "required": ["media_url"],
    "additionalProperties": False
})
@queue_task_wrapper(bypass_queue=False)
def transcribe(job_id, data):
    media_url = data['media_url']
    task = data.get('task', 'transcribe')
    include_text = data.get('include_text', True)
    include_srt = data.get('include_srt', False)
    include_segments = data.get('include_segments', False)
    word_timestamps = data.get('word_timestamps', False)
    response_type = data.get('response_type', 'direct')
    language = data.get('language', None)
    webhook_url = data.get('webhook_url')
    id = data.get('id')

    logger.info(f"Job {job_id}: Received transcription request for {media_url}")

    try:
        result = process_transcribe_media(media_url, task, include_text, include_srt, include_segments, word_timestamps, response_type, language, job_id)
        logger.info(f"Job {job_id}: Transcription process completed successfully")

        # Always upload files to cloud storage regardless of response_type
        cloud_urls = {
            "text": None,
            "srt": None,
            "segments": None,
            "text_url": None,
            "srt_url": None,
            "segments_url": None,
        }

        # Upload text file if it was generated
        if include_text and result[0]:
            try:
                # Generate a destination path with a unique name
                import uuid
                filename = os.path.basename(result[0])
                destination_path = f"transcriptions/{job_id}/{filename}"
                cloud_urls["text_url"] = upload_file(result[0])
                logger.info(f"Job {job_id}: Text file uploaded to cloud: {cloud_urls['text_url']}")
                # Keep the local file path for direct response type
                cloud_urls["text"] = result[0] if response_type == "direct" else None
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to upload text file to cloud: {str(e)}")
                cloud_urls["text"] = result[0]

        # Upload SRT file if it was generated
        if include_srt and result[1]:
            try:
                # Generate a destination path with a unique name
                filename = os.path.basename(result[1])
                destination_path = f"transcriptions/{job_id}/{filename}"
                cloud_urls["srt_url"] = upload_file(result[1])
                logger.info(f"Job {job_id}: SRT file uploaded to cloud: {cloud_urls['srt_url']}")
                # Keep the local file path for direct response type
                cloud_urls["srt"] = result[1] if response_type == "direct" else None
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to upload SRT file to cloud: {str(e)}")
                cloud_urls["srt"] = result[1]

        # Upload segments file if it was generated
        if include_segments and result[2]:
            try:
                # Generate a destination path with a unique name
                filename = os.path.basename(result[2])
                destination_path = f"transcriptions/{job_id}/{filename}"
                cloud_urls["segments_url"] = upload_file(result[2])
                logger.info(f"Job {job_id}: Segments file uploaded to cloud: {cloud_urls['segments_url']}")
                # Keep the local file path for direct response type
                cloud_urls["segments"] = result[2] if response_type == "direct" else None
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to upload segments file to cloud: {str(e)}")
                cloud_urls["segments"] = result[2]

        # Clean up temporary files if not needed for direct response
        if response_type != "direct":
            if include_text and result[0]:
                try:
                    os.remove(result[0])
                    logger.info(f"Job {job_id}: Removed temporary text file: {result[0]}")
                except Exception as e:
                    logger.warning(f"Job {job_id}: Failed to remove temporary text file: {str(e)}")
            
            if include_srt and result[1]:
                try:
                    os.remove(result[1])
                    logger.info(f"Job {job_id}: Removed temporary SRT file: {result[1]}")
                except Exception as e:
                    logger.warning(f"Job {job_id}: Failed to remove temporary SRT file: {str(e)}")

            if include_segments and result[2]:
                try:
                    os.remove(result[2])
                    logger.info(f"Job {job_id}: Removed temporary segments file: {result[2]}")
                except Exception as e:
                    logger.warning(f"Job {job_id}: Failed to remove temporary segments file: {str(e)}")
        
        return cloud_urls, "/v1/transcribe/media", 200

    except Exception as e:
        logger.error(f"Job {job_id}: Error during transcription process - {str(e)}")
        return str(e), "/v1/transcribe/media", 500
