"""Live integration tests against the real Omada Controller.

Run with: pytest tests/test_live.py -v -s
Requires .env with valid OMADA_URL, OMADA_USERNAME, OMADA_PASSWORD.
"""

import os
import pytest
import pytest_asyncio
from pathlib import Path
from dotenv import load_dotenv

from omada_mcp.client import OmadaClient, SITE_RESOURCES, OPENAPI_RESOURCES, CONTROLLER_RESOURCES, OmadaApiError

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SKIP_LIVE = not os.getenv("OMADA_URL")


@pytest_asyncio.fixture
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
        assert isinstance(devices, list)
        assert len(devices) > 0
        print(f"  Devices: {[d['name'] for d in devices]}")

    async def test_get_active_clients(self, client):
        clients = await client.get_active_clients()
        assert isinstance(clients, list)
        print(f"  Active clients: {len(clients)}")

    async def test_get_known_clients(self, client):
        clients = await client.get_known_clients()
        assert isinstance(clients, list)
        print(f"  Known clients: {len(clients)}")

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
        assert isinstance(networks, list)
        print(f"  LAN networks: {[n['name'] for n in networks]}")

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

    async def test_check_connection(self, client):
        result = await client.check_connection()
        assert result["connected"] is True
        print(f"  Controller: {result['controller']} v{result['version']}")

    async def test_get_alerts(self, client):
        alerts = await client.get_alerts()
        assert isinstance(alerts, list)
        print(f"  Alerts: {len(alerts)}")

    @pytest.mark.parametrize("resource", SITE_RESOURCES)
    async def test_read_resources(self, client, resource):
        try:
            result = await client.get_site_resource(resource)
        except OmadaApiError as exc:
            if resource == "device_account" and exc.error_code == -1007:
                pytest.skip("Viewer is explicitly denied device-account settings")
            raise
        assert isinstance(result, (dict, list))

    async def test_detailed_readers(self, client):
        sites = await client.get_sites()
        site = sites["data"][0]["id"]
        devices = await client.get_devices(site)
        for device in devices:
            detail = await client.get_device_detail(device["mac"], site)
            assert detail["mac"] == device["mac"]
            assert isinstance(await client.get_device_ports(device["mac"], site), list)
        clients = await client.get_active_clients(site)
        if clients:
            detail = await client.get_client_detail(clients[0]["mac"], site)
            assert detail["mac"] == clients[0]["mac"]
        assert "topologyArray" in await client.get_topology(site)
        assert isinstance((await client.get_events(site))["data"], list)

    async def test_usage_and_reports(self, client):
        usage = await client.get_application_usage()
        assert "categoryTraffics" in usage["overview"]
        assert isinstance(usage["applications"], list)
        assert "retention" in usage["status"]
        if usage["applications"]:
            app = usage["applications"][0]
            attribution = await client.get_application_clients(app["familyId"], [app["applicationId"]])
            assert isinstance(attribution["clients"], list)
        clients = await client.get_active_clients()
        if clients:
            attribution = await client.get_client_application_usage(clients[0]["mac"])
            assert isinstance(attribution["applications"], list)
        report = await client.get_report(["overviewSummary", "internet", "clientConnectionTrend"])
        assert "totalTraffic" in report["cards"]["internet"]

    async def test_incident_audit_security_readers(self, client):
        incidents = await client.get_incidents()
        assert isinstance(incidents["data"], list)
        summary = await client.get_incident_summary()
        assert "statistics" in summary
        assert "activeNum" in summary["active"]
        assert isinstance(await client.get_audit_logs(), list)
        assert isinstance(await client.get_audit_logs(controller_wide=True), list)
        threats = await client.get_security_logs()
        assert "enable" in threats["ips_settings"]
        assert isinstance(threats["data"], list)
        assert isinstance((await client.get_security_logs(archived=True))["data"], list)

    async def test_vpn_configuration_readers(self, client):
        inventory = await client.get_vpn_configs()
        assert set(inventory["groups"]) == {"site_to_site", "servers", "clients"}
        for group, table in inventory["groups"].items():
            for item in table["data"]:
                result = await client.get_vpn_detail(item["id"], group=group)
                assert result["configuration"]["id"] == item["id"]
                assert result["configuration"]["vpnType"] == item["vpnType"]

    @pytest.mark.parametrize("resource", [*OPENAPI_RESOURCES, "vpn_users"])
    async def test_new_openapi_resources(self, client, resource):
        assert isinstance(await client.get_site_resource(resource), (dict, list))

    @pytest.mark.parametrize("resource", CONTROLLER_RESOURCES)
    async def test_controller_resources(self, client, resource):
        try:
            assert isinstance(await client.get_controller_resource(resource), (dict, list))
        except OmadaApiError as exc:
            if resource == "auto_backup" and exc.error_code == -1007:
                pytest.skip("Viewer is explicitly denied auto-backup settings")
            raise

    async def test_bounded_events_acl_resolution_and_masked_ssid(self, client):
        import json
        from omada_mcp.output import prepare_output

        result = await client.get_events(limit=10)
        assert len(result["data"]) <= 10
        assert result["range"]["end_ms"] - result["range"]["start_ms"] == 86400000
        assert len(json.dumps(prepare_output(result))) < 150000
        for kind, typ in [("gateway", 0), ("switch", 1), ("ap", 2)]:
            acl = await client.get_acl_rules(kind)
            assert all(row["type"] == typ for row in acl["data"])
            assert all("sourceResolved" in row for row in acl["data"])
        ssids = await client.get_site_resource("ssid_details")
        if ssids:
            detail = await client.get_ssid_detail(ssids[0]["id"])
            masked = prepare_output(detail)
            if detail.get("pskSetting", {}).get("securityKey"):
                assert masked["pskSetting"]["securityKey"] == "[REDACTED]"
        for device in await client.get_devices():
            if device["type"] == "ap":
                assert isinstance(await client.get_rf_scan(device["mac"]), (dict, list))
                break

    async def test_vpn_output_compact_acl_status_and_parallel_readers(self, client):
        import asyncio
        import json
        from omada_mcp.server import _json

        resources = ["wan", "ssid_details", "ip_groups", "ip_port_groups", "port_profiles",
                     "ips_settings", "upnp", "mdns", "ddns", "reboot_schedules",
                     "upgrade_schedules", "rogue_aps"]
        results = await asyncio.gather(*(client.get_site_resource(r) for r in resources))
        assert len(results) == 12
        for group in (None, "servers"):
            data = json.loads(_json(await client.get_vpn_configs(group=group)))
            assert data["vpn_types"]["2"] == "IPsec"
        compact = await client.get_acl_rules()
        assert all(set(obj["value"]) <= {"id", "groupId", "ssidId", "name", "ssidName"}
                   for rule in compact["data"] for side in ("sourceResolved", "destinationResolved")
                   for obj in rule[side]["objects"] if obj["value"] is not None)
        for resource in ("rogue_aps", "reboot_schedules", "upgrade_schedules"):
            result = await client.get_resource_status(resource)
            assert result["status"]["readable"] is True
            assert result["status"]["record_count"] == len(result["data"])
