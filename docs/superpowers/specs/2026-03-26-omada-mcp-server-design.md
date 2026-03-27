# Omada MCP Server — Design Spec

## Overview

MCP server that wraps the TP-Link Omada Controller's internal REST API (v2), providing Claude with direct access to network monitoring, device status, client information, and configuration analysis for a home network managed by an OC220 hardware controller.

**Target controller:** `https://omada.kohlsalem.com/` (OC220, firmware 1.2.11, controller version 6.0.0.36)
**Site:** Riffenzell 7 (single site)
**Auth user:** Viewer role (read-only)

## Stack

- **Language:** Python 3.12+
- **MCP SDK:** `mcp[cli]` (FastMCP)
- **HTTP client:** `httpx`
- **Build system:** hatch (pyproject.toml)
- **Config:** `.env` file with env-var fallback
- **Pattern:** Matches existing `pulse-mcp` project structure

## Project Structure

```
omada-mcp/
  src/omada_mcp/
    __init__.py
    client.py       # OmadaClient — auth, session, HTTP calls
    server.py       # FastMCP tools — formatted output
  pyproject.toml
  .env.example
  .gitignore
  README.md
```

## Authentication Flow

The Omada Controller API uses a cookie-based session with CSRF token protection.

```
1. POST /api/v2/login
   Body: { "username": "...", "password": "..." }
   Response: { "result": { "omadacId": "<cid>", "token": "<csrf>" } }
   Set-Cookie: TPOMADA_SESSIONID=<session>

2. GET /api/v2/current/user/init-info
   Headers: Cookie + Csrf-Token
   Response: { "result": { "omadacId": "<cid>", "siteId": "<site>" } }

3. All subsequent calls:
   URL prefix: /{omadacId}/api/v2/...
   Headers: Cookie: TPOMADA_SESSIONID=<session>
            Csrf-Token: <csrf>
```

### Session Management

- Login on first API call (lazy init)
- Store `session_cookie`, `csrf_token`, `omadac_id`, `site_id` in memory
- On HTTP response returning HTML instead of JSON (session expired) → automatic re-login
- On `errorCode != 0` → raise descriptive error with the `msg` field

### Configuration

Via `.env` file (primary) or environment variables (fallback, for MCP server config in settings.json):

| Variable | Required | Default | Description |
|---|---|---|---|
| `OMADA_URL` | yes | — | Base URL (e.g. `https://omada.kohlsalem.com`) |
| `OMADA_USERNAME` | yes | — | Login username |
| `OMADA_PASSWORD` | yes | — | Login password |
| `OMADA_SITE` | no | first site | Site name or ID to use |
| `OMADA_SKIP_TLS_VERIFY` | no | `false` | Skip TLS certificate verification |

## API Client (`client.py`)

### Class: `OmadaClient`

```python
class OmadaClient:
    def __init__(self, url, username, password, site=None, skip_tls_verify=False)

    # Auth
    async def _login() -> None
    async def _ensure_auth() -> None
    async def _get(path: str, params: dict = None) -> Any
    async def _post(path: str, json: Any = None) -> Any

    # Controller-level (prefix: /{cid}/api/v2/)
    async def get_controller_status() -> dict
    async def get_sites() -> dict
    async def get_capabilities() -> list
    async def get_user_detail() -> dict

    # Site-level (prefix: /{cid}/api/v2/sites/{siteId}/)
    async def get_dashboard_overview() -> dict
    async def get_wifi_channels() -> dict
    async def get_devices(page: int = 1, page_size: int = 100) -> dict
    async def get_active_clients(page: int = 1, page_size: int = 100) -> dict
    async def get_known_clients(page: int = 1, page_size: int = 100) -> dict
    async def get_wlans() -> dict
    async def get_ssids() -> dict
    async def get_lan_networks(page: int = 1, page_size: int = 100) -> dict
    async def get_alerts(resolved: bool = False, page: int = 1, page_size: int = 50) -> dict
    async def get_alert_count() -> dict
```

### URL Construction

All site-level methods build URLs as:
```
/{omadac_id}/api/v2/sites/{site_id}/{endpoint}
```

Controller-level methods:
```
/{omadac_id}/api/v2/{endpoint}
```

### Response Handling

All API responses follow this pattern:
```json
{ "errorCode": 0, "msg": "Success.", "result": { ... } }
```

The client:
- Returns `result` directly on `errorCode == 0`
- Raises `OmadaApiError(errorCode, msg)` otherwise
- Detects HTML responses (session expired) and re-authenticates

## MCP Tools (`server.py`)

### Controller & System

#### `get_controller_status`
Returns controller version, model, firmware, IP, uptime, storage usage, and device capacity (adopted vs. max devices).

**Endpoint:** `GET /{cid}/api/v2/settings/system/status`

#### `get_sites`
Lists all sites with name, region, timezone, scenario, and supported features.

**Endpoint:** `GET /{cid}/api/v2/sites/basic`

#### `get_user_info`
Shows current user details: name, role, site privileges.

**Endpoint:** `GET /{cid}/api/v2/current/user-detail`

### Dashboard & Overview

