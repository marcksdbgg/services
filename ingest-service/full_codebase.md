# Estructura de la Codebase del Microservicio ingest-service

```
app/
├── __init__.py
├── api
│   ├── __init__.py
│   └── v1
│       ├── __init__.py
│       ├── endpoints
│       │   ├── __init__.py
│       │   └── ingest.py
│       └── schemas.py
├── core
│   ├── __init__.py
│   ├── config.py
│   └── logging_config.py
├── main.py
├── models
│   ├── __init__.py
│   └── domain.py
└── services
    ├── __init__.py
    ├── kafka_producer.py
    └── s3_client.py
```

# Codebase del Microservicio ingest-service: `app`

## File: `app\__init__.py`
```py

```

## File: `app\api\__init__.py`
```py

```

## File: `app\api\v1\__init__.py`
```py

```

## File: `app\api\v1\endpoints\__init__.py`
```py

```

## File: `app\api\v1\endpoints\ingest.py`
```py
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
    company_id = request.headers.get("X-Company-ID", "default-company") # Usar un valor por defecto si no viene
    
    endpoint_log = log.bind(company_id=company_id, filename=file.filename)
    endpoint_log.info("Document upload request received.")

    if file.content_type not in settings.SUPPORTED_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported file type")

    document_id = str(uuid.uuid4())
    normalized_filename = normalize_filename(file.filename)
    s3_path = f"{company_id}/{document_id}/{normalized_filename}"
    
    try:
        file_content = await file.read()
        await s3_client.upload_file_async(s3_path, file_content, file.content_type)
        
        kafka_payload = {
            "document_id": document_id,
            "company_id": company_id,
            "s3_path": s3_path
        }
        kafka_producer.produce(
            topic=settings.KAFKA_DOCUMENTS_RAW_TOPIC,
            key=document_id,
            value=kafka_payload
        )
        endpoint_log.info("File uploaded to S3 and message produced to Kafka.", s3_path=s3_path)

    except (S3ClientError, KafkaException) as e:
        endpoint_log.exception("Error during S3 upload or Kafka production", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process file upload.")
    finally:
        await file.close()

    return IngestResponse(
        document_id=document_id,
        status="Event-Sent",
        message="Document received and processing event sent to Kafka."
    )
```

## File: `app\api\v1\schemas.py`
```py
# File: ingest-service/app/api/v1/schemas.py
import uuid
from pydantic import BaseModel, Field

class ErrorDetail(BaseModel):
    """Schema for error details in responses."""
    detail: str

class IngestResponse(BaseModel):
    """
    Schema for the response after successfully receiving a document
    and sending an event to Kafka.
    """
    document_id: uuid.UUID
    status: str = Field(description="Indicates the event status.")
    message: str = Field(description="A descriptive message about the outcome.")

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "Event-Sent",
                "message": "Document received and processing event sent to Kafka."
            }
        }
```

## File: `app\core\__init__.py`
```py

```

## File: `app\core\config.py`
```py
# File: ingest-service/app/core/config.py
import sys
import logging
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_prefix='INGEST_',
        case_sensitive=False,
        env_file_encoding='utf-8',
        extra='ignore'
    )

    PROJECT_NAME: str = "Atenex Ingest Service (Kafka Producer, DB-less)"
    API_V1_STR: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # --- AWS S3 ---
    AWS_S3_BUCKET_NAME: str = Field(description="Name of the S3 bucket for storing original files.")
    AWS_REGION: str = Field(default="us-east-1", description="AWS region for S3 client.")

    # --- Kafka Producer ---
    KAFKA_BOOTSTRAP_SERVERS: str = Field(description="Comma-separated list of Kafka bootstrap servers.")
    KAFKA_DOCUMENTS_RAW_TOPIC: str = Field(default="documents.raw", description="Kafka topic for new raw documents.")
    KAFKA_PRODUCER_ACKS: str = "all"
    KAFKA_PRODUCER_LINGER_MS: int = 10

    SUPPORTED_CONTENT_TYPES: List[str] = [
        "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword", "text/plain", "text/markdown", "text/html",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel",
    ]

    @field_validator('LOG_LEVEL')
    @classmethod
    def check_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL '{v}'. Must be one of {valid_levels}")
        return v.upper()

temp_log = logging.getLogger("ingest_service.config.loader")
if not temp_log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    temp_log.addHandler(handler)
    temp_log.setLevel(logging.INFO)

try:
    temp_log.info("Loading DB-less Ingest Service settings...")
    settings = Settings()
    temp_log.info("--- DB-less Ingest Service Settings Loaded ---")
    temp_log.info(f"  PROJECT_NAME: {settings.PROJECT_NAME}")
    temp_log.info(f"  AWS_S3_BUCKET_NAME: {settings.AWS_S3_BUCKET_NAME}")
    temp_log.info(f"  KAFKA_BOOTSTRAP_SERVERS: {settings.KAFKA_BOOTSTRAP_SERVERS}")
    temp_log.info("------------------------------------------")
except Exception as e:
    temp_log.critical(f"FATAL: Error loading Ingest Service settings: {e}")
    sys.exit("FATAL: Invalid configuration. Check logs.")
```

