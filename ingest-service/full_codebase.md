# Estructura de la Codebase

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
├── db
│   ├── __init__.py
│   └── postgres_client.py
├── main.py
├── models
│   ├── __init__.py
│   └── domain.py
└── services
    ├── __init__.py
    ├── kafka_producer.py
    └── s3_client.py
```

# Codebase: `app`

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
# File: app/api/v1/endpoints/ingest.py
import uuid
import json
from typing import List, Optional, Dict, Any
import asyncio
from contextlib import asynccontextmanager

import structlog
import asyncpg
from fastapi import (
    APIRouter, Depends, HTTPException, status,
    UploadFile, File, Form, Request
)

from app.core.config import settings
from app.db import postgres_client as db_client
from app.models.domain import DocumentStatus
from app.api.v1.schemas import IngestResponse, StatusResponse
from app.services.s3_client import S3Client, S3ClientError
from app.services.kafka_producer import KafkaProducerClient

log = structlog.get_logger(__name__)
router = APIRouter()

# --- Dependencias ---

def get_s3_client():
    """Dependency para obtener el cliente S3."""
    try:
        return S3Client()
    except Exception as e:
        log.exception("Failed to initialize S3Client dependency.", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service (S3) configuration error."
        )

def get_kafka_producer(request: Request) -> KafkaProducerClient:
    """Dependency para obtener el productor de Kafka del estado de la app."""
    return request.app.state.kafka_producer

@asynccontextmanager
async def get_db_conn():
    """Context manager para obtener una conexión del pool de DB."""
    pool = await db_client.get_db_pool()
    conn = None
    try:
        conn = await pool.acquire()
        yield conn
    finally:
        if conn:
            await pool.release(conn)

def normalize_filename(filename: str) -> str:
    """Normaliza el nombre de archivo eliminando espacios extra."""
    return " ".join(filename.strip().split())


# --- Endpoints ---

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
    company_id = request.headers.get("X-Company-ID")
    req_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    endpoint_log = log.bind(request_id=req_id)

    if not company_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing X-Company-ID header.")
    
    try:
        company_uuid = uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Company ID format.")

    normalized_filename = normalize_filename(file.filename)
    endpoint_log = endpoint_log.bind(company_id=company_id, filename=normalized_filename)
    endpoint_log.info("Document upload request received.")

    metadata = {}
    if metadata_json:
        try:
            metadata = json.loads(metadata_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid metadata JSON format.")

    async with get_db_conn() as conn:
        existing_doc = await db_client.find_document_by_name_and_company(conn, normalized_filename, company_uuid)
        if existing_doc and existing_doc['status'] != DocumentStatus.ERROR.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Document '{normalized_filename}' already exists.")

    document_id = uuid.uuid4()
    s3_path = f"{company_id}/{document_id}/{normalized_filename}"

    async with get_db_conn() as conn:
        await db_client.create_document_record(
            conn, document_id, company_uuid, normalized_filename, file.content_type, s3_path, DocumentStatus.PENDING, metadata
        )

    try:
        file_content = await file.read()
        await s3_client.upload_file_async(s3_path, file_content, file.content_type)
        
        async with get_db_conn() as conn:
            await db_client.update_document_status(conn, document_id, DocumentStatus.UPLOADED)
        
        # Producir mensaje a Kafka
        kafka_payload = {"document_id": str(document_id), "company_id": company_id, "s3_path": s3_path}
        kafka_producer.produce(
            topic=settings.KAFKA_DOCUMENTS_RAW_TOPIC,
            key=str(document_id),
            value=kafka_payload
        )
        endpoint_log.info("Message produced to Kafka topic.", topic=settings.KAFKA_DOCUMENTS_RAW_TOPIC, key=str(document_id))

    except (S3ClientError, KafkaException, Exception) as e:
        error_message = f"Failed during S3 upload or Kafka production: {type(e).__name__}"
        endpoint_log.exception("Error after creating DB record", error=error_message)
        async with get_db_conn() as conn:
            await db_client.update_document_status(conn, document_id, DocumentStatus.ERROR, error_message)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_message)
    finally:
        await file.close()

    # El task_id ya no existe
    return IngestResponse(
        document_id=document_id,
        task_id="deprecated_kafka_pipeline",
        status=DocumentStatus.UPLOADED.value,
        message="Document uploaded and event sent to Kafka for processing."
    )


@router.get(
    "/status/{document_id}",
    response_model=StatusResponse,
    summary="Get the status of a specific document.",
)
async def get_document_status(
    request: Request,
    document_id: uuid.UUID,
):
    company_id = request.headers.get("X-Company-ID")
    if not company_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing X-Company-ID header.")
    try:
        company_uuid = uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Company ID format.")

    async with get_db_conn() as conn:
        doc_data = await db_client.get_document_by_id(conn, document_id, company_uuid)
    
    if not doc_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    
    return StatusResponse(**doc_data)


@router.get(
    "/status",
    response_model=List[StatusResponse],
    summary="List document statuses for a company.",
)
async def list_document_statuses(
    request: Request,
    limit: int = 30,
    offset: int = 0,
):
    company_id = request.headers.get("X-Company-ID")
    if not company_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing X-Company-ID header.")
    try:
        company_uuid = uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Company ID format.")

    async with get_db_conn() as conn:
        docs, _ = await db_client.list_documents_paginated(conn, company_uuid, limit, offset)
    
    return [StatusResponse(**doc) for doc in docs]
```

