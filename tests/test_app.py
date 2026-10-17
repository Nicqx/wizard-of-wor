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
    monkeypatch.setattr("server.app.asset_checks", lambda: {"game_d64": "missing", "vice_core": "ok"})
    app = create_app()
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            health = await client.get("/healthz")
            assert health.status == 503
            health_json = await health.json()
            assert health_json["ok"] is False
            assert health_json["checks"]["game_d64"] == "missing"
            assert health_json["ui"] == "KB5"
            result = await client.post(PREFIX + "/api/rooms")
            assert result.status == 503
            page = await client.get(PREFIX + "/")
            assert page.status == 200
            body = await page.text()
            assert "WIZARD" in body
            assert "Billentyűzet megnyitása" in body
            assert "C64 UI KB5" in body
            assert 'id="keyboardClose"' in body
            assert page.headers["Cache-Control"] == "no-store, max-age=0"
            version = await client.get(PREFIX + "/api/version")
            assert version.status == 200
            assert (await version.json())["ui"] == "KB5"
            script = await client.get(PREFIX + "/assets/app.js")
            assert script.status == 200
            assert script.headers["Cache-Control"] == "no-store, max-age=0"
            keyboard_js = await client.get(PREFIX + "/assets/c64-keyboard.js")
            assert keyboard_js.status == 200
            assert "createC64Keyboard" in await keyboard_js.text()
            assert keyboard_js.headers["Cache-Control"] == "no-store, max-age=0"

@pytest.mark.asyncio
async def test_join_no_room():
    async with TestServer(create_app()) as server:
        async with TestClient(server) as client:
            result = await client.post(PREFIX + "/api/rooms/12345/join")
            assert result.status == 404
            ws = await client.get(PREFIX + "/api/rooms/12345/ws")
            assert ws.status == 404


def test_asset_checks_diagnostics(tmp_path, monkeypatch):
    import server.app as mod
    game = tmp_path / "game.d64"
    core = tmp_path / "vice.so"
    monkeypatch.setattr(mod, "GAME", game)
    monkeypatch.setattr(mod, "CORE", core)
    assert mod.asset_checks() == {"game_d64": "missing", "vice_core": "missing"}
    game.write_bytes(b"bad")
    assert mod.asset_checks()["game_d64"] == "invalid_size"
    game.write_bytes(b"\x00" * 174848)
    core.write_bytes(b"dummy")
    assert mod.asset_checks() == {"game_d64": "ok", "vice_core": "ok"}


def test_room_media_queue_drops_old_packets_and_never_blocks():
    import asyncio
    from server.app import Room
    room = Room("12345", "token")
    queue = asyncio.Queue(maxsize=12)
    for i in range(100):
        room.queue_media(0, queue, (False, b"V" + bytes([i])))
    assert queue.qsize() <= 12
    assert room.media_drops[0] > 0
    packets = []
    while not queue.empty():
        packets.append(queue.get_nowait())
    assert packets[-1] == (False, b"V" + bytes([99]))
    assert packets[0][1] != b"V" + bytes([0])

@pytest.mark.asyncio
async def test_room_media_sender_pumps_binary_and_text_packets():
    import asyncio
    from server.app import Room
    room = Room("12345", "token")
    sent = []
    class FakeWs:
        closed = False
        async def send_bytes(self, data): sent.append(("binary", data))
        async def send_str(self, data): sent.append(("text", data))
    ws=FakeWs()
    queue=asyncio.Queue()
    room.queue_media(0,queue,(False,b"Vjpeg"))
    room.queue_media(0,queue,(True,'{"type":"stats"}'))
    task=asyncio.create_task(room.pump_media(0,ws,queue))
    for _ in range(20):
        if len(sent) >= 2: break
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    assert sent == [("binary",b"Vjpeg"),("text",'{"type":"stats"}')]
