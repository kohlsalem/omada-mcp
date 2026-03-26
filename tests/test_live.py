"""Live integration tests against the real Omada Controller.

Run with: pytest tests/test_live.py -v -s
Requires .env with valid OMADA_URL, OMADA_USERNAME, OMADA_PASSWORD.
"""

import os
import pytest
import pytest_asyncio
from pathlib import Path
from dotenv import load_dotenv

from omada_mcp.client import OmadaClient

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
