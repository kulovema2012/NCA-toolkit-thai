import requests
import logging
import json

logger = logging.getLogger(__name__)

def send_webhook(webhook_url, data):
    """Send a POST request to a webhook URL with the provided data."""
    try:
        # Ensure data is JSON serializable
        try:
            # Test if the data is JSON serializable
            json_data = json.dumps(data)
            # Use the serialized data to ensure it's properly formatted
            data_dict = json.loads(json_data)
            
            logger.info(f"Attempting to send webhook to {webhook_url}")
            response = requests.post(webhook_url, json=data_dict)
            response.raise_for_status()
            logger.info(f"Webhook sent successfully")
        except (TypeError, json.JSONDecodeError) as json_error:
            logger.error(f"Data is not JSON serializable: {json_error}")
            # Create a simplified version that should be serializable
            simple_data = {
                "status": "error",
                "message": "Failed to serialize response data",
                "error": str(json_error)
            }
            response = requests.post(webhook_url, json=simple_data)
            response.raise_for_status()
            logger.info(f"Simplified webhook sent")
    except requests.RequestException as e:
        logger.error(f"Webhook request failed: {e}")
