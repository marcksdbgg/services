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
# CORRECCIÓN: Se simplifica la configuración de CORS para permitir todos los orígenes.
# Esto es más robusto para entornos de desarrollo con Vercel y Ngrok.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitir cualquier origen
    allow_credentials=True,
    allow_methods=["*"],  # Permitir todos los métodos (GET, POST, etc.)
    allow_headers=["*"],  # Permitir todas las cabeceras
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