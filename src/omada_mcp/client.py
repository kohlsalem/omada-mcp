"""Omada Controller API client wrapping httpx.AsyncClient."""

import asyncio
import json
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
    "gateway_acls": ("setting/firewall/acls", True),
    "switch_acls": ("setting/firewall/acls", True),
    "ap_acls": ("setting/firewall/acls", True),
    "gateway_custom_acls": ("setting/firewall/gateway-acls", True),
    "gateway_acl_mode": ("setting/firewall/gateway-acls/config-mode", False),
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
    "ip_groups": ("setting/profiles/groups/0", False),
    "ip_port_groups": ("setting/profiles/groups/1", False),
    "mac_groups": ("setting/profiles/groups/2", False),
    "time_profiles": ("setting/profiles/timeranges", False),
    "wireless_features": ("setting/wireless/feature", False),
    "site_settings": ("setting", False),
    "device_account": ("setting/device_account", False),
    "attack_defense": ("setting/firewall/attackdefense", False),
    "mac_filter_settings": ("setting/firewall/macfilter", False),
    "mac_filters": ("setting/firewall/macfilters", True),
    "ips_settings": ("setting/ips", False),
    "upnp": ("setting/upnp", False),
    "mdns": ("setting/service/mdns", True),
    "bonjour_profiles": ("setting/profiles/mdns", False),
    "ddns": ("setting/service/ddns", True),
    "reboot_schedules": ("setting/service/rebootSchedules", True),
    "poe_schedules": ("setting/port-schedules", False),
    "upgrade_schedules": ("setting/service/upgrade-schedules", True),
    "one_to_one_nat": ("setting/transmission/otonats", True),
    "disable_nat": ("setting/wired-networks/disable-nats", True),
    "ip_mac_binding_settings": ("setting/firewall/imb", False),
    "ip_mac_bindings": ("setting/firewall/imbs", True),
    "url_filters": ("setting/firewall/urlfilterings", True),
    "ap_url_filters": ("setting/firewall/urlfilterings", True),
    "rogue_aps": ("insight/rogueaps", True),
    "mac_auth": ("setting/macAuth", False),
    "nat_alg": ("setting/transmission/alg", False),
}

CONTROLLER_RESOURCES = {
    "settings": ("controller/setting", False),
    "general_ntp": ("controller/settings/general", False),
    "cloud_access": ("cloud/status", False),
    "users": ("account/users", True),
    "roles": ("roles", False),
    "current_user_mfa": ("current/user-detail", False),
    "auto_backup": ("autoBackup/autoBackupTask", False),
}
OPENAPI_RESOURCES = {
    "rrm": "rrm/config", "remote_logging": "remote-logging",
    "lan_multicast": "lan-multicasts", "ssid_details": "wireless-network/ssid-operation",
}

REPORT_CARDS = (
    "overviewSummary", "clientConnectionTrend", "internet", "network", "alertSummary",
    "gatewaySummary", "ispLoad", "switchHealthTrend", "switchStatus",
    "topSwitchByTrafficAndPoePower", "topSwitchCpuMemory", "poePowerTrend",
    "wirelessTraffic", "apHealth", "apStatus", "topApByTrafficAndClient",
    "topApByRtAndDrop", "topApByInterference", "topApByCpuAndMemory",
    "topSsidByTraffic", "clientsOverview", "clientsAssociationActivities",
    "clientsWithOnboardingTimes", "appCategories", "topApplicationByTraffic",
)

