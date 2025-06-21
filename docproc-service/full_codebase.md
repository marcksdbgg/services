# Estructura de la Codebase

```
app/
├── __init__.py
├── application
│   ├── __init__.py
│   ├── ports
│   │   ├── __init__.py
│   │   ├── chunking_port.py
│   │   └── extraction_port.py
│   └── use_cases
│       ├── __init__.py
│       └── process_document_use_case.py
├── core
│   ├── __init__.py
│   ├── config.py
│   └── logging_config.py
├── domain
│   ├── __init__.py
│   └── models.py
├── infrastructure
│   ├── __init__.py
│   ├── chunkers
│   │   ├── __init__.py
│   │   └── default_chunker_adapter.py
│   └── extractors
│       ├── __init__.py
│       ├── base_extractor.py
│       ├── docx_adapter.py
│       ├── excel_adapter.py
│       ├── html_adapter.py
│       ├── md_adapter.py
│       ├── pdf_adapter.py
│       └── txt_adapter.py
├── main.py
└── services
    ├── __init__.py
    ├── kafka_clients.py
    └── s3_client.py
```

# Codebase: `app`

## File: `app\__init__.py`
```py

```

## File: `app\application\__init__.py`
```py

```

## File: `app\application\ports\__init__.py`
```py

```

## File: `app\application\ports\chunking_port.py`
```py
from abc import ABC, abstractmethod
from typing import List

class ChunkingError(Exception):
    """Base exception for chunking errors."""
    pass

class ChunkingPort(ABC):
    """
    Interface (Port) para la división de texto en fragmentos (chunks).
    """

    @abstractmethod
    def chunk_text(
        self,
        text_content: str,
        chunk_size: int,
        chunk_overlap: int
    ) -> List[str]:
        """
        Divide un bloque de texto en fragmentos más pequeños.

        Args:
            text_content: El texto a dividir.
            chunk_size: El tamaño deseado para cada chunk (en alguna unidad, ej. tokens o palabras).
            chunk_overlap: El tamaño del solapamiento entre chunks consecutivos.

        Returns:
            Una lista de strings, donde cada string es un chunk.

        Raises:
            ChunkingError: Si ocurre un error durante el chunking.
        """
        pass
```

## File: `app\application\ports\extraction_port.py`
```py
from abc import ABC, abstractmethod
from typing import List, Tuple, Union, Any, Dict # <--- AÑADIR Dict AQUÍ

class ExtractionError(Exception):
    """Base exception for extraction errors."""
    pass

class UnsupportedContentTypeError(ExtractionError):
    """Exception raised when a content type is not supported for extraction."""
    pass

class ExtractionPort(ABC):
    """
    Interface (Port) para la extracción de texto de documentos.
    """

    @abstractmethod
    def extract_text(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> Tuple[Union[str, List[Tuple[int, str]]], Dict[str, Any]]: # Ahora Dict es conocido
        """
        Extrae texto de los bytes de un archivo.

        Args:
            file_bytes: Contenido del archivo en bytes.
            filename: Nombre original del archivo (para logging y metadatos).
            content_type: Tipo MIME del archivo.

        Returns:
            Una tupla conteniendo:
            - El texto extraído. Puede ser un string único (para formatos sin páginas como TXT, MD, HTML)
              o una lista de tuplas (page_number, page_text) para formatos con páginas (como PDF).
            - Un diccionario con metadatos de la extracción (ej. {'total_pages_extracted': 10}).

        Raises:
            UnsupportedContentTypeError: Si el content_type no es soportado.
            ExtractionError: Para otros errores durante la extracción.
        """
        pass
```

## File: `app\application\use_cases\__init__.py`
```py

```

