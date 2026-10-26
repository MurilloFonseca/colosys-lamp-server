import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, TypedDict
from urllib.parse import quote

import httpx

from .. import config
from ..common.exeptions import FiwareError

log: logging.Logger = logging.getLogger("fiware")


# --- Types ---------------------------------------------------------------------
type Method = Literal["GET", "POST", "DELETE", "PATCH"]

type Row = list[tuple[str, float]]


class IoTError(TypedDict):
    message: str


class OrionError(TypedDict):
    description: str


class STHError(TypedDict):
    error: str


class Threshold(TypedDict):
    min: float | None
    max: float | None


class Thresholds(TypedDict):
    luminosity: Threshold
    humidity: Threshold
    temperature: Threshold


class Lamp(TypedDict):
    id: str
    type: str
    humidity: float
    luminosity: float
    temperature: float
    state: Literal["on", "off"]
    owner: str
    name: str
    thresholds: Thresholds
    on_status: Literal["OK", "ERROR", "PENDING", "UNKNOWN"]
    off_status: Literal["OK", "ERROR", "PENDING", "UNKNOWN"]


class Entity(TypedDict):
    idPattern: str
    type: str


class Condition(TypedDict):
    attrs: list[str]


class Subject(TypedDict):
    entities: list[Entity]
    condition: Condition


class HttpCustom(TypedDict):
    url: str
    headers: dict[str, str]


class Notification(TypedDict):
    attrs: list[str]
    httpCustom: HttpCustom
    attrsFormat: str


class Subscription(TypedDict):
    id: str
    description: str
    status: str
    subject: Subject
    notification: Notification


class CreateSubscriptionBody(TypedDict):
    description: str
    subject: Subject
    notification: Notification


class Value(TypedDict):
    _id: str
    attrValue: float
    attrName: str
    recvTime: str


class History(TypedDict):
    type: str
    value: list[Value]


class Point(TypedDict):
    t: str
    luminosity: float | None
    temperature: float | None
    humidity: float | None


# --- Constants -----------------------------------------------------------------
ENTITY_PREFIX: str = "urn:ngsi-ld:Lamp:"

CONDITION_ATTRS: list[str] = ["luminosity", "temperature", "humidity", "state"]
NOTIFY_ATTRS: list[str] = [
    "owner",
    "name",
    "thresholds",
    "luminosity",
    "temperature",
    "humidity",
    "state",
    "on_status",
    "off_status",
]

HISTORY_ATTRS: list[str] = ["luminosity", "temperature", "humidity"]
SAME_POINT = timedelta(milliseconds=500)


DEFAULT_THRESHOLDS: Thresholds = {
    "luminosity": {"min": 30, "max": None},
    "temperature": {"min": 18, "max": 30},
    "humidity": {"min": 30, "max": 70},
}


# --- Helpers -------------------------------------------------------------------
def _iot_err(res: httpx.Response) -> str:
    err: IoTError = res.json()

    return err.get("message", f"HTTP {res.status_code}")


def _orion_err(res: httpx.Response) -> str:
    err: OrionError = res.json()

    return err.get("description", f"HTTP {res.status_code}")


def _sth_err(res: httpx.Response) -> str:
    err: STHError = res.json()

    return err.get("error", f"HTTP {res.status_code}")


def _eid(entity_id: str) -> str:
    return quote(entity_id, safe=":")


def _sth_rows(data: History) -> Row:
    raw_rows: list[Value] = data["value"]

    return [(r["recvTime"], r["attrValue"]) for r in raw_rows]