VPN_GROUPS = {
    "site_to_site": "site-to-site-vpns",
    "servers": "client-to-site-vpn-servers",
    "clients": "client-to-site-vpn-clients",
}
VPN_TYPES = {0: "L2TP", 1: "PPTP", 2: "IPsec", 3: "OpenVPN", 4: "WireGuard", 5: "SSL VPN"}


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
            headers={"Omada-Request-Source": "web-local"},
        )
        self._authenticated = False
        self._csrf_token: str = ""
        self._omadac_id: str = ""
        self._site_id: str = ""
        self._auth_lock = asyncio.Lock()
        self._request_slots = asyncio.Semaphore(4)

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
            async with self._auth_lock:
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
                async with self._request_slots:
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
        build_path = path if callable(path) else lambda: path
        token = self._csrf_token
        resp = await self._request_with_retry("GET", build_path(), params=params)
        self._raise_for_status(resp)

        # Detect HTML response (session expired)
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.warning("Session expired, re-authenticating...")
            async with self._auth_lock:
                if self._csrf_token == token:
                    self._authenticated = False
                    await self._login()
            resp = await self._request_with_retry("GET", build_path(), params=params)
            self._raise_for_status(resp)

        data = resp.json()
        if data.get("errorCode") != 0:
            raise OmadaApiError(data["errorCode"], data.get("msg", "Unknown error"))
        return data["result"]

    async def _post(self, path: str | Any, json: Any = None) -> dict[str, Any]:
        """POST request with auth, error handling, and session recovery."""
        await self._ensure_auth()
        build_path = path if callable(path) else lambda: path
        request_path = build_path()
        token = self._csrf_token
        resp = await self._request_with_retry("POST", request_path, json=json)
        self._raise_for_status(resp)

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.warning("Session expired, re-authenticating...")
            async with self._auth_lock:
                if self._csrf_token == token:
                    self._authenticated = False
                    await self._login()
            resp = await self._request_with_retry("POST", build_path(), json=json)
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
        *, page: int = 1, limit: int = 50, event_key: str | None = None,
        severity: str | None = None, device: str | None = None,
    ) -> dict:
        if page < 1 or not 1 <= limit <= 100:
            raise ValueError("page must be >= 1 and limit between 1 and 100")
        end_ms = int(time.time() * 1000) if end_ms is None else end_ms
        start_ms = max(0, end_ms - 86400000) if start_ms is None else start_ms
        params = {**self._time_filters(start_ms, end_ms),
                  "currentPage": page, "currentPageSize": limit, "sorts.time": "desc"}
        result = await self._read_site("logs/events", site, params=params)
        definitions = {}
        if severity:
            notifications = await self._read_site("logs/notification", site)
            for entries in notifications.values():
                if isinstance(entries, list):
                    definitions.update({e["key"]: e.get("level") for e in entries
                                        if isinstance(e, dict) and "key" in e})
        entries = []
        for item in result.get("data", [])[:limit]:
            level = item.get("level") or definitions.get(item.get("key"))
            if event_key and str(item.get("key", "")).casefold() != event_key.casefold():
                continue
            if severity and str(level).casefold() != severity.casefold():
                continue
            dev = item.get("device") or {}
            if device and not self._identity_matches(dev, device):
                continue
            entry = dict(item)
            if level:
                entry["severity"] = level
            # Keep each row bounded, including nested serialized payloads. Normal
            # events preserve their fields; oversized rows are explicitly marked.
            if len(json.dumps(entry, ensure_ascii=False).encode()) > 2048:
                entry = {k: entry[k] for k in ("id", "key", "module", "time", "level", "severity") if k in entry}
                entry["content"] = str(item.get("content", ""))[:512]
                entry["truncated_fields"] = True
            entries.append(entry)
        total = result.get("totalRows", 0)
        more = page * limit < total
        return {"data": entries, "page": page, "limit": limit, "totalRows": total,
                "next_page": page + 1 if more else None, "has_more": more,
                "range": {"start_ms": start_ms, "end_ms": end_ms},
                "filter_scope": "event_key/severity/device applied locally to this API page",
                "scanned": len(result.get("data", [])),
                "filters": {"event_key": event_key, "severity": severity, "device": device}}

    async def get_controller_resource(self, resource: str) -> Any:
        if resource not in CONTROLLER_RESOURCES:
            raise ValueError(f"Unknown controller resource. Choose from: {', '.join(CONTROLLER_RESOURCES)}")
        endpoint, paginated = CONTROLLER_RESOURCES[resource]
        path = lambda: self._controller_path(endpoint)
        if paginated:
            return await self._get_all_pages(path)
        return await self._get(path)

    async def get_ssid_detail(self, name_or_id: str, site: str | None = None) -> dict:
        table = await self.get_site_resource("ssid_details", site)
        matches = [row for row in table if row.get("id") == name_or_id
                   or str(row.get("idInt", "")) == name_or_id
                   or str(row.get("name", "")).casefold() == name_or_id.casefold()]
        if len(matches) != 1:
            raise ValueError(f"SSID {name_or_id!r}: {len(matches)} matches; select an ID from ssid_details")
        return await self._read_openapi_site(
            f"wireless-network/ssids/{quote(matches[0]['id'], safe='')}", site,
        )

    async def get_rf_scan(self, name_or_mac: str, site: str | None = None) -> Any:
        device = await self._find_device(name_or_mac, site)
        if device.get("type") != "ap":
            raise ValueError("RF scan results are available only for APs")
        return await self._read_site(
            f"{self._device_endpoint(device)}/tools/rfScan", site,
        )

    async def get_site_resource(self, resource: str, site: str | None = None) -> Any:
        if resource in OPENAPI_RESOURCES:
            endpoint = OPENAPI_RESOURCES[resource]
            if resource not in ("ssid_details", "lan_multicast"):
                return await self._read_openapi_site(endpoint, site)
            items = []
            page = 1
            while True:
                result = await self._read_openapi_site(endpoint, site, {"page": page, "pageSize": 100})
                rows = result.get("data", [])
                items.extend(rows)
                if not rows or len(items) >= result.get("totalRows", 0):
                    return items
                page += 1
        if resource == "vpn_users":
            site_id = await self._resolve_site(site)
            items = []
            page = 1
            while True:
                result = await self._get(
                    lambda: f"/openapi/v2/{self._omadac_id}/sites/{quote(site_id, safe='')}/vpn/users",
                    params={"page": page, "pageSize": 100},
                )
                items.extend(result.get("data", []))
                if not result.get("data") or len(items) >= result.get("totalRows", 0):
                    return items
                page += 1
        if resource not in SITE_RESOURCES:
            raise ValueError(f"Unknown resource {resource!r}. Choose from: {', '.join(SITE_RESOURCES)}")
        endpoint, paginated = SITE_RESOURCES[resource]
        acl_types = {"gateway_acls": 0, "switch_acls": 1, "ap_acls": 2}
        params = {"type": acl_types[resource]} if resource in acl_types else None
        if resource in ("url_filters", "ap_url_filters"):
            params = {"type": "gateway" if resource == "url_filters" else "ap"}
        return await self._read_site(endpoint, site, params=params, paginated=paginated)

    async def get_resource_status(self, resource: str, site: str | None = None) -> dict:
        """Report observed read access without inferring activation from empty rows."""
        if resource not in ("rogue_aps", "reboot_schedules", "upgrade_schedules"):
            raise ValueError("Status resource must be rogue_aps, reboot_schedules or upgrade_schedules")
        try:
            data = await self.get_site_resource(resource, site)
        except OmadaApiError as exc:
            return {"data": None, "status": {"readable": False, "supported": False if exc.error_code == -1600 else None,
                    "permission": "denied" if exc.error_code == -1007 else "unknown", "enabled": None,
                    "error": str(exc)}}
        enabled = [row.get("enable", row.get("enabled", row.get("status"))) for row in data]
        return {"data": data, "status": {"readable": True, "permission": "allowed", "supported": True,
                "enabled": None, "record_count": len(data), "record_enable_values": enabled,
                "interpretation": "No configured schedules" if not data and resource != "rogue_aps" else
                "No returned detections; detection activation is unknown" if not data else "Records returned",
                "note": "API read support does not establish hardware detection support or activation."}}

    async def get_acl_rules(self, kind: str = "gateway", site: str | None = None, expand_objects: bool = False) -> dict:
        if kind not in ("gateway", "switch", "ap"):
            raise ValueError("kind must be gateway, switch or ap")
        typ = {"gateway": 0, "switch": 1, "ap": 2}[kind]
        # Preserve feature flags (e.g. unsupported counters) as well as all rules.
        first = await self._read_site("setting/firewall/acls", site,
                                      params={"type": typ, "currentPage": 1, "currentPageSize": 100})
        rules = list(first.get("data", []))
        page = 2
        while rules and len(rules) < first.get("totalRows", 0):
            result = await self._read_site("setting/firewall/acls", site,
                                           params={"type": typ, "currentPage": page, "currentPageSize": 100})
            rows = result.get("data", [])
            if not rows:
                break
            rules.extend(rows)
            page += 1
        errors = {}
        async def optional(resource):
            try:
                return await self.get_site_resource(resource, site)
            except (OmadaApiError, httpx.HTTPStatusError) as exc:
                errors[resource] = str(exc)
                return []

        def rows(data):
            return data.get("data", []) if isinstance(data, dict) else data

        indexes = {}
        resources = {0: "lan_networks", 1: "ip_groups", 2: "ip_port_groups", 3: "mac_groups"}
        for code, resource in resources.items():
            indexes[code] = {x.get("id", x.get("groupId")): x for x in rows(await optional(resource))}
        ssids = await self.get_ssids(site)
        indexes[4] = {s["ssidId"]: {**s, "wlanName": w.get("wlanName")}
                      for w in ssids.get("ssids", []) for s in w.get("ssidList", [])}
        profiles = {x["id"]: x for x in rows(await optional("time_profiles"))}
        devices = await self.get_devices(site) if kind == "switch" else []
        device_index = {d.get("mac"): d for d in devices}
        switch_ports = {}
        if kind == "switch":
            for dev in devices:
                if dev.get("type") == "switch":
                    try:
                        switch_ports[dev["mac"]] = await self.get_device_ports(dev["mac"], site)
                    except (OmadaApiError, httpx.HTTPStatusError) as exc:
                        errors[f"ports:{dev['mac']}"] = str(exc)
        type_names = {0: "network", 1: "ip_group", 2: "ip_port_group", 3: "mac_group",
                      4: "ssid", 5: "gateway_management", 6: "ipv6_group", 7: "ipv6_port_group",
                      8: "country", 9: "country_group", 10: "domain_port_group",
                      11: "not_network", 12: "not_ip_group", 13: "not_ip_port_group",
                      14: "not_ipv6_group", 15: "not_ipv6_port_group", 24: "domain_group"}
        def compact(obj):
            if obj is None or expand_objects:
                return obj
            return {k: obj[k] for k in ("id", "groupId", "ssidId", "name", "ssidName") if k in obj}
        for rule in rules:
            rule["policyText"] = {0: "deny", 1: "permit"}.get(rule.get("policy"), "unknown")
            for side in ("source", "destination"):
                code = rule.get(f"{side}Type")
                base = {11: 0, 12: 1, 13: 2, 14: 6, 15: 7}.get(code, code)
                refs = rule.get(f"{side}Ids", [])
                rule[f"{side}Resolved"] = {
                    "type": type_names.get(code, "unknown"), "negated": code in (11, 12, 13, 14, 15),
                    "objects": [{"id": ref, "resolved": ref in indexes.get(base, {}),
                                 "value": compact(indexes.get(base, {}).get(ref))} for ref in refs],
                }
            rule["timeProfileResolved"] = compact(profiles.get(rule.get("timeRangeId")))
            rule["syslogStatus"] = {"configured": rule.get("syslog"), "available": "syslog" in rule}
            rule["hitCounterStatus"] = {
                "supported": first.get("supportHitCount"),
                "value": rule.get("hitCounts", rule.get("hitCount")),
                "available": "hitCounts" in rule or "hitCount" in rule,
            }
            if kind == "switch":
                bound = rule.get("customAclDevices", [])
                rule["bindingResolved"] = {
                    "bindingType": rule.get("bindingType"),
                    "bindingTypeText": {0: "all_ports", 1: "custom_ports", 2: "all_switches", 3: "custom_switches"}.get(rule.get("bindingType"), "unknown"),
                    "devices": [{"raw": d, "device": compact(device_index.get(d)) if isinstance(d, str) else None}
                                for d in bound],
                    "ports": rule.get("customAclPorts", []),
                    "network": compact(indexes[0].get(rule.get("networkId"))),
                    "inventoryPorts": [{"switchMac": mac, "switchName": device_index.get(mac, {}).get("name"),
                                        "ports": [{"port": p.get("port"), "name": p.get("name"), "id": p.get("id")}
                                                  for p in ports]}
                                       for mac, ports in switch_ports.items()
                                       if rule.get("bindingType") in (0, 2)
                                       or mac in bound
                                       or any(isinstance(p, dict) and p.get("mac") == mac for p in rule.get("customAclPorts", []))],
                    "note": "inventoryPorts lists candidate inventory ports, not runtime enforcement; custom selections remain in ports. VLAN-based bindings also require the selected network.",
                }
        return {"kind": kind, "data": rules,
                "capabilities": {k: v for k, v in first.items() if k != "data"},
                "resolution_errors": errors,
                "note": "Configured rules are not proof of enforcement. Missing hit counters are unavailable, not zero."}

    async def get_topology(self, site: str | None = None) -> dict:
        return await self._read_site("topology-v2", site)

    async def get_vpn_configs(self, site: str | None = None, group: str | None = None) -> dict:
        """Read modern VPN tables, retaining controller capability metadata."""
        if group is not None and group not in VPN_GROUPS:
            raise ValueError(f"Unknown VPN group. Choose from: {', '.join(VPN_GROUPS)}")
        site_id = await self._resolve_site(site)
        groups = [group] if group is not None else VPN_GROUPS
        results = {}
        for name in groups:
            endpoint = VPN_GROUPS[name]
            items = []
            page = 1
            while True:
                result = await self._get(
                    lambda: f"/openapi/v2/{self._omadac_id}/sites/{quote(site_id, safe='')}/vpn/{endpoint}",
                    params={"page": page, "pageSize": 100},
                )
                if page == 1:
                    metadata = {k: v for k, v in result.items()
                                if k not in ("data", "currentPage", "currentSize")}
                data = result.get("data", [])
                items.extend(data)
                if len(items) >= result.get("totalRows", 0) or not data:
                    break
                page += 1
            results[name] = {**metadata, "data": items}
        return {"groups": results, "vpn_types": VPN_TYPES}

    async def get_vpn_detail(
        self, name_or_id: str, site: str | None = None, group: str | None = None,
    ) -> dict:
        inventory = await self.get_vpn_configs(site, group)
        matches = [(category, item) for category, table in inventory["groups"].items()
                   for item in table["data"]
                   if item.get("id") == name_or_id
                   or (bool(item.get("name")) and item["name"].casefold() == name_or_id.casefold())]
        if len(matches) != 1:
            raise ValueError(f"VPN {name_or_id!r}: {len(matches)} matches. Use get_vpn_configs and select an ID/group.")
        category, item = matches[0]
        site_id = await self._resolve_site(site)
        endpoint = VPN_GROUPS[category]
        vpn_id = quote(item["id"], safe="")
        detail = await self._get(
            lambda: f"/openapi/v2/{self._omadac_id}/sites/{quote(site_id, safe='')}/vpn/{endpoint}/{vpn_id}",
        )
        return {"group": category, "vpn_type": VPN_TYPES.get(detail.get("vpnType"), "unknown"),
                "configuration": detail}

    async def _read_openapi_site(
        self, endpoint: str, site: str | None = None, params: dict | None = None,
    ) -> Any:
        site_id = await self._resolve_site(site)
        return await self._get(
            lambda: f"/openapi/v1/{self._omadac_id}/sites/{quote(site_id, safe='')}/{endpoint}",
            params=params,
        )

    @staticmethod
    def _incident_filters(
        start_ms: int | None, end_ms: int | None, status: int | None,
    ) -> dict:
        window = OmadaClient._time_filters(start_ms, end_ms)
        params = {"filters.startTime": window["filters.timeStart"],
                  "filters.endTime": window["filters.timeEnd"]}
        if status is not None:
            params["filters.status"] = status
        return params

    async def get_incidents(
        self, site: str | None = None, start_ms: int | None = None,
        end_ms: int | None = None, status: int | None = None,
        search: str | None = None,
    ) -> dict:
        params = self._incident_filters(start_ms, end_ms, status)
        if search:
            params["searchKey"] = search
        items = []
        page = 1
        first = None
        while True:
            result = await self._read_openapi_site(
                "anomaly/incidents", site, {**params, "page": page, "pageSize": 100},
            )
            if first is None:
                first = result
            data = result.get("data", [])
            items.extend(data)
            if len(items) >= result.get("totalRows", 0) or not data:
                break
            page += 1
        return {"data": items, "totalRows": first.get("totalRows", 0),
                "statistic": first.get("statistic", {}), "filters": params}

    async def get_incident_summary(
        self, site: str | None = None, start_ms: int | None = None,
        end_ms: int | None = None, status: int | None = None,
    ) -> dict:
        params = self._incident_filters(start_ms, end_ms, status)
        return {
            "filters": params,
            "statistics": await self._read_openapi_site("anomaly/overview/statistics", site, params),
            "active": await self._read_openapi_site("anomaly/unresolved-incidents", site),
        }

    async def get_audit_logs(
        self, site: str | None = None, start_ms: int | None = None,
        end_ms: int | None = None, controller_wide: bool = False,
        search: str | None = None,
    ) -> list[dict]:
        if controller_wide and site is not None:
            raise ValueError("Specify either site or controller_wide, not both.")
        window = self._time_filters(start_ms, end_ms)
        params = {"filters.times": json.dumps([{
            "timeStart": window["filters.timeStart"], "timeEnd": window["filters.timeEnd"],
        }])}
        if search:
            params["searchKey"] = search
        if controller_wide:
            return await self._get_all_pages(lambda: self._controller_path("audit/logs"), params=params)
        return await self._read_site("audit/logs", site, params=params, paginated=True)

    async def get_security_logs(
        self, site: str | None = None, start_ms: int | None = None,
        end_ms: int | None = None, archived: bool = False,
        search: str | None = None,
    ) -> dict:
        window = self._time_filters(start_ms, end_ms)
        params = {
            "filters.startTime": window["filters.timeStart"] // 1000,
            "filters.endTime": window["filters.timeEnd"] // 1000,
            "archived": str(archived).lower(),
        }
        if search:
            params["searchKey"] = search
        return {
            "filters": params,
            "ips_settings": await self._read_site("setting/ips", site),
            "data": await self._read_site("ips/threat-management", site, params=params, paginated=True),
            "note": "An empty threat log does not establish absence of threats; check IDS/IPS enable status and retention.",
        }

    @staticmethod
    def _usage_range(start: int | None, end: int | None) -> dict:
        end = int(time.time()) if end is None else end
        start = end - 86400 if start is None else start
        if not 0 <= start < end < 100_000_000_000:
            raise ValueError("Usage range must be 0 <= start < end in Unix seconds, not milliseconds.")
        return {"start": start, "end": end}

    async def get_usage_status(self, site: str | None = None) -> dict:
        return {
            "capabilities": await self._read_site("dpi/status", site),
            "collection": await self._read_site("applicationControl/status", site),
            "retention": await self._read_site("stat/dpi/crop", site),
        }

    async def get_application_usage(
        self, site: str | None = None, start: int | None = None, end: int | None = None,
        family_ids: list[int] | None = None,
    ) -> dict:
        window = self._usage_range(start, end)
        overview = await self._read_site("stat/dpi/overview", site, params=window)
        families = family_ids if family_ids is not None else [
            c["familyId"] for c in overview.get("categoryTraffics", []) if c.get("familyId") is not None
        ]
        applications = []
        if families:
            applications = await self._read_site(
                "stat/dpi/application/stat", site, paginated=True,
                params={**window, "filters.family": ",".join(map(str, families)), "filters.type": 0},
            )
        return {"range": window, "overview": overview, "applications": applications,
                "status": await self.get_usage_status(site)}

    async def get_client_application_usage(
        self, name_or_mac_or_ip: str, site: str | None = None,
        start: int | None = None, end: int | None = None,
    ) -> dict:
        window = self._usage_range(start, end)
        # A known MAC may have traffic history even when absent from today's inventory.
        mac = name_or_mac_or_ip.replace(":", "").replace("-", "").replace(".", "")
        if len(mac) == 12 and all(ch in "0123456789abcdefABCDEF" for ch in mac):
            mac = "-".join(mac[i:i + 2] for i in range(0, 12, 2)).upper()
            client = {"mac": mac}
        else:
            client = await self.get_client_detail(name_or_mac_or_ip, site)
            mac = client["mac"]
        prefix = f"stat/dpi/clients/{quote(mac, safe='')}"
        return {
            "client": {k: client[k] for k in ("mac", "name", "ip") if k in client},
            "range": window,
            "categories": await self._read_site(f"{prefix}/categoryTraffic", site, params=window),
            "applications": await self._read_site(
                f"{prefix}/applicationTrafficStat", site, paginated=True,
                params={**window, "filters.all": "true"},
            ),
            "status": await self.get_usage_status(site),
            "note": "Empty DPI records do not establish zero usage. Check collection and crop/retention status.",
        }

    async def get_application_clients(
        self, family_id: int, application_ids: list[int], site: str | None = None,
        start: int | None = None, end: int | None = None,
    ) -> dict:
        window = self._usage_range(start, end)
        if family_id < 0 or not application_ids or any(i < 0 for i in application_ids):
            raise ValueError("Provide a nonnegative family_id and at least one nonnegative application ID.")
        return {
            "range": window,
            "clients": await self._read_site(
                f"stat/dpi/{family_id}/clientTraffic", site, paginated=True,
                params={**window, "filters.application": ",".join(map(str, application_ids))},
            ),
            "status": await self.get_usage_status(site),
            "note": "Empty DPI records do not establish zero usage. Check collection and crop/retention status.",
        }

    async def get_report(
        self, cards: list[str], site: str | None = None,
        start: int | None = None, end: int | None = None, top_k: int = 20,
    ) -> dict:
        window = self._usage_range(start, end)
        if not cards or any(card not in REPORT_CARDS for card in cards):
            raise ValueError(f"Choose report cards from: {', '.join(REPORT_CARDS)}")
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        site_id = await self._resolve_site(site)
        # This specific POST computes report data; it does not save/export/schedule a report.
        data = await self._post(
            lambda: f"/openapi/v1/{self._omadac_id}/sites/{quote(site_id, safe='')}/report/cards",
            {**window, "cards": [{"type": card, "topK": top_k} for card in dict.fromkeys(cards)]},
        )
        return {"range": window, "cards": data}

    @staticmethod
    def _identity_matches(item: dict, query: str) -> bool:
        def normalize(value: str) -> str:
            return value.casefold().replace(":", "").replace("-", "").replace(".", "")
        return any(
            str(item.get(key, "")).casefold() == query.casefold()
            for key in ("name", "hostName", "hostname", "host_name", "systemName", "ip", "ipAddress")
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
        query = name_or_mac_or_ip.strip()
        if not query:
            raise ValueError("Client lookup requires a nonempty name, hostname, MAC or IP")
        active = await self.get_active_clients(site)
        candidates = active
        matches = [c for c in candidates if self._identity_matches(c, query)]
        if not matches:
            known = await self.get_known_clients(site)
            # Prefer the active record's fields for duplicate MACs.
            merged = {c["mac"]: c for c in known if c.get("mac")}
            for record in active:
                if record.get("mac"):
                    merged[record["mac"]] = {**merged.get(record["mac"], {}),
                                             **{k: v for k, v in record.items() if v not in (None, "")}}
            candidates = list(merged.values())
            matches = [c for c in candidates if self._identity_matches(c, query)]
        if not matches:
            matches = [c for c in candidates if any(
                query.casefold() in str(c.get(k, "")).casefold()
                for k in ("name", "hostName", "hostname", "host_name", "systemName")
            )]
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
