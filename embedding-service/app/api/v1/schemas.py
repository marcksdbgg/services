from typing import Optional
from pydantic import BaseModel

class ModelInfo(BaseModel):
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
