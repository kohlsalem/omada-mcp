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

## Deployment

### Local (stdio — default)

Register with Claude Code in `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "omada": {
      "command": "/path/to/omada-mcp/.venv/bin/omada-mcp"
    }
  }
}
```

### Docker (HTTP with Basic Auth)

```bash
cp .env.example .env
# Edit .env — set OMADA_* and MCP_USERNAME/MCP_PASSWORD

docker compose up -d
```

The server starts on port 8000 with Basic Auth. Connect any MCP client using the streamable-http transport at `http://<host>:8000/mcp/`.

Environment variables for HTTP mode:

| Variable | Required | Default | Description |
|---|---|---|---|
| `MCP_TRANSPORT` | no | `stdio` | `stdio` or `streamable-http` |
| `MCP_HOST` | no | `0.0.0.0` | Bind address |
| `MCP_PORT` | no | `8000` | Listen port |
| `MCP_USERNAME` | yes (HTTP) | — | Basic Auth username |
| `MCP_PASSWORD` | yes (HTTP) | — | Basic Auth password |

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
# Unit tests (all)
pytest tests/ -v --ignore=tests/test_live.py

# Live integration tests (requires .env)
pytest tests/test_live.py -v -s
```

## License

This software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.
