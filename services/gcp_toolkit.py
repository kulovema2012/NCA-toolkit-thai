import os
import json
import logging
from google.oauth2 import service_account
from google.cloud import storage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GCS environment variables
GCP_BUCKET_NAME = os.getenv('GCP_BUCKET_NAME')
STORAGE_PATH = "/tmp/"
gcs_client = None

def initialize_gcp_client():
    GCP_SA_CREDENTIALS = os.getenv('GCP_SA_CREDENTIALS')

    if not GCP_SA_CREDENTIALS:
        logger.warning("GCP credentials not found. Skipping GCS client initialization.")
        return None  # Skip client initialization if credentials are missing

    # Define the required scopes for Google Cloud Storage
    GCS_SCOPES = ['https://www.googleapis.com/auth/devstorage.full_control']

    try:
        credentials_info = json.loads(GCP_SA_CREDENTIALS)
        gcs_credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=GCS_SCOPES
        )
        return storage.Client(credentials=gcs_credentials)
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        return None

# Initialize the GCS client
gcs_client = initialize_gcp_client()

def upload_to_gcs(file_path, bucket_name=GCP_BUCKET_NAME):
    if not gcs_client:
        raise ValueError("GCS client is not initialized. Skipping file upload.")

    try:
        logger.info(f"Uploading file to Google Cloud Storage: {file_path}")
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(os.path.basename(file_path))
        blob.upload_from_filename(file_path)
        logger.info(f"File uploaded successfully to GCS: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        logger.error(f"Error uploading file to GCS: {e}")
        raise

def upload_to_gcs_with_path(file_path, bucket_name=GCP_BUCKET_NAME, destination_path=None):
    """
    Upload a file to Google Cloud Storage with a custom destination path.
    
    Args:
        file_path: Local path to the file to upload
        bucket_name: GCS bucket name
        destination_path: Custom path in the bucket (e.g., 'thumbnails/image.jpg')
        
    Returns:
        Public URL to the uploaded file
    """
    if not gcs_client:
        raise ValueError("GCS client is not initialized. Skipping file upload.")

    try:
        logger.info(f"Uploading file to Google Cloud Storage with custom path: {file_path} -> {destination_path}")
        bucket = gcs_client.bucket(bucket_name)
        
        # Use destination_path if provided, otherwise use the basename
        blob_path = destination_path if destination_path else os.path.basename(file_path)
        blob = bucket.blob(blob_path)
        
        blob.upload_from_filename(file_path)
        logger.info(f"File uploaded successfully to GCS: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        logger.error(f"Error uploading file to GCS with custom path: {e}")
        raise
