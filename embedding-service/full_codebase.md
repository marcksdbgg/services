# Estructura de la Codebase del Microservicio embedding-service

```
app/
├── __init__.py
├── api
│   └── v1
│       ├── __init__.py
│       └── schemas.py
├── application
│   ├── __init__.py
│   ├── ports
│   │   ├── __init__.py
│   │   └── embedding_model_port.py
│   └── use_cases
│       ├── __init__.py
│       └── embed_texts_use_case.py
├── core
│   ├── __init__.py
│   ├── config.py
│   ├── logging_config.py
│   └── metrics.py
├── domain
│   ├── __init__.py
│   └── models.py
├── infrastructure
│   ├── __init__.py
│   └── embedding_models
│       ├── __init__.py
│       ├── fastembed_adapter.py
│       └── openai_adapter.py
├── main.py
└── services
    ├── __init__.py
    └── kafka_clients.py
```

# Codebase del Microservicio embedding-service: `app`

## File: `app\__init__.py`
```py

```

## File: `app\api\v1\__init__.py`
```py

```

## File: `app\api\v1\schemas.py`
```py
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class ModelInfo(BaseModel):
    """
    Información básica sobre el modelo de embeddings que se está utilizando.
    - Se acepta tanto `name` como `model_name` gracias al alias.
    - Se permiten campos adicionales (p. ej. `dimension`) para no
      romper la compatibilidad con adaptadores que devuelvan
      metadatos extra.
    """
    # Alias para que los adaptadores puedan seguir devolviendo `model_name`
    name: str = Field(alias="model_name")

    version: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None

    # Metadatos adicionales habituales
    dimension: Optional[int] = None

    # Configuración del modelo
    model_config = ConfigDict(
        populate_by_name=True,  # Permite acceder con .name aunque entre model_name
        extra="allow",          # Ignora / conserva cualquier campo adicional
    )

```

## File: `app\application\__init__.py`
```py

```

## File: `app\application\ports\__init__.py`
```py
# embedding-service/app/application/ports/__init__.py
from .embedding_model_port import EmbeddingModelPort

__all__ = ["EmbeddingModelPort"]
```

## File: `app\application\ports\embedding_model_port.py`
```py
# embedding-service/app/application/ports/embedding_model_port.py
import abc
from typing import List, Tuple, Dict, Any

class EmbeddingModelPort(abc.ABC):
    """
    Abstract port defining the interface for an embedding model.
    """

    @abc.abstractmethod
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Generates embeddings for a list of texts.

        Args:
            texts: A list of strings to embed.

        Returns:
            A list of embeddings, where each embedding is a list of floats.

        Raises:
            Exception: If embedding generation fails.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """
        Returns information about the loaded embedding model.

        Returns:
            A dictionary containing model_name, dimension, etc.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def health_check(self) -> Tuple[bool, str]:
        """
        Checks the health of the embedding model.

        Returns:
            A tuple (is_healthy: bool, status_message: str).
        """
        raise NotImplementedError
```

## File: `app\application\use_cases\__init__.py`
```py

```

## File: `app\application\use_cases\embed_texts_use_case.py`
```py
# embedding-service/app/application/use_cases/embed_texts_use_case.py
import structlog
from typing import List, Tuple, Dict, Any

from app.application.ports.embedding_model_port import EmbeddingModelPort
from app.api.v1.schemas import ModelInfo # For response structure

log = structlog.get_logger(__name__)

class EmbedTextsUseCase:
    """
    Use case for generating embeddings for a list of texts.
    """
    def __init__(self, embedding_model: EmbeddingModelPort):
        self.embedding_model = embedding_model
        log.info("EmbedTextsUseCase initialized", model_adapter=type(embedding_model).__name__)

    async def execute(self, texts: List[str]) -> Tuple[List[List[float]], ModelInfo]:
        """
        Executes the embedding generation process.

        Args:
            texts: A list of strings to embed.

        Returns:
            A tuple containing:
                - A list of embeddings (list of lists of floats).
                - ModelInfo object containing details about the embedding model.

        Raises:
            ValueError: If no texts are provided.
            Exception: If embedding generation fails.
        """
        if not texts:
            log.warning("EmbedTextsUseCase executed with no texts.")
            # Return empty list and model info, consistent with schema
            model_info_dict = self.embedding_model.get_model_info()
            return [], ModelInfo(**model_info_dict)


        use_case_log = log.bind(num_texts=len(texts))
        use_case_log.info("Executing embedding generation for texts")

        try:
            embeddings = await self.embedding_model.embed_texts(texts)
            model_info_dict = self.embedding_model.get_model_info()
            model_info_obj = ModelInfo(**model_info_dict)

            use_case_log.info("Successfully generated embeddings", num_embeddings=len(embeddings))
            return embeddings, model_info_obj
        except Exception as e:
            use_case_log.exception("Failed to generate embeddings in use case")
            # Re-raise to be handled by the endpoint or a global exception handler
            raise
```

