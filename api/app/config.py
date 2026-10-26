"""All settings come from environment variables (see docker-compose.yml / .env.example)."""

import os
import secrets


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# ------------------------------------------------------------------ Keyrock --
KEYROCK_URL: str = os.getenv("KEYROCK_URL", "http://keyrock:3005")
ADMIN_EMAIL: str = os.getenv("KEYROCK_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD: str = os.getenv("KEYROCK_ADMIN_PASSWORD", "change-me-admin")
CLIENT_ID: str | None = os.getenv("KEYROCK_CLIENT_ID") or None
CLIENT_SECRET: str | None = os.getenv("KEYROCK_CLIENT_SECRET") or None
CREDENTIALS_FILE: str = os.getenv("CREDENTIALS_FILE", "/data/keyrock_app.json")

# ---------------------------------------------------------------- This API --
APP_URL: str = os.getenv("APP_URL", "http://localhost:8000")
COOKIE_NAME: str = "access_token"
COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
CORS_ORIGINS: list[str] = _list("CORS_ORIGINS")

# ------------------------------------------------------------------- FIWARE --
ORION_URL: str = os.getenv("ORION_URL", "http://orion:1026").rstrip("/")
IOTA_URL: str = os.getenv("IOTA_URL", "http://iot-agent:4041").rstrip(
    "/"
)  # IoT Agent northbound API

# How the IoT Agent itself reaches Orion (it may differ from ORION_URL above)
IOTA_CBROKER: str = os.getenv("IOTA_CBROKER", "http://orion:1026")

# Orion in the course stack runs without -multiservice, so these are ignored
# by it, but the IoT Agent wants them. Keep them consistent everywhere.
FIWARE_SERVICE: str = os.getenv("FIWARE_SERVICE", "smartlamp")
FIWARE_SERVICEPATH: str = os.getenv("FIWARE_SERVICEPATH", "/")

# MQTT topics are /<apikey>/<deviceId>/...  The course material uses TEF.
IOTA_API_KEY: str = os.getenv("IOTA_API_KEY", "TEF")

# Shown to the user in the "register lamp" response so a device knows where to connect
MQTT_HOST: str = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT: int = int(os.getenv("MQTT_PORT", "1883"))

# Where Orion sends notifications. It must be reachable FROM the Orion container.
NOTIFY_URL: str = os.getenv(
    "NOTIFY_URL", "http://smartlamp-api:8000/internal/orion/notify"
)
# Shared secret Orion sends in X-Notify-Token. If unset, a random one is generated at
# each start and the Orion subscription is updated to match.
NOTIFY_TOKEN: str = os.getenv("NOTIFY_TOKEN") or secrets.token_urlsafe(32)

# ------------------------------------------------------------------ History --
# STH-Comet stores every measurement Orion notifies it about; the API reads the last N back.
STH_URL: str = os.getenv("STH_URL", "http://fiware-sth-comet:8666").rstrip("/")
# Where Orion sends notifications for STH-Comet (must be reachable FROM the Orion container).
STH_NOTIFY_URL: str = os.getenv("STH_NOTIFY_URL", "http://fiware-sth-comet:8666/notify")
# How many measurements the history keeps/returns. STH-Comet rejects lastN above its
# MAX_PAGE_SIZE setting, which defaults to 100.
HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "100"))

# --------------------------------------------------------------- Automation --
# The same command is not repeated for this many seconds, to give the device time to answer.
# After that it is sent again (a device that was offline never saw the first one).
AUTOMATION_RETRY_SECONDS: float = float(os.getenv("AUTOMATION_RETRY_SECONDS", "30"))
