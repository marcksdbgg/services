# File: docproc-service/app/main.py
import sys
import os
import json
import uuid
import tempfile
import pathlib
import asyncio
import structlog
from typing import Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

from prometheus_client import start_http_server

from app.core.logging_config import setup_logging
setup_logging()

from app.core.config import settings
from app.services.kafka_clients import KafkaConsumerClient, KafkaProducerClient
from app.services.s3_client import S3Client, S3ClientError
from app.application.use_cases.process_document_use_case import ProcessDocumentUseCase
from app.dependencies import get_process_document_use_case
from app.core.metrics import (
    MESSAGES_CONSUMED_TOTAL,
    PROCESSING_DURATION_SECONDS,
    CHUNKS_PRODUCED_TOTAL,
    PROCESSING_ERRORS_TOTAL,
)

log = structlog.get_logger(__name__)

def main():
    """Punto de entrada principal para el worker de procesamiento de documentos."""
    log.info("Initializing DocProc Worker...", config=settings.model_dump(exclude=['SUPPORTED_CONTENT_TYPES']))

    try:
        # Start Prometheus metrics server
        start_http_server(8001)
        log.info("Prometheus metrics server started on port 8001.")

        consumer = KafkaConsumerClient(topics=[settings.KAFKA_INPUT_TOPIC])
        producer = KafkaProducerClient()
        s3_client = S3Client()
        use_case: ProcessDocumentUseCase = get_process_document_use_case()
    except Exception as e:
        log.critical("Failed to initialize worker dependencies", error=str(e), exc_info=True)
        sys.exit(1)

    log.info("Worker initialized successfully. Starting message consumption loop...")
    
    try:
        for msg in consumer.consume():
            process_message(msg, s3_client, use_case, producer)
            consumer.commit(message=msg)
    except KeyboardInterrupt:
        log.info("Shutdown signal received.")
    except Exception as e:
        log.critical("Critical error in consumer loop. Exiting.", error=str(e), exc_info=True)
    finally:
        log.info("Closing worker resources...")
        consumer.close()
        producer.flush()
        log.info("Worker shut down gracefully.")


def process_message(msg, s3_client: S3Client, use_case: ProcessDocumentUseCase, producer: KafkaProducerClient):
    """Procesa un único mensaje de Kafka."""
    event_data = None
    try:
        event_data = json.loads(msg.value().decode('utf-8'))
        MESSAGES_CONSUMED_TOTAL.labels(topic=msg.topic(), status="success").inc()
    except json.JSONDecodeError:
        log.error("Failed to decode Kafka message value", raw_value=msg.value())
        MESSAGES_CONSUMED_TOTAL.labels(topic=msg.topic(), status="failure").inc()
        return

    log_context = {
        "kafka_topic": msg.topic(),
        "kafka_partition": msg.partition(),
        "kafka_offset": msg.offset(),
        "document_id": event_data.get("document_id"),
        "company_id": event_data.get("company_id"),
    }
    msg_log = log.bind(**log_context)
    msg_log.info("Received new message to process.")

    s3_path = event_data.get("s3_path")
    document_id = event_data.get("document_id")
    company_id = event_data.get("company_id")
    content_type = event_data.get("content_type") or guess_content_type(s3_path)

    if not all([s3_path, document_id, content_type, company_id]):
        msg_log.error("Message is missing required fields.")
        PROCESSING_ERRORS_TOTAL.labels(stage="validation").inc()
        return

    with PROCESSING_DURATION_SECONDS.labels(company_id=company_id, content_type=content_type).time():
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                local_path = pathlib.Path(temp_dir) / os.path.basename(s3_path)
                s3_client.download_file_sync(s3_path, str(local_path))
                file_bytes = local_path.read_bytes()

            msg_log.info("File downloaded from S3, proceeding with processing.", file_size=len(file_bytes))
            
            process_response_data = asyncio.run(use_case.execute(
                file_bytes=file_bytes,
                original_filename=os.path.basename(s3_path),
                content_type=content_type,
                document_id_trace=document_id,
                company_id_trace=company_id
            ))

            chunks = process_response_data.chunks
            msg_log.info(f"Document processed. Found {len(chunks)} chunks to produce.")
            CHUNKS_PRODUCED_TOTAL.labels(company_id=company_id, content_type=content_type).inc(len(chunks))
            
            for i, chunk in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                page_number = chunk.source_metadata.page_number
                
                output_payload = {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "company_id": company_id,
                    "text": chunk.text,
                    "page": page_number if page_number is not None else -1
                }
                producer.produce(
                    topic=settings.KAFKA_OUTPUT_TOPIC,
                    key=document_id,
                    value=output_payload
                )
            msg_log.info("All chunks produced to output topic.", num_chunks=len(chunks))
        except S3ClientError as e:
            msg_log.error("Failed to process message due to S3 error", error=str(e), exc_info=True)
            PROCESSING_ERRORS_TOTAL.labels(stage="s3_download").inc()
        except Exception as e:
            msg_log.error("Unhandled error processing message", error=str(e), exc_info=True)
            PROCESSING_ERRORS_TOTAL.labels(stage="unknown").inc()


def guess_content_type(filename: str) -> Optional[str]:
    """Intenta adivinar el content-type a partir de la extensión del archivo."""
    import mimetypes
    content_type, _ = mimetypes.guess_type(filename)
    if content_type is None:
        if filename.lower().endswith('.md'):
            return 'text/markdown'
    return content_type


if __name__ == "__main__":
    main()