## File: `app\core\__init__.py`
```py

```

## File: `app\core\config.py`
```py
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
    OPENAI_API_BASE: Optional[str] = Field(default=None, description="Optional override for the OpenAI API base URL.")
    OPENAI_EMBEDDING_DIMENSIONS_OVERRIDE: Optional[int] = Field(default=None, description="Optional override for embedding dimensions (for newer OpenAI models).")

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
```

## File: `app\core\logging_config.py`
```py
# embedding-service/app/core/logging_config.py
import logging
import sys
import structlog
from app.core.config import settings # Ensures settings are loaded first

def setup_logging():
    """Configures structured logging with structlog for the Embedding Service."""

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.LOG_LEVEL == "DEBUG":
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
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Avoid adding handler multiple times if already configured
    if not any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, structlog.stdlib.ProcessorFormatter) for h in root_logger.handlers):
        root_logger.addHandler(handler)

    root_logger.setLevel(settings.LOG_LEVEL.upper())

    # Silence verbose libraries that might be used by FastEmbed or its dependencies
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.INFO)
    # Add others as needed

    log = structlog.get_logger("embedding_service")
    log.info("Logging configured for Embedding Service", log_level=settings.LOG_LEVEL)
```

## File: `app\core\metrics.py`
```py
# File: embedding-service/app/core/metrics.py
from prometheus_client import Counter, Histogram

MESSAGES_CONSUMED_TOTAL = Counter(
    "embedding_messages_consumed_total",
    "Total number of Kafka messages consumed from a batch.",
    ["topic", "partition"]
)

BATCH_PROCESSING_DURATION_SECONDS = Histogram(
    "embedding_batch_processing_duration_seconds",
    "Time taken to process a batch of texts.",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30]
)

TEXTS_PROCESSED_TOTAL = Counter(
    "embedding_texts_processed_total",
    "Total number of individual texts processed for embedding.",
    ["company_id"]
)

OPENAI_API_DURATION_SECONDS = Histogram(
    "embedding_openai_api_duration_seconds",
    "Duration of calls to the OpenAI Embedding API.",
    ["model_name"]
)

OPENAI_API_ERRORS_TOTAL = Counter(
    "embedding_openai_api_errors_total",
    "Total number of errors from the OpenAI API.",
    ["model_name", "error_type"]
)

KAFKA_MESSAGES_PRODUCED_TOTAL = Counter(
    "embedding_kafka_messages_produced_total",
    "Total number of embedding messages produced to Kafka.",
    ["topic", "status"]
)
```

## File: `app\domain\__init__.py`
```py
# Domain package for embedding-service

```

## File: `app\domain\models.py`
```py
# embedding-service/app/domain/models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# Currently, requests and responses are simple enough to be handled by API schemas.
# This file is a placeholder if more complex domain logic/entities arise.

# Example of a potential domain model if needed:
# class EmbeddingResult(BaseModel):
#     text_id: Optional[str] = None # If texts need to be identified
#     vector: List[float]
#     source_text_preview: str # For context
```

## File: `app\infrastructure\__init__.py`
```py
# Infrastructure package for embedding-service

```

## File: `app\infrastructure\embedding_models\__init__.py`
```py
# Models subpackage for infrastructure

```

