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