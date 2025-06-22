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