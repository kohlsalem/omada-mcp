"""Tests for server-side formatting functions and tools."""

import base64
import json

import pytest
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from omada_mcp.server import _fmt_bytes, get_device_detail, check_connection, BasicAuthMiddleware


@pytest.mark.asyncio
async def test_alert_formatter_uses_controller_v2_fields():
    from omada_mcp.server import get_alerts

    alert = {"key": "WAN_ONLINE_DETECTION", "content": "WAN2 detection was offline.",
             "time": 1794962382000, "level": "Information", "resolved": False,
             "device": {"name": "Router Keller"}}
    with patch("omada_mcp.server._get_client") as factory:
        factory.return_value.get_alerts = AsyncMock(return_value=[alert])
        result = await get_alerts()
    assert "WAN2 detection was offline." in result
    assert "Type: WAN_ONLINE_DETECTION" in result
    assert "Time: 2026-11-" in result and "+00:00" in result
    assert "Router Keller" in result
    assert "Type: ?" not in result and "Time: ?" not in result


# ── _fmt_bytes ──────────────────────────────────────────────────────


class TestFmtBytes:
    def test_zero(self):
        assert _fmt_bytes(0) == "0 B"

    def test_bytes(self):
        assert _fmt_bytes(512) == "512 B"

    def test_kilobytes(self):
        assert _fmt_bytes(1024) == "1 KB"

    def test_megabytes(self):
        assert _fmt_bytes(1_500_000) == "1.4 MB"

    def test_gigabytes(self):
        assert _fmt_bytes(2 * 1024**3) == "2 GB"

    def test_terabytes(self):
        assert _fmt_bytes(5 * 1024**4) == "5 TB"

    def test_petabytes(self):
        assert _fmt_bytes(3 * 1024**5) == "3.0 PB"

    def test_negative(self):
        result = _fmt_bytes(-1024)
        assert result == "-1 KB"

    def test_fractional_bytes(self):
        assert _fmt_bytes(1.5) == "1.5 B"


# ── get_device_detail ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_device_detail_by_name():
    """Should find device by name (case-insensitive)."""
    devices = [
        {"name": "AP-Office", "mac": "AA:BB:CC:DD:EE:FF", "type": "ap",
         "showModel": "EAP620", "firmwareVersion": "1.0", "hwVersion": "2.0",
         "ip": "10.0.0.1", "sn": "SN123", "statusCategory": 1,
         "cpuUtil": 15, "memUtil": 30, "uptime": "10h",
         "clientNum": 5, "download": 1024000, "upload": 512000,
         "configSyncStatus": "synced", "needUpgrade": False, "locateEnable": False},
    ]

    with patch("omada_mcp.server._get_client") as mock:
        mock.return_value.get_device_detail = AsyncMock(return_value=devices[0])
        result = await get_device_detail("ap-office")
        mock.return_value.get_device_detail.assert_awaited_once_with("ap-office", None)

    assert "AP-Office" in result
    assert "EAP620" in result


@pytest.mark.asyncio
async def test_device_detail_by_mac():
    """Should find device by MAC (case-insensitive)."""
    devices = [
        {"name": "Switch1", "mac": "AA:BB:CC:DD:EE:FF", "type": "switch",
         "showModel": "T1600G", "firmwareVersion": "2.0", "hwVersion": "1.0",
         "ip": "10.0.0.2", "sn": "SN456", "statusCategory": 1,
         "cpuUtil": 20, "memUtil": 40, "uptime": "5d",
         "clientNum": 10, "download": 0, "upload": 0,
         "configSyncStatus": "synced", "needUpgrade": False, "locateEnable": False},
    ]

    with patch("omada_mcp.server._get_client") as mock:
        mock.return_value.get_device_detail = AsyncMock(return_value=devices[0])
        result = await get_device_detail("aa:bb:cc:dd:ee:ff")

    assert "Switch1" in result


@pytest.mark.asyncio
async def test_device_detail_not_found():
    """Lookup failures should reach the MCP error handler, not look like empty data."""
    with patch("omada_mcp.server._get_client") as mock:
        mock.return_value.get_device_detail = AsyncMock(side_effect=ValueError("Device not found"))
        with pytest.raises(ValueError, match="not found"):
            await get_device_detail("nonexistent")


@pytest.mark.asyncio
async def test_resource_discovery_and_site_forwarding():
    from omada_mcp.server import list_read_resources, read_site_resource, mcp

    resources = json.loads(await list_read_resources())
    assert resources["gateway_acls"]["paginated"] is True
    with patch("omada_mcp.server._get_client") as mock:
        mock.return_value.get_site_resource = AsyncMock(return_value=[{"vlan": 10}])
        result = await read_site_resource("port_profiles", "Branch")
        mock.return_value.get_site_resource.assert_awaited_once_with("port_profiles", "Branch")
        assert json.loads(result) == [{"vlan": 10}]
    tools = {t.name: t for t in await mcp.list_tools()}
    assert tools["read_site_resource"].annotations.readOnlyHint is True
    assert "site" in tools["get_device_detail"].inputSchema["properties"]


# ── check_connection tool ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_connection_tool_ok():
    """check_connection tool should format success correctly."""
    conn_result = {
        "connected": True,
        "authenticated": True,
        "controller": "MyController",
        "version": "6.0.0",
    }

    with patch("omada_mcp.server._get_client") as mock:
        mock.return_value.check_connection = AsyncMock(return_value=conn_result)
        result = await check_connection()

    assert "Connection: OK" in result
    assert "MyController" in result


@pytest.mark.asyncio
async def test_check_connection_tool_failed():
    """check_connection tool should format failure correctly."""
    conn_result = {
        "connected": False,
        "authenticated": False,
        "error": "Connection refused",
    }

    with patch("omada_mcp.server._get_client") as mock:
        mock.return_value.check_connection = AsyncMock(return_value=conn_result)
        result = await check_connection()

    assert "Connection: FAILED" in result
    assert "Connection refused" in result


# ── BasicAuthMiddleware ────────────────────────────────────────────


def _make_auth_app(username: str = "admin", password: str = "secret") -> Starlette:
    """Build a tiny Starlette app wrapped with BasicAuthMiddleware."""

    async def _ok(request):
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/", _ok)])
    app.add_middleware(BasicAuthMiddleware, username=username, password=password)
    return app


def _basic_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


class TestBasicAuthMiddleware:
    def test_no_auth_returns_401(self):
        client = TestClient(_make_auth_app())
        resp = client.get("/")
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == 'Basic realm="omada-mcp"'

    def test_wrong_credentials_returns_401(self):
        client = TestClient(_make_auth_app())
        resp = client.get("/", headers={"Authorization": _basic_header("wrong", "creds")})
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == 'Basic realm="omada-mcp"'

    def test_valid_credentials_pass_through(self):
        client = TestClient(_make_auth_app())
        resp = client.get("/", headers={"Authorization": _basic_header("admin", "secret")})
        assert resp.status_code == 200
        assert resp.text == "OK"

    def test_missing_env_vars_raises_system_exit(self):
        """main() should raise SystemExit when credentials are missing in HTTP mode."""
        env = {"MCP_TRANSPORT": "streamable-http"}
        with patch.dict("os.environ", env, clear=False), \
             patch.dict("os.environ", {"MCP_USERNAME": "", "MCP_PASSWORD": ""}):
            from omada_mcp.server import main
            with pytest.raises(SystemExit, match="MCP_USERNAME and MCP_PASSWORD"):
                main()