## File: `app\application\use_cases\process_document_use_case.py`
```py
import time
import structlog
from typing import List, Dict, Any, Optional, Tuple, Union

from app.core.config import settings
from app.domain.models import (
    ProcessedChunk,
    ProcessedDocumentMetadata,
    ProcessedChunkSourceMetadata,
    ProcessResponseData
)
from app.application.ports.extraction_port import ExtractionPort, UnsupportedContentTypeError, ExtractionError
from app.application.ports.chunking_port import ChunkingPort, ChunkingError

log = structlog.get_logger(__name__)

class ProcessDocumentUseCase:
    def __init__(
        self,
        extraction_port: ExtractionPort,
        chunking_port: ChunkingPort,
    ):
        self.extraction_port = extraction_port
        self.chunking_port = chunking_port
        self.log = log.bind(component="ProcessDocumentUseCase")

    async def execute(
        self,
        file_bytes: bytes,
        original_filename: str,
        content_type: str,
        # Parámetros de chunking pueden venir de la request o de la config del servicio
        chunk_size: Optional[int] = None, 
        chunk_overlap: Optional[int] = None,
        # IDs opcionales para tracing
        document_id_trace: Optional[str] = None, 
        company_id_trace: Optional[str] = None
    ) -> ProcessResponseData:
        
        start_time = time.perf_counter()
        
        use_case_log = self.log.bind(
            original_filename=original_filename, 
            content_type=content_type,
            document_id_trace=document_id_trace,
            company_id_trace=company_id_trace
        )
        use_case_log.info("Starting document processing")

        # Determinar parámetros de chunking
        effective_chunk_size = chunk_size if chunk_size is not None else settings.CHUNK_SIZE
        effective_chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP

        # 1. Extracción de Texto
        try:
            extracted_data, extraction_meta = await self._run_extraction(file_bytes, original_filename, content_type)
        except UnsupportedContentTypeError as e:
            use_case_log.warning("Unsupported content type for extraction", error=str(e))
            raise  # Re-raise para que el endpoint lo maneje como 415
        except ExtractionError as e:
            use_case_log.error("Extraction failed", error=str(e))
            raise # Re-raise para que el endpoint lo maneje como 422 o 500

        # 2. Concatenación y Chunking
        all_chunks_data: List[ProcessedChunk] = []
        raw_text_length = 0

        if isinstance(extracted_data, str): # Para TXT, HTML, MD
            raw_text_length = len(extracted_data)
            if extracted_data.strip(): # Solo chunkear si hay contenido no vacío
                text_chunks = self._run_chunking(extracted_data, effective_chunk_size, effective_chunk_overlap)
                for text_chunk_content in text_chunks:
                    all_chunks_data.append(
                        ProcessedChunk(
                            text=text_chunk_content,
                            source_metadata=ProcessedChunkSourceMetadata() # Sin página para estos formatos
                        )
                    )
        elif isinstance(extracted_data, list): # Para PDF (lista de tuplas (page_num, page_text))
            current_page_text_for_chunking = ""
            for page_num, page_text in extracted_data:
                raw_text_length += len(page_text)
                if page_text.strip():
                    text_chunks_from_page = self._run_chunking(page_text, effective_chunk_size, effective_chunk_overlap)
                    for text_chunk_content in text_chunks_from_page:
                        all_chunks_data.append(
                            ProcessedChunk(
                                text=text_chunk_content,
                                source_metadata=ProcessedChunkSourceMetadata(page_number=page_num)
                            )
                        )
            # Alternativa: concatenar todo el texto del PDF y luego chunkear una vez.
            # Esto podría perder la granularidad de página para source_metadata de chunks que cruzan páginas.
            # La estrategia actual (chunkear página por página) es más simple para mantener metadatos de página.
        else:
            use_case_log.error("Unexpected data type from extraction port", type_received=type(extracted_data))
            raise ExtractionError("Internal error: Unexpected data type from extraction.")

        end_time = time.perf_counter()
        processing_time_ms = (end_time - start_time) * 1000

        doc_meta = ProcessedDocumentMetadata(
            original_filename=original_filename,
            content_type=content_type,
            total_pages_extracted=extraction_meta.get("total_pages_extracted"),
            raw_text_length_chars=raw_text_length,
            processing_time_ms=round(processing_time_ms, 2),
            num_chunks_generated=len(all_chunks_data)
        )

        use_case_log.info("Document processing finished successfully", 
                          num_chunks=len(all_chunks_data), 
                          processing_time_ms=doc_meta.processing_time_ms)
        
        return ProcessResponseData(document_metadata=doc_meta, chunks=all_chunks_data)

    async def _run_extraction(self, file_bytes: bytes, filename: str, content_type: str):
        # En un entorno real, podrías querer ejecutar esto en un ThreadPoolExecutor si es bloqueante
        # pero FastAPI maneja UploadFile de forma asíncrona y los extractores de PyMuPDF/docx
        # pueden ser CPU-bound pero no necesariamente bloquean el event loop si se manejan bien.
        # Por ahora, llamada directa.
        return self.extraction_port.extract_text(file_bytes, filename, content_type)

    def _run_chunking(self, text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
        try:
            return self.chunking_port.chunk_text(text, chunk_size, chunk_overlap)
        except ChunkingError as e:
            self.log.error("Chunking failed during use case execution", error=str(e))
            # Decide si re-elevar o devolver lista vacía. Por ahora, re-elevar.
            raise


```

## File: `app\core\__init__.py`
```py

```

## File: `app\core\config.py`
```py
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
```

