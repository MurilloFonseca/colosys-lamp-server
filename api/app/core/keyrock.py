import asyncio
import json
import logging
import os
import time
from base64 import b64encode
from pathlib import Path
from typing import Literal, TypedDict

import httpx

from ..common.exeptions import KeyrockError

log: logging.Logger = logging.getLogger("keyrock")


# --- Types ---------------------------------------------------------------------
type Method = Literal["GET", "POST"]


class User(TypedDict):
    id: str
    username: str
    email: str


class Application(TypedDict):
    id: str
    name: str
    secret: str


class Credentials(TypedDict):
    id: str
    secret: str


class LoginResponse(TypedDict):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    scope: list[str]


class Error(TypedDict):
    message: str
    code: int
    title: str


# --- Constants -----------------------------------------------------------------
ADMIN_TOKEN_TTL: float = 25 * 60  # 25 min
USER_CACHE_TTL: float = 30  # 30 s


# --- Helpers -------------------------------------------------------------------
def _err_msg(res: httpx.Response) -> str:
    try:
        err: Error = res.json().get("error", {})

        return err.get("message", f"HTTP {res.status_code}")

    except AttributeError:
        return res.json()


# --- Client --------------------------------------------------------------------
class KeyrockClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        admin_email: str,
        admin_password: str,
    ) -> None:
        self.http: httpx.AsyncClient = http
        self.base_url: str = base_url
        self.admin_email: str = admin_email
        self.admin_password: str = admin_password

        self.client_id: str | None = None
        self.client_secret: str | None = None

        self._admin_token: str | None = None
        self._admin_token_exp: float = 0
        self._admin_lock = asyncio.Lock()
        self._user_cache: dict[str, tuple[float, User]] = {}

    # --- admin side ------------------------------------------------------------
    async def _get_admin_token(self, force: bool = False) -> str:
        async with self._admin_lock:
            if (
                not force
                and self._admin_token
                and time.monotonic() < self._admin_token_exp
            ):
                return self._admin_token

            r: httpx.Response = await self.http.post(
                f"{self.base_url}/v1/auth/tokens",
                json={"name": self.admin_email, "password": self.admin_password},
            )

            token: str | None = r.headers.get("X-Subject-Token")

            if r.status_code != 201 or not token:
                raise KeyrockError(502, f"Keyrock admin login failed: {_err_msg(r)}")

            self._admin_token: str = token
            self._admin_token_exp: float = time.monotonic() + ADMIN_TOKEN_TTL
            return token

    async def _admin_req(self, method: Method, path: str, **kwargs) -> httpx.Response:
        r: httpx.Response
        for attempt in (1, 2):
            token: str = await self._get_admin_token(force=attempt == 2)

            r: httpx.Response = await self.http.request(
                method,
                f"{self.base_url}{path}",
                headers={"X-Auth-token": token},
                **kwargs,
            )

            if r.status_code != 401:
                break

        return r

    # --- bootstrap -------------------------------------------------------------
    async def wait_until_ready(self, attempts: int = 60, delay: float = 3) -> None:
        last: Exception
        for i in range(1, attempts + 1):
            try:
                await self._get_admin_token(force=True)
                log.info("Keyrock is ready")
                return

            except (httpx.HTTPError, KeyrockError) as exc:
                last: httpx.HTTPError | KeyrockError = exc
                log.info("Waiting for keyrock (%d/%d): %s", i, attempts, exc)
                await asyncio.sleep(delay)

        raise RuntimeError(f"Keyrock not ready after {attempts} attempts: {last}")

    async def ensure_application(
        self,
        name: str,
        url: str,
        redirect_uri: str,
        credentials_file: str,
        env_client_id: str | None = None,
        env_client_secret: str | None = None,
    ) -> None:
        # Load from environment
        if env_client_id and env_client_secret:
            self.client_id: str = env_client_id
            self.client_secret: str = env_client_secret

            log.info("Using OAuth client credentials from the environment")
            return

        # Load from credentials file
        path = Path(credentials_file)
        if path.exists():
            data: Credentials = json.loads(path.read_text())

            self.client_id: str = data["id"]
            self.client_secret: str = data["secret"]

            log.info("Loaded OAuth client credentials from %s", path)
            return

        # Load existing application
        r: httpx.Response = await self._admin_req("GET", "/v1/applications")
        apps: list[Application] = r.json().get("applications", [])
        existing: Application | None = next(
            (a for a in apps if a.get("name") == name), None
        )

        if existing:
            r: httpx.Response = await self._admin_req(
                "GET", f"/v1/applications/{existing['id']}"
            )
            app: Application | None = r.json().get("application")
            if not app or not app.get("secret"):
                raise RuntimeError(
                    f"Application '{name}' already exists in Keyrock but its secret could not be read."
                    "Set KEYROCK_CLIENT_ID and KEYROCK_CLIENT_SECRET manually."
                )

        # Create new application
        else:
            r: httpx.Response = await self._admin_req(
                "POST",
                "/v1/applications",
                json={
                    "application": {
                        "name": name,
                        "description": "Back-end API (password grant)",
                        "url": url,
                        "redirect_uri": redirect_uri,
                        "grant_type": ["password", "refresh_token"],
                    }
                },
            )

            if r.status_code != 201:
                raise RuntimeError(
                    f"Could not register OAuth application: {_err_msg(r)}"
                )

            app: Application = r.json()["application"]
            log.info("Registered OAuth application '%s' in Keyrock", name)

        self.client_id: str = app["id"]
        self.client_secret: str = app["secret"]

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"id": self.client_id, "secret": self.client_secret})
        )

        try:
            os.chmod(path, 0o600)

        except OSError:
            pass

    # --- user side -------------------------------------------------------------
    async def create_user(self, username: str, email: str, password: str) -> User:
        r: httpx.Response = await self._admin_req(
            "POST",
            "/v1/users",
            json={"user": {"username": username, "email": email, "password": password}},
        )

        if r.status_code != 201:
            raise KeyrockError(r.status_code, _err_msg(r))

        return r.json()["user"]

    async def password_login(self, email: str, password: str) -> LoginResponse | None:
        basic: str = b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        r: httpx.Response = await self.http.post(
            f"{self.base_url}/oauth2/token",
            headers={"Authorization": f"Basic {basic}"},
            data={"grant_type": "password", "username": email, "password": password},
        )

        if r.status_code in (400, 401):
            body: str = _err_msg(r).lower()

            if "client" in body or "grant type" in body:
                raise KeyrockError(502, f"OAuth client rejected by Keyrock: {body}")

            return None

        if r.status_code != 200:
            raise KeyrockError(502, f"Keyrock login failed: {_err_msg(r)}")

        return r.json()

    async def get_user(self, access_token: str) -> User | None:
        now: float = time.monotonic()
        hit: tuple[float, User] | None = self._user_cache.get(access_token)

        if hit and hit[0] > now:
            return hit[1]

        r: httpx.Response = await self.http.get(
            f"{self.base_url}/user", params={"access_token": access_token}
        )

        if r.status_code >= 500:
            raise KeyrockError(502, f"Keyrock error: {_err_msg(r)}")

        if r.status_code != 200:
            self._user_cache.pop(access_token, None)
            return None

        data: User = r.json()
        user: User = {
            "id": data["id"],
            "email": data["email"],
            "username": data["username"],
        }

        if len(self._user_cache) > 1_000:
            self._user_cache.clear()

        self._user_cache[access_token] = (now + USER_CACHE_TTL, user)

        return user

    def forget_token(self, access_token: str) -> None:
        self._user_cache.pop(access_token, None)
