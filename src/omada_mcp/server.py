"""Omada MCP Server — tools for monitoring and managing an Omada Controller."""

import base64
import json
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from omada_mcp.client import OmadaClient, SITE_RESOURCES, REPORT_CARDS

# Logging to stderr only (stdout is JSON-RPC)
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("omada-mcp")


# ═══════════════════════════════════════════════════════════════════
#  BASIC AUTH MIDDLEWARE (HTTP mode only)
# ═══════════════════════════════════════════════════════════════════


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware enforcing HTTP Basic Authentication."""

    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Basic "):
            return self._unauthorized()

        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            user, password = decoded.split(":", 1)
        except Exception:
            return self._unauthorized()

        if not (
            secrets.compare_digest(user, self._username)
            and secrets.compare_digest(password, self._password)
        ):
            return self._unauthorized()

        return await call_next(request)

    @staticmethod
    def _unauthorized() -> Response:
        return Response(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="omada-mcp"'},
        )

_client: OmadaClient | None = None


def _get_client() -> OmadaClient:
    global _client
    if _client is None:
        _client = OmadaClient()
    return _client


@asynccontextmanager
async def _lifespan(server):
    """Manage OmadaClient lifecycle — clean up on shutdown."""
    yield
    global _client
    if _client is not None:
        await _client.close()
        _client = None
        logger.info("OmadaClient closed.")


mcp = FastMCP(
    "omada",
    instructions=(
        "MCP server for TP-Link Omada Controller. "
        "Provides access to network monitoring, device status, client information, "
        "WiFi analysis, topology, ports/PoE, WAN/firewall/routing/VPN/DNS settings, and logs. "
        "All tools are read-only. Use list_read_resources to discover configuration sections. "
        "Site-aware tools accept a site name or ID; omit it for the configured default."
    ),
    lifespan=_lifespan,
)


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
async def get_network_overview(site: str | None = None) -> str:
    """Get full network health snapshot: gateway health, WAN ports, switch/AP/client counts, and power consumption."""
    d = await _get_client().get_dashboard_overview(site)

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
async def get_wifi_channels(site: str | None = None) -> str:
    """Get WiFi channel utilization across 2.4 GHz, 5 GHz, and 6 GHz bands."""
    data = await _get_client().get_wifi_channels(site)
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


@mcp.tool()
async def check_connection() -> str:
    """Verify that the Omada Controller is reachable and authentication is working."""
    result = await _get_client().check_connection()
    if result["connected"]:
        return (
            f"Connection: OK\n"
            f"  Authenticated: yes\n"
            f"  Controller: {result['controller']}\n"
            f"  Version: {result['version']}"
        )
    return (
        f"Connection: FAILED\n"
        f"  Authenticated: {'yes' if result['authenticated'] else 'no'}\n"
        f"  Error: {result.get('error', 'unknown')}"
    )


# ═══════════════════════════════════════════════════════════════════
#  DEVICE TOOLS
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_devices(site: str | None = None) -> str:
    """List all network devices (gateways, switches, APs) with status, CPU/mem, firmware, and client count."""
    devices = await _get_client().get_devices(site)
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
async def get_device_detail(name_or_mac: str, site: str | None = None) -> str:
    """Read full device configuration/status: AP radios/uplink, switch STP/PoE, or gateway ports."""
    return _json(await _get_client().get_device_detail(name_or_mac, site))


# ═══════════════════════════════════════════════════════════════════
#  CLIENT TOOLS
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_active_clients(site: str | None = None) -> str:
    """List all currently connected clients with IP, MAC, SSID, signal, traffic, and VLAN."""
    clients = await _get_client().get_active_clients(site)

    if not clients:
        return "No active clients."

    lines = [f"Active Clients ({len(clients)}):"]
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
async def get_known_clients(site: str | None = None) -> str:
    """List all historically known clients (active and inactive) with MAC, last seen, and traffic totals."""
    clients = await _get_client().get_known_clients(site)

    if not clients:
        return "No known clients."

    lines = [f"Known Clients ({len(clients)}):"]
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
async def get_wlans(site: str | None = None) -> str:
    """List WLAN groups with name, primary flag, and max SSIDs per band."""
    data = await _get_client().get_wlans(site)
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
async def get_ssids(site: str | None = None) -> str:
    """List all SSIDs with their VLAN assignments, grouped by WLAN."""
    data = await _get_client().get_ssids(site)
    wlans = data.get("ssids", [])
    if not wlans:
        return "No SSIDs found."

    lines = ["SSIDs:"]
    for wlan in wlans:
        lines.append(f"\n  WLAN Group: {wlan.get('wlanName', '?')}")
        for ssid in wlan.get("ssidList", []):
            security = ssid.get("security", "?")
            band = ssid.get("band", "")
            band_str = f"  Band: {band}" if band else ""
            rate_limit_down = ssid.get("rateLimitDownload", 0)
            rate_limit_up = ssid.get("rateLimitUpload", 0)
            rate_str = ""
            if rate_limit_down or rate_limit_up:
                rate_str = f"  Rate: {_fmt_bytes(rate_limit_down)}/s down, {_fmt_bytes(rate_limit_up)}/s up"
            lines.append(
                f"    {ssid.get('ssidName', '?')}  VLAN: {ssid.get('vlanId', '?')}"
                f"  Security: {security}{band_str}{rate_str}"
            )

    return "\n".join(lines)


@mcp.tool()
async def get_lan_networks(site: str | None = None) -> str:
    """List LAN network profiles with VLAN, gateway/subnet, DHCP settings, and domain."""
    networks = await _get_client().get_lan_networks(site)
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
async def get_alerts(
    resolved: bool | None = False, site: str | None = None,
    start_ms: int | None = None, end_ms: int | None = None,
) -> str:
    """Read alerts: false=active, true=resolved, null=both. Unix millisecond range defaults to last 30 days."""
    alerts = await _get_client().get_alerts(
        resolved=resolved, site=site, start_ms=start_ms, end_ms=end_ms,
    )

    if not alerts:
        return "No matching alerts."

    lines = [f"Alerts ({len(alerts)}):"]
    for a in alerts:
        lines.append(
            f"  [{a.get('level', '?').upper()}] {a.get('msg', a.get('message', '?'))}\n"
            f"    Type: {a.get('type', '?')}  Time: {a.get('timestamp', '?')}"
        )

    return "\n".join(lines)


# Detailed readers preserve controller fields rather than guessing model-specific schemas.
def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def list_read_resources() -> str:
    """Discover settings/status sections supported by read_site_resource, with API paths."""
    return _json({name: {"endpoint": path, "paginated": paginated}
                  for name, (path, paginated) in SITE_RESOURCES.items()})


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def read_site_resource(resource: str, site: str | None = None) -> str:
    """Read full JSON for a settings/status section. Use list_read_resources for names.

    Includes wan, gateway_acls, switch_acls, ap_acls, gateway_custom_acls,
    gateway_acl_mode, port_forwarding, static_routes, policy_routes,
    dhcp_reservations, port_profiles, rate_limits, vpn_pptp_l2tp, vpn_clients,
    ssl_vpn_server, dns_proxy, lan_dns, portals, switch_ports, poe, port_counters,
    dpi_status, notifications, wlans, ssids, and lan_networks.
    Fetches all pages of tables. Availability depends on hardware/version/role;
    API permission/unsupported errors are reported rather than treated as empty data.
    gateway_acls reads standard rules; gateway_custom_acls is a separate table.
    Check gateway_acl_mode before interpreting an empty table. These are configured
    rules, not proof of enforcement; use device/config-sync status separately.
    """
    return _json(await _get_client().get_site_resource(resource, site))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_capabilities() -> str:
    """Read controller capabilities to identify supported features."""
    return _json(await _get_client().get_capabilities())


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_topology(site: str | None = None) -> str:
    """Read network topology, links, device relationships, and last update time as JSON."""
    return _json(await _get_client().get_topology(site))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_vpn_configs(site: str | None = None, group: str | None = None) -> str:
    """List modern VPN configuration tables, IDs, types, enable flags and supported features.

    group: site_to_site, servers, clients, or omit for all three. Includes IPsec,
    L2TP, WireGuard, OpenVPN and SSL VPN where configured. Fetches all pages.
    Use get_vpn_detail for peers, subnets, IKE/proposals and other full configuration fields.
    """
    return _json(await _get_client().get_vpn_configs(site, group))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_vpn_detail(
    name_or_id: str, site: str | None = None, group: str | None = None,
) -> str:
    """Read full VPN configuration by exact name or ID, with case-insensitive name matching.

    Optional group: site_to_site, servers, clients. Preserves protocol-specific
    controller fields: IPsec/IKE phase-1/phase-2 proposals, remote/local networks,
    peers, authentication/encryption and lifetimes where returned. L2TP encryption
    is separate from standalone IPsec (vpnType=2). Configuration can include secret
    values returned by the account. This is configuration, not live tunnel status.
    """
    return _json(await _get_client().get_vpn_detail(name_or_id, site, group))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_device_ports(name_or_mac: str, site: str | None = None) -> str:
    """Read device ports including available link, VLAN/profile, PoE and traffic fields."""
    return _json(await _get_client().get_device_ports(name_or_mac, site))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_client_detail(name_or_mac_or_ip: str, site: str | None = None) -> str:
    """Find a client by exact name, MAC or IP; read signal/SNR, AP/switch, rates, VLAN, IP settings and status."""
    return _json(await _get_client().get_client_detail(name_or_mac_or_ip, site))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_events(
    site: str | None = None, start_ms: int | None = None, end_ms: int | None = None,
) -> str:
    """Read all site event-log pages as JSON. Unix millisecond range defaults to last 30 days."""
    return _json(await _get_client().get_events(site, start_ms, end_ms))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_incidents(
    site: str | None = None, start_ms: int | None = None,
    end_ms: int | None = None, status: int | None = None,
    search: str | None = None,
) -> str:
    """Read all incident pages, including causes/affected objects where returned, plus statistics.

    Time range uses Unix milliseconds, default last 30 days. Omit status for all
    statuses, or supply a controller enum value from returned data. Optional search
    is passed to the controller. Does not acknowledge, resolve, ignore or delete incidents.
    """
    return _json(await _get_client().get_incidents(site, start_ms, end_ms, status, search))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_incident_summary(
    site: str | None = None, start_ms: int | None = None,
    end_ms: int | None = None, status: int | None = None,
) -> str:
    """Read incident counts by status, severity and category for a Unix millisecond range (default 30 days).

    Omit status for all statuses. The separate active count is the current unresolved
    count, independent of the requested historical window.
    """
    return _json(await _get_client().get_incident_summary(site, start_ms, end_ms, status))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_audit_logs(
    site: str | None = None, start_ms: int | None = None,
    end_ms: int | None = None, controller_wide: bool = False,
    search: str | None = None,
) -> str:
    """Read administrator audit history: operator, source IP, action, result and change values where available.

    Default is the selected site's audit log. Set controller_wide=true for controller
    audit activity such as logins (a separate scope, not necessarily a superset of site
    changes). Do not combine controller_wide with site. Unix millisecond range defaults
    to last 30 days. Fetches all pages; optional search is server-side.
    """
    return _json(await _get_client().get_audit_logs(site, start_ms, end_ms, controller_wide, search))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_security_logs(
    site: str | None = None, start_ms: int | None = None,
    end_ms: int | None = None, archived: bool = False,
    search: str | None = None,
) -> str:
    """Read IDS/IPS threat detections and IPS enable/settings. All pages, optional server-side search.

    Unix millisecond range defaults to last 30 days. archived=false reads unarchived
    detections; true reads archived ones. Empty data is not proof of no threats,
    especially when IDS/IPS is disabled. Does not archive, block or modify detections.
    """
    return _json(await _get_client().get_security_logs(site, start_ms, end_ms, archived, search))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_usage_status(site: str | None = None) -> str:
    """Check DPI support, enabled collection/logging, cropping and history retention before interpreting usage."""
    return _json(await _get_client().get_usage_status(site))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_application_usage(
    site: str | None = None, start: int | None = None, end: int | None = None,
    family_ids: list[int] | None = None,
) -> str:
    """Statistics tab: traffic by category and all allowed applications, including upload/download bytes.

    Range is Unix SECONDS (default last 24h). Optional family_ids restrict the application
    table; overview remains site-wide. Returns category/application IDs for drilldowns.
    DPI classifies services, not individual destination IPs/domains. Includes collection/retention status.
    """
    return _json(await _get_client().get_application_usage(site, start, end, family_ids))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_client_application_usage(
    name_or_mac_or_ip: str, site: str | None = None,
    start: int | None = None, end: int | None = None,
) -> str:
    """Read a client's historical DPI categories and application upload/download/packet totals.

    Range is Unix SECONDS, default last 24h. Accepts historical MACs directly.
    Cropped/disabled/expired data may be empty; never interpret that as zero usage.
    """
    return _json(await _get_client().get_client_application_usage(name_or_mac_or_ip, site, start, end))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_application_clients(
    family_id: int, application_ids: list[int], site: str | None = None,
    start: int | None = None, end: int | None = None,
) -> str:
    """Which clients used these applications? Use IDs from get_application_usage.

    Range is Unix SECONDS, default last 24h. Returns all client table pages and DPI
    collection/retention status. Cropped data may be empty, not proof of no usage.
    """
    return _json(await _get_client().get_application_clients(family_id, application_ids, site, start, end))


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def list_report_cards() -> str:
    """Discover historical Reports tab cards supported by get_report (traffic, clients, AP/switch/SSID/PoE/health)."""
    return _json(REPORT_CARDS)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_report(
    cards: list[str], site: str | None = None,
    start: int | None = None, end: int | None = None, top_k: int = 20,
) -> str:
    """Read historical Reports tab cards. Discover names with list_report_cards.

    Range is Unix SECONDS, default last 24h. Start with overviewSummary, internet,
    network, clientConnectionTrend, topSsidByTraffic. Internet and all-network totals
    are distinct scopes, not additive. Returns controller time-series and totals.
    Uses a read-only report-query POST; does not save, export or schedule reports.
    """
    return _json(await _get_client().get_report(cards, site, start, end, top_k))


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════


def main():
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        username = os.environ.get("MCP_USERNAME", "")
        password = os.environ.get("MCP_PASSWORD", "")
        if not username or not password:
            raise SystemExit(
                "MCP_USERNAME and MCP_PASSWORD must be set for HTTP transport."
            )

        host = os.environ.get("MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("MCP_PORT", "8000"))

        app = mcp.streamable_http_app()
        app.add_middleware(BasicAuthMiddleware, username=username, password=password)

        logger.info("Starting HTTP server on %s:%d", host, port)
        uvicorn.run(app, host=host, port=port)
    else:
        raise SystemExit(
            f"Unknown MCP_TRANSPORT={transport!r}. Use 'stdio' or 'streamable-http'."
        )


if __name__ == "__main__":
    main()
