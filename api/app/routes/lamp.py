import asyncio
import contextlib
import hmac
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Literal, TypedDict

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from fastapi.responses import StreamingResponse

from .. import config
from ..common.deps import current_user, get_automation, get_fiware, get_hub
from ..common.exeptions import FiwareError
from ..common.schemas import (
    DEVICE_ID_PATTERN,
    DeviceInfo,
    LampCreate,
    LampCreated,
    LampHistory,
    LampOut,
    LampThresholds,
    ThresholdsPut,
)
from ..core.automation import Automation
from ..core.fiware import ENTITY_PREFIX, FiwareClient, Lamp, Point, Thresholds
from ..core.hub import Event, EventPayload, Hub, UpsertEvent
from ..core.keyrock import User

lamp_router = APIRouter()

log: logging.Logger = logging.getLogger("lamps")


class NotificationPayload(TypedDict):
    subscriptionId: str
    data: list[Lamp]


def format_lamp(entity: Lamp) -> UpsertEvent:
    return {
        "id": entity["id"],
        "deviceId": entity["id"].removeprefix(ENTITY_PREFIX),
        "name": entity.get("name"),
        "state": entity.get("state"),
        "luminosity": entity.get("luminosity"),
        "temperature": entity.get("temperature"),
        "humidity": entity.get("humidity"),
        "thresholds": entity.get("thresholds"),
        "commandStatus": {
            "on": entity.get("on_status"),
            "off": entity.get("off_status"),
        },
    }


def device_info(device_id: str) -> DeviceInfo:
    base: str = f"/{config.IOTA_API_KEY}/{device_id}"

    return DeviceInfo(
        deviceId=device_id,
        apiKey=config.IOTA_API_KEY,
        mqttHost=config.MQTT_HOST,
        mqttPort=config.MQTT_PORT,
        topics={
            "attrs": f"{base}/attrs",
            "cmd": f"{base}/cmd",
            "cmdexe": f"{base}/cmdexe",
        },
        examplePayload="l|42|t|23.5|h|60|s|off",
    )


async def _owned_lamp(fw: FiwareClient, device_id: str, user: User) -> Lamp:
    entity: Lamp | None = await fw.get_entity(ENTITY_PREFIX + device_id)

    if not entity or entity.get("owner") != user["id"]:
        raise HTTPException(status_code=404, detail="Lamp not found")

    return entity


