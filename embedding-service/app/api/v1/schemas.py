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
