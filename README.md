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
