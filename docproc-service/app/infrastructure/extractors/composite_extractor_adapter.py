# File: app/infrastructure/extractors/composite_extractor_adapter.py
from typing import Dict, Any, Tuple, Union, List
import structlog

from app.application.ports.extraction_port import ExtractionPort, UnsupportedContentTypeError, ExtractionError
from .base_extractor import BaseExtractorAdapter

log = structlog.get_logger(__name__)

class CompositeExtractorAdapter(BaseExtractorAdapter):
    """
    Un adaptador compuesto que delega la extracción al adaptador apropiado
    basado en el content_type.
    """
    def __init__(self, extractors: Dict[str, ExtractionPort]):
        """
        Inicializa el adaptador compuesto con un mapeo de content_type a extractor.
        
        Args:
            extractors: Un diccionario donde las claves son content_types (ej. "application/pdf")
                        y los valores son instancias de adaptadores de extracción.
        """
        self.extractors = extractors
        self.log = log.bind(component="CompositeExtractorAdapter")
        self.log.info("Initialized with supported content types", types=list(extractors.keys()))

    def extract_text(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> Tuple[Union[str, List[Tuple[int, str]]], Dict[str, Any]]:
        """
        Delega la extracción al adaptador correcto.
        """
        self.log.debug("Delegating extraction", filename=filename, content_type=content_type)
        
        # Normalizar content_type por si acaso (ej. con parámetros charset)
        normalized_content_type = content_type.split(';')[0].strip().lower()

        extractor = self.extractors.get(normalized_content_type)

        if not extractor:
            # Manejar tipos que son alias (ej. doc/docx)
            if normalized_content_type == "application/msword":
                extractor = self.extractors.get("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            elif normalized_content_type == "application/vnd.ms-excel":
                 extractor = self.extractors.get("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        if not extractor:
            self.log.warning("Unsupported content type for composite extraction", content_type=content_type)
            raise UnsupportedContentTypeError(f"No extractor registered for content type: {content_type}")
            
        try:
            return extractor.extract_text(file_bytes, filename, content_type)
        except ExtractionError:
            raise # Re-raise errores específicos de la extracción
        except Exception as e:
            # Capturar cualquier otro error inesperado del adaptador subyacente
            raise self._handle_extraction_error(e, filename, f"CompositeAdapter -> {type(extractor).__name__}")