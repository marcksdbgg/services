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