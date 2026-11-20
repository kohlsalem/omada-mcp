"""Read-only request contract, site isolation, detail lookup and log range tests."""

import asyncio

import httpx
import pytest
import pytest_asyncio

from omada_mcp.client import OmadaApiError, OmadaClient


@pytest_asyncio.fixture
async def client():
    c = OmadaClient(url="https://omada.example.com", username="viewer", password="test")
    c._authenticated = True
    c._omadac_id = "controller"
    c._site_id = "default"
    yield c
    await c.close()


def respond(result):
    return httpx.Response(200, json={"errorCode": 0, "result": result})


@pytest.mark.asyncio
async def test_site_isolation_and_resource_pagination(client):
    seen = []

    async def handler(request):
        assert request.method == "GET"
        seen.append(request)
        if request.url.path.endswith("sites/basic"):
            return respond({"data": [{"id": "branch", "name": "Branch"}], "totalRows": 1})
        if "/sites/branch/" in request.url.path:
            assert request.url.params["type"] == "0"
            page = int(request.url.params["currentPage"])
            return respond({"data": [{"id": page}], "totalRows": 2})
        assert "/sites/default/" in request.url.path
        return respond({"data": [{"id": "default"}], "totalRows": 1})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    branch, default = await asyncio.gather(
        client.get_site_resource("gateway_acls", "bRaNcH"),
        client.get_site_resource("gateway_acls"),
    )
    assert branch == [{"id": 1}, {"id": 2}]
    assert default == [{"id": "default"}]
    assert client._site_id == "default"
    assert any(r.url.params.get("currentPage") == "2" for r in seen)
    with pytest.raises(ValueError, match="not found"):
        await client.get_site_resource("wan", "missing")


@pytest.mark.asyncio
async def test_detail_and_ports_use_model_specific_endpoints(client):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        assert request.method == "GET"
        if request.url.path.endswith("grid/devices"):
            return respond({"data": [{"name": "Office", "mac": "AA-BB-CC-DD-EE-FF", "type": "ap"}], "totalRows": 1})
        if request.url.path.endswith("/ports"):
            return respond([{"port": 1, "poe": True}])
        return respond({"radioSetting5g": {"channel": 36}, "wiredUplink": {"port": 4}})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    detail = await client.get_device_detail("aa:bb:cc:dd:ee:ff")
    assert detail["radioSetting5g"]["channel"] == 36
    assert await client.get_device_ports("office") == [{"port": 1, "poe": True}]
    assert paths[-1].endswith("eaps/AA-BB-CC-DD-EE-FF/ports")


@pytest.mark.asyncio
async def test_client_lookup_uses_known_clients_and_rejects_ambiguity(client):
    known = [{"name": "Printer", "mac": "AA-BB-CC-DD-EE-FF"}]

    def handler(request):
        assert request.method == "GET"
        if request.url.path.endswith("insight/clients"):
            return respond({"data": known, "totalRows": len(known)})
        if request.url.path.endswith("/clients"):
            return respond({"data": [], "totalRows": 0})
        return respond({"mac": known[0]["mac"], "active": False, "lastSeen": 100})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    assert (await client.get_client_detail("printer"))["active"] is False
    known.append({"name": "Printer", "mac": "11-22-33-44-55-66"})
    with pytest.raises(ValueError, match="2 matches"):
        await client.get_client_detail("printer")


@pytest.mark.asyncio
async def test_log_filters_and_errors(client):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("setting/wan/networks"):
            return httpx.Response(200, json={"errorCode": -403, "msg": "Permission denied"})
        return respond({"data": [], "totalRows": 0})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    await client.get_alerts(resolved=None, start_ms=1000, end_ms=2000)
    assert "filters.resolved" not in requests[-1].url.params
    await client.get_alerts(resolved=True, start_ms=1000, end_ms=2000)
    assert requests[-1].url.params["filters.resolved"] == "true"
    await client.get_events(start_ms=1000, end_ms=2000)
    assert requests[-1].url.path.endswith("logs/events")
    assert requests[-1].url.params["filters.timeStart"] == "1000"
    with pytest.raises(ValueError, match="Time range"):
        await client.get_events(start_ms=2000, end_ms=1000)
    with pytest.raises(ValueError, match="Unknown resource"):
        await client.get_site_resource("../cmd/reboot")
    with pytest.raises(OmadaApiError, match="Permission denied"):
        await client.get_site_resource("wan")