## File: `app\core\logging_config.py`
```py
import logging
import sys
import structlog
from app.core.config import settings # type: ignore
import os

def setup_logging():
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
    
    # Clear existing handlers only if we're not in a managed environment that might set them up (like Gunicorn)
    # A simple check is if any handlers are already StreamHandlers to stdout.
    # This avoids duplicate logs when Uvicorn/Gunicorn also configures logging.
    is_stdout_handler_present = any(
        isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
        for h in root_logger.handlers
    )
    if not is_stdout_handler_present:
        # Clear all handlers if no specific stdout handler detected, to avoid conflicts
        # But this might be too aggressive if other handlers are desired (e.g. file logger from a lib)
        # For service logging, focusing on stdout is usually fine.
        # root_logger.handlers.clear() # Commented out to be less aggressive
        root_logger.addHandler(handler)
    elif not root_logger.handlers: # If no handlers at all, add ours.
        root_logger.addHandler(handler)


    root_logger.setLevel(settings.LOG_LEVEL)

    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("gunicorn.error").setLevel(logging.WARNING) # Gunicorn logs to stderr by default
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    # For PyMuPDF, set to WARNING to avoid too many debug messages unless needed
    logging.getLogger("fitz").setLevel(logging.WARNING)


    log = structlog.get_logger(settings.PROJECT_NAME)
    log.info("Logging configured", log_level=settings.LOG_LEVEL)
```

## File: `app\domain\__init__.py`
```py

```

## File: `app\domain\models.py`
```py
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class ProcessedChunkSourceMetadata(BaseModel):
    """Metadatos originados durante el procesamiento en docproc-service para un chunk."""
    page_number: Optional[int] = Field(None, description="Número de página original del chunk (si aplica, ej. PDF).")
    # Se pueden añadir otros metadatos específicos del extractor o chunker aquí
    # por ejemplo, tipo de contenido original del bloque (ej. "table", "paragraph")
    # original_block_type: Optional[str] = None

class ProcessedChunk(BaseModel):
    """Representa un chunk de texto procesado."""
    text: str = Field(..., description="El contenido textual del chunk.")
    source_metadata: ProcessedChunkSourceMetadata = Field(default_factory=ProcessedChunkSourceMetadata, description="Metadatos asociados al origen del chunk.")

class ProcessedDocumentMetadata(BaseModel):
    """Metadatos generales sobre el documento procesado."""
    original_filename: str = Field(..., description="Nombre original del archivo procesado.")
    content_type: str = Field(..., description="Tipo MIME del archivo procesado.")
    total_pages_extracted: Optional[int] = Field(None, description="Número total de páginas de las que se extrajo texto (ej. para PDF).")
    raw_text_length_chars: int = Field(..., description="Longitud del texto crudo extraído en caracteres.")
    processing_time_ms: float = Field(..., description="Tiempo total de procesamiento en milisegundos.")
    num_chunks_generated: int = Field(..., description="Número total de chunks generados.")

class ProcessResponseData(BaseModel):
    """Datos contenidos en una respuesta exitosa del endpoint de procesamiento."""
    document_metadata: ProcessedDocumentMetadata
    chunks: List[ProcessedChunk]

class ProcessResponse(BaseModel):
    """Schema de respuesta para el endpoint POST /api/v1/process."""
    data: ProcessResponseData

    class Config:
        json_schema_extra = {
            "example": {
                "data": {
                    "document_metadata": {
                        "original_filename": "example_document.pdf",
                        "content_type": "application/pdf",
                        "total_pages_extracted": 10,
                        "raw_text_length_chars": 15000,
                        "processing_time_ms": 543.21,
                        "num_chunks_generated": 15
                    },
                    "chunks": [
                        {
                            "text": "Este es el contenido del primer chunk procesado...",
                            "source_metadata": {"page_number": 1}
                        },
                        {
                            "text": "Este es el contenido del segundo chunk procesado...",
                            "source_metadata": {"page_number": 1}
                        }
                    ]
                }
            }
        }
```

## File: `app\infrastructure\__init__.py`
```py

```

## File: `app\infrastructure\chunkers\__init__.py`
```py

```

