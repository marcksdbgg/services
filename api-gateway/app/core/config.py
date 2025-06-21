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