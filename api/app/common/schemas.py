from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    fiware: bool
    history: bool
