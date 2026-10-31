import asyncio
import logging
from _asyncio import Task
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from . import config
from .core.automation import Automation
from .core.fiware import FiwareClient
from .core.hub import Hub
from .core.keyrock import KeyrockClient

log: logging.Logger = logging.getLogger("api")


async def _fiware_loop(app: FastAPI) -> None:
    fw: FiwareClient = app.state.fw

    while True:
        delay = 120
        try:
            await fw.ensure_service_group()
            await fw.ensure_subscription()
            if not app.state.fiware_ready:
                log.info("FIWARE is ready")

            app.state.fiware_ready = True
        except asyncio.CancelledError:
            raise

        except Exception as exc:
            if app.state.fiware_ready:
                log.warning("Lost contact with FIWARE: %s", exc)

            else:
                log.info("Waiting for FIWARE: %s", exc)

            app.state.fiware_ready = False
            app.state.history_ready = False
            delay = 5

        else:
            try:
                await fw.ensure_history_subscription()
                if not app.state.history_ready:
                    log.info("History (STH-Comet subscription) is ready")

                app.state.history_ready = True

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                log.warning("History subscription not ready: %s", exc)
                app.state.history_ready = False
                delay = 15

        await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with httpx.AsyncClient(timeout=10.0) as http:
        kr = KeyrockClient(
            http, config.KEYROCK_URL, config.ADMIN_EMAIL, config.ADMIN_PASSWORD
        )
        await kr.wait_until_ready()
        await kr.ensure_application(
            name="smartlamp-api",
            url=config.APP_URL,
            redirect_uri=f"{config.APP_URL}/auth/callback",
            credentials_file=config.CREDENTIALS_FILE,
            env_client_id=config.CLIENT_ID,
            env_client_secret=config.CLIENT_SECRET,
        )
        app.state.kr = kr
        app.state.hub = Hub()
        app.state.fw = FiwareClient(http)
        app.state.automation = Automation(app.state.fw)
        app.state.fiware_ready = False
        app.state.history_ready = False

        task: Task[None] = asyncio.create_task(_fiware_loop(app))
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await app.state.automation.close()
