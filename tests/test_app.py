from pathlib import Path
import pytest
from aiohttp.test_utils import TestClient, TestServer
from server.app import mask, create_app, PREFIX


def test_mask():
    assert mask({"up": True, "fire": True}) == 17
    assert mask({"left": True, "right": True, "fire": True}) == 16
    assert mask({"up": True, "down": True}) == 0
    assert mask({"up": "true"}) == 0
    assert mask(None) == 0
    assert mask({"up": True, "down": False}) == 1

@pytest.mark.asyncio
async def test_http_routes(monkeypatch):
    monkeypatch.setattr("server.app.available", lambda: False)
    app = create_app()
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            health = await client.get("/healthz")
            assert health.status == 503
            assert (await health.json())["ok"] is False
            result = await client.post(PREFIX + "/api/rooms")
            assert result.status == 503
            page = await client.get(PREFIX + "/")
            assert page.status == 200
            assert "WIZARD" in await page.text()
            script = await client.get(PREFIX + "/assets/app.js")
            assert script.status == 200

@pytest.mark.asyncio
async def test_join_no_room():
    async with TestServer(create_app()) as server:
        async with TestClient(server) as client:
            result = await client.post(PREFIX + "/api/rooms/12345/join")
            assert result.status == 404
            ws = await client.get(PREFIX + "/api/rooms/12345/ws")
            assert ws.status == 404
