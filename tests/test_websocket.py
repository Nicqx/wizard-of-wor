"""Real aiohttp WebSocket protocol regression tests without a ROM."""
import json

import pytest
from aiohttp import WSServerHandshakeError, WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from server.app import PREFIX, Room, create_app


@pytest.mark.asyncio
async def test_websocket_room_auth_and_media_and_ping():
    app = create_app()
    room = Room("12345", "private-owner-token")
    app["rooms"]["12345"] = room
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            origin = str(client.make_url("/").origin())
            async with client.ws_connect(
                PREFIX + "/api/rooms/12345/ws",
                headers={"Origin": origin},
            ) as ws:
                await ws.send_json({"token": room.owner})
                assert (await ws.receive_json(timeout=2))["type"] == "welcome"
                assert (await ws.receive_json(timeout=2))["type"] == "players"
                room.queue_media(0, room.media_queues[0], (False, b"V\xff\xd8fakejpeg"))
                item = await ws.receive(timeout=2)
                assert item.type == WSMsgType.BINARY
                assert item.data == b"V\xff\xd8fakejpeg"
                room.queue_media(0, room.media_queues[0], (True, json.dumps({
                    "type": "stats", "emulator": {"fps": 50},
                })))
                assert (await ws.receive_json(timeout=2))["emulator"]["fps"] == 50
                await ws.send_json({"type": "ping", "sent": 7.5})
                assert (await ws.receive_json(timeout=2)) == {
                    "type": "pong", "sent": 7.5,
                }


@pytest.mark.asyncio
async def test_refresh_replaces_socket_for_same_room_token():
    app = create_app()
    room = Room("12345", "owner")
    app["rooms"]["12345"] = room
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            old = await client.ws_connect(PREFIX + "/api/rooms/12345/ws")
            await old.send_json({"token": room.owner})
            assert (await old.receive_json(timeout=2))["type"] == "welcome"
            await old.receive_json(timeout=2)  # players
            new = await client.ws_connect(PREFIX + "/api/rooms/12345/ws")
            await new.send_json({"token": room.owner})
            assert (await new.receive_json(timeout=3))["type"] == "welcome"
            assert room.sockets.get(0) is not None
            assert room.input[0] == 0
            await new.close()
            await old.close()


@pytest.mark.asyncio
async def test_expired_room_returns_websocket_404():
    async with TestServer(create_app()) as server:
        async with TestClient(server) as client:
            with pytest.raises(WSServerHandshakeError) as exc:
                await client.ws_connect(PREFIX + "/api/rooms/12345/ws")
            assert exc.value.status == 404


@pytest.mark.asyncio
async def test_https_public_origin_allowlist(monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://pmqxyz.hopto.org")
    app = create_app()
    app["rooms"]["12345"] = Room("12345", "owner")
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            with pytest.raises(WSServerHandshakeError) as exc:
                await client.ws_connect(
                    PREFIX + "/api/rooms/12345/ws",
                    headers={"Origin": "https://evil.example"},
                )
            assert exc.value.status == 403
            async with client.ws_connect(
                PREFIX + "/api/rooms/12345/ws",
                headers={"Origin": "https://pmqxyz.hopto.org"},
            ) as ws:
                await ws.send_json({"token": "owner"})
                assert (await ws.receive_json(timeout=2))["type"] == "welcome"
