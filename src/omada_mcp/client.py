"""Omada Controller API client wrapping httpx.AsyncClient."""

import asyncio
import logging
import os
import sys
import time
from typing import Any

import httpx
from dotenv import find_dotenv, load_dotenv

logger = logging.getLogger(__name__)


class OmadaApiError(Exception):
    """Raised when the Omada API returns a non-zero errorCode."""

    def __init__(self, error_code: int, msg: str):
        self.error_code = error_code
        self.msg = msg
        super().__init__(f"Omada API error {error_code}: {msg}")


class OmadaClient:
    """Async HTTP client for the TP-Link Omada Controller API v2."""

    def __init__(
        self,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        site: str | None = None,
        skip_tls_verify: bool | None = None,
    ):
        # Load .env from project root
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path:
            load_dotenv(dotenv_path)

        self.base_url = (url or os.getenv("OMADA_URL", "")).rstrip("/")
        self.username = username or os.getenv("OMADA_USERNAME", "")
        self.password = password or os.getenv("OMADA_PASSWORD", "")
        self._site_name = site or os.getenv("OMADA_SITE", "")

        if skip_tls_verify is None:
            skip_tls_verify = os.getenv("OMADA_SKIP_TLS_VERIFY", "false").lower() in ("true", "1", "yes")

        if not self.base_url:
            logger.error("OMADA_URL is required")
            sys.exit(1)

        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            verify=not skip_tls_verify,
            timeout=30.0,
            follow_redirects=True,
        )
        self._authenticated = False
        self._csrf_token: str = ""
        self._omadac_id: str = ""
        self._site_id: str = ""

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        """Call raise_for_status only when a request object is attached (real HTTP calls)."""
        if resp._request is not None:
            resp.raise_for_status()
        elif resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP error {resp.status_code}",
                request=None,  # type: ignore[arg-type]
                response=resp,
            )

    async def _login(self) -> None:
        """Authenticate with the Omada Controller."""
        resp = await self._http.post(
            "/api/v2/login",
            json={"username": self.username, "password": self.password},
        )
        self._raise_for_status(resp)
        data = resp.json()
        if data.get("errorCode") != 0:
            raise OmadaApiError(data["errorCode"], data.get("msg", "Login failed"))

        result = data["result"]
        self._csrf_token = result["token"]
        self._omadac_id = result["omadacId"]
        self._http.headers["Csrf-Token"] = self._csrf_token

        # Get site ID from init-info
        init_resp = await self._http.get("/api/v2/current/user/init-info")
        self._raise_for_status(init_resp)
        init_data = init_resp.json()
        if init_data.get("errorCode") != 0:
            raise OmadaApiError(init_data["errorCode"], init_data.get("msg", "Init failed"))

        self._site_id = init_data["result"]["siteId"]

        # If a specific site was requested, resolve it
        if self._site_name:
            sites_resp = await self._http.get(
                f"/{self._omadac_id}/api/v2/sites/basic",
                params={"currentPageSize": 100, "currentPage": 1},
            )
            sites_data = sites_resp.json()
            if sites_data.get("errorCode") == 0:
                for s in sites_data["result"].get("data", []):
                    if s["name"].lower() == self._site_name.lower() or s["id"] == self._site_name:
                        self._site_id = s["id"]
                        break

        self._authenticated = True
        logger.info("Authenticated as %s (site: %s)", self.username, self._site_id)

    async def _ensure_auth(self) -> None:
        """Login if not already authenticated."""
        if not self._authenticated:
            await self._login()

    def _controller_path(self, endpoint: str) -> str:
        """Build a controller-level API path."""
        return f"/{self._omadac_id}/api/v2/{endpoint}"

    def _site_path(self, endpoint: str) -> str:
        """Build a site-level API path."""
        return f"/{self._omadac_id}/api/v2/sites/{self._site_id}/{endpoint}"

    _RETRYABLE_STATUS_CODES = {502, 503, 504}
    _MAX_RETRIES = 2
    _RETRY_BASE_DELAY = 1.0

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Execute an HTTP request with retry on transient failures."""
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                resp = await self._http.request(method, path, params=params, json=json)
                if resp.status_code in self._RETRYABLE_STATUS_CODES and attempt < self._MAX_RETRIES:
                    delay = self._RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning("HTTP %d on %s %s, retrying in %.1fs...", resp.status_code, method, path, delay)
                    await asyncio.sleep(delay)
                    continue
                return resp
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    delay = self._RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning("%s on %s %s, retrying in %.1fs...", type(exc).__name__, method, path, delay)
                    await asyncio.sleep(delay)
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    async def _get(self, path: str | Any, params: dict | None = None) -> dict[str, Any]:
        """GET request with auth, error handling, and session recovery.

        *path* may be a plain string **or** a zero-argument callable that
        returns a string.  Passing a callable defers path construction until
        after authentication so that ``_omadac_id`` and ``_site_id`` are
        already populated when the path is built.
        """
        await self._ensure_auth()
        if callable(path):
            path = path()
        resp = await self._request_with_retry("GET", path, params=params)
        self._raise_for_status(resp)

        # Detect HTML response (session expired)
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.warning("Session expired, re-authenticating...")
            self._authenticated = False
            await self._login()
            resp = await self._request_with_retry("GET", path, params=params)
            self._raise_for_status(resp)

        data = resp.json()
        if data.get("errorCode") != 0:
            raise OmadaApiError(data["errorCode"], data.get("msg", "Unknown error"))
        return data["result"]

    async def _post(self, path: str, json: Any = None) -> dict[str, Any]:
        """POST request with auth, error handling, and session recovery."""
        await self._ensure_auth()
        resp = await self._request_with_retry("POST", path, json=json)
        self._raise_for_status(resp)

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.warning("Session expired, re-authenticating...")
            self._authenticated = False
            await self._login()
            resp = await self._request_with_retry("POST", path, json=json)
            self._raise_for_status(resp)

        data = resp.json()
        if data.get("errorCode") != 0:
            raise OmadaApiError(data["errorCode"], data.get("msg", "Unknown error"))
        return data["result"]

    async def _get_all_pages(
        self,
        path: str | Any,
        params: dict | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a paginated endpoint and return the combined data list."""
        all_data: list[dict[str, Any]] = []
        page = 1
        while True:
            page_params = {**(params or {}), "currentPage": page, "currentPageSize": page_size}
            result = await self._get(path, params=page_params)
            items = result.get("data", [])
            all_data.extend(items)
            total = result.get("totalRows", 0)
            if len(all_data) >= total or not items:
                break
            page += 1
        return all_data

    # ── Controller-level endpoints ───────────────────────────────────

    async def get_controller_status(self) -> dict[str, Any]:
        return await self._get(lambda: self._controller_path("settings/system/status"))

    async def get_sites(self) -> dict[str, Any]:
        return await self._get(
            lambda: self._controller_path("sites/basic"),
            params={"currentPageSize": 100, "currentPage": 1},
        )

    async def get_capabilities(self) -> list[dict[str, Any]]:
        return await self._get(lambda: self._controller_path("capabilities"))

    async def get_user_detail(self) -> dict[str, Any]:
        return await self._get(lambda: self._controller_path("current/user-detail"))

    async def get_alert_count(self) -> dict[str, Any]:
        return await self._get(lambda: self._controller_path("alerts/num"))

    # ── Site-level endpoints ─────────────────────────────────────────

    async def get_dashboard_overview(self) -> dict[str, Any]:
        return await self._get(lambda: self._site_path("dashboard/overviewDiagram"))

    async def get_wifi_channels(self) -> dict[str, Any]:
        return await self._get(lambda: self._site_path("dashboard/channels"))

    async def get_devices(self) -> list[dict[str, Any]]:
        return await self._get_all_pages(lambda: self._site_path("grid/devices"))

    async def get_active_clients(self) -> list[dict[str, Any]]:
        return await self._get_all_pages(
            lambda: self._site_path("clients"),
            params={"filters.active": "true"},
        )

    async def get_known_clients(self) -> list[dict[str, Any]]:
        return await self._get_all_pages(lambda: self._site_path("insight/clients"))

    async def get_wlans(self) -> dict[str, Any]:
        return await self._get(lambda: self._site_path("setting/wlans"))

    async def get_ssids(self) -> dict[str, Any]:
        return await self._get(lambda: self._site_path("setting/ssids"))

    async def get_lan_networks(self) -> list[dict[str, Any]]:
        return await self._get_all_pages(lambda: self._site_path("setting/lan/networks"))

    async def get_alerts(self, resolved: bool = False) -> list[dict[str, Any]]:
        now_ms = int(time.time() * 1000)
        thirty_days_ms = 30 * 24 * 60 * 60 * 1000
        return await self._get_all_pages(
            lambda: self._site_path("logs/alerts"),
            params={
                "filters.resolved": str(resolved).lower(),
                "filters.timeStart": now_ms - thirty_days_ms,
                "filters.timeEnd": now_ms,
            },
            page_size=50,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def check_connection(self) -> dict[str, Any]:
        """Verify controller reachability and auth status."""
        try:
            await self._ensure_auth()
            status = await self.get_controller_status()
            return {
                "connected": True,
                "authenticated": True,
                "controller": status.get("name", "?"),
                "version": status.get("controllerVersion", "?"),
            }
        except Exception as exc:
            return {
                "connected": False,
                "authenticated": self._authenticated,
                "error": str(exc),
            }