#### `get_network_overview`
Full network health snapshot: gateway status (CPU, mem, temp, WAN ports), switch count and port/power info, AP count, total clients (wired/wireless/guest).

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/dashboard/overviewDiagram`

#### `get_wifi_channels`
Channel utilization across 2.4 GHz, 5 GHz, and 6 GHz bands. Shows which channels are in use, how many APs and clients per channel, and utilization percentage.

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/dashboard/channels`

### Devices

#### `get_devices`
All network devices (gateways, switches, APs) with: name, model, firmware, IP, status, CPU/mem usage, uptime, client count, config sync status.

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/grid/devices`

**Parameters:** `currentPage`, `currentPageSize`

#### `get_device_detail(name_or_mac: str)`
Detailed info for a single device, found by name or MAC address from the devices list.

**Implementation:** Calls `get_devices`, filters by name or MAC.

### Clients

#### `get_active_clients`
Currently connected clients with: name, hostname, MAC, IP, connection type (wired/wireless), SSID, AP name, signal strength (RSSI/SNR), channel, WiFi mode, VLAN, traffic up/down, uptime.

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/clients?filters.active=true`

**Parameters:** `currentPage`, `currentPageSize`

#### `get_known_clients`
All historically known clients (active and inactive): MAC, name, last seen, total traffic, wireless/wired, blocked status, VLAN.

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/insight/clients`

**Parameters:** `currentPage`, `currentPageSize`

### Network Configuration

#### `get_wlans`
WLAN groups with name, primary flag, max SSIDs per band.

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/setting/wlans`

#### `get_ssids`
All SSIDs with their VLAN assignments, grouped by WLAN.

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/setting/ssids`

#### `get_lan_networks`
LAN network profiles: name, VLAN ID, gateway/subnet, DHCP settings (range, DNS, lease time), domain, isolation, portal settings.

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/setting/lan/networks`

**Parameters:** `currentPage`, `currentPageSize`

### Alerts & Logs

#### `get_alerts`
Site alerts (optionally filtered by resolved status).

**Endpoint:** `GET /{cid}/api/v2/sites/{siteId}/logs/alerts`

**Parameters:** `filters.resolved`, `currentPage`, `currentPageSize`

**Note:** Requires `filters.timeStart` and `filters.timeEnd` (epoch milliseconds). The client automatically sets these to cover the last 30 days when not explicitly provided by the tool caller.

#### `get_alert_count`
Number of active alerts for the controller.

**Endpoint:** `GET /{cid}/api/v2/alerts/num`

## Output Format

All tools return human-readable formatted strings (matching pulse-mcp convention). The LLM can parse and reason over this text directly.

Example for `get_network_overview`:
```
Network Overview — Riffenzell 7
  Gateway: Router Keller (connected)
    CPU: 1%  Mem: 16%  Temp: 42°C
    WAN1: 2.5G WAN1 (192.168.2.2) — up
    WAN2: 2.5G WAN/LAN2 (192.168.1.100) — up
  Switches: 1 connected, 0 disconnected
    Ports: 16 total, 0 available  Power: 15.4W
  APs: 3 connected, 0 disconnected, 0 isolated
  Clients: 54 total (3 wired, 51 wireless, 0 guest)
```

## MCP Server Registration

In `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "omada": {
      "command": "/Users/D054904/kohlsalem/omada-mcp/.venv/bin/omada-mcp",
      "env": {}
    }
  }
}
```

Credentials in `/Users/D054904/kohlsalem/omada-mcp/.env`:
```
OMADA_URL=https://omada.kohlsalem.com
OMADA_USERNAME=anzeiger
OMADA_PASSWORD=Display/01
OMADA_SKIP_TLS_VERIFY=true
```

## Extensibility

The design supports later expansion to write operations (client blocking, device reboot, SSID config changes) by:
- Adding write methods to `OmadaClient` (`_post`, `_put`, `_patch`, `_delete`)
- Adding corresponding MCP tools in `server.py`
- Using a user with higher privileges than Viewer

The client's `_post` method is already part of the base design to support this.

## Verified API Endpoints

All endpoints below have been tested against the live controller and confirmed working with the Viewer role:

| Method | Endpoint | Status |
|---|---|---|
| POST | `/api/v2/login` | OK |
| GET | `/api/v2/current/login-status?needToken=true` | OK |
| GET | `/api/v2/current/user/init-info` | OK |
| GET | `/{cid}/api/v2/settings/system/status` | OK |
| GET | `/{cid}/api/v2/sites/basic` | OK |
| GET | `/{cid}/api/v2/capabilities` | OK |
| GET | `/{cid}/api/v2/current/user-detail` | OK |
| GET | `/{cid}/api/v2/alerts/num` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/dashboard/overviewDiagram` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/dashboard/channels` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/grid/devices` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/clients?filters.active=true` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/insight/clients` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/setting/wlans` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/setting/ssids` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/setting/lan/networks` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/logs/alerts` | OK (needs time filters) |
| GET | `/{cid}/api/v2/sites/{siteId}/dpi/status` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/dashboard/alertLogs` | OK |
| GET | `/{cid}/api/v2/sites/{siteId}/logs/notification` | OK |
