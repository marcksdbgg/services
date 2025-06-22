# File: ingest-service/app/api/v1/schemas.py
import uuid
from pydantic import BaseModel, Field

class ErrorDetail(BaseModel):
    """Schema for error details in responses."""
    detail: str

class IngestResponse(BaseModel):
    """
    Schema for the response after successfully receiving a document
    and sending an event to Kafka.
    """
    document_id: uuid.UUID
    status: str = Field(description="Indicates the event status.")
    message: str = Field(description="A descriptive message about the outcome.")

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "Event-Sent",
                "message": "Document received and processing event sent to Kafka."
            }
        }