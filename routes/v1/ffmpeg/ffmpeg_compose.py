import os
import logging
import uuid
import json
from flask import Blueprint, request, jsonify
from app_utils import *
from services.v1.ffmpeg.ffmpeg_compose import process_ffmpeg_compose
from services.authentication import authenticate
from services.cloud_storage import upload_file

v1_ffmpeg_compose_bp = Blueprint('v1_ffmpeg_compose', __name__)
logger = logging.getLogger(__name__)

@v1_ffmpeg_compose_bp.route('/v1/ffmpeg/compose', methods=['POST'])
@authenticate
@validate_payload({
    "type": "object",
    "properties": {
        "inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file_url": {"type": "string", "format": "uri"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "option": {"type": "string"},
                                "argument": {"type": ["string", "number", "null"]}
                            },
                            "required": ["option"]
                        }
                    }
                },
                "required": ["file_url"]
            },
            "minItems": 1
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filter": {"type": "string"}
                },
                "required": ["filter"]
            }
        },
        "outputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "option": {"type": "string"},
                                "argument": {"type": ["string", "number", "null"]}
                            },
                            "required": ["option"]
                        }
                    }
                },
                "required": ["options"]
            },
            "minItems": 1
        },
        "global_options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "option": {"type": "string"},
                    "argument": {"type": ["string", "number", "null"]}
                },
                "required": ["option"]
            }
        },
        "metadata": {
            "type": "object",
            "properties": {
                "thumbnail": {"type": "boolean"},
                "filesize": {"type": "boolean"},
                "duration": {"type": "boolean"},
                "bitrate": {"type": "boolean"},
                "encoder": {"type": "boolean"}
            }
        },
        "webhook_url": {"type": "string", "format": "uri"},
        "id": {"type": "string"}
    },
    "required": ["inputs", "outputs"],
    "additionalProperties": False
})
def ffmpeg_compose():
    """
    Flexible FFmpeg composition endpoint.
    
    This endpoint allows for flexible composition of FFmpeg commands,
    supporting multiple inputs, filters, and outputs.
    """
    try:
        # Generate a unique job ID
        job_id = str(uuid.uuid4())
        logger.info(f"Job {job_id}: Received flexible FFmpeg request")
        
        # Get request data
        data = request.get_json()
        logger.debug(f"Job {job_id}: Request data: {json.dumps(data, indent=2)}")
        
        # Process FFmpeg request
        try:
            output_filenames, metadata = process_ffmpeg_compose(data, job_id)
            logger.info(f"Job {job_id}: FFmpeg processing completed successfully")
            logger.debug(f"Job {job_id}: Output filenames: {output_filenames}")
            logger.debug(f"Job {job_id}: Metadata: {json.dumps(metadata, indent=2, default=str)}")
        except Exception as e:
            logger.error(f"Job {job_id}: Error processing FFmpeg request - {str(e)}")
            logger.exception(e)  # Log the full stack trace
            return jsonify({"status": "error", "message": f"Error processing FFmpeg request: {str(e)}"}), 500
        
        # Upload results to cloud storage
        response = []
        try:
            logger.info(f"Job {job_id}: Uploading {len(output_filenames)} files to cloud storage")
            for i, output_filename in enumerate(output_filenames):
                if not os.path.exists(output_filename):
                    logger.error(f"Job {job_id}: Output file does not exist: {output_filename}")
                    continue
                    
                # Upload the file
                file_url = upload_file(output_filename)
                logger.info(f"Job {job_id}: Uploaded file {i+1}/{len(output_filenames)} to {file_url}")
                
                # Add to response
                result = {
                    "file_url": file_url
                }
                
                # Add metadata if available
                if i < len(metadata):
                    result["metadata"] = metadata[i]
                    
                    # If there's a thumbnail, upload it too
                    if "thumbnail" in metadata[i] and os.path.exists(metadata[i]["thumbnail"]):
                        thumbnail_url = upload_file(metadata[i]["thumbnail"])
                        result["metadata"]["thumbnail_url"] = thumbnail_url
                        logger.info(f"Job {job_id}: Uploaded thumbnail to {thumbnail_url}")
                
                response.append(result)
                
                # Clean up the output file
                try:
                    os.remove(output_filename)
                    logger.info(f"Job {job_id}: Removed output file: {output_filename}")
                except Exception as e:
                    logger.warning(f"Job {job_id}: Failed to remove output file {output_filename}: {str(e)}")
                    
                # Clean up the thumbnail if it exists
                if i < len(metadata) and "thumbnail" in metadata[i] and os.path.exists(metadata[i]["thumbnail"]):
                    try:
                        os.remove(metadata[i]["thumbnail"])
                        logger.info(f"Job {job_id}: Removed thumbnail file: {metadata[i]['thumbnail']}")
                    except Exception as e:
                        logger.warning(f"Job {job_id}: Failed to remove thumbnail file {metadata[i]['thumbnail']}: {str(e)}")
        except Exception as e:
            logger.error(f"Job {job_id}: Error uploading results - {str(e)}")
            logger.exception(e)  # Log the full stack trace
            return jsonify({"status": "error", "message": f"Error uploading results: {str(e)}"}), 500
        
        logger.info(f"Job {job_id}: Request completed successfully")
        return jsonify({"status": "success", "response": response})
    except Exception as e:
        logger.error(f"Unhandled error in FFmpeg compose endpoint: {str(e)}")
        logger.exception(e)  # Log the full stack trace
        return jsonify({"status": "error", "message": f"Unhandled error: {str(e)}"}), 500