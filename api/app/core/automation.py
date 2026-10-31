import asyncio
import logging
import time
from typing import Literal

from .. import config
from ..common.exeptions import FiwareError
from .fiware import ENTITY_PREFIX, FiwareClient, Lamp, Thresholds

log: logging.Logger = logging.getLogger("automation")


MEASURES = ("luminosity", "temperature", "humidity")


def out_of_limits(thresholds: Thresholds, readings: Lamp) -> list[str]:
    reasons: list[str] = []
    for measure in MEASURES:
        value: float | None = readings.get(measure)

        if value is None:
            continue

        low: float | None = thresholds[measure]["min"]
        high: float | None = thresholds[measure]["max"]

        if low is not None and value < low:
            reasons.append(f"{measure} {value:g} < min {low:g}")

        elif high is not None and value > high:
            reasons.append(f"{measure} {value:g} > max {high:g}")

    return reasons


def desired_state(entity: Lamp) -> tuple[Literal["on", "off"] | None, list[str]]:
    if all(entity.get(measure) is None for measure in MEASURES):
        return None, []

    reasons: list[str] = out_of_limits(entity.get("thresholds"), entity)
    return ("on" if reasons else "off"), reasons


class Automation:
    def __init__(self, fw: FiwareClient, retry_after: float | None = None) -> None:
        self._fw: FiwareClient = fw
        self._retry_after: float = (
            config.AUTOMATION_RETRY_SECONDS if retry_after is None else retry_after
        )
        self._sent: dict[str, tuple[str, float]] = {}
        self._tasks: set[asyncio.Task] = set()

    async def apply(self, entity: Lamp) -> None | Literal["on", "off"]:
        entity_id: str = entity.get("id", "")
        command, reasons = desired_state(entity)

        if command is None:
            return None

        if entity.get("state", "").lower() == command:
            self._sent.pop(entity_id, None)  # already as wanted
            return None

        now: float = time.monotonic()
        previous: tuple[str, float] | None = self._sent.get(entity_id)
        if (
            previous
            and previous[0] == command
            and now - previous[1] < self._retry_after
        ):
            return None  # already asked: give the device time to answer

        # Remember BEFORE awaiting, so a concurrent notification for the same lamp sees it.
        if len(self._sent) > 10_000:
            self._sent.clear()

        self._sent[entity_id] = (command, now)
        try:
            await self._fw.send_command(entity_id, command)

        except FiwareError:
            self._sent.pop(entity_id, None)
            raise

        log.info(
            "Lamp %s -> %s (%s)",
            entity_id.removeprefix(ENTITY_PREFIX),
            command,
            "; ".join(reasons) or "all values within limits",
        )

        return command

    def schedule(self, entity: Lamp) -> None:
        task: asyncio.Task[None] = asyncio.create_task(self._run(entity))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, entity: Lamp) -> None:
        try:
            await self.apply(entity)

        except FiwareError as exc:
            log.warning("Could not command %s: %s", entity.get("id"), exc.message)

        except Exception:
            log.exception("Automation failed for %s", entity.get("id"))

    def forget(self, entity_id: str) -> None:
        self._sent.pop(entity_id, None)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
