import os
import logging
from abc import ABC, abstractmethod
from services.gcp_toolkit import upload_to_gcs, GCP_BUCKET_NAME, gcs_client
from services.s3_toolkit import upload_to_s3
from config import validate_env_vars

logger = logging.getLogger(__name__)

# Define an abstract class for cloud storage providers
class CloudStorageProvider(ABC):
    @abstractmethod
    def upload_file(self, file_path: str) -> str:
        pass

# Define a GCP cloud storage provider
class GCPStorageProvider(CloudStorageProvider):
    def __init__(self):
        self.bucket_name = os.getenv('GCP_BUCKET_NAME')

    def upload_file(self, file_path: str) -> str:
        if not gcs_client:
            raise ValueError("GCP client is not initialized. Ensure GCP credentials are set.")
        return upload_to_gcs(file_path, self.bucket_name)

# Define an S3-compatible storage provider (e.g., DigitalOcean Spaces)
class S3CompatibleProvider(CloudStorageProvider):
    def __init__(self):
        self.bucket_name = os.getenv('S3_BUCKET_NAME')
        self.region = os.getenv('S3_REGION')
        self.endpoint_url = os.getenv('S3_ENDPOINT_URL')
        self.access_key = os.getenv('S3_ACCESS_KEY')
        self.secret_key = os.getenv('S3_SECRET_KEY')

    def upload_file(self, file_path: str) -> str:
        return upload_to_s3(file_path, self.bucket_name, self.region, self.endpoint_url, self.access_key, self.secret_key)

# Function to determine which cloud storage provider to use
def get_storage_provider() -> CloudStorageProvider:
    if os.getenv('S3_BUCKET_NAME'):
        validate_env_vars('S3')
        return S3CompatibleProvider()
    elif os.getenv('GCP_BUCKET_NAME'):
        validate_env_vars('GCP')
        return GCPStorageProvider()
    else:
        raise ValueError("No valid storage provider configuration found.")

# Function to upload the file using the selected storage provider
def upload_file(file_path: str) -> str:
    provider = get_storage_provider()
    try:
        logger.info(f"Uploading file to cloud storage: {file_path}")
        url = provider.upload_file(file_path)
        logger.info(f"File uploaded successfully: {url}")
        return url
    except Exception as e:
        logger.error(f"Error uploading file to cloud storage: {e}")
        raise

# Define the media processing functions (e.g., for FFmpeg operations)
def process_conversion(input_file: str, output_file: str, options: dict) -> str:
    logger.info(f"Converting {input_file} to {output_file} with options {options}")
    # Assuming ffmpeg is available; use the appropriate FFmpeg command for conversion
    import ffmpeg
    ffmpeg.input(input_file).output(output_file, **options).run()
    return output_file

def process_video_combination(input_files: list, output_file: str, options: dict) -> str:
    logger.info(f"Combining {input_files} into {output_file} with options {options}")
    # Example of using FFmpeg to concatenate multiple input files
    import ffmpeg
    ffmpeg.concat(*[ffmpeg.input(file) for file in input_files]).output(output_file, **options).run()
    return output_file
