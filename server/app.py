"""Wizard of Wor room and streaming server. All emulation lives in isolated workers."""
import asyncio
import json
import logging
import os
import secrets
import struct
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import WSMsgType, web

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "/wizard-of-wor"
GAME = Path(os.environ.get("GAME_D64", "/games/game.d64"))
CORE = Path(os.environ.get("VICE_CORE_PATH", "/opt/vice/vice_x64_libretro.so"))
MAX_ROOMS = int(os.environ.get("MAX_ROOMS", "4"))
ROOM_TTL = 3600
IDLE_TTL = 300
MAX_PACKET = 2_000_000
log = logging.getLogger("wizard")

def mask(data):
    """Joystick bits: UP DOWN LEFT RIGHT FIRE. Malformed input releases all."""
    if type(data) is not dict:
        return 0
    keys = ("up", "down", "left", "right", "fire")
    if any(type(data.get(k, False)) is not bool for k in keys):
        return 0
    value = sum((1 << i) for i, k in enumerate(keys) if data.get(k, False))
    if value & 3 == 3:
        value &= ~3
    if value & 12 == 12:
        value &= ~12
    return value

@dataclass
class Room:
    code: str
    owner: str
    guest: str | None = None
    sockets: dict = field(default_factory=dict)
    input: dict = field(default_factory=lambda: {0: 0, 1: 0})
    created: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    proc: object = None
    reader: object = None
    sender: object = None
    stderr: object = None
    ready: object = field(default_factory=asyncio.Event)
    startup_error: str | None = None
    sample_rate: int = 48000

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "server.emulator_worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            limit=4_000_000,
        )
        self.reader = asyncio.create_task(self.read_output())
        self.sender = asyncio.create_task(self.send_input())
        self.stderr = asyncio.create_task(self.read_errors())
        await asyncio.wait_for(self.ready.wait(), timeout=15)
        if self.startup_error:
            raise RuntimeError(self.startup_error)

    async def read_errors(self):
        while self.proc and self.proc.stderr:
            line = await self.proc.stderr.readline()
            if not line:
                return
            log.warning("Room %s emulator: %s", self.code, line.decode(errors="replace").strip()[:500])

    async def read_output(self):
        try:
            while True:
                header = await self.proc.stdout.readexactly(5)
                kind = header[:1]
                length = struct.unpack(">I", header[1:])[0]
                if length > MAX_PACKET:
                    raise RuntimeError("Emulator packet too large")
                payload = await self.proc.stdout.readexactly(length)
                if kind == b"M":
                    info = json.loads(payload)
                    self.sample_rate = info.get("sample_rate", 48000)
                    self.ready.set()
                elif kind in (b"V", b"A"):
                    for ws in tuple(self.sockets.values()):
                        if not ws.closed and ws._writer.transport.get_write_buffer_size() < 1_000_000:
                            await ws.send_bytes(kind + payload)
        except (asyncio.IncompleteReadError, ConnectionError) as exc:
            # Wait for native worker termination and diagnostic stderr before
            # signaling failure; otherwise close() cancels the log reader.
            return_code = None
            if self.proc:
                try:
                    return_code = await asyncio.wait_for(self.proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            if self.stderr:
                try:
                    await asyncio.wait_for(asyncio.shield(self.stderr), timeout=1)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
            self.startup_error = f"Emulator process ended unexpectedly (exit={return_code})"
            log.warning("Room %s ended: %s; exit=%s", self.code, exc, return_code)
        except Exception as exc:
            self.startup_error = str(exc)[:160]
            log.exception("Room %s failed", self.code)
        finally:
            self.ready.set()
            for ws in tuple(self.sockets.values()):
                await ws.close(code=1011, message=b"Emulator stopped")

    async def send_input(self):
        """Sample both controller states every 20 ms, not every browser event."""
        try:
            while True:
                await asyncio.sleep(0.02)
                if not self.proc or self.proc.returncode is not None:
                    return
                values = [self.input[0], self.input[1]]
                self.proc.stdin.write((json.dumps(values) + "\n").encode())
                await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionError, OSError):
            return
        except asyncio.CancelledError:
            raise

    async def broadcast(self):
        msg = json.dumps({"type": "players", "connected": [i in self.sockets for i in (0, 1)]})
        for ws in tuple(self.sockets.values()):
            if not ws.closed:
                await ws.send_str(msg)

    async def close(self):
        for task in (self.sender, self.reader, self.stderr):
            if task:
                task.cancel()
        for ws in tuple(self.sockets.values()):
            await ws.close(code=1001, message=b"Room closed")
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()

def error(message, status):
    return web.json_response({"error": message}, status=status)

def get_rooms(request):
    return request.app["rooms"]

def asset_checks():
    """Return safe diagnostics without exposing local filesystem paths."""
    game_present = GAME.is_file()
    game_valid = game_present and GAME.stat().st_size in (174848, 175531, 196608)
    return {
        "game_d64": "ok" if game_valid else ("invalid_size" if game_present else "missing"),
        "vice_core": "ok" if CORE.is_file() else "missing",
    }

def available():
    return all(state == "ok" for state in asset_checks().values())

