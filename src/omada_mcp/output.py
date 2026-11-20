"""MCP output boundary: recursive secret masking and non-destructive annotations."""

import json
import re


SPEED_MBPS = {1: 10, 2: 100, 3: 1000, 4: 2500, 5: 10000, 6: 5000,
              7: 25000, 8: 100000, 9: 40000}
SECRET_NAMES = {
    "key", "psk", "password", "passwd", "pwd", "passphrase", "secret", "token",
    "community", "readcommunity", "writecommunity", "accountsid", "authtoken",
    "accesskey", "apikey", "privatekey", "presharedkey", "sharedkey", "wpaKey".lower(),
    "radiuskey", "radiussecret", "authkey", "encryptkey", "encryptionkey", "credential",
    "securitykey", "authpassword", "privpassword", "pskkey", "pskvalue", "sid",
    "credentials", "recoverycodes", "backupcodes", "totpsecret", "snmpcommunity",
}


def _secret_key(key) -> bool:
    name = re.sub(r"[^a-z0-9]", "", str(key).lower())
    # Event 'key' is an identifier, handled separately by the caller below.
    return name in SECRET_NAMES or any(
        term in name for term in ("password", "passwd", "passphrase", "privatekey", "presharedkey",
                                   "sharedsecret", "authtoken", "accesstoken", "refreshtoken",
                                   "clientsecret", "twilio", "smtppass", "communitystring",
                                   "securitykey", "radiussecret", "sharedkey", "pskpassword")
    )


def prepare_output(data, include_secrets: bool = False):
    """Return a new structure; never mutate controller objects or replace raw enums."""
    if isinstance(data, (list, tuple)):
        return [prepare_output(item, include_secrets) for item in data]
    if not isinstance(data, dict):
        if isinstance(data, str) and not include_secrets:
            if "-----BEGIN" in data and "PRIVATE KEY-----" in data:
                return "[REDACTED]"
            # Audit changes may contain serialized configuration, not just nested objects.
            try:
                nested = json.loads(data) if data.lstrip().startswith(("{", "[")) else None
            except (ValueError, TypeError):
                nested = None
            if isinstance(nested, (dict, list)):
                return json.dumps(prepare_output(nested), ensure_ascii=False)
            return re.sub(
                r"(?i)((?:password|passwd|psk|secret|token|privateKey)\s*[:=]\s*)([^\r\n]+)",
                r"\1[REDACTED]", data,
            )
        return data
    result = {}
    event = "key" in data and any(k in data for k in ("module", "content", "shortMsg"))
    for key, value in data.items():
        sensitive = _secret_key(key) and not (key == "key" and event)
        if not include_secrets and sensitive and value is not None and value != "":
            result[key] = "[REDACTED]"
        else:
            result[key] = prepare_output(value, include_secrets)
        if key in ("linkSpeed", "maxSpeed") and isinstance(value, int) and not isinstance(value, bool):
            result[f"{key}Mbps"] = SPEED_MBPS.get(value)
            result[f"{key}Text"] = f"{SPEED_MBPS[value]} Mbit/s" if value in SPEED_MBPS else (
                "Auto / no negotiated speed (see linkStatus and field context)" if value == 0 else "Unknown code"
            )
    if "onlineDetection" in data:
        result["onlineDetectionNote"] = "Configured WAN health probes, not measured link/Internet health."
    if "ssidOverrides" in data:
        result["ssidOverridesNote"] = "Per-device override/placeholders; vlanId/vlanPoolIds may not be effective. Read get_ssid_detail for configured SSID settings."
    if "pmfMode" in data:
        result["pmfModeText"] = {1: "required", 2: "capable/optional", 3: "disabled"}.get(data["pmfMode"], "unknown")
    if "pskSetting" in data or ("ssidEnable" in data and "security" in data):
        result["securityText"] = {0: "open", 2: "WPA Enterprise", 3: "WPA Personal",
                                  4: "PPSK without RADIUS", 5: "PPSK with RADIUS"}.get(data.get("security"), "unknown")
        if isinstance(data.get("band"), int):
            result["bandsText"] = [name for bit, name in ((1, "2.4 GHz"), (2, "5 GHz"), (4, "6 GHz"))
                                   if data["band"] & bit]
    if "versionPsk" in data:
        result["versionPskText"] = {1: "WPA-PSK", 2: "WPA2-PSK", 3: "WPA/WPA2-PSK",
                                    4: "WPA2-PSK/WPA3-SAE transition mode"}.get(data["versionPsk"], "unknown")
    if isinstance(result.get("pskSetting"), dict) and data["pskSetting"].get("versionPsk") == 4:
        result["pskSetting"]["versionPskText"] = (
            "WPA3-SAE" if data.get("band") == 4 else "WPA2-PSK/WPA3-SAE transition mode"
        )
    # Audit old/new strings can contain credentials without structured keys. Do not
    # expose those opaque blobs by default; action/operator/result remain readable.
    if not include_secrets and "auditType" in data:
        for field in ("oldValue", "newValue"):
            if data.get(field):
                result[field] = "[REDACTED]"
    return result


def mask_portal_metadata(data):
    """Privacy fields in portal configuration, without breaking IDs in other tools."""
    if isinstance(data, list):
        return [mask_portal_metadata(x) for x in data]
    if not isinstance(data, dict):
        return data
    private = {"site", "siteid", "omadacid", "phone", "phonenum", "phonenumber", "from", "fromnumber",
               "tonumber", "telephone", "mobilenumber", "twiliophone", "sendernumber"}
    return {k: "[REDACTED]" if str(k).lower() in private and v not in (None, "")
            else mask_portal_metadata(v) for k, v in data.items()}