## File: `app\api\v1\schemas.py`
```py
# ingest-service/app/api/v1/schemas.py
import uuid
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from app.models.domain import DocumentStatus
from datetime import datetime, date # Asegurar que date está importado
import json
import logging

log = logging.getLogger(__name__)

class ErrorDetail(BaseModel):
    """Schema for error details in responses."""
    detail: str

class IngestResponse(BaseModel):
    document_id: uuid.UUID
    task_id: str
    status: str
    message: str = "Document upload received and queued for processing."

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "123e4567-e89b-12d3-a456-426614174000",
                "task_id": "c79ba436-fe88-4b82-9afc-44b1091564e4",
                "status": DocumentStatus.UPLOADED.value,
                "message": "Document upload accepted, processing started."
            }
        }

class StatusResponse(BaseModel):
    document_id: uuid.UUID = Field(..., alias="id")
    company_id: Optional[uuid.UUID] = None
    file_name: str
    file_type: str
    file_path: Optional[str] = Field(None, description="Path to the original file in GCS.")
    metadata: Optional[Dict[str, Any]] = None
    status: str
    chunk_count: Optional[int] = 0
    error_message: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    gcs_exists: Optional[bool] = Field(None, description="Indicates if the original file currently exists in GCS.")
    milvus_chunk_count: Optional[int] = Field(None, description="Live count of chunks found in Milvus for this document (-1 if check failed).")
    message: Optional[str] = None

    @field_validator('metadata', mode='before')
    @classmethod
    def metadata_to_dict(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                log.warning("Invalid metadata JSON found in DB record", raw_metadata=v)
                return {"error": "invalid metadata JSON in DB"}
        return v if v is None or isinstance(v, dict) else {}

    class Config:
        validate_assignment = True
        populate_by_name = True
        json_schema_extra = {
             "example": {
                "id": "52ad2ba8-cab9-4108-a504-b9822fe99bdc",
                "company_id": "51a66c8f-f6b1-43bd-8038-8768471a8b09",
                "file_name": "Anexo-00-Modificaciones-de-la-Guia-5.1.0.pdf",
                "file_type": "application/pdf",
                "file_path": "51a66c8f-f6b1-43bd-8038-8768471a8b09/52ad2ba8-cab9-4108-a504-b9822fe99bdc/Anexo-00-Modificaciones-de-la-Guia-5.1.0.pdf",
                "metadata": {"source": "manual upload", "version": "1.1"},
                "status": DocumentStatus.ERROR.value,
                "chunk_count": 0,
                "error_message": "Processing timed out after 600 seconds.",
                "uploaded_at": "2025-04-19T19:42:38.671016Z",
                "updated_at": "2025-04-19T19:42:42.337854Z",
                "gcs_exists": True,
                "milvus_chunk_count": 0,
                "message": "El procesamiento falló: Timeout."
            }
        }

class PaginatedStatusResponse(BaseModel):
    """Schema for paginated list of document statuses."""
    items: List[StatusResponse] = Field(..., description="List of document status objects on the current page.")
    total: int = Field(..., description="Total number of documents matching the query.")
    limit: int = Field(..., description="Number of items requested per page.")
    offset: int = Field(..., description="Number of items skipped for pagination.")

    class Config:
        json_schema_extra = {
            "example": {
                "items": [
                     {
                        "id": "52ad2ba8-cab9-4108-a504-b9822fe99bdc",
                        "company_id": "51a66c8f-f6b1-43bd-8038-8768471a8b09",
                        "file_name": "Anexo-00-Modificaciones-de-la-Guia-5.1.0.pdf",
                        "file_type": "application/pdf",
                        "file_path": "51a66c8f-f6b1-43bd-8038-8768471a8b09/52ad2ba8-cab9-4108-a504-b9822fe99bdc/Anexo-00-Modificaciones-de-la-Guia-5.1.0.pdf",
                        "metadata": {"source": "manual upload", "version": "1.1"},
                        "status": DocumentStatus.ERROR.value,
                        "chunk_count": 0,
                        "error_message": "Processing timed out after 600 seconds.",
                        "uploaded_at": "2025-04-19T19:42:38.671016Z",
                        "updated_at": "2025-04-19T19:42:42.337854Z",
                        "gcs_exists": True,
                        "milvus_chunk_count": 0,
                        "message": "El procesamiento falló: Timeout."
                    }
                ],
                "total": 1,
                "limit": 30,
                "offset": 0
            }
        }

# --- NUEVOS SCHEMAS PARA ESTADÍSTICAS DE DOCUMENTOS ---
class DocumentStatsByStatus(BaseModel):
    processed: int = 0
    processing: int = 0
    uploaded: int = 0
    error: int = 0
    pending: int = 0 # Añadir pending ya que es un DocumentStatus

class DocumentStatsByType(BaseModel):
    pdf: int = Field(0, alias="application/pdf")
    docx: int = Field(0, alias="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    doc: int = Field(0, alias="application/msword")
    txt: int = Field(0, alias="text/plain")
    md: int = Field(0, alias="text/markdown")
    html: int = Field(0, alias="text/html")
    other: int = 0

    class Config:
        populate_by_name = True


class DocumentStatsByUser(BaseModel):
    # Esta parte es más compleja de implementar en ingest-service si no tiene acceso a la tabla de users
    # Por ahora, la definición del schema está aquí, pero su implementación podría ser básica o diferida.
    user_id: str # Podría ser UUID del user que subió el doc, pero no está en la tabla 'documents'
    name: Optional[str] = None
    count: int

class DocumentRecentActivity(BaseModel):
    # Similar, agrupar por fecha y estado es una query más compleja.
    # Definición aquí, implementación podría ser básica.
    date: date
    uploaded: int = 0
    processing: int = 0
    processed: int = 0
    error: int = 0
    pending: int = 0

class DocumentStatsResponse(BaseModel):
    total_documents: int
    total_chunks_processed: int # Suma de chunk_count para documentos en estado 'processed'
    by_status: DocumentStatsByStatus
    by_type: DocumentStatsByType
    # by_user: List[DocumentStatsByUser] # Omitir por ahora para simplificar
    # recent_activity: List[DocumentRecentActivity] # Omitir por ahora para simplificar
    oldest_document_date: Optional[datetime] = None
    newest_document_date: Optional[datetime] = None

    model_config = { # Anteriormente Config
        "from_attributes": True # Anteriormente orm_mode
    }
```

