# File: ingest-service/app/api/v1/endpoints/ingest.py
import uuid
import json
from typing import Optional

import structlog
from fastapi import (
    APIRouter, Depends, HTTPException, status,
    UploadFile, File, Form, Request
)

from app.core.config import settings
from app.api.v1.schemas import IngestResponse
from app.services.s3_client import S3Client, S3ClientError
from app.services.kafka_producer import KafkaProducerClient, KafkaException
from app.core.metrics import UPLOADS_TOTAL, UPLOAD_FILE_SIZE_BYTES

log = structlog.get_logger(__name__)
router = APIRouter()

def get_s3_client():
    return S3Client()

def get_kafka_producer(request: Request) -> KafkaProducerClient:
    return request.app.state.kafka_producer

def normalize_filename(filename: str) -> str:
    return " ".join(filename.strip().split())

@router.post(
    "/upload",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document, store it in S3, and produce a Kafka message.",
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    metadata_json: Optional[str] = Form(None),
    s3_client: S3Client = Depends(get_s3_client),
    kafka_producer: KafkaProducerClient = Depends(get_kafka_producer),
):
    company_id = request.headers.get("X-Company-ID", "default-company")
    content_type = file.content_type
    
    endpoint_log = log.bind(company_id=company_id, filename=file.filename, content_type=content_type)
    endpoint_log.info("Document upload request received.")

    if content_type not in settings.SUPPORTED_CONTENT_TYPES:
        UPLOADS_TOTAL.labels(company_id=company_id, content_type=content_type, status="error_client").inc()
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported file type")

    document_id = str(uuid.uuid4())
    normalized_filename = normalize_filename(file.filename)
    s3_path = f"{company_id}/{document_id}/{normalized_filename}"
    
    try:
        file_content = await file.read()
        UPLOAD_FILE_SIZE_BYTES.labels(company_id=company_id, content_type=content_type).observe(len(file_content))
        
        await s3_client.upload_file_async(s3_path, file_content, content_type)
        
        kafka_payload = {
            "document_id": document_id,
            "company_id": company_id,
            "s3_path": s3_path,
            "content_type": content_type # Add content_type for consumer
        }
        kafka_producer.produce(
            topic=settings.KAFKA_DOCUMENTS_RAW_TOPIC,
            key=document_id,
            value=kafka_payload
        )
        endpoint_log.info("File uploaded to S3 and message produced to Kafka.", s3_path=s3_path)
        UPLOADS_TOTAL.labels(company_id=company_id, content_type=content_type, status="success").inc()

    except (S3ClientError, KafkaException) as e:
        endpoint_log.exception("Error during S3 upload or Kafka production", error=str(e))
        UPLOADS_TOTAL.labels(company_id=company_id, content_type=content_type, status="error_server").inc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process file upload.")
    finally:
        await file.close()

    return IngestResponse(
        document_id=document_id,
        status="Event-Sent",
        message="Document received and processing event sent to Kafka."
    )