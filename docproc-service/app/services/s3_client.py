# File: app/services/s3_client.py
import boto3
from botocore.exceptions import ClientError
import structlog
from typing import Optional

from app.core.config import settings

log = structlog.get_logger(__name__)

class S3ClientError(Exception):
    pass

class S3Client:
    """Synchronous client to interact with Amazon S3."""

    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket_name = bucket_name or settings.AWS_S3_BUCKET_NAME
        self.s3_client = boto3.client("s3", region_name=settings.AWS_REGION)
        self.log = log.bind(s3_bucket=self.bucket_name, aws_region=settings.AWS_REGION)

    def download_file_sync(self, object_name: str, download_path: str):
        """Downloads a file from S3 to a local path."""
        self.log.info("Downloading file from S3...", object_name=object_name, target_path=download_path)
        try:
            self.s3_client.download_file(self.bucket_name, object_name, download_path)
            self.log.info("File downloaded successfully from S3.", object_name=object_name)
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                self.log.error("Object not found in S3", object_name=object_name)
                raise S3ClientError(f"Object not found in S3: {object_name}") from e
            else:
                self.log.error("S3 download failed", error_code=e.response.get("Error", {}).get("Code"), error=str(e))
                raise S3ClientError(f"S3 error downloading {object_name}") from e