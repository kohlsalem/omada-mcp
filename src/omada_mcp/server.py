"""Omada MCP Server — tools for monitoring and managing an Omada Controller."""

import logging
import sys
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from omada_mcp.client import OmadaClient

# Logging to stderr only (stdout is JSON-RPC)
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("omada-mcp")

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
        "WiFi channel analysis, LAN/WLAN configuration, and alerts."
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
async def get_devices() -> str:
    """List all network devices (gateways, switches, APs) with status, CPU/mem, firmware, and client count."""
    devices = await _get_client().get_devices()
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
    devices = await _get_client().get_devices()
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
    clients = await _get_client().get_active_clients()

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
async def get_known_clients() -> str:
    """List all historically known clients (active and inactive) with MAC, last seen, and traffic totals."""
    clients = await _get_client().get_known_clients()

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
async def get_lan_networks() -> str:
    """List LAN network profiles with VLAN, gateway/subnet, DHCP settings, and domain."""
    networks = await _get_client().get_lan_networks()
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
    alerts = await _get_client().get_alerts(resolved=resolved)

    if not alerts:
        return f"No {'resolved ' if resolved else 'active '}alerts."

    lines = [f"Alerts ({len(alerts)}):"]
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
