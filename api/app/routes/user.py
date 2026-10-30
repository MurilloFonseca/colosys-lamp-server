import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import config
from ..common.deps import current_user, get_kr
from ..common.schemas import LoginIn, RegisterIn, UserOut
from ..core.keyrock import KeyrockClient, LoginResponse, User

user_router = APIRouter()


# Very small in-memory brute-force guard (per client IP + e-mail, single process).
_FAILS: dict[str, list[float]] = {}
MAX_FAILS, WINDOW = 5, 300


def _locked(key: str) -> bool:
    now: float = time.monotonic()

    if len(_FAILS) > 10_000:
        _FAILS.clear()

    recent: list[float] = [t for t in _FAILS.get(key, []) if now - t < WINDOW]

    _FAILS[key] = recent
    return len(recent) >= MAX_FAILS


# --- Routes -----------------------------------------------------------------
@user_router.post("/api/users", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, kr: KeyrockClient = Depends(get_kr)) -> UserOut:
    user: User = await kr.create_user(body.username, body.email, body.password)

    return UserOut(**user)


@user_router.post("/api/auth/login", response_model=UserOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    kr: KeyrockClient = Depends(get_kr),
) -> UserOut:
    key: str = f"{request.client.host if request.client else '?'}:{body.email.lower()}"

    if _locked(key):
        raise HTTPException(
            status_code=429, detail="Too many failed attempts, try again later"
        )

    tokens: LoginResponse | None = await kr.password_login(body.email, body.password)

    if not tokens:
        _FAILS.setdefault(key, []).append(time.monotonic())
        raise HTTPException(status_code=401, detail="Invalid e-mail or password")

    _FAILS.pop(key, None)

    access_token: str = tokens["access_token"]
    user: User | None = await kr.get_user(access_token)

    if not user:
        raise HTTPException(status_code=502, detail="Could not read the logged-in user")

    response.set_cookie(
        config.COOKIE_NAME,
        access_token,
        max_age=int(tokens.get("expires_in", 3600)),
        httponly=True,  # JavaScript cannot read it
        samesite="none",
        secure=config.COOKIE_SECURE,
        path="/",
    )

    return UserOut(**user)


@user_router.post("/api/auth/logout")
async def logout(
    request: Request, response: Response, kr: KeyrockClient = Depends(get_kr)
) -> dict[str, bool]:
    token: str | None = request.cookies.get(config.COOKIE_NAME)

    if token:
        kr.forget_token(token)

    response.delete_cookie(config.COOKIE_NAME, path="/")
    return {"ok": True}


@user_router.get("/api/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(**user)