## File: `app\infrastructure\chunkers\default_chunker_adapter.py`
```py
import structlog
from typing import List

from app.application.ports.chunking_port import ChunkingPort, ChunkingError
from app.core.config import settings as service_settings # Use specific settings for docproc

log = structlog.get_logger(__name__)

class DefaultChunkerAdapter(ChunkingPort):
    """
    Adaptador de chunking por defecto, basado en división por palabras y solapamiento.
    Reutiliza la lógica de text_splitter.py del ingest-service.
    """

    def chunk_text(
        self,
        text_content: str,
        chunk_size: int, # Parameter passed from use case, originating from request or service default
        chunk_overlap: int
    ) -> List[str]:
        if not text_content or text_content.isspace():
            log.debug("DefaultChunkerAdapter: Empty or whitespace-only text provided, returning no chunks.")
            return []
        
        if chunk_size <= 0:
            raise ChunkingError(f"Chunk size must be positive. Received: {chunk_size}")
        if chunk_overlap < 0:
            raise ChunkingError(f"Chunk overlap must be non-negative. Received: {chunk_overlap}")
        if chunk_overlap >= chunk_size:
            raise ChunkingError(f"Chunk overlap ({chunk_overlap}) must be less than chunk size ({chunk_size}).")

        log.debug("DefaultChunkerAdapter: Splitting text into chunks", 
                  text_length=len(text_content), 
                  chunk_size=chunk_size, 
                  chunk_overlap=chunk_overlap)
        
        # Lógica de text_splitter.py (adaptada)
        # Asumimos que chunk_size y chunk_overlap se refieren a número de palabras.
        # Si se refiere a caracteres, la lógica debería ajustarse.
        # Por simplicidad y para coincidir con el text_splitter original, usamos palabras.
        
        words = text_content.split() # Split by whitespace
        if not words:
            log.debug("DefaultChunkerAdapter: Text content resulted in no words after split.")
            return []

        chunks: List[str] = []
        current_pos = 0
        
        while current_pos < len(words):
            end_pos = min(current_pos + chunk_size, len(words))
            chunk_words = words[current_pos:end_pos]
            chunks.append(" ".join(chunk_words))
            
            if end_pos == len(words): # Reached the end
                break
            
            current_pos += (chunk_size - chunk_overlap)
            if current_pos >= len(words): # Prevent infinite loop if step is too small or overlap too large making step 0 or negative.
                # This should not happen if overlap < size.
                log.warning("DefaultChunkerAdapter: Chunking step led to no progress, breaking loop.", current_pos=current_pos, num_words=len(words))
                break
        
        log.info("DefaultChunkerAdapter: Text split into chunks", num_chunks=len(chunks))
        return chunks
```

## File: `app\infrastructure\extractors\__init__.py`
```py
from .base_extractor import BaseExtractorAdapter
from .pdf_adapter import PdfAdapter
from .docx_adapter import DocxAdapter
from .txt_adapter import TxtAdapter
from .html_adapter import HtmlAdapter
from .md_adapter import MdAdapter
from .excel_adapter import ExcelAdapter # NUEVA LÍNEA

__all__ = [
    "BaseExtractorAdapter",
    "PdfAdapter",
    "DocxAdapter",
    "TxtAdapter",
    "HtmlAdapter",
    "MdAdapter",
    "ExcelAdapter", # NUEVA LÍNEA
]
```

## File: `app\infrastructure\extractors\base_extractor.py`
```py
import structlog
from app.application.ports.extraction_port import ExtractionPort, ExtractionError

log = structlog.get_logger(__name__)

class BaseExtractorAdapter(ExtractionPort):
    """
    Clase base para adaptadores de extracción con logging común.
    """
    def _handle_extraction_error(self, e: Exception, filename: str, adapter_name: str) -> ExtractionError:
        log.error(f"{adapter_name} extraction failed", filename=filename, error=str(e), exc_info=True)
        raise ExtractionError(f"Error extracting with {adapter_name} for {filename}: {e}") from e
```

## File: `app\infrastructure\extractors\docx_adapter.py`
```py
import io
import docx  # python-docx
import structlog
from typing import Tuple, Dict, Any, Union, List

from app.application.ports.extraction_port import ExtractionPort, ExtractionError, UnsupportedContentTypeError
from app.infrastructure.extractors.base_extractor import BaseExtractorAdapter

log = structlog.get_logger(__name__)

class DocxAdapter(BaseExtractorAdapter):
    """Adaptador para extraer texto de archivos DOCX."""

    SUPPORTED_CONTENT_TYPES = [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword" # python-docx can sometimes handle .doc, but it's not guaranteed
    ]

    def extract_text(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> Tuple[str, Dict[str, Any]]:
        if content_type not in self.SUPPORTED_CONTENT_TYPES:
            raise UnsupportedContentTypeError(f"DocxAdapter does not support content type: {content_type}")

        log.debug("DocxAdapter: Extracting text from DOCX bytes", filename=filename)
        extraction_metadata: Dict[str, Any] = {}
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs if p.text and not p.text.isspace()])
            
            extraction_metadata["num_paragraphs_extracted"] = len([p for p in doc.paragraphs if p.text and not p.text.isspace()])
            log.info("DocxAdapter: DOCX extraction successful", filename=filename, num_paragraphs=extraction_metadata["num_paragraphs_extracted"])
            return text, extraction_metadata
        except Exception as e:
            # If it's a .doc file, it might fail here. Log a specific warning.
            if content_type == "application/msword":
                log.warning("DocxAdapter: Failed to process .doc file. This format has limited support.", filename=filename, error=str(e))
            raise self._handle_extraction_error(e, filename, "DocxAdapter")
```

