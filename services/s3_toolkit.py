import os
import boto3
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def parse_s3_url(s3_url):
    """Parse S3 URL to extract bucket name, region, and endpoint URL."""
    parsed_url = urlparse(s3_url)
    
    # Extract bucket name from the host
    bucket_name = parsed_url.hostname.split('.')[0]
    
    # Extract region from the host
    region = parsed_url.hostname.split('.')[1]
    
    # Construct endpoint URL
    endpoint_url = f"https://{region}.digitaloceanspaces.com"
    
    return bucket_name, region, endpoint_url

def upload_to_s3(file_path, s3_url, access_key, secret_key):
    # Parse the S3 URL into bucket, region, and endpoint
    bucket_name, region, endpoint_url = parse_s3_url(s3_url)
    
    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    
    client = session.client('s3', endpoint_url=endpoint_url)

    try:
        # Upload the file to the specified S3 bucket
        with open(file_path, 'rb') as data:
            client.upload_fileobj(data, bucket_name, os.path.basename(file_path), ExtraArgs={'ACL': 'public-read'})

        file_url = f"{endpoint_url}/{bucket_name}/{os.path.basename(file_path)}"
        return file_url
    except Exception as e:
        logger.error(f"Error uploading file to S3: {e}")
        raise

def upload_to_s3_with_path(file_path, s3_url, access_key, secret_key, destination_path=None):
    """
    Upload a file to S3-compatible storage with a custom destination path.
    
    Args:
        file_path: Local path to the file to upload
        s3_url: S3 endpoint URL
        access_key: S3 access key
        secret_key: S3 secret key
        destination_path: Custom path in the bucket (e.g., 'thumbnails/image.jpg')
        
    Returns:
        Public URL to the uploaded file
    """
    # Parse the S3 URL into bucket, region, and endpoint
    bucket_name, region, endpoint_url = parse_s3_url(s3_url)
    
    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    
    client = session.client('s3', endpoint_url=endpoint_url)

    try:
        # Use destination_path if provided, otherwise use the basename
        object_key = destination_path if destination_path else os.path.basename(file_path)
        
        logger.info(f"Uploading file to S3 with custom path: {file_path} -> {object_key}")
        
        # Upload the file to the specified S3 bucket with the custom path
        with open(file_path, 'rb') as data:
            client.upload_fileobj(data, bucket_name, object_key, ExtraArgs={'ACL': 'public-read'})

        file_url = f"{endpoint_url}/{bucket_name}/{object_key}"
        logger.info(f"File uploaded successfully to S3: {file_url}")
        return file_url
    except Exception as e:
        logger.error(f"Error uploading file to S3 with custom path: {e}")
        raise