## File: `app\infrastructure\embedding_models\fastembed_adapter.py`
```py
# embedding-service/app/infrastructure/embedding_models/fastembed_adapter.py
import structlog
from typing import List, Tuple, Dict, Any, Optional
import asyncio
import time

from fastembed import TextEmbedding 

from app.application.ports.embedding_model_port import EmbeddingModelPort
from app.core.config import settings

log = structlog.get_logger(__name__)

class FastEmbedAdapter(EmbeddingModelPort):
    """
    Adapter for FastEmbed library.
    Note: This adapter is currently not the primary one used by default.
    """
    _model: Optional[TextEmbedding] = None
    _model_name: str
    _model_dimension: int # This will be set from global settings.EMBEDDING_DIMENSION
    _model_loaded: bool = False
    _model_load_error: Optional[str] = None

    def __init__(self):
        self._model_name = settings.FASTEMBED_MODEL_NAME
        # IMPORTANT: This adapter will use the global EMBEDDING_DIMENSION from settings.
        # If settings.EMBEDDING_DIMENSION is configured for OpenAI (e.g., 1536),
        # and this FastEmbed model (e.g., all-MiniLM-L6-v2 -> 384) has a different dimension,
        # the health check/validation within initialize_model WILL LIKELY FAIL.
        # This is expected if the service is globally configured for a different provider like OpenAI.
        self._model_dimension = settings.EMBEDDING_DIMENSION
        log.info("FastEmbedAdapter initialized", configured_model_name=self._model_name, expected_dimension_from_global_settings=self._model_dimension)


    async def initialize_model(self):
        """
        Initializes and loads the FastEmbed model.
        This should be called during service startup (e.g., lifespan).
        """
        if self._model_loaded:
            log.debug("FastEmbed model already initialized.", model_name=self._model_name)
            return

        init_log = log.bind(adapter="FastEmbedAdapter", action="initialize_model", model_name=self._model_name)
        init_log.info("Initializing FastEmbed model...")
        start_time = time.perf_counter()
        try:
            # TextEmbedding initialization is synchronous
            self._model = TextEmbedding(
                model_name=self._model_name,
                cache_dir=settings.FASTEMBED_CACHE_DIR,
                threads=settings.FASTEMBED_THREADS,
                max_length=settings.FASTEMBED_MAX_LENGTH,
            )
            
            # Perform a test embedding to confirm dimension and successful loading
            # The .embed() method is CPU-bound, so run in a thread pool if called from async context
            test_embeddings_generator = await asyncio.to_thread(self._model.embed, ["test vector"])
            test_embeddings_list = list(test_embeddings_generator) 

            if not test_embeddings_list or not test_embeddings_list[0].any():
                raise ValueError("Test embedding with FastEmbed failed or returned empty result.")

            actual_dim = len(test_embeddings_list[0])
            
            # Validate against the dimension this adapter was initialized with (from global settings)
            if actual_dim != self._model_dimension:
                self._model_load_error = (
                    f"FastEmbed Model dimension mismatch. Global EMBEDDING_DIMENSION is {self._model_dimension}, "
                    f"but FastEmbed model '{self._model_name}' produced {actual_dim} dimensions."
                )
                init_log.error(self._model_load_error)
                self._model = None 
                self._model_loaded = False # Ensure model is not marked as loaded
                # This exception will be caught and handled by the main startup logic
                raise ValueError(self._model_load_error) 

            self._model_loaded = True
            self._model_load_error = None
            duration_ms = (time.perf_counter() - start_time) * 1000
            init_log.info("FastEmbed model initialized and validated successfully.", duration_ms=duration_ms, actual_dimension=actual_dim)

        except Exception as e:
            self._model_load_error = f"Failed to load FastEmbed model '{self._model_name}': {str(e)}"
            init_log.critical(self._model_load_error, exc_info=True)
            self._model = None
            self._model_loaded = False
            # Propagate as ConnectionError to indicate a critical startup failure for this adapter
            raise ConnectionError(self._model_load_error) from e


    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not self._model_loaded or not self._model:
            log.error("FastEmbed model not loaded. Cannot generate embeddings.", model_error=self._model_load_error)
            raise ConnectionError(f"FastEmbed model is not available. Load error: {self._model_load_error}")

        if not texts:
            return []

        embed_log = log.bind(adapter="FastEmbedAdapter", action="embed_texts", num_texts=len(texts))
        embed_log.debug("Generating embeddings with FastEmbed...")
        try:
            # FastEmbed's embed method is CPU-bound; run in thread pool.
            embeddings_generator = await asyncio.to_thread(self._model.embed, texts, batch_size=128)
            embeddings_list = [emb.tolist() for emb in embeddings_generator]

            embed_log.debug("FastEmbed embeddings generated successfully.")
            return embeddings_list
        except Exception as e:
            embed_log.exception("Error during FastEmbed embedding process")
            raise RuntimeError(f"FastEmbed embedding generation failed: {e}") from e

    def get_model_info(self) -> Dict[str, Any]:
        # Returns the dimension this adapter *expects* based on global config,
        # and the model name it's configured to use.
        # Actual dimension is validated during init.
        return {
            "model_name": self._model_name,
            "dimension": self._model_dimension, 
        }

    async def health_check(self) -> Tuple[bool, str]:
        if self._model_loaded and self._model:
            try:
                # Test with a short text
                test_embeddings_generator = await asyncio.to_thread(self._model.embed, ["health check"], batch_size=1)
                _ = list(test_embeddings_generator) 
                return True, f"FastEmbed model '{self._model_name}' loaded and responsive."
            except Exception as e:
                log.error("FastEmbed model health check failed during test embedding", error=str(e), exc_info=True)
                return False, f"FastEmbed model '{self._model_name}' loaded but unresponsive: {str(e)}"
        elif self._model_load_error:
            return False, f"FastEmbed model '{self._model_name}' failed to load: {self._model_load_error}"
        else:
            return False, f"FastEmbed model '{self._model_name}' not loaded."
```

