"""Exercise actual HTTP room, WebSocket authentication, JPEG stream, stats and RTT.

Run inside the container using a locally mounted .d64 or synthetic CI disk:
  python -m server.smoke_stream
Requires the aiohttp game server to already be running on localhost:8107.
No D64 or secret is included in this repository.
"""
import asyncio
import json
import os
import time

import aiohttp


async def main():
    base = f"http://127.0.0.1:{os.environ.get('PORT', '8107')}/wizard-of-wor"
    timeout = aiohttp.ClientTimeout(total=40)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(base + "/api/rooms") as resp:
            if resp.status != 200:
                raise RuntimeError(f"Room create failed: HTTP {resp.status}: {(await resp.text())[:200]}")
            room = await resp.json()
        assert isinstance(room["token"], str) and len(room["code"]) == 5
        try:
            async with session.ws_connect(
                base + "/api/rooms/" + room["code"] + "/ws",
                headers={"Origin": "http://127.0.0.1:8107"},
                heartbeat=10,
            ) as socket:
                await socket.send_json({"token": room["token"]})
                welcomed = False
                video = False
                stats = False
                ping = False
                audio_packets = 0
                audio_samples = 0
                deadline = time.monotonic() + 12
                await socket.send_json({"type": "ping", "sent": 1234.5})
                while time.monotonic() < deadline:
                    msg = await socket.receive(timeout=3)
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        if msg.data[:1] == b"V":
                            video = video or msg.data[1:3] == b"\xff\xd8"
                        elif msg.data[:1] == b"A":
                            if (len(msg.data) - 1) % 4:
                                raise RuntimeError("Corrupted stereo PCM framing")
                            audio_packets += 1
                            audio_samples += (len(msg.data) - 1) // 4
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        payload = json.loads(msg.data)
                        if payload.get("type") == "welcome":
                            if payload.get("c64_joystick_port") != 1:
                                raise RuntimeError("Solo player must control C64 port 1")
                            welcomed = True
                        if payload.get("type") == "pong":
                            ping = payload.get("sent") == 1234.5
                        if payload.get("type") == "stats":
                            stats = payload.get("emulator", {}).get("fps", 0) > 1
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        raise RuntimeError(f"Unexpected WS close: {socket.close_code}")
                    if welcomed and video and stats and ping and audio_packets >= 40:
                        if audio_samples < 48000:
                            raise RuntimeError(
                                f"SID samples missing or under-produced: {audio_samples}"
                            )
                        print(
                            "HTTP+WebSocket C64 streaming E2E: PASS "
                            f"(JPEG, {audio_packets} PCM packets, "
                            f"{audio_samples} stereo samples, FPS, RTT)"
                        )
                        return
                raise RuntimeError(f"Incomplete WS stream: welcome={welcomed}, video={video}, stats={stats}, ping={ping}, audio_packets={audio_packets}, samples={audio_samples}")
        finally:
            # A separate test room is isolated; idle rooms are GC'd by backend.
            pass


if __name__ == "__main__":
    asyncio.run(main())
