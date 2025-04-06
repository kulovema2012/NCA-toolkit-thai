import os
import sys

# Try to import dotenv, but continue if not available
try:
    from dotenv import load_dotenv
    # Load environment variables from .env file
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed. Using environment variables as is.")

from flask import Flask, request

# Load environment variables from .env file
load_dotenv()

# Retrieve the API key from environment variables
API_KEY = os.environ.get('API_KEY')
if not API_KEY:
    print("WARNING: API_KEY environment variable is not set. Some functionality may be limited.")
    API_KEY = "test_key"  # Provide a default for testing

# GCP environment variables
GCP_SA_CREDENTIALS = os.environ.get('GCP_SA_CREDENTIALS', '')
GCP_BUCKET_NAME = os.environ.get('GCP_BUCKET_NAME', '')

# S3 (DigitalOcean Spaces) environment variables
S3_ENDPOINT_URL = os.environ.get('S3_ENDPOINT_URL', '')
S3_ACCESS_KEY = os.environ.get('S3_ACCESS_KEY', '')
S3_SECRET_KEY = os.environ.get('S3_SECRET_KEY', '')

def validate_env_vars(provider):
    """ Validate the necessary environment variables for the selected storage provider """
    required_vars = {
        'GCP': ['GCP_BUCKET_NAME', 'GCP_SA_CREDENTIALS'],
        'S3': ['S3_ENDPOINT_URL', 'S3_ACCESS_KEY', 'S3_SECRET_KEY']
    }
    
    if provider not in required_vars:
        print(f"WARNING: Unknown provider '{provider}'. Supported providers: {list(required_vars.keys())}")
        return False
    
    missing_vars = []
    for var in required_vars[provider]:
        if not globals().get(var) or globals().get(var) == '':
            missing_vars.append(var)
    
    if missing_vars:
        print(f"WARNING: Missing required environment variables for {provider}: {missing_vars}")
        return False
    
    return True

class CloudStorageProvider:
    """ Abstract CloudStorageProvider class to define the upload_file method """
    def upload_file(self, file_path: str) -> str:
        raise NotImplementedError("upload_file must be implemented by subclasses")

class GCPStorageProvider(CloudStorageProvider):
    """ GCP-specific cloud storage provider """
    def __init__(self):
        self.bucket_name = os.getenv('GCP_BUCKET_NAME')

    def upload_file(self, file_path: str) -> str:
        from services.gcp_toolkit import upload_to_gcs
        return upload_to_gcs(file_path, self.bucket_name)

class S3CompatibleProvider(CloudStorageProvider):
    """ S3-compatible storage provider (e.g., DigitalOcean Spaces) """
    def __init__(self):
        self.bucket_name = os.getenv('S3_BUCKET_NAME')
        self.region = os.getenv('S3_REGION')
        self.endpoint_url = os.getenv('S3_ENDPOINT_URL')
        self.access_key = os.getenv('S3_ACCESS_KEY')
        self.secret_key = os.getenv('S3_SECRET_KEY')

    def upload_file(self, file_path: str) -> str:
        from services.s3_toolkit import upload_to_s3
        return upload_to_s3(file_path, self.bucket_name, self.region, self.endpoint_url, self.access_key, self.secret_key)

def get_storage_provider() -> CloudStorageProvider:
    """ Get the appropriate storage provider based on the STORAGE_PATH environment variable """
    storage_path = os.getenv('STORAGE_PATH', 'GCP').upper()
    
    if storage_path == 'S3':
        if not validate_env_vars('S3'):
            print("Falling back to GCP due to missing S3 environment variables.")
            storage_path = 'GCP'
    else:
        if not validate_env_vars('GCP'):
            print("Falling back to S3 due to missing GCP environment variables.")
            storage_path = 'S3'
    
    if storage_path == 'S3':
        return S3CompatibleProvider()
    else:
        return GCPStorageProvider()
