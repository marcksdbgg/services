# File: app/core/config.py
import sys
import json
import logging
from typing import List, Optional
from pydantic import Field, field_validator, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env', env_prefix='DOCPROC_', env_file_encoding='utf-8',
        case_sensitive=False, extra='ignore'
    )

    PROJECT_NAME: str = "Atenex Document Processing Worker"
    LOG_LEVEL: str = "INFO"

    # --- Lógica de procesamiento (se mantiene) ---
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
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
    
    # --- Kafka (NUEVO) ---
    KAFKA_BOOTSTRAP_SERVERS: str = Field(description="Comma-separated list of Kafka bootstrap servers.")
    KAFKA_CONSUMER_GROUP_ID: str = Field(default="docproc_workers", description="Kafka consumer group ID.")
    KAFKA_INPUT_TOPIC: str = Field(default="documents.raw", description="Topic to consume raw document events from.")
    KAFKA_OUTPUT_TOPIC: str = Field(default="chunks.processed", description="Topic to produce processed chunks to.")
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"
    
    # --- AWS S3 (NUEVO) ---
    AWS_S3_BUCKET_NAME: str = Field(description="Name of the S3 bucket where original files are stored.")
    AWS_REGION: str = Field(default="us-east-1", description="AWS region for S3 client.")

    @field_validator("LOG_LEVEL")
    @classmethod
    def check_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        normalized_v = v.upper()
        if normalized_v not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL '{v}'. Must be one of {valid_levels}")
        return normalized_v

# Configuración básica de logging para la fase de carga
temp_log_config = logging.getLogger("docproc_service.config.loader")
if not temp_log_config.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(levelname)-8s [%(name)s] %(message)s')
    handler.setFormatter(formatter)
    temp_log_config.addHandler(handler)
    temp_log_config.setLevel(logging.INFO)

try:
    temp_log_config.info("Loading DocProc Worker settings...")
    settings = Settings()
    temp_log_config.info("--- DocProc Worker Settings Loaded ---")
    temp_log_config.info(f"  PROJECT_NAME: {settings.PROJECT_NAME}")
    temp_log_config.info(f"  LOG_LEVEL: {settings.LOG_LEVEL}")
    temp_log_config.info(f"  CHUNK_SIZE: {settings.CHUNK_SIZE}")
    temp_log_config.info(f"  AWS_S3_BUCKET_NAME: {settings.AWS_S3_BUCKET_NAME}")
    temp_log_config.info(f"  KAFKA_BOOTSTRAP_SERVERS: {settings.KAFKA_BOOTSTRAP_SERVERS}")
    temp_log_config.info(f"  KAFKA_INPUT_TOPIC: {settings.KAFKA_INPUT_TOPIC}")
    temp_log_config.info(f"  KAFKA_OUTPUT_TOPIC: {settings.KAFKA_OUTPUT_TOPIC}")
    temp_log_config.info("---------------------------------------------")

except ValidationError as e:
    temp_log_config.critical(f"FATAL: DocProc Worker configuration validation failed:\n{e}")
    sys.exit(1)