## File: `app\core\__init__.py`
```py

```

## File: `app\core\config.py`
```py
# File: app/core/config.py
import os
import sys
import logging
from typing import Optional, List
from pydantic import Field, field_validator, SecretStr, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_prefix='INGEST_',
        case_sensitive=False,
        env_file_encoding='utf-8',
        extra='ignore'
    )

    PROJECT_NAME: str = "Atenex Ingest Service (Kafka Producer)"
    API_V1_STR: str = "/api/v1/ingest"
    LOG_LEVEL: str = "INFO"

    # --- PostgreSQL (se mantiene para metadatos del documento) ---
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_SERVER: str = "postgresql.nyro-develop.svc.cluster.local"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "atenex"

    # --- AWS S3 (reemplaza GCS) ---
    AWS_S3_BUCKET_NAME: str = Field(description="Name of the S3 bucket for storing original files.")
    AWS_REGION: str = Field(default="us-east-1", description="AWS region for S3 client.")

    # --- Kafka Producer ---
    KAFKA_BOOTSTRAP_SERVERS: str = Field(description="Comma-separated list of Kafka bootstrap servers.")
    KAFKA_DOCUMENTS_RAW_TOPIC: str = Field(default="documents.raw", description="Kafka topic for new raw documents.")
    KAFKA_PRODUCER_ACKS: str = "all"
    KAFKA_PRODUCER_LINGER_MS: int = 10
    
    SUPPORTED_CONTENT_TYPES: List[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "text/plain",
        "text/markdown",
        "text/html",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ]

    @field_validator('LOG_LEVEL')
    @classmethod
    def check_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL '{v}'. Must be one of {valid_levels}")
        return v.upper()

    @field_validator('POSTGRES_PASSWORD', 'AWS_S3_BUCKET_NAME', 'KAFKA_BOOTSTRAP_SERVERS', mode='before')
    @classmethod
    def check_required_fields(cls, v: Optional[str], info) -> str:
        if not v:
            raise ValueError(f"Required environment variable for '{info.field_name}' is not set.")
        return v

temp_log = logging.getLogger("ingest_service.config.loader")
# Basic setup for config loading phase
if not temp_log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    temp_log.addHandler(handler)
    temp_log.setLevel(logging.INFO)

try:
    temp_log.info("Loading Ingest Service settings for Kafka Producer...")
    settings = Settings()
    temp_log.info("--- Ingest Service Settings Loaded ---")
    temp_log.info(f"  PROJECT_NAME: {settings.PROJECT_NAME}")
    temp_log.info(f"  LOG_LEVEL: {settings.LOG_LEVEL}")
    temp_log.info(f"  POSTGRES_SERVER: {settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}")
    temp_log.info(f"  AWS_S3_BUCKET_NAME: {settings.AWS_S3_BUCKET_NAME}")
    temp_log.info(f"  KAFKA_BOOTSTRAP_SERVERS: {settings.KAFKA_BOOTSTRAP_SERVERS}")
    temp_log.info(f"  KAFKA_DOCUMENTS_RAW_TOPIC: {settings.KAFKA_DOCUMENTS_RAW_TOPIC}")
    temp_log.info("--------------------------------------")
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

## File: `app\db\__init__.py`
```py

