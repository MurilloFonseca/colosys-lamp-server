from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from ..core.fiware import Thresholds
from ..core.hub import CommandStatus

DEVICE_ID_PATTERN = r"^[A-Za-z0-9_-]{3,32}$"


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


class LampCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    device_id: str = Field(pattern=DEVICE_ID_PATTERN)


class LampOut(BaseModel):
    id: str
    deviceId: str
    name: str | None = None
    state: str | None = None
    luminosity: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    thresholds: Thresholds | None = None
    commandStatus: CommandStatus = {"on": None, "off": None}
    receivedAt: str | None = None  # only present on live SSE events


class DeviceInfo(BaseModel):
    deviceId: str
    apiKey: str
    mqttHost: str
    mqttPort: int
    topics: dict[str, str]
    examplePayload: str


class LampCreated(LampOut):
    device: DeviceInfo


class HistoryPoint(BaseModel):
    t: str  # ISO-8601, UTC, milliseconds
    luminosity: float | None = None
    temperature: float | None = None
    humidity: float | None = None


class LampHistory(BaseModel):
    deviceId: str
    limit: int
    points: list[HistoryPoint]  # oldest first


class LampThresholds(BaseModel):
    deviceId: str
    thresholds: Thresholds
    # "on"/"off" if saving the limits made the lamp change
    command: Literal["on", "off"] | None = None


class LimitsIn(BaseModel):
    min: float | None = None
    max: float | None = None


class ThresholdsPut(BaseModel):
    luminosity: LimitsIn
    temperature: LimitsIn
    humidity: LimitsIn