## File: `app\infrastructure\embedding_models\openai_adapter.py`
```py
# File: embedding-service/app/infrastructure/embedding_models/openai_adapter.py
import structlog
from typing import List, Tuple, Dict, Any, Optional
import asyncio
import time
from openai import AsyncOpenAI, APIConnectionError, RateLimitError, AuthenticationError, OpenAIError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.application.ports.embedding_model_port import EmbeddingModelPort
from app.core.config import settings
from app.core.metrics import OPENAI_API_DURATION_SECONDS, OPENAI_API_ERRORS_TOTAL

log = structlog.get_logger(__name__)

class OpenAIAdapter(EmbeddingModelPort):
    """
    Adapter for OpenAI's Embedding API.
    """
    _client: Optional[AsyncOpenAI] = None
    _model_name: str
    _embedding_dimension: int
    _dimensions_override: Optional[int]
    _model_initialized: bool = False
    _initialization_error: Optional[str] = None

    def __init__(self):
        self._model_name = settings.OPENAI_EMBEDDING_MODEL_NAME
        self._embedding_dimension = settings.EMBEDDING_DIMENSION
        self._dimensions_override = settings.OPENAI_EMBEDDING_DIMENSIONS_OVERRIDE
        log.info("OpenAIAdapter initialized", model_name=self._model_name, target_dimension=self._embedding_dimension)

    async def initialize_model(self):
        if self._model_initialized:
            log.debug("OpenAI client already initialized.", model_name=self._model_name)
            return

        init_log = log.bind(adapter="OpenAIAdapter", action="initialize_model", model_name=self._model_name)
        init_log.info("Initializing OpenAI client...")
        start_time = time.perf_counter()

        if not settings.OPENAI_API_KEY.get_secret_value():
            self._initialization_error = "OpenAI API Key is not configured."
            init_log.critical(self._initialization_error)
            self._model_initialized = False
            raise ConnectionError(self._initialization_error)

        try:
            self._client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY.get_secret_value(),
                base_url=settings.OPENAI_API_BASE,
                timeout=settings.OPENAI_TIMEOUT_SECONDS,
                max_retries=0
            )
            self._model_initialized = True
            self._initialization_error = None
            duration_ms = (time.perf_counter() - start_time) * 1000
            init_log.info("OpenAI client initialized successfully.", duration_ms=duration_ms)
        except Exception as e:
            self._initialization_error = f"Failed to initialize OpenAI client: {str(e)}"
            init_log.critical(self._initialization_error, exc_info=True)
            self._client = None
            self._model_initialized = False
            raise ConnectionError(self._initialization_error) from e

    @retry(
        stop=stop_after_attempt(settings.OPENAI_MAX_RETRIES + 1),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError, OpenAIError)),
        before_sleep=lambda retry_state: log.warning(
            "Retrying OpenAI embedding call",
            model_name=settings.OPENAI_EMBEDDING_MODEL_NAME,
            attempt_number=retry_state.attempt_number,
            wait_time=retry_state.next_action.sleep,
            error=str(retry_state.outcome.exception()) if retry_state.outcome else "Unknown error"
        )
    )
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not self._model_initialized or not self._client:
            log.error("OpenAI client not initialized.", init_error=self._initialization_error)
            raise ConnectionError("OpenAI embedding model is not available.")

        if not texts:
            return []

        embed_log = log.bind(adapter="OpenAIAdapter", num_texts=len(texts), model=self._model_name)
        embed_log.debug("Generating embeddings via OpenAI API...")

        try:
            api_params: Dict[str, Any] = {
                "model": self._model_name,
                "input": texts,
                "encoding_format": "float"
            }
            if self._dimensions_override is not None:
                api_params["dimensions"] = self._dimensions_override

            with OPENAI_API_DURATION_SECONDS.labels(model_name=self._model_name).time():
                response = await self._client.embeddings.create(**api_params)

            if not response.data or not all(item.embedding for item in response.data):
                raise ValueError("OpenAI API returned no valid embedding data.")

            embeddings_list = [item.embedding for item in response.data]
            return embeddings_list
        except AuthenticationError as e:
            embed_log.error("OpenAI API Authentication Error", error=str(e))
            OPENAI_API_ERRORS_TOTAL.labels(model_name=self._model_name, error_type="authentication_error").inc()
            raise ConnectionError(f"OpenAI authentication failed: {e}") from e
        except RateLimitError as e:
            embed_log.error("OpenAI API Rate Limit Exceeded", error=str(e))
            OPENAI_API_ERRORS_TOTAL.labels(model_name=self._model_name, error_type="rate_limit_error").inc()
            raise OpenAIError(f"OpenAI rate limit exceeded: {e}") from e
        except APIConnectionError as e:
            embed_log.error("OpenAI API Connection Error", error=str(e))
            OPENAI_API_ERRORS_TOTAL.labels(model_name=self._model_name, error_type="connection_error").inc()
            raise OpenAIError(f"OpenAI connection error: {e}") from e
        except OpenAIError as e:
            error_type = type(e).__name__
            embed_log.error(f"OpenAI API Error: {error_type}", error=str(e))
            OPENAI_API_ERRORS_TOTAL.labels(model_name=self._model_name, error_type=error_type).inc()
            raise RuntimeError(f"OpenAI API error: {e}") from e
        except Exception as e:
            embed_log.exception("Unexpected error during OpenAI embedding process")
            OPENAI_API_ERRORS_TOTAL.labels(model_name=self._model_name, error_type="unexpected_error").inc()
            raise RuntimeError(f"Embedding generation failed with unexpected error: {e}") from e

    def get_model_info(self) -> Dict[str, Any]:
        return { "model_name": self._model_name, "dimension": self._embedding_dimension }

    async def health_check(self) -> Tuple[bool, str]:
        if self._model_initialized and self._client:
            return True, f"OpenAI client initialized for model {self._model_name}."
        elif self._initialization_error:
            return False, f"OpenAI client initialization failed: {self._initialization_error}"
        else:
            return False, "OpenAI client not initialized."
```

