from pydantic import BaseModel, EmailStr, Field


class HealthResponse(BaseModel):
    status: str
    fiware: bool
    history: bool


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: str
    username: str | None = None
    email: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
