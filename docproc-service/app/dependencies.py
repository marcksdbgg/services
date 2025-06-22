# File: app/dependencies.py
from app.application.ports.extraction_port import ExtractionPort
from app.application.ports.chunking_port import ChunkingPort
from app.application.use_cases.process_document_use_case import ProcessDocumentUseCase

# Importar implementaciones concretas (Adaptadores)
from app.infrastructure.chunkers.default_chunker_adapter import DefaultChunkerAdapter
from app.infrastructure.extractors import (
    CompositeExtractorAdapter,
    PdfAdapter,
    DocxAdapter,
    TxtAdapter,
    HtmlAdapter,
    MdAdapter,
    ExcelAdapter,
)

def get_process_document_use_case() -> ProcessDocumentUseCase:
    """
    Inicializa y devuelve una instancia del ProcessDocumentUseCase con todas
    sus dependencias concretas inyectadas.
    """
    # 1. Inicializar el adaptador de chunking
    chunking_adapter: ChunkingPort = DefaultChunkerAdapter()

    # 2. Inicializar todos los adaptadores de extracción específicos
    pdf_extractor = PdfAdapter()
    docx_extractor = DocxAdapter()
    txt_extractor = TxtAdapter()
    html_extractor = HtmlAdapter()
    md_extractor = MdAdapter()
    excel_extractor = ExcelAdapter()

    # 3. Crear el adaptador de extracción compuesto
    # Mapea los content types a su extractor correspondiente.
    # Esta es la "inteligencia" que decide qué adaptador usar.
    composite_extractor: ExtractionPort = CompositeExtractorAdapter(
        extractors={
            "application/pdf": pdf_extractor,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": docx_extractor,
            "application/msword": docx_extractor,  # DOCX adapter puede intentar manejar .doc
            "text/plain": txt_extractor,
            "text/html": html_extractor,
            "text/markdown": md_extractor,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": excel_extractor,
            "application/vnd.ms-excel": excel_extractor,
        }
    )

    # 4. Inyectar los adaptadores en el caso de uso
    process_document_use_case = ProcessDocumentUseCase(
        extraction_port=composite_extractor,
        chunking_port=chunking_adapter
    )
    
    return process_document_use_case