## File: `app\core\logging_config.py`
```py
import logging
import sys
import structlog
from app.core.config import settings
import os

def setup_logging():
    """Configura el logging estructurado con structlog."""

    # Disable existing handlers if running in certain environments (like Uvicorn default)
    # to avoid duplicate logs. This might need adjustment based on deployment.
    # logging.getLogger().handlers.clear()

    # Determine if running inside Celery worker
    is_celery_worker = "celery" in sys.argv[0]

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.LOG_LEVEL == logging.DEBUG:
         # Add caller info only in debug mode for performance
         shared_processors.append(structlog.processors.CallsiteParameterAdder(
             {
                 structlog.processors.CallsiteParameter.FILENAME,
                 structlog.processors.CallsiteParameter.LINENO,
             }
         ))

    # Configure structlog
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure the formatter for stdlib logging
    formatter = structlog.stdlib.ProcessorFormatter(
        # These run ONCE per log structuralization
        foreign_pre_chain=shared_processors,
         # These run on EVERY record
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(), # Render as JSON
        ],
    )

    # Configure root logger handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Avoid adding handler twice if already configured (e.g., by Uvicorn/Gunicorn)
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
         root_logger.addHandler(handler)

    root_logger.setLevel(settings.LOG_LEVEL)

    # Silence verbose libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("haystack").setLevel(logging.INFO) # Or DEBUG for more Haystack details
    logging.getLogger("milvus_haystack").setLevel(logging.INFO) # Adjust as needed

    log = structlog.get_logger("ingest_service")
    log.info("Logging configured", log_level=settings.LOG_LEVEL, is_celery_worker=is_celery_worker)
```

## File: `app\main.py`
```py
# File: ingest-service/app/main.py
import time
import uuid
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status as fastapi_status
from fastapi.responses import JSONResponse

from app.core.logging_config import setup_logging
setup_logging()

from app.core.config import settings
from app.api.v1.endpoints import ingest
from app.services.kafka_producer import KafkaProducerClient

log = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Ingest Service startup sequence initiated...")
    app.state.kafka_producer = KafkaProducerClient()
    log.info("Dependencies (Kafka Producer) initialized.")
    yield
    log.info("Ingest Service shutdown sequence initiated...")
    app.state.kafka_producer.flush()
    log.info("Shutdown sequence complete.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    version="2.1.0-final",
    description="Atenex Ingest Service. Uploads files to S3 and produces events to Kafka.",
    lifespan=lifespan,
)

@app.middleware("http")
async def add_request_context(request: Request, call_next):
    start_time = time.perf_counter()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    process_time = (time.perf_counter() - start_time) * 1000
    log.info("Request processed", method=request.method, path=request.url.path, status_code=response.status_code, duration_ms=round(process_time, 2))
    return response

app.include_router(ingest.router, prefix=settings.API_V1_STR, tags=["Ingestion"])

@app.get("/health", tags=["Health Check"])
async def health_check():
    # El health check ya no depende de la base de datos
    return {"status": "healthy"}
```

## File: `app\models\__init__.py`
```py

```

## File: `app\models\domain.py`
```py
# ingest-service/app/models/domain.py
import uuid
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    # INDEXED = "indexed" # Merged into PROCESSED
    ERROR = "error"
    PENDING = "pending"

class ChunkVectorStatus(str, Enum):
    """Possible status values for the vector associated with a chunk."""
    PENDING = "pending"     # Initial state before Milvus insertion attempt
    CREATED = "created"     # Successfully inserted into Milvus
    ERROR = "error"         # Failed to insert into Milvus

class DocumentChunkMetadata(BaseModel):
    """Structure for metadata stored in the JSONB field of document_chunks."""
    page: Optional[int] = None
    title: Optional[str] = None
    tokens: Optional[int] = None
    content_hash: Optional[str] = Field(None, max_length=64) # e.g., SHA256 hex digest

class DocumentChunkData(BaseModel):
    """Internal representation of a chunk before DB insertion."""
    document_id: uuid.UUID
    company_id: uuid.UUID
    chunk_index: int
    content: str
    metadata: DocumentChunkMetadata = Field(default_factory=DocumentChunkMetadata)
    embedding_id: Optional[str] = None # Populated after Milvus insertion
    vector_status: ChunkVectorStatus = ChunkVectorStatus.PENDING
```

## File: `app\services\__init__.py`
```py

```

