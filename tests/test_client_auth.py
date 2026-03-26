"""Tests for OmadaClient authentication and session management."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from omada_mcp.client import OmadaClient, OmadaApiError


@pytest.fixture
def client():
    return OmadaClient(
        url="https://omada.example.com",
        username="testuser",
        password="testpass",
    )


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

    with patch.object(client._http, "get", new_callable=AsyncMock, return_value=error_response):
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

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return html_response
        return json_response

    with patch.object(client._http, "get", side_effect=mock_get):
        with patch.object(client, "_login", new_callable=AsyncMock) as mock_login:
            result = await client._get("/test")

    mock_login.assert_called_once()
    assert result == {"data": "ok"}
