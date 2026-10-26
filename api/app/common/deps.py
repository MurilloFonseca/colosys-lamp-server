"""Shared FastAPI dependencies."""

from fastapi import Depends, HTTPException, Request

from .. import config
from ..core.automation import Automation
from ..core.fiware import FiwareClient
from ..core.hub import Hub
from ..core.keyrock import KeyrockClient, User


def get_kr(request: Request) -> KeyrockClient:
    return request.app.state.kr


def get_hub(request: Request) -> Hub:
    return request.app.state.hub


def get_automation(request: Request) -> Automation:
    return request.app.state.automation


def get_fiware(request: Request) -> FiwareClient:
    """FIWARE is bootstrapped in the background, so it may not be ready right after start."""
    if not request.app.state.fiware_ready:
        raise HTTPException(
            status_code=503, detail="FIWARE is not ready yet, try again shortly"
        )

    return request.app.state.fw


async def current_user(request: Request, kr: KeyrockClient = Depends(get_kr)) -> User:
    token: str | None = request.cookies.get(config.COOKIE_NAME)
    user: User | None = await kr.get_user(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return user
