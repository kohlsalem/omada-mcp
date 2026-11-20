"""Output-boundary regressions for controller secrets and port enums."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from omada_mcp.output import prepare_output
from omada_mcp.server import get_device_detail, read_site_resource, get_vpn_detail, _json


def test_recursive_masking_preserves_event_keys_and_does_not_mutate():
    raw = {"ssidOverrides": [{"psk": "wifi-secret"}], "pskSetting": {"securityKey": "ssid-secret"},
           "portal": {"password": "guest-secret", "sms": {"sid": "twilio-account", "authToken": "twilio-token"}}, "twilioConfig": {"accountSid": "sid-secret"},
           "vpn": {"privateKey": "vpn-secret", "preSharedKey": "shared-secret", "publicKey": "public"},
           "radius": {"secret": "radius-secret"}, "snmp": {"community": "public-secret"},
           "events": [{"key": "OSG_DHCP_S", "module": "Device", "content": "allocated IP"}],
           "oldValue": json.dumps({"password": "nested-secret"})}
    output = _json(raw)
    for secret in ("wifi-secret", "ssid-secret", "guest-secret", "sid-secret", "vpn-secret",
                   "shared-secret", "radius-secret", "public-secret", "nested-secret", "twilio-account", "twilio-token"):
        assert secret not in output
    assert "OSG_DHCP_S" in output
    assert "publicKey" in output
    assert raw["ssidOverrides"][0]["psk"] == "wifi-secret"
    assert "wifi-secret" in _json(raw, include_secrets=True)


def test_speed_codes_do_not_confuse_5g_with_10g_and_preserve_raw():
    result = prepare_output({"portStatus": {"linkSpeed": 5}, "maxSpeed": 6,
                             "ports": [{"linkSpeed": 0}, {"linkSpeed": 99}]})
    assert result["portStatus"]["linkSpeed"] == 5
    assert result["portStatus"]["linkSpeedMbps"] == 10000
    assert result["maxSpeedMbps"] == 5000
    assert result["ports"][0]["linkSpeedMbps"] is None
    assert result["ports"][1]["linkSpeedText"] == "Unknown code"


@pytest.mark.asyncio
async def test_sensitive_tools_mask_by_default_and_opt_in_is_per_call():
    with patch("omada_mcp.server._get_client") as factory:
        c = factory.return_value
        c.get_device_detail = AsyncMock(return_value={"psk": "device-secret"})
        c.get_site_resource = AsyncMock(return_value={"password": "portal-secret"})
        c.get_vpn_detail = AsyncMock(return_value={"privateKey": "vpn-secret"})
        assert "device-secret" not in await get_device_detail("AP")
        assert "device-secret" in await get_device_detail("AP", include_secrets=True)
        assert "device-secret" not in await get_device_detail("AP")
        assert "portal-secret" not in await read_site_resource("portals")
        assert "portal-secret" in await read_site_resource("portals", include_secrets=True)
        assert "vpn-secret" not in await get_vpn_detail("vpn")


@pytest.mark.asyncio
async def test_catalog_distinguishes_acl_type_and_exposes_secret_opt_in():
    from omada_mcp.server import list_read_resources, mcp

    catalog = json.loads(await list_read_resources())
    assert [catalog[k]["params"]["type"] for k in ("gateway_acls", "switch_acls", "ap_acls")] == [0, 1, 2]
    assert catalog["url_filters"]["params"]["type"] == "gateway"
    assert "ssid_details" in catalog and "vpn_users" in catalog
    tools = {t.name: t for t in await mcp.list_tools()}
    for name in ("get_device_detail", "get_vpn_detail", "get_ssid_detail", "read_site_resource", "read_controller_resource"):
        assert tools[name].inputSchema["properties"]["include_secrets"]["default"] is False


def test_ssid_and_wan_annotations_are_not_effective_status_claims():
    result = prepare_output({"ssidEnable": True, "security": 3, "pmfMode": 2, "band": 3,
                             "pskSetting": {"versionPsk": 2, "securityKey": "hidden"},
                             "onlineDetection": {"mode": 0}, "ssidOverrides": [{"vlanId": 0}]})
    assert result["pmfModeText"] == "capable/optional"
    assert result["bandsText"] == ["2.4 GHz", "5 GHz"]
    assert result["pskSetting"]["versionPskText"] == "WPA2-PSK"
    assert "not measured" in result["onlineDetectionNote"]
    assert "placeholders" in result["ssidOverridesNote"]


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [None, "servers"])
async def test_vpn_configs_serializes_numeric_enum_keys(group):
    from omada_mcp.client import VPN_TYPES
    from omada_mcp.server import get_vpn_configs

    with patch("omada_mcp.server._get_client") as factory:
        factory.return_value.get_vpn_configs = AsyncMock(return_value={"groups": {}, "vpn_types": VPN_TYPES})
        result = json.loads(await get_vpn_configs(group=group))
        assert result["vpn_types"]["2"] == "IPsec"
        assert result["vpn_types"]["4"] == "WireGuard"


def test_portal_privacy_keeps_other_resource_ids_usable():
    from omada_mcp.output import mask_portal_metadata

    data = {"site": "site-ref", "omadacId": "controller-ref", "sms": {"phoneNumber": "+1234", "phoneNum": "+5678"}, "id": "portal-ref"}
    masked = mask_portal_metadata(data)
    assert masked["site"] == "[REDACTED]"
    assert masked["sms"]["phoneNumber"] == "[REDACTED]"
    assert masked["sms"]["phoneNum"] == "[REDACTED]"
    assert masked["id"] == "portal-ref"
    assert prepare_output(data)["site"] == "site-ref"


def test_psk4_label_is_definite_and_six_ghz_is_sae_only():
    assert prepare_output({"versionPsk": 4})["versionPskText"] == "WPA2-PSK/WPA3-SAE transition mode"
    assert prepare_output({"band": 4, "pskSetting": {"versionPsk": 4}})["pskSetting"]["versionPskText"] == "WPA3-SAE"
