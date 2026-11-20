"""Omada Controller API client wrapping httpx.AsyncClient."""

import asyncio
import logging
import os
import sys
import time
from typing import Any
from urllib.parse import quote

import httpx
from dotenv import find_dotenv, load_dotenv

logger = logging.getLogger(__name__)

# Paths verified against the controller's web client and read-only API.
# The boolean indicates a paginated table rather than a single object/list.
SITE_RESOURCES = {
    "wan": ("setting/wan/networks", False),
    "gateway_acls": ("setting/firewall/gateway-acls", True),
    "port_forwarding": ("setting/transmission/portForwardings", True),
    "static_routes": ("setting/transmission/staticRoutings", True),
    "policy_routes": ("setting/transmission/policyRoutings", True),
    "dhcp_reservations": ("setting/service/dhcp", True),
    "port_profiles": ("setting/lan/profiles", True),
    "rate_limits": ("setting/profiles/rateLimits", False),
    "vpn_pptp_l2tp": ("setting/vpns/pptpAndL2tp", False),
    "vpn_clients": ("setting/vpns/c2s-client", False),
    "ssl_vpn_server": ("setting/sslvpn/server", False),
    "dns_proxy": ("setting/dns-proxy", False),
    "lan_dns": ("setting/lan/dns", True),
    "portals": ("setting/portals", False),
    "switch_ports": ("insight/switch/port/overview", True),
    "poe": ("insight/switch/port/poe", True),
    "port_counters": ("insight/switch/port/counters", True),
    "dpi_status": ("dpi/status", False),
    "notifications": ("logs/notification", False),
    "wlans": ("setting/wlans", False),
    "ssids": ("setting/ssids", False),
    "lan_networks": ("setting/lan/networks", True),
}


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
                else:
                    raise ValueError(f"Omada site {self._site_name!r} not found")
            else:
                raise OmadaApiError(sites_data["errorCode"], sites_data.get("msg", "Site lookup failed"))

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

    async def _resolve_site(self, site: str | None = None) -> str:
        """Resolve a site per request without changing shared client state."""
        await self._ensure_auth()
        if site is None:
            return self._site_id
        sites = await self.get_sites()
        for item in sites.get("data", []):
            if item["id"] == site or item["name"].casefold() == site.casefold():
                return item["id"]
        raise ValueError(f"Omada site {site!r} not found. Use get_sites to list sites.")

    async def _read_site(
        self, endpoint: str, site: str | None = None, *,
        params: dict | None = None, paginated: bool = False,
    ) -> Any:
        site_id = await self._resolve_site(site)
        path = lambda: self._controller_path(f"sites/{quote(site_id, safe='')}/{endpoint}")
        if paginated:
            return await self._get_all_pages(path, params=params)
        return await self._get(path, params=params)

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
        sites = await self._get_all_pages(lambda: self._controller_path("sites/basic"))
        return {"data": sites, "totalRows": len(sites)}

    async def get_capabilities(self) -> list[dict[str, Any]]:
        return await self._get(lambda: self._controller_path("capabilities"))

    async def get_user_detail(self) -> dict[str, Any]:
        return await self._get(lambda: self._controller_path("current/user-detail"))

    async def get_alert_count(self) -> dict[str, Any]:
        return await self._get(lambda: self._controller_path("alerts/num"))

    # ── Site-level endpoints ─────────────────────────────────────────

    async def get_dashboard_overview(self, site: str | None = None) -> dict[str, Any]:
        return await self._read_site("dashboard/overviewDiagram", site)

    async def get_wifi_channels(self, site: str | None = None) -> dict[str, Any]:
        return await self._read_site("dashboard/channels", site)

    async def get_devices(self, site: str | None = None) -> list[dict[str, Any]]:
        return await self._read_site("grid/devices", site, paginated=True)

    async def get_active_clients(self, site: str | None = None) -> list[dict[str, Any]]:
        return await self._read_site(
            "clients", site, paginated=True,
            params={"filters.active": "true"},
        )

    async def get_known_clients(self, site: str | None = None) -> list[dict[str, Any]]:
        return await self._read_site("insight/clients", site, paginated=True)

    async def get_wlans(self, site: str | None = None) -> dict[str, Any]:
        return await self._read_site("setting/wlans", site)

    async def get_ssids(self, site: str | None = None) -> dict[str, Any]:
        return await self._read_site("setting/ssids", site)

    async def get_lan_networks(self, site: str | None = None) -> list[dict[str, Any]]:
        return await self._read_site("setting/lan/networks", site, paginated=True)

    async def get_alerts(
        self, resolved: bool | None = False, site: str | None = None,
        start_ms: int | None = None, end_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        params = self._time_filters(start_ms, end_ms)
        if resolved is not None:
            params["filters.resolved"] = str(resolved).lower()
        return await self._read_site("logs/alerts", site, params=params, paginated=True)

    @staticmethod
    def _time_filters(start_ms: int | None, end_ms: int | None) -> dict:
        now_ms = int(time.time() * 1000)
        thirty_days_ms = 30 * 24 * 60 * 60 * 1000
        end = now_ms if end_ms is None else end_ms
        start = end - thirty_days_ms if start_ms is None else start_ms
        if start < 0 or end < 0 or start >= end:
            raise ValueError("Time range must satisfy 0 <= start_ms < end_ms (Unix milliseconds).")
        return {"filters.timeStart": start, "filters.timeEnd": end}

    async def get_events(
        self, site: str | None = None,
        start_ms: int | None = None, end_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        return await self._read_site(
            "logs/events", site, params=self._time_filters(start_ms, end_ms), paginated=True,
        )

    async def get_site_resource(self, resource: str, site: str | None = None) -> Any:
        if resource not in SITE_RESOURCES:
            raise ValueError(f"Unknown resource {resource!r}. Choose from: {', '.join(SITE_RESOURCES)}")
        endpoint, paginated = SITE_RESOURCES[resource]
        return await self._read_site(endpoint, site, paginated=paginated)

    async def get_topology(self, site: str | None = None) -> dict:
        return await self._read_site("topology-v2", site)

    @staticmethod
    def _identity_matches(item: dict, query: str) -> bool:
        def normalize(value: str) -> str:
            return value.casefold().replace(":", "").replace("-", "").replace(".", "")
        return any(
            str(item.get(key, "")).casefold() == query.casefold()
            for key in ("name", "hostName", "ip")
        ) or (bool(item.get("mac")) and normalize(item["mac"]) == normalize(query))

    async def _find_device(self, name_or_mac: str, site: str | None = None) -> dict:
        matches = [d for d in await self.get_devices(site) if self._identity_matches(d, name_or_mac)]
        if len(matches) != 1:
            raise ValueError(f"Device {name_or_mac!r}: {len(matches)} matches. Use get_devices and select a MAC.")
        return matches[0]

    @staticmethod
    def _device_endpoint(device: dict) -> str:
        types = {"ap": "eaps", "switch": "switches", "gateway": "gateways"}
        if device.get("type") not in types:
            raise ValueError(f"Unsupported device type: {device.get('type')}")
        return f"{types[device['type']]}/{quote(device['mac'], safe='')}"

    async def get_device_detail(self, name_or_mac: str, site: str | None = None) -> dict:
        device = await self._find_device(name_or_mac, site)
        return await self._read_site(self._device_endpoint(device), site)

    async def get_device_ports(self, name_or_mac: str, site: str | None = None) -> Any:
        device = await self._find_device(name_or_mac, site)
        return await self._read_site(f"{self._device_endpoint(device)}/ports", site)

    async def get_client_detail(self, name_or_mac_or_ip: str, site: str | None = None) -> dict:
        matches = [c for c in await self.get_active_clients(site)
                   if self._identity_matches(c, name_or_mac_or_ip)]
        if not matches:
            matches = [c for c in await self.get_known_clients(site)
                       if self._identity_matches(c, name_or_mac_or_ip)]
        if len(matches) != 1:
            raise ValueError(f"Client {name_or_mac_or_ip!r}: {len(matches)} matches. Select a MAC from the client lists.")
        mac = quote(matches[0]["mac"], safe="")
        return await self._read_site(f"clients/{mac}", site)

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
