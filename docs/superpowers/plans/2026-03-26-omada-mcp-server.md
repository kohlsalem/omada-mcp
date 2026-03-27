# Omada MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MCP server that wraps the TP-Link Omada Controller REST API v2, exposing network monitoring and configuration data as Claude tools.

**Architecture:** Python MCP server using FastMCP with a two-file structure: `client.py` handles auth (cookie + CSRF token), session management, and HTTP calls; `server.py` defines MCP tools that format API responses as human-readable text. Config via `.env` file with env-var fallback.

**Tech Stack:** Python 3.12+, mcp[cli] (FastMCP), httpx, hatch build system, python-dotenv

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/omada_mcp/__init__.py`
- Create: `.gitignore`
- Create: `.env.example`

- [ ] **Step 1: Initialize git repo**

```bash
cd /Users/D054904/kohlsalem/omada-mcp
git init
```

- [ ] **Step 2: Create pyproject.toml**

Create `pyproject.toml`:

```toml
[project]
name = "omada-mcp"
version = "1.0.0"
description = "MCP server for TP-Link Omada Controller"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.26.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
]

[project.scripts]
omada-mcp = "omada_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/omada_mcp"]
```

- [ ] **Step 3: Create __init__.py**

Create `src/omada_mcp/__init__.py`:

```python
"""Omada MCP Server — TP-Link Omada Controller integration for Claude."""
```

- [ ] **Step 4: Create .gitignore**

Create `.gitignore`:

```
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
.env
.playwright-mcp/
```

- [ ] **Step 5: Create .env.example**

Create `.env.example`:

```
OMADA_URL=https://omada.example.com
OMADA_USERNAME=admin
OMADA_PASSWORD=changeme
# OMADA_SITE=MySite
# OMADA_SKIP_TLS_VERIFY=true
```

- [ ] **Step 6: Create .env with real credentials**

Create `.env`:

```
OMADA_URL=https://omada.kohlsalem.com
OMADA_USERNAME=anzeiger
OMADA_PASSWORD=Display/01
OMADA_SKIP_TLS_VERIFY=true
```

- [ ] **Step 7: Create venv and install**

```bash
cd /Users/D054904/kohlsalem/omada-mcp
uv venv
uv pip install -e .
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/omada_mcp/__init__.py .gitignore .env.example
git commit -m "CHORE: scaffold omada-mcp project"
```

---

### Task 2: API Client — Auth & Session

**Files:**
- Create: `src/omada_mcp/client.py`
- Create: `tests/test_client_auth.py`

- [ ] **Step 1: Write the auth test**

Create `tests/test_client_auth.py`:

```python
"""Tests for OmadaClient authentication and session management."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from omada_mcp.client import OmadaClient, OmadaApiError


@pytest.fixture
def client():
    return OmadaClient(
        url="https://omada.example.com",
        username="testuser",
        password="testpass",
    )


@pytest.mark.asyncio
async def test_login_sets_session_state(client):
    """Login should store csrf_token, omadac_id, and site_id."""
    login_response = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {"omadacId": "abc123", "token": "csrf456"},
        },
        headers={"set-cookie": "TPOMADA_SESSIONID=session789; Path=/"},
    )
    init_response = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {"omadacId": "abc123", "siteId": "site001"},
        },
    )

    with patch.object(client._http, "post", new_callable=AsyncMock, return_value=login_response):
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=init_response):
            await client._login()

    assert client._csrf_token == "csrf456"
    assert client._omadac_id == "abc123"
    assert client._site_id == "site001"
    assert client._authenticated is True


@pytest.mark.asyncio
async def test_get_raises_on_error_code(client):
    """API errors should raise OmadaApiError."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._csrf_token = "csrf456"
    client._site_id = "site001"

    error_response = httpx.Response(
        200,
        json={"errorCode": -1, "msg": "General error."},
    )

    with patch.object(client._http, "get", new_callable=AsyncMock, return_value=error_response):
        with pytest.raises(OmadaApiError, match="General error"):
            await client._get("/test")


