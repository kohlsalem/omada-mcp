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
| `get_client_detail` | Client lookup by name, hostname, MAC or IP; exact matches preferred, unique partial names accepted |
| `get_topology` | Network topology, links and device relationships |
| `get_capabilities` | Controller-supported capabilities |
| `list_read_resources` | Discover settings/status resources and their API paths |
| `read_site_resource` | Full JSON for a named settings/status resource; automatically fetches all table pages |
| `get_wlans` | WLAN groups |
| `get_ssids` | SSIDs with VLAN assignments |
| `get_lan_networks` | LAN profiles with DHCP and gateway |
| `get_alerts` | Site alerts: `resolved=false` active, `true` resolved, `null` both; configurable time range |
| `get_alert_count` | Number of active alerts |
| `get_events` | Bounded event page: default 50 records/24h, max 100; page/key/severity/device filters |
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
| `get_vpn_configs` | Modern site-to-site, VPN-server and VPN-client tables, IDs, types and capabilities |
| `get_vpn_detail` | Full protocol-specific VPN configuration by name or ID, including IPsec/IKE fields where configured |
| `get_ssid_detail` | Dedicated SSID security/PMF/band/VLAN/rate/MAC/schedule configuration |
| `get_acl_rules` | Gateway/switch/AP ACLs with reference resolution, syslog/counter availability and switch bindings |
| `get_rf_scan` | Existing AP RF scan results/status; never starts a scan |
| `list_controller_resources` | Discover controller-level read sections |
| `read_controller_resource` | Controller settings/certificate metadata, NTP, cloud, accounts/roles/MFA, auto-backup |
| `get_resource_status` | Rogue AP/schedule rows plus explicit API access, permission, count and unknown activation status |

### Secret masking and output annotations

MCP JSON output recursively masks WLAN PSKs (`ssidOverrides` and `pskSetting`),
portal passwords, Twilio SID/token settings, VPN private/shared keys, SMTP/RADIUS
credentials, tokens and SNMP communities by default. Audit old/new-value blobs
are masked as well. This happens at the output boundary; raw API-client responses
are intended for internal processing, not direct display.

Only explicit `include_secrets=true` on `get_device_detail`, `get_ssid_detail`,
`get_vpn_detail`, `read_site_resource` or `read_controller_resource` opts that one
call into plaintext values returned by Omada. This never changes later calls.
Portal outputs also mask SMS/Twilio phone numbers and redundant site/controller
identifiers. IDs in other resources remain usable for lookups. Numeric dictionary
keys (e.g. the VPN type map) are supported by the masking layer.

Port `linkSpeed`/`maxSpeed` codes are preserved with additional `*Mbps`/`*Text`
fields (1=10M, 2=100M, 3=1G, 4=2.5G, 5=10G, 6=5G, 7=25G, 8=100G, 9=40G).
Code 0 remains unknown/auto rather than being reported as a measured speed.
Configured speed and nested `portStatus` negotiated speed are separate fields.

SSID responses add security-family, PMF and band labels. Detailed PSK mode depends
on `versionPsk`, band and mode. Raw enum values are retained. AP `ssidOverrides`
can contain placeholders, so use `get_ssid_detail` for configured SSID values.
WAN `onlineDetection` describes configured probes, not measured health.
PSK mode 4 is labelled WPA2-PSK/WPA3-SAE transition mode; an explicitly 6-GHz-only
SSID is labelled WPA3-SAE.

### Parallel calls and empty resources

Controller requests are limited to four in flight per server client. Concurrent
cold calls share one login; HTML session-expiry recovery is serialized too.
Twelve simultaneous reader calls including `ssid_details` completed in a live
check. The reported client message “may not have run” remains unconfirmed as a
server/transport fault; a client can also omit scheduling calls. This check covers
the server readers, not every external MCP client's orchestration or timeouts.

`get_resource_status("rogue_aps"|"reboot_schedules"|"upgrade_schedules")` returns
`data` and `status` rather than a bare list. It reports observed permission/API
read support and record count. Activation is `null` when the endpoint does not
report it. No rogue detections is not proof that detection is enabled; no schedule
records means no configured schedules. Existing resource readers retain their
list response for compatibility; the catalog points to the status tool.

### Bounded event queries (response-shape change)

`get_events()` now returns an object with `data`, `page`, `limit`, `totalRows`,
`has_more`, `next_page`, and a fixed `range`, instead of fetching every event.
Default: last 24h, 50 rows; `limit` is capped at 100. Oversized rows are clipped
and explicitly marked `truncated_fields`. The prior unbounded 30-day response
could exceed MCP transport limits.

`event_key`, `severity` and `device` (exact name/MAC) are applied locally to the
bounded API page; severity is supplemented from notification definitions when
missing. `totalRows` is the count **before** local filters. An empty filtered page
may still have `next_page`: continue using the same returned `range`, `limit` and
filters. This prevents a filtered request from silently scanning megabytes.

### VPN configuration