## File: `app\infrastructure\extractors\excel_adapter.py`
```py
import io
import pandas as pd
import structlog
from typing import List, Tuple, Dict, Any

from app.application.ports.extraction_port import ExtractionPort, ExtractionError, UnsupportedContentTypeError
from app.infrastructure.extractors.base_extractor import BaseExtractorAdapter

log = structlog.get_logger(__name__)

class ExcelAdapter(BaseExtractorAdapter):
    """Adaptador para extraer texto de archivos Excel (XLSX, XLS)."""

    SUPPORTED_CONTENT_TYPES = [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-excel"  # .xls
    ]

    def extract_text(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> Tuple[List[Tuple[int, str]], Dict[str, Any]]:
        content_type_lower = content_type.lower()
        if content_type_lower not in self.SUPPORTED_CONTENT_TYPES:
            raise UnsupportedContentTypeError(f"ExcelAdapter does not support content type: {content_type}")

        log.debug("ExcelAdapter: Extracting text from Excel bytes", filename=filename, content_type=content_type)
        pages_content: List[Tuple[int, str]] = []
        extraction_metadata: Dict[str, Any] = {
            "total_sheets_extracted": 0,
            "sheet_names": []
        }

        try:
            # Pandas usa openpyxl para xlsx y puede usar xlrd para xls.
            # Si se necesita específicamente xlrd para .xls antiguos, asegurar que esté instalado.
            # Por defecto, pandas intentará el motor apropiado.
            excel_file = pd.ExcelFile(io.BytesIO(file_bytes))
            sheet_names = excel_file.sheet_names
            extraction_metadata["sheet_names"] = sheet_names
            
            log.info("ExcelAdapter: Processing Excel file", filename=filename, num_sheets=len(sheet_names), sheet_names_list=sheet_names)

            for i, sheet_name in enumerate(sheet_names):
                page_num_one_based = i + 1
                try:
                    df = excel_file.parse(sheet_name)
                    if not df.empty:
                        # Convertir DataFrame a Markdown. Incluir el índice puede ser útil o no.
                        # index=False evita escribir el índice numérico del DataFrame.
                        # tablefmt="pipe" es un formato común de Markdown para tablas.
                        markdown_text = df.to_markdown(index=False, tablefmt="pipe")
                        
                        # Añadir un título con el nombre de la hoja al principio del texto Markdown
                        sheet_title_md = f"# Hoja: {sheet_name}\n\n"
                        full_sheet_text = sheet_title_md + markdown_text

                        if full_sheet_text.strip():
                            pages_content.append((page_num_one_based, full_sheet_text))
                            log.debug("ExcelAdapter: Extracted text from sheet", sheet_name=sheet_name, page_num=page_num_one_based, length=len(full_sheet_text))
                        else:
                            log.debug("ExcelAdapter: Skipping empty sheet after markdown conversion", sheet_name=sheet_name, page_num=page_num_one_based)
                    else:
                        log.debug("ExcelAdapter: Skipping empty DataFrame for sheet", sheet_name=sheet_name, page_num=page_num_one_based)
                except Exception as sheet_err:
                    log.warning("ExcelAdapter: Error extracting text from sheet", filename=filename, sheet_name=sheet_name, page_num=page_num_one_based, error=str(sheet_err))
            
            extraction_metadata["total_sheets_extracted"] = len(pages_content)
            log.info("ExcelAdapter: Excel extraction successful", filename=filename, sheets_with_text=len(pages_content), total_doc_sheets=len(sheet_names))
            return pages_content, extraction_metadata
        except Exception as e:
            raise self._handle_extraction_error(e, filename, "ExcelAdapter")
```

## File: `app\infrastructure\extractors\html_adapter.py`
```py
from bs4 import BeautifulSoup
import structlog
from typing import Tuple, Dict, Any, Union, List

from app.application.ports.extraction_port import ExtractionPort, ExtractionError, UnsupportedContentTypeError
from app.infrastructure.extractors.base_extractor import BaseExtractorAdapter

log = structlog.get_logger(__name__)

class HtmlAdapter(BaseExtractorAdapter):
    """Adaptador para extraer texto de archivos HTML."""

    SUPPORTED_CONTENT_TYPES = ["text/html"]

    def extract_text(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        encoding: str = "utf-8" # Default encoding for HTML
    ) -> Tuple[str, Dict[str, Any]]:
        if content_type not in self.SUPPORTED_CONTENT_TYPES:
            raise UnsupportedContentTypeError(f"HtmlAdapter does not support content type: {content_type}")

        log.debug("HtmlAdapter: Extracting text from HTML bytes", filename=filename)
        extraction_metadata: Dict[str, Any] = {}
        try:
            # BeautifulSoup typically handles encoding detection well, but providing a hint can help.
            html_content = file_bytes.decode(encoding, errors='replace') # Replace errors to avoid decode failure
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Remove script and style elements
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
            
            text = soup.get_text(separator="\n", strip=True)
            
            extraction_metadata["title_extracted"] = soup.title.string if soup.title else None
            log.info("HtmlAdapter: HTML extraction successful", filename=filename, length=len(text))
            return text, extraction_metadata
        except Exception as e:
            raise self._handle_extraction_error(e, filename, "HtmlAdapter")
```

