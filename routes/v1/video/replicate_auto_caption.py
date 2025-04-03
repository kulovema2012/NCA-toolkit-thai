import os
import time
import tempfile
import uuid
import traceback
import logging
import json
from typing import Dict, List, Any, Optional, Union
from flask import Blueprint, request, jsonify

from services.file_management import download_file
from services.v1.transcription.replicate_whisper import transcribe_with_replicate
from services.v1.media.script_enhanced_subtitles import enhance_subtitles_from_segments
from services.v1.video.caption_video import add_subtitles_to_video
from services.cloud_storage import upload_to_cloud_storage

# Set up logging
logger = logging.getLogger(__name__)

# Create blueprint
replicate_auto_caption_bp = Blueprint('replicate_auto_caption', __name__)

@replicate_auto_caption_bp.route('/api/v1/video/replicate-auto-caption', methods=['POST'])
def replicate_auto_caption():
    """
    API endpoint for Replicate Whisper auto-captioning.
    
    This endpoint specifically uses Replicate's Incredibly Fast Whisper model
    for transcription, with no fallback to OpenAI Whisper.
    
    Request JSON format:
    {
        "video_url": "URL to video file",
        "script_text": "Script text to align with video",
        "language": "Language code (default: en)",
        "settings": {
            "start_time": 0,
            "font_size": 24,
            "font_name": "Arial",
            "max_width": 40,
            "batch_size": 64
        }
    }
    """
    try:
        # Get request data
        data = request.get_json()
        
        # Extract required parameters
        video_url = data.get('video_url')
        script_text = data.get('script_text')
        language = data.get('language', 'en')
        settings = data.get('settings', {})
        
        # Validate required parameters
        if not video_url:
            return jsonify({"status": "error", "message": "video_url is required"}), 400
        if not script_text:
            return jsonify({"status": "error", "message": "script_text is required"}), 400
            
        # Generate job ID
        job_id = f"replicate_auto_caption_{int(time.time())}"
        
        # Process the request directly (no queue)
        try:
            result = process_replicate_auto_caption(
                video_url=video_url,
                script_text=script_text,
                language=language,
                settings=settings,
                job_id=job_id
            )
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in replicate-auto-caption task: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({"status": "error", "message": str(e)}), 500
        
    except Exception as e:
        logger.error(f"Error in replicate-auto-caption: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500

def process_replicate_auto_caption(video_url, script_text, language="en", settings=None, job_id=None):
    """
    Process a video with Replicate Whisper auto-captioning.
    
    Args:
        video_url: URL to the video file
        script_text: Script text to align with the video
        language: Language code (default: "en")
        settings: Additional settings for the captioning process
        job_id: Job ID for tracking
        
    Returns:
        Dictionary with results
    """
    # Initialize settings
    settings_obj = settings if settings else {}
    start_time = float(settings_obj.get("start_time", 0))
    
    # Log job start
    logger.info(f"Job {job_id}: Starting Replicate auto-caption")
    logger.info(f"Job {job_id}: Video URL: {video_url}")
    logger.info(f"Job {job_id}: Language: {language}")
    logger.info(f"Job {job_id}: Start time: {start_time} seconds")
    
    # Track processing time
    process_start_time = time.time()
    
    # Create a temporary directory for processing
    temp_dir = os.path.join(tempfile.gettempdir(), f"replicate_auto_caption_{job_id}")
    os.makedirs(temp_dir, exist_ok=True)
    logger.info(f"Job {job_id}: Created temporary directory: {temp_dir}")
    
    try:
        # Step 1: Download the video
        logger.info(f"Job {job_id}: Downloading video from {video_url}")
        downloaded_video_path = os.path.join(temp_dir, f"video_{job_id}.mp4")
        download_file(video_url, downloaded_video_path)
        logger.info(f"Job {job_id}: Video downloaded to {downloaded_video_path}")
        
        # Step 2: Transcribe the video using Replicate Whisper
        logger.info(f"Job {job_id}: Transcribing video with Replicate Whisper")
        
        # Extract audio URL if provided
        audio_url = settings_obj.get("audio_url")
        if not audio_url:
            # If no audio URL provided, use the video URL
            audio_url = video_url
            
        # Ensure the audio_url is a remote URL (not a local path)
        if not audio_url.startswith(('http://', 'https://')):
            logger.warning(f"Audio URL {audio_url} is not a remote URL. Replicate requires a remote URL.")
            # Fall back to using the video URL if it's remote
            if video_url.startswith(('http://', 'https://')):
                logger.info(f"Using video URL instead: {video_url}")
                audio_url = video_url
            else:
                error_msg = "Replicate requires a publicly accessible URL for audio. Please provide a public URL."
                logger.error(error_msg)
                raise ValueError(error_msg)
            
        # Use Replicate for transcription
        logger.info(f"Using Replicate Whisper for transcription with URL: {audio_url}")
        segments = transcribe_with_replicate(
            audio_url=audio_url,
            language=language,
            batch_size=settings_obj.get("batch_size", 64)
        )
        logger.info(f"Transcription completed with Replicate Whisper, got {len(segments)} segments")
        
        # Step 3: Adjust segment start times if needed
        if start_time > 0:
            logger.info(f"Adjusting segment start times by {start_time} seconds")
            for segment in segments:
                segment["start"] = segment["start"] + start_time
                segment["end"] = segment["end"] + start_time
        
        # Ensure segments have minimum duration
        min_duration = 1.0  # Minimum duration in seconds
        for segment in segments:
            if segment["end"] - segment["start"] < min_duration:
                segment["end"] = segment["start"] + min_duration
        
        # Step 4: Enhance subtitles with script alignment
        logger.info(f"Job {job_id}: Aligning script with transcription segments")
        
        try:
            # Get subtitle settings
            subtitle_settings = {
                "font_name": settings_obj.get("font_name", "Arial"),
                "font_size": settings_obj.get("font_size", 24),
                "max_width": settings_obj.get("max_width", 40)
            }
            
            # Generate enhanced subtitles
            srt_path, ass_path = enhance_subtitles_from_segments(
                segments=segments,
                script_text=script_text,
                language=language,
                settings=subtitle_settings
            )
            
            logger.info(f"Generated subtitle files: SRT={srt_path}, ASS={ass_path}")
            
            # Use the ASS file for captioning
            subtitle_path = ass_path
        except Exception as e:
            logger.error(f"Error in enhanced subtitles generation: {str(e)}")
            raise ValueError(f"Enhanced subtitles generation error: {str(e)}")
        
        # Step 5: Add subtitles to video
        logger.info(f"Job {job_id}: Adding subtitles to video")
        
        # Create the output path
        output_path = os.path.join(temp_dir, f"captioned_{job_id}.mp4")
        
        # Get font settings
        font_name = settings_obj.get("font_name", "Arial")
        font_size = settings_obj.get("font_size", 24)
        
        # Add subtitles to video
        try:
            captioned_video_path = add_subtitles_to_video(
                video_path=downloaded_video_path,
                subtitle_path=subtitle_path,
                output_path=output_path,
                font_size=font_size,
                font_name=font_name
            )
            logger.info(f"Job {job_id}: Subtitles added to video: {captioned_video_path}")
        except Exception as e:
            logger.error(f"Error adding subtitles to video: {str(e)}")
            raise ValueError(f"Error adding subtitles to video: {str(e)}")
        
        # Step 6: Upload the captioned video to cloud storage
        logger.info(f"Job {job_id}: Uploading captioned video to cloud storage")
        
        try:
            # Use a UUID for the filename to avoid collisions
            file_uuid = str(uuid.uuid4())
            cloud_path = f"videos/captioned/{file_uuid}_{os.path.basename(captioned_video_path)}"
            output_video_url = upload_to_cloud_storage(captioned_video_path, cloud_path)
            logger.info(f"Job {job_id}: Captioned video uploaded to cloud storage: {output_video_url}")
        except Exception as e:
            logger.error(f"Job {job_id}: Failed to upload captioned video to cloud storage: {str(e)}")
            raise ValueError(f"Failed to upload captioned video: {str(e)}")
        
        # Step 7: Upload SRT file to cloud storage if requested
        include_srt = settings_obj.get("include_srt", False)
        srt_cloud_url = None
        
        if srt_path and include_srt:
            try:
                file_uuid = str(uuid.uuid4())
                srt_cloud_path = f"subtitles/{file_uuid}_{os.path.basename(srt_path)}"
                srt_cloud_url = upload_to_cloud_storage(srt_path, srt_cloud_path)
                logger.info(f"Job {job_id}: Successfully uploaded SRT to cloud storage: {srt_cloud_url}")
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to upload SRT to cloud storage: {str(e)}")
                logger.error(traceback.format_exc())
                # Fall back to local file path if upload fails
                srt_cloud_url = f"file://{srt_path}"
        
        # Calculate total processing time
        end_time = time.time()
        total_time = end_time - process_start_time
        
        # Prepare response
        response = {
            "status": "success",
            "message": "Replicate auto-caption completed successfully",
            "output_video_url": output_video_url,
            "transcription_tool": "replicate_whisper",
            "job_id": job_id,
            "processing_time": round(total_time, 3)
        }
        
        # Add SRT URL to the response if requested
        if srt_cloud_url and include_srt:
            response["srt_url"] = srt_cloud_url
        
        # Clean up temporary files
        try:
            import shutil
            shutil.rmtree(temp_dir)
            logger.info(f"Job {job_id}: Cleaned up temporary files")
        except Exception as e:
            logger.warning(f"Job {job_id}: Failed to clean up temporary files: {str(e)}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error in replicate auto-caption processing: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Clean up temporary files
        try:
            import shutil
            shutil.rmtree(temp_dir)
            logger.info(f"Job {job_id}: Cleaned up temporary files")
        except Exception as cleanup_error:
            logger.warning(f"Job {job_id}: Failed to clean up temporary files: {str(cleanup_error)}")
        
        # Re-raise the exception with a more informative message
        raise ValueError(f"Replicate auto-caption processing error: {str(e)}")