## File: `app\main.py`
```py
# File: embedding-service/app/main.py
import sys
import json
import asyncio
import structlog
from typing import Any, List, Generator, Dict

from prometheus_client import start_http_server

from app.core.logging_config import setup_logging
setup_logging()

from app.core.config import settings
from app.services.kafka_clients import KafkaConsumerClient, KafkaProducerClient, KafkaError
from app.infrastructure.embedding_models.openai_adapter import OpenAIAdapter
from app.application.use_cases.embed_texts_use_case import EmbedTextsUseCase
from app.core.metrics import (
    MESSAGES_CONSUMED_TOTAL,
    BATCH_PROCESSING_DURATION_SECONDS,
    TEXTS_PROCESSED_TOTAL,
)

log = structlog.get_logger(__name__)

def main():
    """Punto de entrada principal para el worker de embeddings."""
    log.info("Initializing Embedding Worker...")
    try:
        # Start Prometheus metrics server
        start_http_server(8002)
        log.info("Prometheus metrics server started on port 8002.")

        openai_adapter = OpenAIAdapter()
        asyncio.run(openai_adapter.initialize_model())
        use_case = EmbedTextsUseCase(embedding_model=openai_adapter)
        
        consumer = KafkaConsumerClient(topics=[settings.KAFKA_INPUT_TOPIC])
        producer = KafkaProducerClient()
    except Exception as e:
        log.critical("Failed to initialize worker dependencies", error=str(e), exc_info=True)
        sys.exit(1)

    log.info("Worker initialized successfully. Starting consumption loop...")
    try:
        for message_batch in batch_consumer(consumer, batch_size=50, batch_timeout_s=5):
            process_message_batch(message_batch, use_case, producer)
            consumer.commit(message=message_batch[-1])
    except KeyboardInterrupt:
        log.info("Shutdown signal received.")
    except Exception as e:
        log.critical("Critical error in consumer loop.", error=str(e), exc_info=True)
    finally:
        log.info("Closing worker resources...")
        consumer.close()
        producer.flush()
        log.info("Worker shut down gracefully.")

def batch_consumer(consumer: KafkaConsumerClient, batch_size: int, batch_timeout_s: int) -> Generator[List[Any], None, None]:
    """Agrupa mensajes de Kafka en lotes para un procesamiento eficiente."""
    batch = []
    while True:
        msg = consumer.consumer.poll(timeout=batch_timeout_s)
        if msg is None:
            if batch: yield batch; batch = []
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                log.error("Kafka consumer poll error", error=msg.error())
            continue
        
        MESSAGES_CONSUMED_TOTAL.labels(topic=msg.topic(), partition=msg.partition()).inc()
        batch.append(msg)
        if len(batch) >= batch_size:
            yield batch; batch = []

@BATCH_PROCESSING_DURATION_SECONDS.time()
def process_message_batch(message_batch: List[Any], use_case: EmbedTextsUseCase, producer: KafkaProducerClient):
    batch_log = log.bind(batch_size=len(message_batch))
    texts_to_embed, metadata_list = [], []
    for msg in message_batch:
        try:
            event_data = json.loads(msg.value().decode('utf-8'))
            if "text" in event_data and event_data["text"] is not None:
                texts_to_embed.append(event_data["text"])
                metadata_list.append(event_data)
            else:
                batch_log.warning("Skipping message with missing or null 'text' field", offset=msg.offset())
        except json.JSONDecodeError:
            batch_log.error("Failed to decode Kafka message", offset=msg.offset())

    if not texts_to_embed:
        batch_log.debug("No valid texts to embed in this batch.")
        return

    try:
        embeddings, _ = asyncio.run(use_case.execute(texts_to_embed))
        if len(embeddings) != len(metadata_list):
            batch_log.error("Mismatch in embedding results count.", expected=len(metadata_list), got=len(embeddings))
            return

        for i, vector in enumerate(embeddings):
            meta = metadata_list[i]
            company_id = meta.get("company_id", "unknown")
            output_payload = {
                "chunk_id": meta.get("chunk_id"),
                "document_id": meta.get("document_id"),
                "company_id": company_id, 
                "vector": vector,
            }
            producer.produce(settings.KAFKA_OUTPUT_TOPIC, key=str(meta.get("document_id")), value=output_payload)
            TEXTS_PROCESSED_TOTAL.labels(company_id=company_id).inc()
        
        batch_log.info(f"Processed and produced {len(embeddings)} embeddings.")
    except Exception as e:
        batch_log.error("Unhandled error processing batch", error=str(e), exc_info=True)

if __name__ == "__main__":
    main()
```