@pytest.mark.asyncio
async def test_usage_discovers_categories_paginates_and_preserves_crop_status(client):
    def handler(request):
        assert request.method == "GET"
        path = request.url.path
        if path.endswith("/overview"):
            assert request.url.params["start"] == "1000"
            return respond({"categoryTraffics": [{"familyId": 2097}], "totalTraffic": 300})
        if path.endswith("application/stat"):
            assert request.url.params["filters.family"] == "2097"
            assert request.url.params["filters.type"] == "0"
            page = int(request.url.params["currentPage"])
            return respond({"totalRows": 2, "data": [{"applicationId": page, "up": 50, "down": 100}]})
        return respond({"enableCrop": True, "showDataDays": 7})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    result = await client.get_application_usage(start=1000, end=2000)
    assert len(result["applications"]) == 2
    assert result["status"]["retention"]["enableCrop"] is True
    with pytest.raises(ValueError, match="not milliseconds"):
        await client.get_application_usage(start=1795100000000, end=1795190000000)


@pytest.mark.asyncio
async def test_report_post_is_fixed_query_and_validates_cards(client):
    seen = []

    def handler(request):
        import json

        seen.append(request)
        assert request.method == "POST"
        assert request.url.path == "/openapi/v1/controller/sites/default/report/cards"
        body = json.loads(request.content)
        assert body == {"start": 1000, "end": 2000, "cards": [{"type": "internet", "topK": 5}]}
        return respond({"internet": {"totalTraffic": 300, "activityList": [{"time": 1500}]}})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    result = await client.get_report(["internet", "internet"], start=1000, end=2000, top_k=5)
    assert result["cards"]["internet"]["totalTraffic"] == 300
    with pytest.raises(ValueError, match="Choose report cards"):
        await client.get_report(["../export-now-email"])
    with pytest.raises(ValueError, match="top_k"):
        await client.get_report(["internet"], top_k=1000)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_historical_mac_usage_keeps_empty_result_distinct_from_zero(client):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        assert request.method == "GET"
        if request.url.path.endswith("applicationTrafficStat"):
            assert "AA-BB-CC-DD-EE-FF" in request.url.path
            assert request.url.params["filters.all"] == "true"
            return respond({"data": [], "totalRows": 0})
        return respond({"enableCrop": True})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    result = await client.get_client_application_usage("aabb.ccdd.eeff", start=1000, end=2000)
    assert result["applications"] == []
    assert "do not establish zero" in result["note"]
    assert not any(path.endswith("grid/devices") or path.endswith("insight/clients") for path in paths)


@pytest.mark.asyncio
async def test_incident_openapi_pagination_and_summary(client):
    def handler(request):
        assert request.method == "GET"
        assert request.url.path.startswith("/openapi/v1/controller/sites/default/anomaly/")
        if request.url.path.endswith("/incidents"):
            assert request.url.params["filters.startTime"] == "1000"
            assert request.url.params["filters.status"] == "3"
            assert request.url.params["searchKey"] == "AP"
            page = int(request.url.params["page"])
            assert "currentPage" not in request.url.params
            return respond({"data": [{"id": page}], "totalRows": 2, "statistic": {"warning": 2}})
        if request.url.path.endswith("/statistics"):
            assert "filters.status" not in request.url.params
            return respond({"all": 2})
        return respond({"activeNum": 1})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    result = await client.get_incidents(start_ms=1000, end_ms=2000, status=3, search="AP")
    assert result["data"] == [{"id": 1}, {"id": 2}]
    assert result["statistic"]["warning"] == 2
    summary = await client.get_incident_summary(start_ms=1000, end_ms=2000)
    assert summary["active"]["activeNum"] == 1