```

## File: `app\db\postgres_client.py`
```py
# File: app/db/postgres_client.py
import uuid
from typing import Any, Optional, Dict, List, Tuple
import asyncpg
import structlog
import json

from app.core.config import settings
from app.models.domain import DocumentStatus

log = structlog.get_logger(__name__)

# --- Pool de Conexiones Asíncronas (para la API) ---
_pool: Optional[asyncpg.Pool] = None

# --- Gestión del Pool Asíncrono ---
async def get_db_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None or _pool._closed:
        log.info("Creating PostgreSQL async connection pool...")
        try:
            _pool = await asyncpg.create_pool(
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD.get_secret_value(),
                database=settings.POSTGRES_DB,
                host=settings.POSTGRES_SERVER,
                port=settings.POSTGRES_PORT,
                min_size=2,
                max_size=10,
            )
            log.info("PostgreSQL async connection pool created.")
        except Exception as e:
            log.critical("Failed to create PostgreSQL async pool", error=str(e))
            raise ConnectionError("Could not connect to the database.") from e
    return _pool

async def close_db_pool():
    global _pool
    if _pool:
        log.info("Closing PostgreSQL async connection pool.")
        await _pool.close()
        _pool = None

async def check_db_connection() -> bool:
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT 1") == 1
    except Exception:
        return False

# --- Operaciones Asíncronas con la Base de Datos ---

async def create_document_record(conn: asyncpg.Connection, doc_id: uuid.UUID, company_id: uuid.UUID, filename: str, file_type: str, file_path: str, status: DocumentStatus, metadata: Optional[Dict[str, Any]] = None) -> None:
    query = """
    INSERT INTO documents (id, company_id, file_name, file_type, file_path, metadata, status, uploaded_at, updated_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC');
    """
    await conn.execute(query, doc_id, company_id, filename, file_type, file_path, json.dumps(metadata) if metadata else None, status.value)

