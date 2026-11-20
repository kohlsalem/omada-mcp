# omada-mcp

Read-only MCP server for TP-Link Omada Controller. Provides network monitoring, detailed device/client inspection, topology, ports/PoE, configuration analysis, and logs.

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

Register with Claude Code in `~/.claude.json` (top-level `mcpServers`):

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
| `get_device_detail` | Full device configuration/status by name, MAC or IP; includes radio, uplink, STP and PoE fields where available |
| `get_device_ports` | Device port status, profiles/VLANs, PoE and traffic fields |
| `get_active_clients` | Connected clients with signal, traffic, VLAN |
| `get_known_clients` | All historically known clients |
| `get_client_detail` | Full client record by exact name, MAC or IP, including SNR, rates and connection details |
| `get_topology` | Network topology, links and device relationships |
| `get_capabilities` | Controller-supported capabilities |
| `list_read_resources` | Discover settings/status resources and their API paths |
| `read_site_resource` | Full JSON for a named settings/status resource; automatically fetches all table pages |
| `get_wlans` | WLAN groups |
| `get_ssids` | SSIDs with VLAN assignments |
| `get_lan_networks` | LAN profiles with DHCP and gateway |
| `get_alerts` | Site alerts: `resolved=false` active, `true` resolved, `null` both; configurable time range |
| `get_alert_count` | Number of active alerts |
| `get_events` | Site event logs with configurable time range |
| `check_connection` | Verify reachability and authentication |
| `get_usage_status` | DPI collection/logging, cropping and history retention |
| `get_application_usage` | Statistics: categories and application upload/download totals |
| `get_client_application_usage` | A client's historical application/category traffic where available |
| `get_application_clients` | Clients responsible for selected applications, where available |
| `list_report_cards` | Discover 25 historical report cards |
| `get_report` | Reports: historical traffic, client trends, AP/switch/SSID/PoE/health summaries |
| `get_incidents` | All incident pages with optional status/search filtering and returned statistics |
| `get_incident_summary` | Incident counts by severity/category/status and current unresolved count |
| `get_audit_logs` | Site administrator changes or controller audit activity, with operator, source IP and results |
| `get_security_logs` | IDS/IPS threat detections (archived or unarchived) and IPS enable/settings |

### Incidents, audit and security logs

These tools accept optional `site`, `start_ms`, and `end_ms` (Unix milliseconds,
default last 30 days), and fetch all matching table pages. Incident and audit
results preserve controller fields. Incidents accept an optional raw `status`
enum from the controller; omit it for all statuses. Incident lists, audit logs
and security logs support server-side `search`.

`get_audit_logs()` reads the default site's change history. Use
`get_audit_logs(controller_wide=True)` for controller activity such as logins.
These are separate scopes; controller activity is not a superset of site changes.
`get_security_logs(archived=True)` reads archived detections; the default is
unarchived. The reader converts its millisecond inputs to the seconds required
by the threat API. The incident summary's `active` count is current, independent
of the historical filter.

Live verification returned populated audit records. Incidents were empty and
the IDS/IPS setting reported `enable=false`, with empty threat logs. An empty
security log does not establish that no threats occurred. No tools acknowledge,
resolve, archive or delete entries, or enable detection.

### Usage analytics and reports

Analytics tools use `start` and `end` in **Unix seconds**, defaulting to the last
24 hours. Log tools use milliseconds (`start_ms`/`end_ms`).

- `get_application_usage()` returns the Statistics tab's site-wide category totals
  and all allowed-application table pages, including upload/download byte counts.
  Optional `family_ids` restrict the application table. Its overview stays site-wide.
- Use category/application IDs from that response with `get_application_clients`
  to request attribution, or `get_client_application_usage` for a named client,
  IP or MAC. Historical MACs work without a current inventory record.
- `get_report(cards=["overviewSummary", "internet", "clientConnectionTrend"])`
  retrieves Reports tab totals and time series. `list_report_cards()` also lists
  wired/wireless, AP, switch, SSID, PoE and client onboarding cards.

Every DPI usage result includes collection and crop/retention status. On the
verified controller, site-wide application traffic is populated but per-client
DPI queries returned empty data, with `enableCrop=true` and `showDataDays=7`.
Empty attribution results do **not** establish zero usage. Reports may likewise
have empty DPI cards even while the Statistics tab has application data.

DPI identifies application/service classes, not individual destination IPs,
domains or connection flows. Internet, all-network and DPI totals cover distinct
scopes and should not be added together. The controller's totals, timestamps and
enum values are preserved rather than reinterpreted.

Report reads use the web UI's fixed `POST .../report/cards` query endpoint. This
computes data without saving, exporting or scheduling reports; all MCP tools
remain read-only. The client sends `Omada-Request-Source: web-local`, required by
the controller's session-authenticated OpenAPI endpoints.

### Configuration and status resources

Pass one of these names to `read_site_resource(resource, site=None)`:

| Resources | Information |
|---|---|
| `wan` | WAN ports, settings, load balancing and status |
| `gateway_acls` | Gateway firewall ACL rules |
| `port_forwarding`, `static_routes`, `policy_routes` | NAT and routing configuration |
| `dhcp_reservations` | Fixed IP/MAC assignments |
| `port_profiles`, `rate_limits` | Switch port/VLAN profiles and bandwidth profiles |
| `vpn_pptp_l2tp`, `vpn_clients`, `ssl_vpn_server` | Available VPN configurations (not every VPN type) |
| `dns_proxy`, `lan_dns` | DNS proxy settings and LAN DNS records |
| `portals` | Captive portal settings |
| `switch_ports`, `poe`, `port_counters` | Site-wide port inventory, PoE and counters |
| `dpi_status` | DPI support/status (not application traffic history) |
| `notifications` | Alert/event notification settings |
| `wlans`, `ssids`, `lan_networks` | Full fields behind the corresponding summary tools |

All site-level tools accept an optional `site` name or ID. Omit it to use
`OMADA_SITE`, or the controller's default site if unset. Site selection is per
request, so concurrent requests for different sites do not change one another's
default. `get_alert_count` is controller-wide.

Detail/resource/topology/event tools return JSON preserving controller field names;
existing inventory tools return concise summaries. API enum values are preserved.
Log tools accept `start_ms` and `end_ms` (Unix milliseconds); the default range is
the 30 days ending at `end_ms`, or now when omitted. Large ranges can return many
records, so use a narrower range for focused troubleshooting.

Example questions this enables:
- “Which switch ports supply PoE, and how much power are they using?”
- “Show the office AP's radio configuration and uplink.”
- “Which ports are forwarded, and what DHCP reservations exist?”
- “Show this client's SNR, VLAN, connection rates and AP.”
- “What events occurred around this device disconnecting?”

The expanded endpoints were live-verified with a Viewer account on controller
6.3.0.111. Availability and returned fields depend on controller version, hardware
and account privileges. Unsupported/permission errors are surfaced as errors,
not empty results. All exposed tools only read controller data; authentication
and report computation use POST requests. Configuration responses may include sensitive
values returned by Omada to the configured account.

## Testing

```bash
# Unit tests (all)
pytest tests/ -v --ignore=tests/test_live.py

# Live integration tests (requires .env)
pytest tests/test_live.py -v -s
```

## License

This software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.