## File: `app\services\__init__.py`
```py

```

## File: `app\services\kafka_clients.py`
```py
# File: app/services/kafka_clients.py
import json
import structlog
from confluent_kafka import Consumer, Producer, KafkaError, KafkaException
from typing import Optional, Generator, Any, Dict

from app.core.config import settings
from app.core.metrics import KAFKA_MESSAGES_PRODUCED_TOTAL

log = structlog.get_logger(__name__)

# --- Kafka Producer ---
class KafkaProducerClient:
    def __init__(self):
        producer_config = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'acks': 'all',
        }
        self.producer = Producer(producer_config)
        self.log = log.bind(component="KafkaProducerClient")

    def _delivery_report(self, err, msg):
        topic = msg.topic()
        if err is not None:
            self.log.error(f"Message delivery failed to topic '{topic}'", key=msg.key().decode('utf-8'), error=str(err))
            KAFKA_MESSAGES_PRODUCED_TOTAL.labels(topic=topic, status="failure").inc()
        else:
            self.log.debug(f"Message delivered to {topic} [{msg.partition()}]")
            KAFKA_MESSAGES_PRODUCED_TOTAL.labels(topic=topic, status="success").inc()

    def produce(self, topic: str, key: str, value: Dict[str, Any]):
        try:
            self.producer.produce(
                topic,
                key=key.encode('utf-8'),
                value=json.dumps(value).encode('utf-8'),
                callback=self._delivery_report
            )
        except KafkaException as e:
            self.log.exception("Failed to produce message", error=str(e))
            KAFKA_MESSAGES_PRODUCED_TOTAL.labels(topic=topic, status="failure").inc()
            raise

    def flush(self, timeout: float = 10.0):
        self.log.info(f"Flushing producer with a timeout of {timeout}s...")
        self.producer.flush(timeout)
        self.log.info("Producer flushed.")

# --- Kafka Consumer ---
class KafkaConsumerClient:
    def __init__(self, topics: list[str]):
        consumer_config = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': settings.KAFKA_CONSUMER_GROUP_ID,
            'auto.offset.reset': settings.KAFKA_AUTO_OFFSET_RESET,
            'enable.auto.commit': False,
        }
        self.consumer = Consumer(consumer_config)
        self.consumer.subscribe(topics)
        self.log = log.bind(component="KafkaConsumerClient", topics=topics)

    def consume(self) -> Generator[Any, None, None]:
        self.log.info("Starting Kafka consumer loop...")
        try:
            while True:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        self.log.error("Kafka consumer error", error=msg.error())
                        raise KafkaException(msg.error())
                    continue
                
                yield msg
                
        except KeyboardInterrupt:
            self.log.info("Consumer loop interrupted by user.")
        finally:
            self.close()

    def commit(self, message: Any):
        self.consumer.commit(message=message, asynchronous=False)

    def close(self):
        self.log.info("Closing Kafka consumer...")
        self.consumer.close()
```

## File: `pyproject.toml`
```toml
# File: embedding-service/pyproject.toml
[tool.poetry]
name = "embedding-service"
version = "2.1.0"
description = "Atenex Embedding Worker using OpenAI (Kafka Consumer/Producer)"
authors = ["Atenex Team <dev@atenex.com>"]
readme = "README.md"
package-mode = false

[tool.poetry.dependencies]
python = ">=3.10,<3.13"
pydantic = {extras = ["email"], version = "^2.6.4"}
pydantic-settings = "^2.2.1"
structlog = "^24.1.0"
tenacity = "^8.2.3"
numpy = "^1.26.0"

# --- Embedding Engine ---
openai = "^1.14.0"

# --- Kafka Client ---
confluent-kafka = "^2.4.0"

# --- Prometheus Metrics Client ---
prometheus-client = "^0.20.0"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.4"
pytest-asyncio = "^0.21.1"
httpx = "^0.27.0"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```
