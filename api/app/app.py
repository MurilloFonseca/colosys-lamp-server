from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config

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
