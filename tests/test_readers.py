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
