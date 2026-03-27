"""Tests for server-side formatting functions and tools."""

import pytest
from unittest.mock import AsyncMock, patch

from omada_mcp.server import _fmt_bytes, get_device_detail, check_connection


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
        mock.return_value.get_devices = AsyncMock(return_value=devices)
        result = await get_device_detail("ap-office")

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
        mock.return_value.get_devices = AsyncMock(return_value=devices)
        result = await get_device_detail("aa:bb:cc:dd:ee:ff")

    assert "Switch1" in result


@pytest.mark.asyncio
async def test_device_detail_not_found():
    """Should return 'not found' message for unknown device."""
    with patch("omada_mcp.server._get_client") as mock:
        mock.return_value.get_devices = AsyncMock(return_value=[])
        result = await get_device_detail("nonexistent")

    assert "not found" in result.lower()


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