def _sse(event: str, data: EventPayload | list[EventPayload]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def to_thresholds(thresholds: ThresholdsPut) -> Thresholds:
    return {
        "humidity": {
            "min": thresholds.humidity.min,
            "max": thresholds.humidity.max,
        },
        "luminosity": {
            "min": thresholds.luminosity.min,
            "max": thresholds.luminosity.max,
        },
        "temperature": {
            "min": thresholds.temperature.min,
            "max": thresholds.temperature.max,
        },
    }


# --- Routes -----------------------------------------------------------------
@lamp_router.post("/api/lamps", response_model=LampCreated, status_code=201)
async def register_lamp(
    body: LampCreate,
    user: User = Depends(current_user),
    hub: Hub = Depends(get_hub),
    fw: FiwareClient = Depends(get_fiware),
) -> LampCreated:
    created_at: datetime = datetime.now()
    device_id: str = body.device_id
    entity_id: str = ENTITY_PREFIX + device_id

    if await fw.get_entity(entity_id) is not None:
        raise FiwareError(409, f"Device id '{device_id}' is already registered")

    await fw.provision_device(device_id, entity_id)

    try:
        await fw.upsert_lamp(entity_id, body.name, user["id"], created_at)

        entity: Lamp | None = await fw.get_entity(entity_id)

    except Exception:
        with contextlib.suppress(Exception):
            await fw.delete_device(device_id)

        raise

    if entity is None:
        raise HTTPException(
            status_code=502, detail="Lamp was created but could not be read back"
        )

    delivered: int = hub.publish(user["id"], ("upsert", format_lamp(entity)))

    log.info(
        "Lamp %s registered for user %s -> %d open stream(s)",
        device_id,
        user["id"],
        delivered,
    )

    formatted: UpsertEvent = format_lamp(entity)

    print(f"\n\n{formatted = }\n\n")

    return LampCreated(**formatted, device=device_info(device_id))


@lamp_router.get("/api/lamps", response_model=list[LampOut])
async def list_lamps(
    user: User = Depends(current_user), fw: FiwareClient = Depends(get_fiware)
) -> list[LampOut]:
    return [LampOut(**format_lamp(e)) for e in await fw.list_lamps(user["id"])]


@lamp_router.get("/api/lamps/stream")
async def stream_lamps(
    request: Request,
    user: User = Depends(current_user),
    fw: FiwareClient = Depends(get_fiware),
    hub: Hub = Depends(get_hub),
) -> StreamingResponse:
    queue: asyncio.Queue[Event] = hub.subscribe(user["id"])

    async def events() -> AsyncGenerator[str, None]:
        try:
            try:
                yield _sse(
                    "snapshot",
                    [format_lamp(e) for e in await fw.list_lamps(user["id"])],
                )

            except FiwareError as exc:
                log.warning("SSE snapshot failed: %s", exc.message)

                yield _sse("snapshot", [])

            while not await request.is_disconnected():
                try:
                    event: Event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield _sse(*event)

                except TimeoutError:
                    yield ": ping\n\n"

        finally:
            hub.unsubscribe(user["id"], queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@lamp_router.get("/api/lamps/{device_id}", response_model=LampOut)
async def get_lamp(
    device_id: str = Path(pattern=DEVICE_ID_PATTERN),
    user: User = Depends(current_user),
    fw: FiwareClient = Depends(get_fiware),
) -> LampOut:
    return LampOut(**format_lamp(await _owned_lamp(fw, device_id, user)))


@lamp_router.delete("/api/lamps/{device_id}", status_code=204)
async def delete_lamp(
    device_id: str = Path(pattern=DEVICE_ID_PATTERN),
    user: User = Depends(current_user),
    hub: Hub = Depends(get_hub),
    fw: FiwareClient = Depends(get_fiware),
    automation: Automation = Depends(get_automation),
) -> Response:
    entity_id: str = ENTITY_PREFIX + device_id

    await _owned_lamp(fw, device_id, user)
    await fw.delete_device(device_id)
    await fw.delete_entity(entity_id)

    automation.forget(entity_id)

    try:
        await fw.delete_history(entity_id)

    except FiwareError as exc:
        log.warning(
            "Could not purge the STH-Comet history of %s: %s", device_id, exc.message
        )

    delivered: int = hub.publish(
        user["id"], ("delete", {"id": entity_id, "deviceId": device_id})
    )

    log.info("Lamp %s deleted -> %d open stream(s)", device_id, delivered)

    return Response(status_code=204)


@lamp_router.get("/api/lamps/{device_id}/history", response_model=LampHistory)
async def lamp_history(
    device_id: str = Path(pattern=DEVICE_ID_PATTERN),
    limit: int = Query(default=config.HISTORY_SIZE, ge=1, le=config.HISTORY_SIZE),
    user: User = Depends(current_user),
    fw: FiwareClient = Depends(get_fiware),
) -> LampHistory:
    entity: Lamp = await _owned_lamp(fw, device_id, user)

    since: datetime = datetime.fromisoformat(entity.get("createdAt"))

    try:
        points: list[Point] = await fw.get_history(entity["id"], limit, since)

    except FiwareError as exc:
        log.warning("History of %s unavailable: %s", device_id, exc.message)

        raise HTTPException(
            status_code=503, detail="History is unavailable right now"
        ) from exc

    return LampHistory(deviceId=device_id, limit=limit, points=points)


@lamp_router.get("/api/lamps/{device_id}/thresholds", response_model=LampThresholds)
async def get_thresholds(
    device_id: str = Path(pattern=DEVICE_ID_PATTERN),
    user: User = Depends(current_user),
    fw: FiwareClient = Depends(get_fiware),
) -> LampThresholds:
    entity: Lamp = await _owned_lamp(fw, device_id, user)

    return LampThresholds(deviceId=device_id, thresholds=entity.get("thresholds"))


@lamp_router.put("/api/lamps/{device_id}/thresholds", response_model=LampThresholds)
async def replace_thresholds(
    body: ThresholdsPut,
    device_id: str = Path(pattern=DEVICE_ID_PATTERN),
    user: User = Depends(current_user),
    fw: FiwareClient = Depends(get_fiware),
    hub: Hub = Depends(get_hub),
    automation: Automation = Depends(get_automation),
) -> LampThresholds:
    entity: Lamp = await _owned_lamp(fw, device_id, user)

    new_thresholds: Thresholds = to_thresholds(body)

    await fw.update_thresholds(entity["id"], new_thresholds)

    entity: Lamp = {**entity, "thresholds": new_thresholds}

    hub.publish(user["id"], ("upsert", format_lamp(entity)))

    command = None

    try:
        command: None | Literal["on", "off"] = await automation.apply(entity)

    except FiwareError as exc:
        log.warning(
            "Limits saved, but the command failed for %s: %s", device_id, exc.message
        )

    return LampThresholds(
        deviceId=device_id, thresholds=new_thresholds, command=command
    )


@lamp_router.post("/internal/orion/notify", status_code=204, include_in_schema=False)
async def orion_notify(
    request: Request,
    x_notify_token: str | None = Header(default=None),
    hub: Hub = Depends(get_hub),
    automation: Automation = Depends(get_automation),
) -> Response:
    if not x_notify_token or not hmac.compare_digest(
        x_notify_token.encode(), config.NOTIFY_TOKEN.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid notification token")

    try:
        payload: NotificationPayload = await request.json()

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None

    received: str = datetime.now(UTC).isoformat(timespec="milliseconds")
    entities: list[Lamp] = payload.get("data", [])

    for entity in entities:
        owner: str = entity.get("owner")
        entity_id: str = entity.get("id", "")

        if not owner or not entity_id.startswith(ENTITY_PREFIX):
            log.warning(
                "Ignoring notification for %r (no owner or not a lamp)", entity_id
            )
            continue

        delivered: int = hub.publish(
            owner, ("reading", {**format_lamp(entity), "receivedAt": received})
        )

        log.info("Reading %s -> %d open stream(s)", entity_id, delivered)

        automation.schedule(entity)

    return Response(status_code=204)