## File: `app\infrastructure\extractors\md_adapter.py`
```py
import markdown
import html2text # To convert HTML generated from Markdown to clean text
import structlog
from typing import Tuple, Dict, Any, Union, List

from app.application.ports.extraction_port import ExtractionPort, ExtractionError, UnsupportedContentTypeError
from app.infrastructure.extractors.base_extractor import BaseExtractorAdapter

log = structlog.get_logger(__name__)

class MdAdapter(BaseExtractorAdapter):
    """Adaptador para extraer texto de archivos Markdown."""

    SUPPORTED_CONTENT_TYPES = ["text/markdown"]

    def extract_text(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        encoding: str = "utf-8" # Default encoding
    ) -> Tuple[str, Dict[str, Any]]:
        if content_type not in self.SUPPORTED_CONTENT_TYPES:
            raise UnsupportedContentTypeError(f"MdAdapter does not support content type: {content_type}")

        log.debug("MdAdapter: Extracting text from MD bytes", filename=filename)
        extraction_metadata: Dict[str, Any] = {}
        try:
            md_text_content = file_bytes.decode(encoding)
            html = markdown.markdown(md_text_content)
            
            # Use html2text to get cleaner text from the rendered HTML
            text_maker = html2text.HTML2Text()
            text_maker.ignore_links = True # Example: ignore links, can be configured
            text_maker.ignore_images = True
            text = text_maker.handle(html)
            
            log.info("MdAdapter: MD extraction successful", filename=filename, length=len(text))
            return text, extraction_metadata
        except Exception as e:
            raise self._handle_extraction_error(e, filename, "MdAdapter")
```

## File: `app\infrastructure\extractors\pdf_adapter.py`
```py
import fitz  # PyMuPDF
import structlog
from typing import List, Tuple, Dict, Any, Union

from app.application.ports.extraction_port import ExtractionPort, ExtractionError, UnsupportedContentTypeError
from app.infrastructure.extractors.base_extractor import BaseExtractorAdapter


log = structlog.get_logger(__name__)

class PdfAdapter(BaseExtractorAdapter):
    """Adaptador para extraer texto de archivos PDF usando PyMuPDF."""

    SUPPORTED_CONTENT_TYPES = ["application/pdf"]

    def extract_text(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> Tuple[List[Tuple[int, str]], Dict[str, Any]]:
        if content_type not in self.SUPPORTED_CONTENT_TYPES:
            raise UnsupportedContentTypeError(f"PdfAdapter does not support content type: {content_type}")

        log.debug("PdfAdapter: Extracting text and pages from PDF bytes", filename=filename)
        pages_content: List[Tuple[int, str]] = []
        extraction_metadata: Dict[str, Any] = {"total_pages_extracted": 0}
        total_pages_in_doc = 0

        try:
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                total_pages_in_doc = len(doc)
                log.info("PdfAdapter: Processing PDF document", filename=filename, num_pages_in_doc=total_pages_in_doc)
                for page_num_zero_based, page in enumerate(doc):
                    page_num_one_based = page_num_zero_based + 1
                    try:
                        page_text = page.get_text("text")
                        if page_text and not page_text.isspace():
                            pages_content.append((page_num_one_based, page_text))
                            log.debug("PdfAdapter: Extracted text from page", page=page_num_one_based, length=len(page_text))
                        else:
                            log.debug("PdfAdapter: Skipping empty or whitespace-only page", page=page_num_one_based)
                    except Exception as page_err:
                        log.warning("PdfAdapter: Error extracting text from PDF page", filename=filename, page=page_num_one_based, error=str(page_err))
                
                extraction_metadata["total_pages_extracted"] = len(pages_content)
                log.info("PdfAdapter: PDF extraction successful", filename=filename, pages_with_text=len(pages_content), total_doc_pages=total_pages_in_doc)
                return pages_content, extraction_metadata
        except Exception as e:
            raise self._handle_extraction_error(e, filename, "PdfAdapter")
```

