import asyncio
from collections import defaultdict
from typing import Literal, TypedDict

from .fiware import Thresholds


class CommandStatus(TypedDict):
    on: Literal["OK", "ERROR", "PENDING", "UNKNOWN"]
    off: Literal["OK", "ERROR", "PENDING", "UNKNOWN"]


class UpsertEvent(TypedDict):
    id: str
    deviceId: str
    name: str
    state: Literal["on", "off"]
    luminosity: float
    temperature: float
    humidity: float
    thresholds: Thresholds
    commandStatus: CommandStatus


class ReadingEvent(TypedDict):
    id: str
    deviceId: str
    name: str
    state: Literal["on", "off"]
    luminosity: float
    temperature: float
    humidity: float
    thresholds: Thresholds
    commandStatus: CommandStatus
    receivedAt: str


class DeleteEvent(TypedDict):
    id: str
    deviceId: str


type EventPayload = UpsertEvent | ReadingEvent | DeleteEvent

type Event = tuple[str, EventPayload]


class Hub:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user_id: str) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        self._subs[user_id].add(queue)

        return queue

    def unsubscribe(self, user_id: str, queue: asyncio.Queue[Event]) -> None:
        self._subs[user_id].discard(queue)

        if not self._subs[user_id]:
            del self._subs[user_id]

    def publish(self, user_id: str, event: Event) -> int:
        queues: list[asyncio.Queue[Event]] = list(self._subs.get(user_id, ()))

        for queue in queues:
            if queue.full():
                queue.get_nowait()

            queue.put_nowait(event)

        return len(queues)