@pytest.mark.asyncio
async def test_get_relogins_on_html_response(client):
    """HTML response (session expired) should trigger re-login."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._csrf_token = "csrf456"
    client._site_id = "site001"

    html_response = httpx.Response(
        200,
        text="<!DOCTYPE HTML><html>...</html>",
        headers={"content-type": "text/html;charset=utf-8"},
    )
    json_response = httpx.Response(
        200,
        json={"errorCode": 0, "msg": "Success.", "result": {"data": "ok"}},
    )

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return html_response
        return json_response

    with patch.object(client._http, "get", side_effect=mock_get):
        with patch.object(client, "_login", new_callable=AsyncMock) as mock_login:
            result = await client._get("/test")

    mock_login.assert_called_once()
    assert result == {"data": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/D054904/kohlsalem/omada-mcp
uv pip install -e ".[dev]" pytest pytest-asyncio 2>/dev/null; .venv/bin/pytest tests/test_client_auth.py -v
```

Expected: FAIL — `omada_mcp.client` does not exist yet.

- [ ] **Step 3: Implement the client**

Create `src/omada_mcp/client.py`:

```python
"""Omada Controller API client wrapping httpx.AsyncClient."""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

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
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)

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

    async def _login(self) -> None:
        """Authenticate with the Omada Controller."""
        resp = await self._http.post(
            "/api/v2/login",
            json={"username": self.username, "password": self.password},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errorCode") != 0:
            raise OmadaApiError(data["errorCode"], data.get("msg", "Login failed"))

        result = data["result"]
        self._csrf_token = result["token"]
        self._omadac_id = result["omadacId"]
        self._http.headers["Csrf-Token"] = self._csrf_token

        # Get site ID from init-info
        init_resp = await self._http.get("/api/v2/current/user/init-info")
        init_resp.raise_for_status()
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

    async def _get(self, path: str, params: dict | None = None) -> Any:
        """GET request with auth, error handling, and session recovery."""
        await self._ensure_auth()
        resp = await self._http.get(path, params=params)
        resp.raise_for_status()

        # Detect HTML response (session expired)
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.warning("Session expired, re-authenticating...")
            self._authenticated = False
            await self._login()
            resp = await self._http.get(path, params=params)
            resp.raise_for_status()

        data = resp.json()
        if data.get("errorCode") != 0:
            raise OmadaApiError(data["errorCode"], data.get("msg", "Unknown error"))
        return data["result"]

    async def _post(self, path: str, json: Any = None) -> Any:
        """POST request with auth, error handling, and session recovery."""
        await self._ensure_auth()
        resp = await self._http.post(path, json=json)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.warning("Session expired, re-authenticating...")
            self._authenticated = False
            await self._login()
            resp = await self._http.post(path, json=json)
            resp.raise_for_status()

        data = resp.json()
        if data.get("errorCode") != 0:
            raise OmadaApiError(data["errorCode"], data.get("msg", "Unknown error"))
        return data["result"]

    # ── Controller-level endpoints ───────────────────────────────────

    async def get_controller_status(self) -> dict:
        return await self._get(self._controller_path("settings/system/status"))

    async def get_sites(self) -> dict:
        return await self._get(
            self._controller_path("sites/basic"),
            params={"currentPageSize": 100, "currentPage": 1},
        )

    async def get_capabilities(self) -> list:
        return await self._get(self._controller_path("capabilities"))

    async def get_user_detail(self) -> dict:
        return await self._get(self._controller_path("current/user-detail"))

    async def get_alert_count(self) -> dict:
        return await self._get(self._controller_path("alerts/num"))

    # ── Site-level endpoints ─────────────────────────────────────────

    async def get_dashboard_overview(self) -> dict:
        return await self._get(self._site_path("dashboard/overviewDiagram"))

    async def get_wifi_channels(self) -> dict:
        return await self._get(self._site_path("dashboard/channels"))

    async def get_devices(self, page: int = 1, page_size: int = 100) -> dict:
        return await self._get(
            self._site_path("grid/devices"),
            params={"currentPage": page, "currentPageSize": page_size},
        )

    async def get_active_clients(self, page: int = 1, page_size: int = 100) -> dict:
        return await self._get(
            self._site_path("clients"),
            params={"filters.active": "true", "currentPage": page, "currentPageSize": page_size},
        )

    async def get_known_clients(self, page: int = 1, page_size: int = 100) -> dict:
        return await self._get(
            self._site_path("insight/clients"),
            params={"currentPage": page, "currentPageSize": page_size},
        )

    async def get_wlans(self) -> dict:
        return await self._get(self._site_path("setting/wlans"))

    async def get_ssids(self) -> dict:
        return await self._get(self._site_path("setting/ssids"))

    async def get_lan_networks(self, page: int = 1, page_size: int = 100) -> dict:
        return await self._get(
            self._site_path("setting/lan/networks"),
            params={"currentPage": page, "currentPageSize": page_size},
        )

    async def get_alerts(self, resolved: bool = False, page: int = 1, page_size: int = 50) -> dict:
        now_ms = int(time.time() * 1000)
        thirty_days_ms = 30 * 24 * 60 * 60 * 1000
        return await self._get(
            self._site_path("logs/alerts"),
            params={
                "filters.resolved": str(resolved).lower(),
                "filters.timeStart": now_ms - thirty_days_ms,
                "filters.timeEnd": now_ms,
                "currentPage": page,
                "currentPageSize": page_size,
            },
        )

    async def close(self) -> None:
        await self._http.aclose()
```

- [ ] **Step 4: Install test deps and run tests**

```bash
cd /Users/D054904/kohlsalem/omada-mcp
uv pip install pytest pytest-asyncio
.venv/bin/pytest tests/test_client_auth.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omada_mcp/client.py tests/test_client_auth.py
git commit -m "FEAT: add OmadaClient with auth, session recovery, and all API methods"
```

---

### Task 3: MCP Server — Controller & Dashboard Tools

**Files:**
- Create: `src/omada_mcp/server.py`

- [ ] **Step 1: Create server.py with controller and dashboard tools**

Create `src/omada_mcp/server.py`:

```python
"""Omada MCP Server — tools for monitoring and managing an Omada Controller."""

import logging
import sys

from mcp.server.fastmcp import FastMCP

from omada_mcp.client import OmadaClient

# Logging to stderr only (stdout is JSON-RPC)
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("omada-mcp")

mcp = FastMCP(
    "omada",
    instructions=(
        "MCP server for TP-Link Omada Controller. "
        "Provides access to network monitoring, device status, client information, "
        "WiFi channel analysis, LAN/WLAN configuration, and alerts."
    ),
)

_client: OmadaClient | None = None


def _get_client() -> OmadaClient:
    global _client
    if _client is None:
        _client = OmadaClient()
    return _client


def _fmt_bytes(b: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.0f} {unit}" if b == int(b) else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _fmt_uptime(s: str) -> str:
    """Pass through the uptime string from the API (e.g. '69day(s) 15h 7m 19s')."""
    return s


# ═══════════════════════════════════════════════════════════════════
#  CONTROLLER & SYSTEM TOOLS
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_controller_status() -> str:
    """Get Omada Controller system status: version, model, firmware, IP, uptime, storage, and device capacity."""
    s = await _get_client().get_controller_status()
    cap = s.get("deviceCapacity", {})
    storage_lines = []
    for st in s.get("hwcStorage", []):
        storage_lines.append(f"    {st['name']}: {st['usedStorage']:.1f} / {st['totalStorage']:.1f} GB")
    storage = "\n".join(storage_lines) if storage_lines else "    N/A"

    return (
        f"Controller: {s.get('name', '?')}\n"
        f"  Model: {s.get('model', '?')}  Firmware: {s.get('firmwareVersion', '?')}\n"
        f"  Controller Version: {s.get('controllerVersion', '?')}\n"
        f"  IP: {s.get('ip', '?')}  MAC: {s.get('macAddress', '?')}\n"
        f"  SN: {s.get('sn', '?')}\n"
        f"  Category: {s.get('category', '?')}\n"
        f"  Storage:\n{storage}\n"
        f"  Device Capacity:\n"
        f"    APs: {cap.get('adoptedApNum', 0)}/{cap.get('apCapacity', '?')}\n"
        f"    Switches: {cap.get('adoptedOswNum', 0)}/{cap.get('oswCapacity', '?')}\n"
        f"    Gateways: {cap.get('adoptedOsgNum', 0)}/{cap.get('osgCapacity', '?')}"
    )


@mcp.tool()
async def get_sites() -> str:
    """List all Omada sites with name, region, timezone, and scenario."""
    data = await _get_client().get_sites()
    sites = data.get("data", [])
    if not sites:
        return "No sites found."
    lines = [f"Sites ({len(sites)}):"]
    for s in sites:
        lines.append(
            f"  {s['name']}  Region: {s.get('region', '?')}  "
            f"TZ: {s.get('timeZone', '?')}  Scenario: {s.get('scenario', '?')}  "
            f"ID: {s['id']}"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_user_info() -> str:
    """Show current Omada user details: name, role, and site privileges."""
    u = await _get_client().get_user_detail()
    return (
        f"User: {u.get('name', '?')}\n"
        f"  Role: {u.get('roleName', '?')} (ID: {u.get('roleId', '?')})\n"
        f"  Type: {u.get('type', '?')}  Level: {u.get('userLevel', '?')}\n"
        f"  MFA: {u.get('enableMFA', False)}\n"
        f"  Alert Notifications: {u.get('alert', False)}"
    )


@mcp.tool()
async def get_network_overview() -> str:
    """Get full network health snapshot: gateway health, WAN ports, switch/AP/client counts, and power consumption."""
    d = await _get_client().get_dashboard_overview()

    # Gateway info
    gw_health = d.get("gatewayHealth", {})
    wan_lines = []
    for w in d.get("wanPortInfos", []):
        status = "up" if w.get("status") == 1 else "down"
        wan_lines.append(f"    {w.get('name', '?')} ({w.get('ip', '?')}) — {status}")
    wan_str = "\n".join(wan_lines) if wan_lines else "    N/A"

    return (
        f"Network Overview\n"
        f"  Gateway: {d.get('gatewayName', '?')} ({'connected' if d.get('gatewayStatus') == 2 else 'disconnected'})\n"
        f"    CPU: {gw_health.get('cpuUtil', '?')}%  Mem: {gw_health.get('memUtil', '?')}%  Temp: {d.get('gatewayTemp', '?')}°C\n"
        f"    WAN Ports:\n{wan_str}\n"
        f"    Net Capacity: {d.get('netCapacity', '?')}%  Utilization: {d.get('netUtilization', '?')}%\n"
        f"  Switches: {d.get('connectedSwitchNum', 0)} connected, {d.get('disconnectedSwitchNum', 0)} disconnected\n"
        f"    Ports: {d.get('totalPorts', '?')} total, {d.get('availablePorts', '?')} available  Power: {d.get('powerConsumption', '?')}W\n"
        f"  APs: {d.get('connectedApNum', 0)} connected, {d.get('disconnectedApNum', 0)} disconnected, {d.get('isolatedApNum', 0)} isolated\n"
        f"  Clients: {d.get('totalClientNum', 0)} total ({d.get('wiredClientNum', 0)} wired, {d.get('wirelessClientNum', 0)} wireless, {d.get('guestNum', 0)} guest)"
    )


@mcp.tool()
async def get_wifi_channels() -> str:
    """Get WiFi channel utilization across 2.4 GHz, 5 GHz, and 6 GHz bands."""
    data = await _get_client().get_wifi_channels()
    lines = ["WiFi Channel Utilization:"]

    for band_key, band_label in [("channels2g", "2.4 GHz"), ("channels5g", "5 GHz"), ("channels6g", "6 GHz")]:
        channels = data.get(band_key, [])
        active = [c for c in channels if c.get("apNum")]
        if not active:
            lines.append(f"\n  {band_label}: no active channels")
            continue
        lines.append(f"\n  {band_label}:")
        for c in active:
            util = c.get("channelUtilization")
            util_str = f"  Util: {util:.0f}%" if util is not None else ""
            lines.append(
                f"    Ch {c['channel']:>3d}: {c.get('apNum', 0)} AP(s), {c.get('clientNum', 0)} clients{util_str}"
            )

    return "\n".join(lines)


@mcp.tool()
async def get_alert_count() -> str:
    """Get the number of active alerts on the Omada Controller."""
    data = await _get_client().get_alert_count()
    return f"Active alerts: {data.get('alertNum', 0)}"


# ═══════════════════════════════════════════════════════════════════
#  DEVICE TOOLS
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_devices() -> str:
    """List all network devices (gateways, switches, APs) with status, CPU/mem, firmware, and client count."""
    data = await _get_client().get_devices()
    devices = data.get("data", []) if isinstance(data, dict) else data
    if not devices:
        return "No devices found."

    lines = [f"Devices ({len(devices)}):"]
    for d in devices:
        status = "online" if d.get("statusCategory") == 1 else "offline"
        lines.append(
            f"  {d.get('name', '?')} ({d.get('type', '?')})\n"
            f"    Model: {d.get('showModel', d.get('model', '?'))}  FW: {d.get('firmwareVersion', '?')}\n"
            f"    IP: {d.get('ip', '?')}  MAC: {d.get('mac', '?')}  SN: {d.get('sn', '?')}\n"
            f"    Status: {status}  CPU: {d.get('cpuUtil', '?')}%  Mem: {d.get('memUtil', '?')}%\n"
            f"    Uptime: {d.get('uptime', '?')}  Clients: {d.get('clientNum', '?')}\n"
            f"    Config Sync: {d.get('configSyncStatus', '?')}  Upgrade needed: {d.get('needUpgrade', False)}"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_device_detail(name_or_mac: str) -> str:
    """Get detailed info for a single device by name or MAC address."""
    data = await _get_client().get_devices()
    devices = data.get("data", []) if isinstance(data, dict) else data
    search = name_or_mac.lower()

    for d in devices:
        if d.get("name", "").lower() == search or d.get("mac", "").lower() == search.lower():
            status = "online" if d.get("statusCategory") == 1 else "offline"
            download = _fmt_bytes(d.get("download", 0))
            upload = _fmt_bytes(d.get("upload", 0))
            return (
                f"Device: {d.get('name', '?')}\n"
                f"  Type: {d.get('type', '?')}  Model: {d.get('showModel', d.get('model', '?'))}\n"
                f"  Firmware: {d.get('firmwareVersion', '?')}  HW: {d.get('hwVersion', '?')}\n"
                f"  IP: {d.get('ip', '?')}  MAC: {d.get('mac', '?')}  SN: {d.get('sn', '?')}\n"
                f"  Status: {status}  CPU: {d.get('cpuUtil', '?')}%  Mem: {d.get('memUtil', '?')}%\n"
                f"  Uptime: {d.get('uptime', '?')}\n"
                f"  Clients: {d.get('clientNum', '?')}\n"
                f"  Traffic: Down {download}  Up {upload}\n"
                f"  Config Sync: {d.get('configSyncStatus', '?')}\n"
                f"  Upgrade needed: {d.get('needUpgrade', False)}\n"
                f"  Locate enabled: {d.get('locateEnable', False)}"
            )

    return f"Device '{name_or_mac}' not found."


# ═══════════════════════════════════════════════════════════════════
#  CLIENT TOOLS
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_active_clients() -> str:
    """List all currently connected clients with IP, MAC, SSID, signal, traffic, and VLAN."""
    data = await _get_client().get_active_clients()
    clients = data.get("data", [])
    total = data.get("totalRows", len(clients))

    if not clients:
        return "No active clients."

    lines = [f"Active Clients ({total}):"]
    for c in clients:
        name = c.get("name") or c.get("hostName") or c.get("mac", "?")
        conn = "wireless" if c.get("wireless") else "wired"

        if c.get("wireless"):
            signal_info = f"  SSID: {c.get('ssid', '?')}  AP: {c.get('apName', '?')}  RSSI: {c.get('rssi', '?')}dBm  Ch: {c.get('channel', '?')}"
        else:
            signal_info = ""

        down = _fmt_bytes(c.get("trafficDown", 0))
        up = _fmt_bytes(c.get("trafficUp", 0))

        lines.append(
            f"  {name} ({conn})\n"
            f"    IP: {c.get('ip', '?')}  MAC: {c.get('mac', '?')}  VLAN: {c.get('vid', '?')}\n"
            f"    Traffic: Down {down}  Up {up}{signal_info}"
        )

    return "\n".join(lines)


@mcp.tool()
async def get_known_clients() -> str:
    """List all historically known clients (active and inactive) with MAC, last seen, and traffic totals."""
    data = await _get_client().get_known_clients()
    clients = data.get("data", [])
    total = data.get("totalRows", len(clients))

    if not clients:
        return "No known clients."

    lines = [f"Known Clients ({total}):"]
    for c in clients:
        name = c.get("name") or c.get("mac", "?")
        conn = "wireless" if c.get("wireless") else "wired"
        down = _fmt_bytes(c.get("download", 0))
        up = _fmt_bytes(c.get("upload", 0))
        blocked = " [BLOCKED]" if c.get("block") else ""

        lines.append(
            f"  {name} ({conn}){blocked}\n"
            f"    MAC: {c.get('mac', '?')}  VLAN: {c.get('vid', '?')}\n"
            f"    Traffic: Down {down}  Up {up}"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  NETWORK CONFIGURATION TOOLS
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_wlans() -> str:
    """List WLAN groups with name, primary flag, and max SSIDs per band."""
    data = await _get_client().get_wlans()
    wlans = data.get("data", [])
    if not wlans:
        return "No WLAN groups found."

    lines = [f"WLAN Groups ({len(wlans)}):"]
    for w in wlans:
        primary = " [primary]" if w.get("primary") else ""
        lines.append(f"  {w.get('name', '?')}{primary}  ID: {w.get('id', '?')}")

    lines.append(f"\n  Max SSIDs: 2.4G={data.get('maxSsids2G', '?')}  5G={data.get('maxSsids5G', '?')}  6G={data.get('maxSsids6G', '?')}")
    return "\n".join(lines)


@mcp.tool()
async def get_ssids() -> str:
    """List all SSIDs with their VLAN assignments, grouped by WLAN."""
    data = await _get_client().get_ssids()
    wlans = data.get("ssids", [])
    if not wlans:
        return "No SSIDs found."

    lines = ["SSIDs:"]
    for wlan in wlans:
        lines.append(f"\n  WLAN Group: {wlan.get('wlanName', '?')}")
        for ssid in wlan.get("ssidList", []):
            lines.append(
                f"    {ssid.get('ssidName', '?')}  VLAN: {ssid.get('vlanId', '?')}"
            )

    return "\n".join(lines)


@mcp.tool()
async def get_lan_networks() -> str:
    """List LAN network profiles with VLAN, gateway/subnet, DHCP settings, and domain."""
    data = await _get_client().get_lan_networks()
    networks = data.get("data", [])
    if not networks:
        return "No LAN networks found."

    lines = [f"LAN Networks ({len(networks)}):"]
    for n in networks:
        dhcp = n.get("dhcpSettings", {})
        dhcp_str = "disabled"
        if dhcp.get("enable"):
            dhcp_str = f"{dhcp.get('ipaddrStart', '?')} - {dhcp.get('ipaddrEnd', '?')}  Lease: {dhcp.get('leasetime', '?')}min  DNS: {dhcp.get('priDns', '?')}"

        lines.append(
            f"\n  {n.get('name', '?')}  VLAN: {n.get('vlan', '?')}\n"
            f"    Gateway/Subnet: {n.get('gatewaySubnet', '?')}\n"
            f"    Domain: {n.get('domain', '?')}\n"
            f"    DHCP: {dhcp_str}\n"
            f"    Isolation: {n.get('isolation', False)}  Portal: {n.get('portal', False)}"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  ALERTS & LOGS TOOLS
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_alerts(resolved: bool = False) -> str:
    """Get site alerts. Set resolved=true to include resolved alerts."""
    data = await _get_client().get_alerts(resolved=resolved)
    alerts = data.get("data", [])
    total = data.get("totalRows", len(alerts))

    if not alerts:
        return f"No {'resolved ' if resolved else 'active '}alerts."

    lines = [f"Alerts ({total}):"]
    for a in alerts:
        lines.append(
            f"  [{a.get('level', '?').upper()}] {a.get('msg', a.get('message', '?'))}\n"
            f"    Type: {a.get('type', '?')}  Time: {a.get('timestamp', '?')}"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the server starts without errors**

```bash
cd /Users/D054904/kohlsalem/omada-mcp
echo '{}' | .venv/bin/omada-mcp 2>&1 | head -5
```

Expected: Server starts (may show JSON-RPC errors since stdin isn't proper MCP, but no import errors).

- [ ] **Step 3: Commit**

```bash
git add src/omada_mcp/server.py
git commit -m "FEAT: add MCP server with all monitoring tools"
```

---

### Task 4: Integration Test Against Live Controller

**Files:**
- Create: `tests/test_live.py`

- [ ] **Step 1: Write a live integration test**

Create `tests/test_live.py`:

```python
"""Live integration tests against the real Omada Controller.

