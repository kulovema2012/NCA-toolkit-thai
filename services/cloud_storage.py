import os
import logging
from abc import ABC, abstractmethod
from services.gcp_toolkit import upload_to_gcs
from services.s3_toolkit import upload_to_s3
from config import validate_env_vars

logger = logging.getLogger(__name__)

class CloudStorageProvider(ABC):
    @abstractmethod
    def upload_file(self, file_path: str) -> str:
        pass

class GCPStorageProvider(CloudStorageProvider):
    def __init__(self):
        self.bucket_name = os.getenv('GCP_BUCKET_NAME')

    def upload_file(self, file_path: str) -> str:
        return upload_to_gcs(file_path, self.bucket_name)

class S3CompatibleProvider(CloudStorageProvider):
    def __init__(self):
        self.endpoint_url = os.getenv('S3_ENDPOINT_URL')
        self.access_key = os.getenv('S3_ACCESS_KEY')
        self.secret_key = os.getenv('S3_SECRET_KEY')

    def upload_file(self, file_path: str) -> str:
        return upload_to_s3(file_path, self.endpoint_url, self.access_key, self.secret_key)

def get_storage_provider() -> CloudStorageProvider:
    storage_path = os.getenv('STORAGE_PATH', 'GCP').upper()
    
    if storage_path == 'S3':
        try:
            validate_env_vars('S3')
            return S3CompatibleProvider()
        except ValueError as e:
            logger.warning(f"Error with S3 configuration: {str(e)}. Falling back to GCP.")
            validate_env_vars('GCP')
            return GCPStorageProvider()
    else:
        validate_env_vars('GCP')
        return GCPStorageProvider()

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

def upload_to_cloud_storage(file_path: str, destination_path: str = None) -> str:
    """
    Upload a file to cloud storage with a custom destination path.
    
    Args:
        file_path: Local path to the file to upload
        destination_path: Optional custom path in the cloud storage bucket
        
    Returns:
        URL to the uploaded file
    """
    provider = get_storage_provider()
    try:
        logger.info(f"Uploading file to cloud storage: {file_path} -> {destination_path}")
        
        if isinstance(provider, GCPStorageProvider):
            from services.gcp_toolkit import upload_to_gcs_with_path
            url = upload_to_gcs_with_path(file_path, provider.bucket_name, destination_path)
        elif isinstance(provider, S3CompatibleProvider):
            from services.s3_toolkit import upload_to_s3_with_path
            url = upload_to_s3_with_path(file_path, provider.endpoint_url, provider.access_key, 
                                        provider.secret_key, destination_path)
        else:
            # Fallback to regular upload if custom path not supported
            url = provider.upload_file(file_path)
            
        logger.info(f"File uploaded successfully: {url}")
        return url
    except Exception as e:
        logger.error(f"Error uploading file to cloud storage: {e}")
        raise