def throttle(request):
    peer = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() if os.environ.get("TRUST_PROXY") == "1" else request.remote
    now = time.monotonic()
    queue = request.app["rate"][peer or "unknown"]
    while queue and queue[0] < now - 60:
        queue.popleft()
    if len(queue) >= 20:
        return False
    queue.append(now)
    return True

async def health(request):
    checks = asset_checks()
    ready = all(state == "ok" for state in checks.values())
    return web.json_response(
        {"ok": ready, "active_rooms": len(get_rooms(request)), "checks": checks},
        status=200 if ready else 503,
    )

async def create_room(request):
    if not throttle(request):
        return error("Túl sok kérés.", 429)
    if not available():
        return error("Az emulátor vagy a D64 fájl hiányzik a szerverről.", 503)
    rooms = get_rooms(request)
    if len(rooms) >= MAX_ROOMS:
        return error("Most minden szoba foglalt.", 503)
    for _ in range(100):
        code = f"{secrets.randbelow(100000):05d}"
        if code not in rooms:
            break
    else:
        return error("Nincs szabad szobakód.", 503)
    room = Room(code=code, owner=secrets.token_urlsafe(32))
    rooms[code] = room
    try:
        await room.start()
    except Exception:
        log.exception("Emulator startup failed")
        rooms.pop(code, None)
        await room.close()
        return error("Az emulátor nem indult el; ellenőrizd a szerver naplóját.", 503)
    return web.json_response({"code": code, "role": 0, "token": room.owner})

async def join_room(request):
    if not throttle(request):
        return error("Túl sok kérés.", 429)
    code = request.match_info["code"]
    room = get_rooms(request).get(code)
    if not room or room.guest:
        return error("Nem létező vagy már betelt szoba.", 404)
    room.guest = secrets.token_urlsafe(32)
    room.last_activity = time.monotonic()
    return web.json_response({"code": code, "role": 1, "token": room.guest})

async def ws_room(request):
    code = request.match_info["code"]
    room = get_rooms(request).get(code)
    if not room:
        raise web.HTTPNotFound()
    # Token checked in first WS message; never place secrets in URLs or logs.
    origin = request.headers.get("Origin")
    host = request.headers.get("Host", "")
    if origin and origin not in ("https://" + host, "http://" + host):
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=1024)
    await ws.prepare(request)
    role = None
    try:
        msg = await ws.receive(timeout=6)
        if msg.type != WSMsgType.TEXT:
            return ws
        try:
            data = json.loads(msg.data)
        except (ValueError, TypeError):
            return ws
        token = data.get("token") if isinstance(data, dict) else None
        if isinstance(token, str):
            if secrets.compare_digest(token, room.owner):
                role = 0
            elif room.guest and secrets.compare_digest(token, room.guest):
                role = 1
        if role is None or role in room.sockets:
            return ws
        room.sockets[role] = ws
        room.last_activity = time.monotonic()
        await ws.send_str(json.dumps({"type": "welcome", "role": role,
                                      "sample_rate": room.sample_rate}))
        await room.broadcast()
        async for item in ws:
            if item.type == WSMsgType.TEXT:
                if len(item.data) > 512:
                    break
                try:
                    data = json.loads(item.data)
                except (ValueError, TypeError):
                    continue
                if type(data) is dict and data.get("type") == "input":
                    room.input[role] = mask(data)
                    room.last_activity = time.monotonic()
            elif item.type == WSMsgType.ERROR:
                break
    finally:
        if role is not None and room.sockets.get(role) is ws:
            room.sockets.pop(role, None)
            room.input[role] = 0
            room.last_activity = time.monotonic()
            await room.broadcast()
        await ws.close()
    return ws

async def index(request):
    return web.FileResponse(ROOT / "web" / "index.html")

async def cleanup_loop(app):
    try:
        while True:
            await asyncio.sleep(10)
            now = time.monotonic()
            for code, room in list(app["rooms"].items()):
                if now - room.created > ROOM_TTL or (
                    not room.sockets and now - room.last_activity > IDLE_TTL
                ) or (room.proc and room.proc.returncode is not None):
                    app["rooms"].pop(code, None)
                    await room.close()
            for key, bucket in list(app["rate"].items()):
                if not bucket or bucket[-1] < now - 120:
                    app["rate"].pop(key, None)
    except asyncio.CancelledError:
        return

async def lifespan(app):
    janitor = asyncio.create_task(cleanup_loop(app))
    yield
    janitor.cancel()
    for room in list(app["rooms"].values()):
        await room.close()

def create_app():
    app = web.Application(client_max_size=2048)
    app["rooms"] = {}
    app["rate"] = defaultdict(deque)
    app.cleanup_ctx.append(lifespan)
    app.router.add_get("/healthz", health)
    app.router.add_get(PREFIX, index)
    app.router.add_get(PREFIX + "/", index)
    app.router.add_get(PREFIX + "/{code:[0-9]{5}}", index)
    app.router.add_static(PREFIX + "/assets/", ROOT / "web" / "assets")
    app.router.add_post(PREFIX + "/api/rooms", create_room)
    app.router.add_post(PREFIX + "/api/rooms/{code:[0-9]{5}}/join", join_room)
    app.router.add_get(PREFIX + "/api/rooms/{code:[0-9]{5}}/ws", ws_room)
    return app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8107")))
