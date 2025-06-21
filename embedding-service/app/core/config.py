# File: embedding-service/app/core/config.py
import sys
import logging
from typing import Optional
from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_prefix='EMBEDDING_',
        case_sensitive=False,
        env_file_encoding='utf-8',
        extra='ignore'
    )

    PROJECT_NAME: str = "Atenex Embedding Worker (OpenAI)"
    LOG_LEVEL: str = "INFO"

    # --- OpenAI Embedding Model ---
    OPENAI_API_KEY: SecretStr = Field(description="Your OpenAI API Key.")
    OPENAI_EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536
    OPENAI_TIMEOUT_SECONDS: int = 30
    OPENAI_MAX_RETRIES: int = 3
    
    # --- Kafka ---
    KAFKA_BOOTSTRAP_SERVERS: str = Field(description="Comma-separated list of Kafka bootstrap servers.")
    KAFKA_CONSUMER_GROUP_ID: str = Field(default="embedding_workers", description="Kafka consumer group ID.")
    KAFKA_INPUT_TOPIC: str = Field(default="chunks.processed", description="Topic to consume processed chunks from.")
    KAFKA_OUTPUT_TOPIC: str = Field(default="embeddings.ready", description="Topic to produce ready embeddings to.")
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"

    @field_validator('LOG_LEVEL')
    @classmethod
    def check_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL '{v}'. Must be one of {valid_levels}")
        return v.upper()

temp_log = logging.getLogger("embedding_service.config.loader")
if not temp_log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    temp_log.addHandler(handler)
    temp_log.setLevel(logging.INFO)

try:
    temp_log.info("Loading Embedding Worker settings...")
    settings = Settings()
    temp_log.info("--- Embedding Worker Settings Loaded ---")
    temp_log.info(f"  PROJECT_NAME: {settings.PROJECT_NAME}")
    temp_log.info(f"  LOG_LEVEL: {settings.LOG_LEVEL}")
    temp_log.info(f"  KAFKA_BOOTSTRAP_SERVERS: {settings.KAFKA_BOOTSTRAP_SERVERS}")
    temp_log.info("----------------------------------------")
except Exception as e:
    temp_log.critical(f"FATAL: Error loading Embedding Worker settings: {e}")
    sys.exit("FATAL: Invalid configuration. Check logs.")