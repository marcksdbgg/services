# Estructura de la Codebase del Microservicio api-gateway

```
app/
├── __init__.py
├── core
│   ├── __init__.py
│   ├── config.py
│   └── logging_config.py
├── main.py
├── routers
│   ├── __init__.py
│   └── gateway_router.py
└── utils
```

# Codebase del Microservicio api-gateway: `app`

## File: `app\__init__.py`
```py
# ...existing code or leave empty...

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
from typing import Optional
from pydantic import Field, field_validator, ValidationError, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# URL por defecto del servicio de ingesta en un entorno de clúster
K8S_INGEST_SVC_URL_DEFAULT = "http://ingest-api-service.nyro-develop.svc.cluster.local:80"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_prefix='GATEWAY_',
        case_sensitive=False,
        env_file_encoding='utf-8',
        extra='ignore'
    )

    PROJECT_NAME: str = "Atenex API Gateway (Simplified)"
    API_V1_STR: str = "/api/v1"

    # URL del único servicio backend al que se hará proxy
    INGEST_SERVICE_URL: HttpUrl = Field(default=K8S_INGEST_SVC_URL_DEFAULT)

    # Configuración General
    LOG_LEVEL: str = "INFO"
    HTTP_CLIENT_TIMEOUT: int = 60
    HTTP_CLIENT_MAX_KEEPALIVE_CONNECTIONS: int = 100
    HTTP_CLIENT_MAX_CONNECTIONS: int = 200

    # CORS
    VERCEL_FRONTEND_URL: Optional[str] = None # Ejemplo: "https://tu-frontend.vercel.app"

    @field_validator('LOG_LEVEL')
    @classmethod
    def check_log_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        normalized_v = v.upper()
        if normalized_v not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL '{v}'. Must be one of {valid_levels}")
        return normalized_v

@lru_cache()
def get_settings() -> Settings:
    temp_log = logging.getLogger("atenex_api_gateway.config.loader")
    if not temp_log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        temp_log.addHandler(handler)
        temp_log.setLevel(logging.INFO)

    temp_log.info("Loading Simplified Gateway settings...")
    try:
        settings_instance = Settings()
        temp_log.info("--- Simplified Gateway Settings Loaded ---")
        temp_log.info(f"  PROJECT_NAME: {settings_instance.PROJECT_NAME}")
        temp_log.info(f"  INGEST_SERVICE_URL: {str(settings_instance.INGEST_SERVICE_URL)}")
        temp_log.info(f"  LOG_LEVEL: {settings_instance.LOG_LEVEL}")
        temp_log.info(f"  HTTP_CLIENT_TIMEOUT: {settings_instance.HTTP_CLIENT_TIMEOUT}")
        temp_log.info("------------------------------------------")
        return settings_instance
    except ValidationError as e:
        temp_log.critical("! FATAL: Error validating Gateway settings: %s", e)
        sys.exit("FATAL: Invalid Gateway configuration. Check logs.")

settings = get_settings()
```

## File: `app\core\logging_config.py`
```py
# File: app/core/logging_config.py
import logging
import sys
import structlog
from app.core.config import settings

def setup_logging():
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.LOG_LEVEL.upper() == "DEBUG":
        shared_processors.append(structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ))

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()

    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)

    try:
        root_logger.setLevel(settings.LOG_LEVEL.upper())
    except ValueError:
        root_logger.setLevel(logging.INFO)
        logging.warning(f"Invalid LOG_LEVEL '{settings.LOG_LEVEL}'. Defaulting to INFO.")

    # Silenciar librerías verbosas
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("gunicorn.error").setLevel(logging.INFO)
    logging.getLogger("gunicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    log = structlog.get_logger("api_gateway.config")
    log.info("Structlog logging configured", log_level=settings.LOG_LEVEL.upper())
```

