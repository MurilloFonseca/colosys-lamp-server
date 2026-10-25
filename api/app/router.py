from fastapi import APIRouter, Request

from .common.schemas import HealthResponse
from .routes.lamp import lamp_router
from .routes.user import user_router

router = APIRouter()
router.include_router(user_router)
router.include_router(lamp_router)


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        fiware=request.app.state.fiware_ready,
        history=request.app.state.history_ready,
    )