`get_vpn_configs(site=None, group=None)` reads all three VPN groups, or a selected
`site_to_site`, `servers`, or `clients` group. `get_vpn_detail(name_or_id, site=None,
group=None)` retrieves a full configuration by exact ID or case-insensitive name.
Duplicate names require selecting an ID/group.

The modern VPN endpoints cover standalone IPsec (`vpnType=2`) as well as L2TP,
PPTP, OpenVPN, WireGuard and SSL VPN. Detail responses preserve the controller's
protocol-specific fields, including IPsec peer/network definitions, IKE version,
phase-1/phase-2 proposals and lifetimes where returned. L2TP's encryption setting
is distinct from a standalone IPsec profile. These are configuration reads, not
live tunnel-status queries. Keys/passwords are masked by default.

Inventory and detail reads were live-verified with the Viewer account against
configured WireGuard, L2TP and SSL VPN entries. No standalone IPsec profile was
present; preservation of its protocol-specific fields is covered by unit tests.

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
| `gateway_acls`, `switch_acls`, `ap_acls` | Standard gateway/switch/AP ACL rules (API types 0/1/2) |
| `gateway_custom_acls`, `gateway_acl_mode` | Separate custom gateway rule table and configured ACL mode |
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
| `ip_groups`, `ip_port_groups`, `mac_groups`, `time_profiles` | ACL objects and schedule definitions |
| `ssid_details`, `wireless_features`, `rrm`, `mac_auth` | Full SSID inventory, roaming/band steering/airtime, RRM and MAC authentication |
| `attack_defense`, `mac_filter_settings`, `mac_filters`, `ip_mac_binding_settings`, `ip_mac_bindings` | Network Security settings and rules |
| `url_filters`, `ap_url_filters`, `ips_settings` | Gateway/AP URL filters and IDS/IPS configuration |
| `upnp`, `mdns`, `bonjour_profiles`, `ddns`, `lan_multicast`, `nat_alg`, `one_to_one_nat`, `disable_nat` | Services, multicast and NAT settings |
| `site_settings`, `remote_logging`, `reboot_schedules`, `poe_schedules`, `upgrade_schedules` | Site settings, syslog and device schedules |
| `vpn_users` | Modern VPN user table (credentials masked) |
| `rogue_aps` | Existing Rogue AP detections; no scan triggered |
| `device_account` | Device account settings, if the configured role is permitted |

DHCP options remain in full `lan_networks`/WAN responses where returned. The
SSID detail's `rateControl` contains minimum-rate settings, `wlanSchedule` its
schedule, and `macFilter` its filtering configuration. `wireless_features` covers
global roaming/band-steering; `rrm` covers automatic radio planning settings.

Controller resources: `settings` (including certificate metadata), `general_ntp`,
`cloud_access`, `users`, `roles`, `current_user_mfa`, and `auto_backup`.
On the verified Viewer account, `device_account` and `auto_backup` return explicit
permission errors; the other new resources were readable. RF scan results may
only contain status if no scan has completed. Full certificate/key export and
runtime ACL enforcement verification are not implemented.

All site-level tools accept an optional `site` name or ID. Omit it to use
`OMADA_SITE`, or the controller's default site if unset. Site selection is per
request, so concurrent requests for different sites do not change one another's
default. `get_alert_count` is controller-wide.

ACL tables are separate: an empty `gateway_custom_acls` table does not mean there
are no standard `gateway_acls`. Check `gateway_acl_mode` for mode metadata. The
standard reader was verified against 14 gateway, 3 switch and 2 AP configured
rules. Rule presence/enable flags alone do not prove enforcement on a device.
The catalog now includes the `type` parameter for each standard ACL resource.
`get_acl_rules(kind="gateway"|"switch"|"ap")` resolves network, IP/IP-port/MAC
groups, SSIDs and time profiles, preserves syslog configuration, and distinguishes
unsupported/missing hit counters from zero hits. Type 11 is **NOT network**, not
"all destinations". Switch bindings decode 0=all ports, 1=custom ports,
2=all switches, 3=custom switches. Candidate inventory ports and explicit custom
selections are separate. Unresolved references and lookup errors remain visible.
Resolved objects contain **only names and IDs by default**, avoiding repeated LAN
DHCP settings per rule. `expand_objects=true` opts into full referenced objects.
The verified 14-rule gateway response shrank from about 118,000 to 28,000 characters.

Detail/resource/topology/event tools return JSON preserving controller field names;
existing inventory tools return concise summaries. API enum values are preserved.
Log tools accept `start_ms` and `end_ms` (Unix milliseconds). Events default to
24h and one bounded page; alerts/audit/security/incidents retain their 30-day range.

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
and report computation use POST requests. Sensitive configuration values are
masked by default and available only through the explicit per-call opt-in above.

## Testing

```bash
# Unit tests (all)
pytest tests/ -v --ignore=tests/test_live.py

# Live integration tests (requires .env)
pytest tests/test_live.py -v -s
```

## License

This software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.