## File: `app\infrastructure\extractors\txt_adapter.py`
```py
import structlog
from typing import Tuple, Dict, Any, Union, List

from app.application.ports.extraction_port import ExtractionPort, ExtractionError, UnsupportedContentTypeError
from app.infrastructure.extractors.base_extractor import BaseExtractorAdapter

log = structlog.get_logger(__name__)

class TxtAdapter(BaseExtractorAdapter):
    """Adaptador para extraer texto de archivos TXT."""

    SUPPORTED_CONTENT_TYPES = ["text/plain"]

    def extract_text(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        encoding: str = "utf-8" # Default encoding
    ) -> Tuple[str, Dict[str, Any]]:
        if content_type not in self.SUPPORTED_CONTENT_TYPES:
            raise UnsupportedContentTypeError(f"TxtAdapter does not support content type: {content_type}")

        log.debug("TxtAdapter: Extracting text from TXT bytes", filename=filename, encoding=encoding)
        extraction_metadata: Dict[str, Any] = {}
        try:
            # Try common encodings if default utf-8 fails
            encodings_to_try = [encoding, 'latin-1', 'iso-8859-1', 'cp1252']
            text = None
            for enc in encodings_to_try:
                try:
                    text = file_bytes.decode(enc)
                    log.info(f"TxtAdapter: Successfully decoded with {enc}", filename=filename)
                    extraction_metadata["encoding_used"] = enc
                    break
                except UnicodeDecodeError:
                    log.debug(f"TxtAdapter: Failed to decode with {enc}, trying next.", filename=filename)
                    continue
            
            if text is None:
                log.error("TxtAdapter: Could not decode TXT file with tried encodings.", filename=filename)
                raise ExtractionError(f"Could not decode TXT file {filename} with tried encodings.")

            log.info("TxtAdapter: TXT extraction successful", filename=filename, length=len(text))
            return text, extraction_metadata
        except Exception as e:
            if not isinstance(e, ExtractionError): # Avoid re-wrapping known ExtractionError
                raise self._handle_extraction_error(e, filename, "TxtAdapter")
            raise e
```

## File: `app\main.py`
```py
# File: app/main.py (Reemplazado)
import sys
import os
import json
import uuid
import tempfile
import pathlib
import asyncio
import structlog
from typing import Dict, Any

# Configurar logging primero que nada
from app.core.logging_config import setup_logging
setup_logging()

from app.core.config import settings
from app.services.kafka_clients import KafkaConsumerClient, KafkaProducerClient
from app.services.s3_client import S3Client, S3ClientError
from app.application.use_cases.process_document_use_case import ProcessDocumentUseCase
from app.dependencies import get_process_document_use_case # Reutilizamos el inyector

log = structlog.get_logger(__name__)

def main():
    """Punto de entrada principal para el worker de procesamiento de documentos."""
    log.info("Initializing DocProc Worker...", config=settings.model_dump(exclude=['SUPPORTED_CONTENT_TYPES']))

    try:
        consumer = KafkaConsumerClient(topics=[settings.KAFKA_INPUT_TOPIC])
        producer = KafkaProducerClient()
        s3_client = S3Client()
        use_case: ProcessDocumentUseCase = get_process_document_use_case()
    except Exception as e:
        log.critical("Failed to initialize worker dependencies", error=str(e), exc_info=True)
        sys.exit(1)

    log.info("Worker initialized successfully. Starting message consumption loop...")
    
    try:
        for msg in consumer.consume():
            process_message(msg, s3_client, use_case, producer)
            consumer.commit(message=msg)
    except KeyboardInterrupt:
        log.info("Shutdown signal received.")
    except Exception as e:
        log.critical("Critical error in consumer loop. Exiting.", error=str(e), exc_info=True)
    finally:
        log.info("Closing worker resources...")
        consumer.close()
        producer.flush()
        log.info("Worker shut down gracefully.")


def process_message(msg, s3_client: S3Client, use_case: ProcessDocumentUseCase, producer: KafkaProducerClient):
    """Procesa un único mensaje de Kafka."""
    try:
        event_data = json.loads(msg.value().decode('utf-8'))
        log_context = {
            "kafka_topic": msg.topic(),
            "kafka_partition": msg.partition(),
            "kafka_offset": msg.offset(),
            "document_id": event_data.get("document_id"),
            "company_id": event_data.get("company_id"),
        }
        msg_log = log.bind(**log_context)
        msg_log.info("Received new message to process.")

        s3_path = event_data.get("s3_path")
        document_id = event_data.get("document_id")
        content_type = guess_content_type(s3_path) # Inferir de la ruta/nombre de archivo

        if not all([s3_path, document_id, content_type]):
            msg_log.error("Message is missing required fields: s3_path, document_id, or content_type cannot be inferred.")
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = pathlib.Path(temp_dir) / os.path.basename(s3_path)
            s3_client.download_file_sync(s3_path, str(local_path))
            file_bytes = local_path.read_bytes()

        msg_log.info("File downloaded from S3, proceeding with processing.", file_size=len(file_bytes))
        
        # Ejecutar el caso de uso asíncrono
        process_response_data = asyncio.run(use_case.execute(
            file_bytes=file_bytes,
            original_filename=os.path.basename(s3_path),
            content_type=content_type,
            document_id_trace=document_id
        ))

        # Producir un mensaje por cada chunk
        chunks = process_response_data.chunks
        msg_log.info(f"Document processed. Found {len(chunks)} chunks to produce.")
        
        for i, chunk in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            page_number = chunk.source_metadata.page_number
            
            output_payload = {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "text": chunk.text,
                "page": page_number if page_number is not None else -1
            }
            producer.produce(
                topic=settings.KAFKA_OUTPUT_TOPIC,
                key=document_id, # Particionar por document_id para mantener el orden de los chunks
                value=output_payload
            )

        msg_log.info("All chunks produced to output topic.", num_chunks=len(chunks))

    except json.JSONDecodeError:
        log.error("Failed to decode Kafka message value", raw_value=msg.value())
    except S3ClientError as e:
        log.error("Failed to process message due to S3 error", error=str(e), exc_info=True)
    except Exception as e:
        log.error("Unhandled error processing message", error=str(e), exc_info=True)


def guess_content_type(filename: str) -> Optional[str]:
    """Intenta adivinar el content-type a partir de la extensión del archivo."""
    import mimetypes
    content_type, _ = mimetypes.guess_type(filename)
    if content_type is None:
        if filename.lower().endswith('.md'):
            return 'text/markdown'
    return content_type


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
        if err is not None:
            self.log.error(f"Message delivery failed to topic '{msg.topic()}'", error=str(err))
        else:
            self.log.debug(f"Message delivered to {msg.topic()} [{msg.partition()}]")

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
            'enable.auto.commit': False,  # Commits manuales para procesar "at-least-once"
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
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        self.log.error("Kafka consumer error", error=msg.error())
                        raise KafkaException(msg.error())
                
                # Mensaje válido recibido, lo entregamos para procesar
                yield msg
                
                # Una vez procesado (fuera de esta función), se hace commit.
                # Aquí simulamos el commit después de yield
                self.consumer.commit(asynchronous=True)
                
        except KeyboardInterrupt:
            self.log.info("Consumer loop interrupted by user.")
        finally:
            self.close()

    def commit(self, message: Any):
        """Commits the offset for the given message."""
        self.consumer.commit(message=message, asynchronous=False)

    def close(self):
        self.log.info("Closing Kafka consumer...")
        self.consumer.close()
```