@pytest.mark.asyncio
async def test_audit_time_filter_and_controller_scope(client):
    import json

    paths = []

    def handler(request):
        paths.append(request.url.path)
        assert request.method == "GET"
        assert json.loads(request.url.params["filters.times"]) == [{"timeStart": 1000, "timeEnd": 2000}]
        assert request.url.params["searchKey"] == "admin"
        return respond({"data": [{"operator": "admin"}], "totalRows": 1})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    await client.get_audit_logs(start_ms=1000, end_ms=2000, search="admin")
    await client.get_audit_logs(start_ms=1000, end_ms=2000, controller_wide=True, search="admin")
    assert paths == ["/controller/api/v2/sites/default/audit/logs", "/controller/api/v2/audit/logs"]
    with pytest.raises(ValueError, match="not both"):
        await client.get_audit_logs(site="other", controller_wide=True)


@pytest.mark.asyncio
async def test_security_converts_milliseconds_and_reports_disabled_ips(client):
    def handler(request):
        assert request.method == "GET"
        if request.url.path.endswith("setting/ips"):
            return respond({"enable": False})
        assert request.url.params["filters.startTime"] == "1"
        assert request.url.params["filters.endTime"] == "2"
        assert request.url.params["archived"] == "true"
        return respond({"data": [], "totalRows": 0})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    result = await client.get_security_logs(start_ms=1000, end_ms=2000, archived=True)
    assert result["ips_settings"]["enable"] is False
    assert result["data"] == []
    assert "does not establish" in result["note"]


@pytest.mark.asyncio
async def test_vpn_pagination_metadata_and_ipsec_detail(client):
    def handler(request):
        assert request.method == "GET"
        assert "/openapi/v2/controller/sites/default/vpn/site-to-site-vpns" in request.url.path
        if request.url.path.endswith("/vpn2"):
            return respond({"id": "vpn2", "name": "Branch", "vpnType": 2,
                            "keyExchangeVersion": 1, "phase1Proposal1": {"encryption": "aes256"},
                            "phase2Proposal1": {"integrity": "sha256"}, "saLifetime2": 3600,
                            "remoteSubnets": ["10.20.0.0/16"]})
        page = int(request.url.params["page"])
        return respond({"data": [{"id": f"vpn{page}", "name": "HQ" if page == 1 else "Branch", "vpnType": 2}],
                        "totalRows": 2, "supportIPsec": True})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    inventory = await client.get_vpn_configs(group="site_to_site")
    assert len(inventory["groups"]["site_to_site"]["data"]) == 2
    assert inventory["groups"]["site_to_site"]["supportIPsec"] is True
    detail = await client.get_vpn_detail("bRaNcH", group="site_to_site")
    assert detail["vpn_type"] == "IPsec"
    assert detail["configuration"]["saLifetime2"] == 3600
    assert detail["configuration"]["phase1Proposal1"]["encryption"] == "aes256"
    with pytest.raises(ValueError, match="0 matches"):
        await client.get_vpn_detail("missing", group="site_to_site")
    with pytest.raises(ValueError, match="Unknown VPN group"):
        await client.get_vpn_configs(group="../psk")


@pytest.mark.asyncio
async def test_vpn_duplicate_names_require_id_or_group(client):
    def handler(request):
        return respond({"data": [{"id": request.url.path.rsplit("/", 1)[-1], "name": "Office", "vpnType": 2}],
                        "totalRows": 1})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="3 matches"):
        await client.get_vpn_detail("Office")


@pytest.mark.asyncio
async def test_acl_resources_select_standard_type_and_keep_custom_separate(client):
    def handler(request):
        assert request.method == "GET"
        if request.url.path.endswith("/firewall/acls"):
            typ = int(request.url.params["type"])
            return respond({"data": [{"type": typ, "name": "Configured rule"}], "totalRows": 1})
        assert request.url.path.endswith("/firewall/gateway-acls")
        assert "type" not in request.url.params
        return respond({"data": [], "totalRows": 0})

    client._http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    for resource, typ in [("gateway_acls", 0), ("switch_acls", 1), ("ap_acls", 2)]:
        assert (await client.get_site_resource(resource))[0]["type"] == typ
    assert await client.get_site_resource("gateway_custom_acls") == []
