import asyncio
import logging

from .. import config
from .fiware import FiwareClient

log: logging.Logger = logging.getLogger("automation")


class Automation:
    def __init__(self, fw: FiwareClient, retry_after: float | None = None) -> None:
        self._fw: FiwareClient = fw
        self._retry_after: float = (
            config.AUTOMATION_RETRY_SECONDS if retry_after is None else retry_after
        )
        self._sent: dict[str, tuple[str, float]] = {}
        self._tasks: set[asyncio.Task] = set()

    async def apply(self, entity): ...