## File: `app\services\s3_client.py`
```py
# File: app/services/s3_client.py
import boto3
from botocore.exceptions import ClientError
import structlog
from typing import Optional

from app.core.config import settings

log = structlog.get_logger(__name__)

class S3ClientError(Exception):
    pass

class S3Client:
    """Synchronous client to interact with Amazon S3."""

    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket_name = bucket_name or settings.AWS_S3_BUCKET_NAME
        self.s3_client = boto3.client("s3", region_name=settings.AWS_REGION)
        self.log = log.bind(s3_bucket=self.bucket_name, aws_region=settings.AWS_REGION)

    def download_file_sync(self, object_name: str, download_path: str):
        """Downloads a file from S3 to a local path."""
        self.log.info("Downloading file from S3...", object_name=object_name, target_path=download_path)
        try:
            self.s3_client.download_file(self.bucket_name, object_name, download_path)
            self.log.info("File downloaded successfully from S3.", object_name=object_name)
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                self.log.error("Object not found in S3", object_name=object_name)
                raise S3ClientError(f"Object not found in S3: {object_name}") from e
            else:
                self.log.error("S3 download failed", error_code=e.response.get("Error", {}).get("Code"), error=str(e))
                raise S3ClientError(f"S3 error downloading {object_name}") from e
```

## File: `pyproject.toml`
```toml
# File: pyproject.toml
[tool.poetry]
name = "docproc-service"
version = "2.0.0-refactor"
description = "Atenex Document Processing Worker (Kafka Consumer/Producer)"
authors = ["Atenex Team <dev@atenex.com>"]
readme = "README.md"

[tool.poetry.dependencies]
python = ">=3.10,<3.13"
pydantic = {extras = ["email"], version = "^2.6.4"}
pydantic-settings = "^2.2.1"
structlog = "^24.1.0"
httpx = "^0.27.0"

# --- AWS and Kafka Clients ---
boto3 = "^1.34.0"
confluent-kafka = "^2.4.0"

# --- Extraction Libraries (se mantienen) ---
pymupdf = "^1.25.0"
python-docx = ">=1.1.0,<2.0.0"
markdown = ">=3.5.1,<4.0.0"
beautifulsoup4 = ">=4.12.3,<5.0.0"
html2text = ">=2024.1.0,<2025.0.0"
pandas = "^2.2.0"
openpyxl = "^3.1.0"
tabulate = "^0.9.0"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.4"
pytest-asyncio = "^0.21.1"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```
