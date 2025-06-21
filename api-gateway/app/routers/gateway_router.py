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