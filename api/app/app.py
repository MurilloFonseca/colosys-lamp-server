from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .common.exeptions import FiwareError, KeyrockError

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


class AppCreator:
    def __init__(self, router: APIRouter, lifespan: Lifespan | None = None) -> None:
        self.app = FastAPI(title="Colosys Back-end", lifespan=lifespan)

        if config.CORS_ORIGINS:
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=config.CORS_ORIGINS,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        self.app.include_router(router)

        @self.app.exception_handler(KeyrockError)
        async def keyrock_error_handler(_: Request, exc: KeyrockError) -> JSONResponse:
            if exc.status in (400, 409):
                return JSONResponse({"detail": exc.message}, status_code=exc.status)

            return JSONResponse({"detail": "Identity service error"}, status_code=502)

        @self.app.exception_handler(FiwareError)
        async def fiware_error_handler(_: Request, exc: FiwareError) -> JSONResponse:
            if exc.status == 409:
                return JSONResponse({"detail": exc.message}, status_code=409)

            if exc.status == 503:
                return JSONResponse(
                    {"detail": "FIWARE is unavailable"}, status_code=503
                )

            return JSONResponse({"detail": "FIWARE error"}, status_code=502)

        @self.app.exception_handler(RequestValidationError)
        async def validation_error_handler(
            _: Request, exc: RequestValidationError
        ) -> JSONResponse:
            """422 without echoing the offending input.

            FastAPI's default answer includes each rejected value. That would send a rejected password
            back in the response body, and it cannot even be encoded when the value is Infinity (the
            request then ends in a 500).
            """
            errors: list[dict[str, Any]] = [
                {
                    "loc": list(e.get("loc", ())),
                    "msg": e.get("msg", ""),
                    "type": e.get("type", ""),
                }
                for e in exc.errors()
            ]

            return JSONResponse({"detail": errors}, status_code=422)

        @self.app.exception_handler(httpx.HTTPError)
        async def http_error_handler(_: Request, exc: httpx.HTTPError) -> JSONResponse:
            return JSONResponse(
                {"detail": "Identity service unavailable"}, status_code=502
            )
