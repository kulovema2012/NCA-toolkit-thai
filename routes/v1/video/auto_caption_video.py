#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import logging
from flask import Blueprint, request, jsonify
import traceback
import sys

# Add explicit NumPy import with error handling
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logging.error("NumPy is not available. This will affect transcription functionality.")

from services.v1.media.media_transcribe import process_transcribe_media
from services.v1.video.caption_video import add_subtitles_to_video

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

auto_caption_video_bp = Blueprint('auto_caption_video', __name__)

# Use only the standard v1 endpoint format
@auto_caption_video_bp.route('/v1/video/auto-caption', methods=['POST'])
def auto_caption_video():
    """
    Automatically transcribe a video and add subtitles in one step.
    
    Expected JSON payload:
    {
        "video_url": "URL or path to video file",
        "language": "th",  # Optional, default is "th" for Thai
        "multi_language": false,  # Optional, detect multiple languages
        "font": "Sarabun",  # Optional, default is "Sarabun"
        "position": "bottom",  # Optional: "bottom", "top", or "middle"
        "style": "classic",  # Optional: "classic" or "modern"
        "margin": 50,  # Optional: vertical margin in pixels
        "max_width": 80,  # Optional: maximum width as percentage of video width
        "output_path": "optional/custom/output/path.mp4"  # Optional
    }
    
    Returns:
    {
        "status": "success",
        "file_url": "URL to the captioned video",
        "transcription": {
            "text": "Full transcription text",
            "segments": [...],  # List of transcription segments
            "language": "Detected language"
        }
    }
    """
    try:
        # Check if NumPy is available
        if not NUMPY_AVAILABLE:
            return jsonify({
                "status": "error",
                "message": "NumPy is not available. Please contact the administrator."
            }), 500
            
        # Get request data
        data = request.get_json()
        
        if not data:
            return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
        # Required parameters
        video_url = data.get('video_url')
        
        if not video_url:
            return jsonify({"status": "error", "message": "video_url is required"}), 400
        
        # Optional parameters with defaults
        language = data.get('language', 'th')
        multi_language = data.get('multi_language', False)
        font = data.get('font', 'Sarabun')
        position = data.get('position', 'bottom')
        style = data.get('style', 'classic')
        margin = data.get('margin', 50)
        max_width = data.get('max_width', 80)
        output_path = data.get('output_path', None)
        
        # Generate a job ID
        import uuid
        job_id = str(uuid.uuid4())
        
        logger.info(f"Starting auto-caption job {job_id} for video: {video_url}")
        
        # Step 1: Transcribe the video
        logger.info(f"Transcribing video: {video_url}")
        transcribe_result = process_transcribe_media(
            media_url=video_url,
            task="transcribe",
            include_text=True,
            include_srt=True,
            include_segments=True,
            word_timestamps=False,
            response_type="json",
            language=None if multi_language else language,
            job_id=job_id
        )
        
        logger.info(f"Transcription result: {transcribe_result}")
        
        # The process_transcribe_media function returns a tuple of (text_filename, srt_filename, segments_filename)
        # when response_type is not "direct"
        if not transcribe_result:
            return jsonify({
                "status": "error", 
                "message": "Transcription failed"
            }), 500
            
        # Unpack the result tuple
        text_path, srt_path, segments_path = transcribe_result
        
        if not srt_path or not os.path.exists(srt_path):
            logger.error(f"SRT file not found at path: {srt_path}")
            return jsonify({
                "status": "error", 
                "message": "Transcription did not produce SRT file"
            }), 500
        
        logger.info(f"Transcription successful, SRT file created at: {srt_path}")
        
        # Step 2: Add subtitles to the video
        logger.info(f"Adding subtitles to video with style: {style}, position: {position}")
        
        # Determine subtitle position alignment
        alignment = "2"  # Default: bottom center
        if position == "top":
            alignment = "8"  # Top center
        elif position == "middle":
            alignment = "5"  # Middle center
        
        # Determine border style
        border_style = "1"  # Default: outline (classic)
        if style == "modern":
            border_style = "3"  # Background box (modern)
        
        caption_result = add_subtitles_to_video(
            video_path=video_url,
            subtitle_path=srt_path,
            output_path=output_path,
            font_name=font,
            font_size=24,
            margin_v=margin,
            subtitle_style=style,
            max_width=max_width,
            position=position,
            job_id=job_id
        )
        
        if not caption_result:
            return jsonify({
                "status": "error", 
                "message": "Failed to add subtitles to video"
            }), 500
        
        # Prepare the response
        response = {
            "status": "success",
            "file_url": caption_result['file_url'] if isinstance(caption_result, dict) else caption_result,
            "transcription": {
                "text": open(text_path, 'r').read(),
                "segments": json.load(open(segments_path, 'r')),
                "language": language
            }
        }
        
        logger.info(f"Auto-caption job {job_id} completed successfully")
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error in auto-caption endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": f"An error occurred: {str(e)}"
        }), 500
