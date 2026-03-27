"""Tests for OmadaClient authentication, session management, retry, and pagination."""

import asyncio

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from omada_mcp.client import OmadaClient, OmadaApiError


@pytest.fixture
def client():
    return OmadaClient(
        url="https://omada.example.com",
        username="testuser",
        password="testpass",
    )


# ── Authentication ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_sets_session_state(client):
    """Login should store csrf_token, omadac_id, and site_id."""
    login_response = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {"omadacId": "abc123", "token": "csrf456"},
        },
        headers={"set-cookie": "TPOMADA_SESSIONID=session789; Path=/"},
    )
    init_response = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {"omadacId": "abc123", "siteId": "site001"},
        },
    )

    with patch.object(client._http, "post", new_callable=AsyncMock, return_value=login_response):
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=init_response):
            await client._login()

    assert client._csrf_token == "csrf456"
    assert client._omadac_id == "abc123"
    assert client._site_id == "site001"
    assert client._authenticated is True


@pytest.mark.asyncio
async def test_get_raises_on_error_code(client):
    """API errors should raise OmadaApiError."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._csrf_token = "csrf456"
    client._site_id = "site001"

    error_response = httpx.Response(
        200,
        json={"errorCode": -1, "msg": "General error."},
    )

    with patch.object(client._http, "request", new_callable=AsyncMock, return_value=error_response):
        with pytest.raises(OmadaApiError, match="General error"):
            await client._get("/test")


@pytest.mark.asyncio
async def test_get_relogins_on_html_response(client):
    """HTML response (session expired) should trigger re-login."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._csrf_token = "csrf456"
    client._site_id = "site001"

    html_response = httpx.Response(
        200,
        text="<!DOCTYPE HTML><html>...</html>",
        headers={"content-type": "text/html;charset=utf-8"},
    )
    json_response = httpx.Response(
        200,
        json={"errorCode": 0, "msg": "Success.", "result": {"data": "ok"}},
    )

    call_count = 0

    async def mock_request(method, path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return html_response
        return json_response

    with patch.object(client._http, "request", side_effect=mock_request):
        with patch.object(client, "_login", new_callable=AsyncMock) as mock_login:
            result = await client._get("/test")

    mock_login.assert_called_once()
    assert result == {"data": "ok"}


# ── Retry logic ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_on_502(client):
    """Should retry on 502 and succeed on second attempt."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._site_id = "site001"

    bad_resp = httpx.Response(502, text="Bad Gateway")
    good_resp = httpx.Response(
        200,
        json={"errorCode": 0, "msg": "Success.", "result": {"ok": True}},
    )

    call_count = 0

    async def mock_request(method, path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return bad_resp
        return good_resp

    with patch.object(client._http, "request", side_effect=mock_request):
        with patch("omada_mcp.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._get("/test")

    assert call_count == 2
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_retry_on_timeout(client):
    """Should retry on TimeoutException and succeed on second attempt."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._site_id = "site001"

    good_resp = httpx.Response(
        200,
        json={"errorCode": 0, "msg": "Success.", "result": {"ok": True}},
    )

    call_count = 0

    async def mock_request(method, path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("read timed out")
        return good_resp

    with patch.object(client._http, "request", side_effect=mock_request):
        with patch("omada_mcp.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._get("/test")

    assert call_count == 2
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_no_retry_on_4xx(client):
    """Should NOT retry on 4xx errors."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._site_id = "site001"

    # Build a proper response with a real request attached so raise_for_status works
    request = httpx.Request("GET", "https://omada.example.com/test")
    bad_resp = httpx.Response(403, text="Forbidden", request=request)

    with patch.object(client._http, "request", new_callable=AsyncMock, return_value=bad_resp):
        with pytest.raises(httpx.HTTPStatusError):
            await client._get("/test")


@pytest.mark.asyncio
async def test_retry_exhausted_raises(client):
    """Should raise after all retries exhausted."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._site_id = "site001"

    async def always_timeout(method, path, **kwargs):
        raise httpx.ReadTimeout("read timed out")

    with patch.object(client._http, "request", side_effect=always_timeout):
        with patch("omada_mcp.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.ReadTimeout):
                await client._get("/test")


# ── Auto-pagination ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_all_pages_single_page(client):
    """When all results fit in one page, return them directly."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._site_id = "site001"

    single_page_resp = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {
                "totalRows": 2,
                "data": [{"id": 1}, {"id": 2}],
            },
        },
    )

    with patch.object(client._http, "request", new_callable=AsyncMock, return_value=single_page_resp):
        result = await client._get_all_pages("/test")

    assert result == [{"id": 1}, {"id": 2}]


@pytest.mark.asyncio
async def test_get_all_pages_multiple_pages(client):
    """Should fetch all pages and combine the data."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._site_id = "site001"

    page1_resp = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {
                "totalRows": 3,
                "data": [{"id": 1}, {"id": 2}],
            },
        },
    )
    page2_resp = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {
                "totalRows": 3,
                "data": [{"id": 3}],
            },
        },
    )

    call_count = 0

    async def mock_request(method, path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return page1_resp
        return page2_resp

    with patch.object(client._http, "request", side_effect=mock_request):
        result = await client._get_all_pages("/test", page_size=2)

    assert call_count == 2
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


@pytest.mark.asyncio
async def test_get_all_pages_empty(client):
    """Empty result should return empty list."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._site_id = "site001"

    empty_resp = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {"totalRows": 0, "data": []},
        },
    )

    with patch.object(client._http, "request", new_callable=AsyncMock, return_value=empty_resp):
        result = await client._get_all_pages("/test")

    assert result == []


# ── check_connection ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_connection_success(client):
    """check_connection should return connected=True when controller is reachable."""
    client._authenticated = True
    client._omadac_id = "abc123"
    client._site_id = "site001"

    status_resp = httpx.Response(
        200,
        json={
            "errorCode": 0,
            "msg": "Success.",
            "result": {"name": "TestController", "controllerVersion": "6.0.0"},
        },
    )

    with patch.object(client._http, "request", new_callable=AsyncMock, return_value=status_resp):
        result = await client.check_connection()

    assert result["connected"] is True
    assert result["controller"] == "TestController"
    assert result["version"] == "6.0.0"


@pytest.mark.asyncio
async def test_check_connection_failure(client):
    """check_connection should return connected=False on error."""
    client._authenticated = False

    with patch.object(client, "_login", side_effect=Exception("Connection refused")):
        result = await client.check_connection()

    assert result["connected"] is False
    assert "Connection refused" in result["error"]