async def find_document_by_name_and_company(conn: asyncpg.Connection, filename: str, company_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    query = "SELECT id, status FROM documents WHERE file_name = $1 AND company_id = $2;"
    record = await conn.fetchrow(query, filename, company_id)
    return dict(record) if record else None

async def update_document_status(conn: asyncpg.Connection, document_id: uuid.UUID, status: DocumentStatus, error_message: Optional[str] = None) -> bool:
    set_clauses = ["status = $2", "updated_at = NOW() AT TIME ZONE 'UTC'"]
    params = [document_id, status.value]
    if status == DocumentStatus.ERROR:
        set_clauses.append("error_message = $3")
        params.append(error_message)
    query = f"UPDATE documents SET {', '.join(set_clauses)} WHERE id = $1;"
    result = await conn.execute(query, *params)
    return result == 'UPDATE 1'

async def get_document_by_id(conn: asyncpg.Connection, doc_id: uuid.UUID, company_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM documents WHERE id = $1 AND company_id = $2;"
    record = await conn.fetchrow(query, doc_id, company_id)
    return dict(record) if record else None

async def list_documents_paginated(conn: asyncpg.Connection, company_id: uuid.UUID, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    query = "SELECT *, COUNT(*) OVER() AS total_count FROM documents WHERE company_id = $1 ORDER BY updated_at DESC LIMIT $2 OFFSET $3;"
    rows = await conn.fetch(query, company_id, limit, offset)
    if not rows:
        return [], 0
    total = rows[0]['total_count']
    results = [dict(r) for r in rows]
    return results, total

async def delete_document(conn: asyncpg.Connection, doc_id: uuid.UUID, company_id: uuid.UUID) -> bool:
    # Ahora la tabla de chunks no existe, así que el ON DELETE CASCADE no aplica aquí
    query = "DELETE FROM documents WHERE id = $1 AND company_id = $2;"
    result = await conn.execute(query, doc_id, company_id)
    return result == 'DELETE 1'
```

## File: `app\main.py`
```py
# File: app/main.py
import time
import uuid
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status as fastapi_status
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.logging_config import setup_logging
setup_logging()

from app.core.config import settings
from app.db import postgres_client
from app.api.v1.endpoints import ingest
from app.services.kafka_producer import KafkaProducerClient

log = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Ingest Service startup sequence initiated...")
    app.state.kafka_producer = KafkaProducerClient()
    await postgres_client.get_db_pool() # Inicializa el pool de la DB
    log.info("Dependencies (DB Pool, Kafka Producer) initialized.")
    yield
    log.info("Ingest Service shutdown sequence initiated...")
    app.state.kafka_producer.flush()
    await postgres_client.close_db_pool()
    log.info("Shutdown sequence complete.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    version="2.0.0-refactor",
    description="Atenex Ingest Service (Refactored to be a Kafka Producer).",
    lifespan=lifespan,
)

@app.middleware("http")
async def add_request_context(request: Request, call_next):
    start_time = time.perf_counter()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    process_time = (time.perf_counter() - start_time) * 1000
    log.info(
        "Request processed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(process_time, 2)
    )
    return response

app.include_router(ingest.router, prefix=settings.API_V1_STR, tags=["Ingestion"])

@app.get("/health", tags=["Health Check"])
async def health_check():
    db_ok = await postgres_client.check_db_connection()
    if db_ok:
        return {"status": "healthy", "database": "ok"}
    else:
        return JSONResponse(
            status_code=fastapi_status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "error"}
        )
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
```

## File: `pyproject.toml`
```toml
# File: pyproject.toml
[tool.poetry]
name = "ingest-service"
version = "2.0.0-refactor"
description = "Ingest service for Atenex - Kafka Producer (Refactored for AWS)"
authors = ["Atenex Team <dev@atenex.com>"]
readme = "README.md"

[tool.poetry.dependencies]
python = ">=3.10,<3.13"
fastapi = "^0.110.0"
uvicorn = {extras = ["standard"], version = "^0.28.0"}
gunicorn = "^21.2.0"
pydantic = {extras = ["email"], version = "^2.6.4"}
pydantic-settings = "^2.2.1"
asyncpg = "^0.29.0"
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