def build_points(
    series: dict[str, Row], limit: int, since: datetime | None = None
) -> list[Point]:
    samples: list[tuple[datetime, str, float]] = []

    for attr, rows in series.items():
        for recv_time, value in rows:
            t: datetime = datetime.fromisoformat(recv_time)

            if since is None or t >= since:
                samples.append((t, attr, value))

    samples.sort(key=lambda s: s[0])

    clusters: list[tuple[datetime, dict[str, float]]] = []

    for t, attr, value in samples:
        if (
            clusters
            and attr not in clusters[-1][1]
            and t - clusters[-1][0] <= SAME_POINT
        ):
            clusters[-1][1][attr] = value

        else:
            clusters.append((t, {attr: value}))

    return [
        {
            "t": t.astimezone(UTC).isoformat(timespec="milliseconds"),
            "luminosity": values.get("luminosity"),
            "temperature": values.get("temperature"),
            "humidity": values.get("humidity"),
        }
        for t, values in clusters[-limit::]
    ]


# --- Client --------------------------------------------------------------------
class FiwareClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http: httpx.AsyncClient = http
        self.headers: dict[str, str] = {
            "Fiware-Service": config.FIWARE_SERVICE,
            "Fiware-ServicePath": config.FIWARE_SERVICEPATH,
        }

    async def _req(self, method: Method, url: str, **kwargs) -> httpx.Response:
        try:
            return await self.http.request(
                method,
                url,
                headers=self.headers,
                **kwargs,
            )

        except httpx.HTTPError as exc:
            raise FiwareError(
                503, f"FIWARE unreachable ({url}): {exc.__class__.__name__}"
            ) from exc

    @staticmethod
    def _description() -> str:
        return f"smartlamp-api:{config.NOTIFY_URL}"

    @staticmethod
    def _history_description() -> str:
        return f"smartlamp-history:{config.STH_NOTIFY_URL}"

    # --- IoT Agent -------------------------------------------------------------
    async def ensure_service_group(self) -> None:
        r: httpx.Response = await self._req("GET", f"{config.IOTA_URL}/iot/services")

        if r.status_code != 200:
            raise FiwareError(502, f"IoT Agent: {_iot_err(r)}")

        if any(
            s.get("apikey") == config.IOTA_API_KEY for s in r.json().get("services", [])
        ):
            return

        r: httpx.Response = await self._req(
            "POST",
            f"{config.IOTA_URL}/iot/services",
            json={
                "services": [
                    {
                        "apikey": config.IOTA_API_KEY,
                        "cbroker": config.IOTA_CBROKER,
                        "entity_type": "Lamp",
                        "resource": "",
                    }
                ]
            },
        )

        if r.status_code not in (201, 409):
            raise FiwareError(502, f"IoT Agent service group: {_iot_err(r)}")

        log.info("Created IoT Agent service group (apikey=%s)", config.IOTA_API_KEY)

    async def provision_device(self, device_id: str, entity_id: str) -> None:
        r: httpx.Response = await self._req(
            "POST",
            f"{config.IOTA_URL}/iot/devices",
            json={
                "devices": [
                    {
                        "device_id": device_id,
                        "entity_name": entity_id,
                        "entity_type": "Lamp",
                        "protocol": "PDI-IoTA-UltraLight",
                        "transport": "MQTT",
                        "attributes": [
                            {"object_id": "l", "name": "luminosity", "type": "Number"},
                            {"object_id": "t", "name": "temperature", "type": "Number"},
                            {"object_id": "h", "name": "humidity", "type": "Number"},
                            {"object_id": "s", "name": "state", "type": "Text"},
                        ],
                        "commands": [
                            {"name": "on", "type": "command"},
                            {"name": "off", "type": "command"},
                        ],
                    }
                ]
            },
        )

        if r.status_code == 409:
            raise FiwareError(409, f"Device id '{device_id}' is already registered")

        if r.status_code != 201:
            raise FiwareError(502, f"IoT Agent: {_iot_err(r)}")

    async def delete_device(self, device_id: str) -> None:
        r: httpx.Response = await self._req(
            "DELETE", f"{config.IOTA_URL}/iot/devices/{quote(device_id, safe='')}"
        )

        if r.status_code not in (204, 404):
            raise FiwareError(502, f"IoT Agent: {_iot_err(r)}")

    # --- Orion -----------------------------------------------------------------
    async def get_entity(self, entity_id: str) -> Lamp | None:
        r: httpx.Response = await self._req(
            "GET",
            f"{config.ORION_URL}/v2/entities/{_eid(entity_id)}",
            params={"type": "Lamp", "options": "keyValues"},
        )

        if r.status_code == 404:
            return None

        if r.status_code != 200:
            raise FiwareError(502, f"Orion: {_orion_err(r)}")

        return r.json()

    async def list_lamps(self, owner: str) -> list[Lamp]:
        r: httpx.Response = await self._req(
            "GET",
            f"{config.ORION_URL}/v2/entities",
            params={
                "type": "Lamp",
                "q": f"owner=='{owner}'",
                "options": "keyValues",
                "limit": 1_000,
            },
        )

        if r.status_code != 200:
            raise FiwareError(502, f"Orion: {_orion_err(r)}")

        return r.json()

    async def upsert_lamp(
        self, entity_id: str, name: str, owner: str, created_at: datetime | None = None
    ) -> None:
        created_at: datetime = created_at or datetime.now(UTC)

        r: httpx.Response = await self._req(
            "POST",
            f"{config.ORION_URL}/v2/entities",
            params={"options": "upsert"},
            json={
                "id": entity_id,
                "type": "Lamp",
                "name": {"type": "Text", "value": name},
                "owner": {"type": "Text", "value": owner},
                "createdAt": {
                    "type": "DateTime",
                    "value": created_at.astimezone(UTC).isoformat(
                        timespec="milliseconds"
                    ),
                },
                "thresholds": {"type": "StructuredValue", "value": DEFAULT_THRESHOLDS},
            },
        )

        if r.status_code != 204:
            raise FiwareError(502, f"Orion: {_orion_err(r)}")

    async def update_thresholds(self, entity_id: str, thresholds: Thresholds) -> None:
        r: httpx.Response = await self._req(
            "PATCH",
            f"{config.ORION_URL}/v2/entities/{_eid(entity_id)}/attrs",
            params={"type": "Lamp"},
            json={"thresholds": {"type": "StructuredValue", "value": thresholds}},
        )

        if r.status_code != 204:
            raise FiwareError(502, f"Orion: {_orion_err(r)}")

    async def send_command(self, entity_id: str, command: Literal["on", "off"]) -> None:
        r: httpx.Response = await self._req(
            "PATCH",
            f"{config.ORION_URL}/v2/entities/{_eid(entity_id)}/attrs",
            params={"type": "Lamp"},
            json={command: {"type": "command", "value": ""}},
        )

        if r.status_code != 204:
            raise FiwareError(502, f"Orion command: {_orion_err(r)}")

    async def delete_entity(self, entity_id: str) -> None:
        r: httpx.Response = await self._req(
            "DELETE",
            f"{config.ORION_URL}/v2/entities/{_eid(entity_id)}",
            params={"type": "Lamp"},
        )

        if r.status_code != 204:
            raise FiwareError(502, f"Orion: {_orion_err(r)}")

    # --- Subscriptions ---------------------------------------------------------
    async def _sync_subscription(
        self,
        description: str,
        is_current: Callable[[Subscription], bool],
        body: CreateSubscriptionBody,
    ) -> None:
        r: httpx.Response = await self._req(
            "GET", f"{config.ORION_URL}/v2/subscriptions", params={"limit": 1_000}
        )

        if r.status_code != 200:
            raise FiwareError(502, f"Orion: {_orion_err(r)}")

        keep: Subscription | None = None
        for sub in (s for s in r.json() if s.get("description") == description):
            if keep is None and sub.get("status") != "expired" and is_current(sub):
                keep: Subscription = sub

            else:
                await self._req(
                    "DELETE", f"{config.ORION_URL}/v2/subscriptions/{sub['id']}"
                )

        if keep:
            return

        r: httpx.Response = await self._req(
            "POST", f"{config.ORION_URL}/v2/subscriptions", json=body
        )

        if r.status_code == 201:
            log.info("Created Orion subscription: %s", description)

        raise FiwareError(502, f"Orion subscription: {_orion_err(r)}")

    async def ensure_subscription(self) -> None:
        description: str = self._description()

        def is_current(sub: Subscription) -> bool:
            custom: HttpCustom = sub.get("notification", {}).get("httpCustom", {})
            headers: dict[str, str] = {
                k.lower(): v for k, v in custom.get("headers", {}).items()
            }

            return (
                custom.get("url", "") == config.NOTIFY_URL
                and headers.get("x-notify-token", "") == config.NOTIFY_TOKEN
            )

        body: CreateSubscriptionBody = {
            "description": description,
            "subject": {
                "entities": [{"idPattern": ".*", "type": "Lamp"}],
                "condition": {"attrs": CONDITION_ATTRS},
            },
            "notification": {
                "httpCustom": {
                    "url": config.NOTIFY_URL,
                    "headers": {"X-Notify-token": config.NOTIFY_TOKEN},
                },
                "attrs": NOTIFY_ATTRS,
                "attrsFormat": "keyValues",
            },
        }

        await self._sync_subscription(description, is_current, body)

    async def ensure_history_subscription(self) -> None:
        description: str = self._history_description()

        def is_current(sub: Subscription) -> bool:
            n: Notification = sub.get("notification", {})
            custom: HttpCustom = n.get("httpCustom", {})
            headers: dict[str, str] = {
                k.lower(): v for k, v in custom.get("headers", {}).items()
            }

            if (
                custom.get("url") != config.STH_NOTIFY_URL
                or n.get("attrsFormat") != "legacy"
            ):
                return False

            if sorted(n.get("attrs", [])) != sorted(HISTORY_ATTRS):
                return False

            return (
                headers.get("fiware-service") == config.STH_SERVICE
                and headers.get("fiware-servicepath") == config.STH_SERVICEPATH
            )

        body: CreateSubscriptionBody = {
            "description": description,
            "subject": {
                "entities": [{"idPattern": ".*", "type": "Lamp"}],
                "condition": {"attrs": HISTORY_ATTRS},
            },
            "notification": {
                "httpCustom": {
                    "url": config.STH_NOTIFY_URL,
                    "headers": {
                        "Fiware-Service": config.STH_SERVICE,
                        "Fiware-ServicePath": config.STH_SERVICEPATH,
                    },
                },
                "attrs": HISTORY_ATTRS,
                "attrsFormat": "legacy",
            },
        }

        await self._sync_subscription(description, is_current, body)

    # --- STH-Comet -------------------------------------------------------------
    async def _sth_series(
        self, entity_id: str, attr: str, limit: int
    ) -> list[tuple[str, float]]:
        r: httpx.Response = await self._req(
            "GET",
            f"{config.STH_URL}/STH/v2/entities/{_eid(entity_id)}/attrs/{attr}",
            params={"type": "Lamp", "lastN": limit},
        )

        if r.status_code == 404:
            return []

        if r.status_code != 200:
            raise FiwareError(502, f"STH-Comet: {_sth_err(r)}")

        return _sth_rows(r.json())

    async def get_history(
        self, entity_id: str, limit: int, since: datetime | None = None
    ) -> list[Point]:
        results: list[Row] = await asyncio.gather(
            *(self._sth_series(entity_id, attr, limit) for attr in HISTORY_ATTRS)
        )

        return build_points(
            dict(zip(HISTORY_ATTRS, results, strict=True)), limit, since
        )

    async def delete_history(self, entity_id: str) -> None:
        r: httpx.Response = await self._req(
            "DELETE",
            f"{config.STH_URL}/STH/v1/contextEntities/type/Lamp/id/{_eid(entity_id)}",
        )

        if r.status_code != 204:
            raise FiwareError(502, f"STH-Comet: {_sth_err(r)}")
