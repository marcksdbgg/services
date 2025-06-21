# File: app/services/s3_client.py
import boto3
from botocore.exceptions import ClientError
import structlog
from typing import Optional
import asyncio

from app.core.config import settings

log = structlog.get_logger(__name__)

class S3ClientError(Exception):
    """Custom exception for S3 related errors."""
    pass

class S3Client:
    """Client to interact with Amazon S3."""

    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket_name = bucket_name or settings.AWS_S3_BUCKET_NAME
        # El cliente se crea usando las credenciales del entorno (IAM role en ECS)
        self.s3_client = boto3.client("s3", region_name=settings.AWS_REGION)
        self.log = log.bind(s3_bucket=self.bucket_name, aws_region=settings.AWS_REGION)

    async def upload_file_async(self, object_name: str, data: bytes, content_type: str) -> str:
        """Uploads a file to S3 asynchronously using an executor."""
        self.log.info("Uploading file to S3...", object_name=object_name, content_type=content_type)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,  # Usa el executor por defecto (ThreadPoolExecutor)
                lambda: self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=object_name,
                    Body=data,
                    ContentType=content_type
                )
            )
            self.log.info("File uploaded successfully to S3", object_name=object_name)
            return object_name
        except ClientError as e:
            self.log.error("S3 upload failed", error_code=e.response.get("Error", {}).get("Code"), error=str(e))
            raise S3ClientError(f"S3 error uploading {object_name}") from e
        except Exception as e:
            self.log.exception("Unexpected error during S3 upload", error=str(e))
            raise S3ClientError(f"Unexpected error uploading {object_name}") from e

    async def check_file_exists_async(self, object_name: str) -> bool:
        """Checks if a file exists in S3."""
        self.log.debug("Checking file existence in S3", object_name=object_name)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.head_object(Bucket=self.bucket_name, Key=object_name)
            )
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            self.log.error("Error checking S3 file existence", error=str(e))
            return False
        except Exception as e:
            self.log.exception("Unexpected error checking S3 file existence", error=str(e))
            return False

    async def delete_file_async(self, object_name: str):
        """Deletes a file from S3."""
        self.log.info("Deleting file from S3...", object_name=object_name)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.delete_object(Bucket=self.bucket_name, Key=object_name)
            )
            self.log.info("File deleted successfully from S3", object_name=object_name)
        except ClientError as e:
            self.log.error("S3 delete failed", error=str(e))
            raise S3ClientError(f"S3 error deleting {object_name}") from e