## File: `app\main.py`
```py
# File: app/main.py
import os
import time
import uuid
import structlog
import httpx
from contextlib import asynccontextmanager
from typing import Optional, Set
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

# --- Setup Logging First ---
from app.core.logging_config import setup_logging
setup_logging()

from app.core.config import settings
from app.routers.gateway_router import router as gateway_router

log = structlog.get_logger(__name__)

# --- Lifespan Manager (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Simplified Gateway: Initializing HTTPX client...")
    try:
        limits = httpx.Limits(
            max_keepalive_connections=settings.HTTP_CLIENT_MAX_KEEPALIVE_CONNECTIONS,
            max_connections=settings.HTTP_CLIENT_MAX_CONNECTIONS
        )
        timeout = httpx.Timeout(settings.HTTP_CLIENT_TIMEOUT, connect=15.0)
        app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
        log.info("HTTPX client initialized successfully.")
    except Exception as e:
        log.exception("CRITICAL: Failed to initialize HTTPX client!", error=str(e))
        app.state.http_client = None

    yield

    log.info("Simplified Gateway: Shutting down...")
    client = getattr(app.state, 'http_client', None)
    if client and not client.is_closed:
        await client.aclose()
        log.info("HTTPX client closed.")
    log.info("Shutdown complete.")

# --- FastAPI App Instance ---
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="A simple API Gateway to proxy requests for the Atenex platform demo.",
    version="2.0.0-refactor",
    lifespan=lifespan,
)

# --- Middlewares ---
allowed_origins_set: Set[str] = {
    "http://localhost:3000", # Frontend dev
    "http://127.0.0.1:3000",
}
if settings.VERCEL_FRONTEND_URL:
    allowed_origins_set.add(settings.VERCEL_FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins_set),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time"],
)

@app.middleware("http")
async def request_context_timing_logging(request: Request, call_next):
    start_time = time.perf_counter()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    
    request_log = log.bind(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown"
    )
    request_log.info("Request received")
    
    try:
        response = await call_next(request)
        process_time = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
        request_log.info("Request completed", status_code=response.status_code, duration_ms=round(process_time, 2))
        return response
    except Exception as e:
        process_time = (time.perf_counter() - start_time) * 1000
        request_log.exception("Unhandled exception during request", duration_ms=round(process_time, 2))
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

# --- Router Inclusion ---
app.include_router(gateway_router, prefix=settings.API_V1_STR)
log.info(f"Gateway router included with prefix: {settings.API_V1_STR}")

# --- Root & Health Endpoints ---
@app.get("/", tags=["General"], include_in_schema=False)
async def read_root():
    return JSONResponse({"message": f"{settings.PROJECT_NAME} is running!"})

@app.get("/health", tags=["Health"], summary="Health check endpoint")
async def health_check(request: Request):
    http_client = getattr(request.app.state, 'http_client', None)
    http_client_ok = http_client is not None and not http_client.is_closed
    
    if http_client_ok:
        return JSONResponse({"status": "healthy", "service": settings.PROJECT_NAME})
    else:
        log.error("Health check failed: HTTP client not available.")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "service": settings.PROJECT_NAME, "detail": "HTTP client is not available."}
        )

# --- Main Execution ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        log_level=settings.LOG_LEVEL.lower()
    )
```

## File: `app\routers\__init__.py`
```py

```