Run with: pytest tests/test_live.py -v -s
Requires .env with valid OMADA_URL, OMADA_USERNAME, OMADA_PASSWORD.
"""

import os
import pytest
from pathlib import Path
from dotenv import load_dotenv

from omada_mcp.client import OmadaClient

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SKIP_LIVE = not os.getenv("OMADA_URL")


@pytest.fixture
async def client():
    c = OmadaClient()
    yield c
    await c.close()


@pytest.mark.skipif(SKIP_LIVE, reason="OMADA_URL not set")
@pytest.mark.asyncio
class TestLiveController:
    async def test_login_and_controller_status(self, client):
        status = await client.get_controller_status()
        assert "controllerVersion" in status
        assert "deviceCapacity" in status
        print(f"  Controller: {status['name']} v{status['controllerVersion']}")

    async def test_get_sites(self, client):
        sites = await client.get_sites()
        assert "data" in sites
        assert len(sites["data"]) > 0
        print(f"  Sites: {[s['name'] for s in sites['data']]}")

    async def test_get_devices(self, client):
        devices = await client.get_devices()
        dev_list = devices.get("data", []) if isinstance(devices, dict) else devices
        assert len(dev_list) > 0
        print(f"  Devices: {[d['name'] for d in dev_list]}")

    async def test_get_active_clients(self, client):
        clients = await client.get_active_clients()
        assert "data" in clients
        print(f"  Active clients: {clients['totalRows']}")

    async def test_get_known_clients(self, client):
        clients = await client.get_known_clients()
        assert "data" in clients
        print(f"  Known clients: {clients['totalRows']}")

    async def test_get_dashboard_overview(self, client):
        overview = await client.get_dashboard_overview()
        assert "totalClientNum" in overview
        print(f"  Total clients: {overview['totalClientNum']}")

    async def test_get_wifi_channels(self, client):
        channels = await client.get_wifi_channels()
        assert "channels2g" in channels
        print(f"  2.4G channels: {len(channels['channels2g'])}")

    async def test_get_ssids(self, client):
        ssids = await client.get_ssids()
        assert "ssids" in ssids
        all_ssids = [s["ssidName"] for wlan in ssids["ssids"] for s in wlan.get("ssidList", [])]
        print(f"  SSIDs: {all_ssids}")

    async def test_get_lan_networks(self, client):
        networks = await client.get_lan_networks()
        assert "data" in networks
        print(f"  LAN networks: {[n['name'] for n in networks['data']]}")

    async def test_get_wlans(self, client):
        wlans = await client.get_wlans()
        assert "data" in wlans
        print(f"  WLANs: {[w['name'] for w in wlans['data']]}")

    async def test_get_alert_count(self, client):
        alerts = await client.get_alert_count()
        assert "alertNum" in alerts
        print(f"  Alert count: {alerts['alertNum']}")

    async def test_get_user_detail(self, client):
        user = await client.get_user_detail()
        assert "name" in user
        print(f"  User: {user['name']} ({user['roleName']})")
```

- [ ] **Step 2: Run live tests**

```bash
cd /Users/D054904/kohlsalem/omada-mcp
.venv/bin/pytest tests/test_live.py -v -s
```

Expected: All tests PASS with real data printed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live.py
git commit -m "TEST: add live integration tests for all Omada API endpoints"
```

---

### Task 5: README and MCP Registration

**Files:**
- Create: `README.md`
- Modify: `~/.claude/settings.json` (add `omada` MCP server)

- [ ] **Step 1: Create README.md**

Create `README.md`:

```markdown
# omada-mcp

MCP server for TP-Link Omada Controller. Provides Claude with direct access to network monitoring, device status, client information, WiFi channel analysis, and LAN/WLAN configuration.

## Setup

```bash
uv venv
uv pip install -e .
```

## Configuration

Create `.env` (see `.env.example`):

```
OMADA_URL=https://omada.example.com
OMADA_USERNAME=admin
OMADA_PASSWORD=changeme
OMADA_SKIP_TLS_VERIFY=true
```

## Claude Code Registration

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "omada": {
      "command": "/path/to/omada-mcp/.venv/bin/omada-mcp"
    }
  }
}
```

## Available Tools

| Tool | Description |
|---|---|
| `get_controller_status` | Controller version, model, firmware, capacity |
| `get_sites` | All sites with region, timezone, scenario |
| `get_user_info` | Current user, role, privileges |
| `get_network_overview` | Gateway health, WAN ports, AP/switch/client counts |
| `get_wifi_channels` | Channel utilization across all bands |
| `get_devices` | All devices with status, CPU/mem, firmware |
| `get_device_detail` | Single device by name or MAC |
| `get_active_clients` | Connected clients with signal, traffic, VLAN |
| `get_known_clients` | All historically known clients |
| `get_wlans` | WLAN groups |
| `get_ssids` | SSIDs with VLAN assignments |
| `get_lan_networks` | LAN profiles with DHCP and gateway |
| `get_alerts` | Site alerts (active or resolved) |
| `get_alert_count` | Number of active alerts |

## Testing

```bash
# Unit tests
pytest tests/test_client_auth.py -v

# Live integration tests (requires .env)
pytest tests/test_live.py -v -s
```
```

- [ ] **Step 2: Register the MCP server in Claude settings**

Add to `~/.claude/settings.json` under `mcpServers`:

```json
"omada": {
  "command": "/Users/D054904/kohlsalem/omada-mcp/.venv/bin/omada-mcp"
}
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "DOC: add README with setup, tools reference, and testing instructions"
```

---

### Task 6: End-to-End Verification

- [ ] **Step 1: Restart Claude Code to pick up the new MCP server**

The user needs to restart Claude Code for the new MCP server to load. After restart, verify tools are available.

- [ ] **Step 2: Test each tool via Claude**

Ask Claude to run:
- "What's my Omada controller status?"
- "Show me all network devices"
- "List active clients"
- "Show WiFi channel utilization"
- "What SSIDs and VLANs are configured?"
- "Show LAN networks"
- "Any active alerts?"

Expected: Each tool returns formatted data from the live controller.
