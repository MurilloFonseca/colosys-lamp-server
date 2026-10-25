from fastapi import FastAPI

from .app import AppCreator
from .lifespan import lifespan
from .router import router


def main() -> FastAPI:
    app_creator = AppCreator(router, lifespan=lifespan)

    return app_creator.app


app: FastAPI = main()