## File: `app\services\kafka_producer.py`
```py
# File: app/services/kafka_producer.py
import json
import structlog
from confluent_kafka import Producer, KafkaException
from typing import Optional

from app.core.config import settings

log = structlog.get_logger(__name__)

class KafkaProducerClient:
    """A client to produce messages to a Kafka topic."""

    def __init__(self):
        producer_config = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'acks': settings.KAFKA_PRODUCER_ACKS,
            'linger.ms': settings.KAFKA_PRODUCER_LINGER_MS,
            # Para AWS MSK con IAM Auth, se necesitarían más configuraciones.
            # 'security.protocol': 'SASL_SSL',
            # 'sasl.mechanisms': 'AWS_MSK_IAM',
            # Para este proyecto universitario, se asume una red simple sin IAM auth.
        }
        self.producer = Producer(producer_config)
        self.log = log.bind(component="KafkaProducerClient")
        self.log.info("Kafka producer initialized.", config=producer_config)

    def _delivery_report(self, err, msg):
        """Callback called once for each message produced."""
        if err is not None:
            self.log.error(f"Message delivery failed to topic '{msg.topic()}'", key=msg.key().decode('utf-8'), error=str(err))
        else:
            self.log.info(f"Message delivered to topic '{msg.topic()}'", key=msg.key().decode('utf-8'), partition=msg.partition(), offset=msg.offset())

    def produce(self, topic: str, key: str, value: dict):
        """
        Produces a message to the specified Kafka topic.

        Args:
            topic: The target Kafka topic.
            key: The message key (e.g., document_id).
            value: The message payload as a dictionary.
        """
        try:
            self.producer.produce(
                topic=topic,
                key=key.encode('utf-8'),
                value=json.dumps(value).encode('utf-8'),
                callback=self._delivery_report
            )
            # poll() es crucial para que se envíen los callbacks de entrega
            # y se procesen los mensajes en el buffer del productor.
            self.producer.poll(0)
        except BufferError:
            self.log.error(
                "Kafka producer's local queue is full. Messages may be dropped.",
                topic=topic
            )
            self.producer.flush() # Intenta forzar el envío
        except KafkaException as e:
            self.log.exception("Failed to produce message to Kafka", topic=topic, error=str(e))
            raise
        except Exception as e:
            self.log.exception("An unexpected error occurred in Kafka producer", topic=topic, error=str(e))
            raise
    
    def flush(self):
        """Waits for all outstanding messages to be delivered."""
        self.log.info("Flushing Kafka producer...")
        self.producer.flush()
        self.log.info("Kafka producer flushed.")
```

## File: `app\services\s3_client.py`
```py
# File: app/services/s3_client.py
import boto3
from botocore.config import Config
from botocore import UNSIGNED  # <-- CORRECCIÓN 1: Importar la constante correcta
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
        
        # Configurar boto3 para usar modo anónimo (sin firma de credenciales).
        # Esto es útil para interactuar con buckets S3 públicos o emuladores locales
        # como MinIO sin necesidad de credenciales de AWS.
        unsigned_config = Config(signature_version=UNSIGNED) # <-- CORRECCIÓN 2: Usar la constante en lugar del string
        self.s3_client = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            config=unsigned_config
        )

        self.log = log.bind(s3_bucket=self.bucket_name, aws_region=settings.AWS_REGION)

    async def upload_file_async(self, object_name: str, data: bytes, content_type: str) -> str:
        """Uploads a file to S3 asynchronously using an executor."""
        self.log.info("Uploading file to S3...", object_name=object_name, content_type=content_type)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
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
```

## File: `pyproject.toml`
```toml
# File: ingest-service/pyproject.toml
[tool.poetry]
name = "ingest-service"
version = "2.1.0"
description = "Ingest service for Atenex - Kafka Producer (Refactored for AWS, DB-less)"
authors = ["Atenex Team <dev@atenex.com>"]
readme = "README.md"
package-mode = false

[tool.poetry.dependencies]
python = ">=3.10,<3.13"
fastapi = "^0.110.0"
uvicorn = {extras = ["standard"], version = "^0.28.0"}
gunicorn = "^21.2.0"
pydantic = {extras = ["email"], version = "^2.6.4"}
pydantic-settings = "^2.2.1"
tenacity = "^8.2.3"
python-multipart = "^0.0.9"
structlog = "^24.1.0"
httpx = {extras = ["http2"], version = "^0.27.0"}

# AWS S3 Client
boto3 = "^1.34.0"

# Kafka Producer Client
confluent-kafka = "^2.4.0"


[tool.poetry.group.dev.dependencies]
pytest = "^7.4.4"
pytest-asyncio = "^0.21.1"

[build-system]
requires = ["poetry-core>=1.0.0" ]
build-backend = "poetry.core.masonry.api"
```