## File: `app\routers\gateway_router.py`
```py
# File: app/routers/gateway_router.py
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status, Path
from fastapi.responses import StreamingResponse
import httpx
import structlog
import uuid
from typing import Optional

from app.core.config import settings

log = structlog.get_logger(__name__)
router = APIRouter()

# Cabeceras que no deben ser reenviadas en un proxy
HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-encoding", "content-length"
}

def get_http_client(request: Request) -> httpx.AsyncClient:
    """Dependencia para obtener el cliente HTTP del estado de la aplicación."""
    client = getattr(request.app.state, "http_client", None)
    if client is None or client.is_closed:
        log.error("HTTP client dependency failed: Client not available or closed.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gateway service is unavailable.")
    return client

async def _proxy_request(
    request: Request,
    target_service_base_url: str,
    backend_path: str,
):
    """Función de proxy genérica para reenviar solicitudes."""
    client = get_http_client(request)
    method = request.method
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    
    proxy_log = log.bind(
        request_id=request_id,
        method=method,
        original_path=request.url.path,
        target_service=target_service_base_url,
        target_path=backend_path
    )
    proxy_log.info("Initiating proxy request")

    target_url = httpx.URL(target_service_base_url).join(backend_path)
    target_url = target_url.copy_with(query=request.url.query.encode("utf-8"))

    headers_to_forward = {
        name: value for name, value in request.headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS
    }
    headers_to_forward["X-Request-ID"] = request_id
    
    # El `company_id` se pasa transparente, no se valida ni se inyecta desde un token.
    # Si el cliente lo envía, se reenvía.
    company_id = request.headers.get("x-company-id")
    if company_id:
        proxy_log = proxy_log.bind(company_id=company_id)
        # La cabecera ya está en `headers_to_forward`
    
    request_body_bytes: Optional[bytes] = await request.body()

    try:
        proxy_log.debug(f"Sending request to {target_url}")
        backend_req = client.build_request(
            method=method,
            url=target_url,
            headers=headers_to_forward,
            content=request_body_bytes,
            timeout=settings.HTTP_CLIENT_TIMEOUT,
        )
        backend_resp = await client.send(backend_req, stream=True)
        proxy_log.info("Received response from backend", status_code=backend_resp.status_code)

        response_headers = {
            name: value for name, value in backend_resp.headers.items()
            if name.lower() not in HOP_BY_HOP_HEADERS
        }

        return StreamingResponse(
            backend_resp.aiter_raw(),
            status_code=backend_resp.status_code,
            headers=response_headers,
            media_type=backend_resp.headers.get("content-type"),
            background=backend_resp.aclose
        )
    except httpx.ConnectError as e:
        proxy_log.error(f"Connection error to backend service: {target_url}", error=str(e))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Upstream service is unavailable.")
    except httpx.TimeoutException as e:
        proxy_log.error(f"Timeout connecting to backend service: {target_url}", error=str(e))
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Upstream service timed out.")
    except Exception as e:
        proxy_log.exception(f"Unexpected error during proxy request to {target_url}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected gateway error occurred.")


@router.api_route(
    "/ingest/{endpoint_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    tags=["Proxy - Ingest Service"],
    summary="Generic proxy for all Ingest Service endpoints",
    include_in_schema=False
)
async def proxy_ingest_service_generic(
    request: Request,
    endpoint_path: str = Path(...),
):
    """
    Este endpoint genérico captura todas las solicitudes a `/api/v1/ingest/*`
    y las reenvía al Ingest Service.
    """
    # Construye la ruta completa para el servicio de ingesta.
    # El settings.API_V1_STR del ingest-service es '/api/v1/ingest'
    backend_path = f"{settings.API_V1_STR}/{endpoint_path}"
    return await _proxy_request(
        request=request,
        target_service_base_url=str(settings.INGEST_SERVICE_URL),
        backend_path=backend_path
    )
```

## File: `pyproject.toml`
```toml
# File: pyproject.toml
[tool.poetry]
name = "atenex-api-gateway"
version = "2.0.0-refactor"
description = "Atenex API Gateway (Simplified Proxy for Kafka/Flink Demo)"
authors = ["Atenex Team <dev@atenex.com>"]
readme = "README.md"

[tool.poetry.dependencies]
python = "^3.10"

# Core FastAPI y servidor ASGI
fastapi = "^0.110.0"
uvicorn = {extras = ["standard"], version = "^0.28.0"}
gunicorn = "^21.2.0"

# Configuración y validación
pydantic = {extras = ["email"], version = "^2.6.4"}
pydantic-settings = "^2.2.1"

# Cliente HTTP asíncrono
httpx = {extras = ["http2"], version = "^0.27.0"}

# Logging estructurado
structlog = "^24.1.0"

# Dependencia necesaria para httpx[http2]
h2 = "^4.1.0"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.4"
pytest-asyncio = "^0.21.1"
pytest-httpx = "^0.29.0"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```
