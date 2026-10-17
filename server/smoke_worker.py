"""End-to-end smoke: real VICE init + at least one encoded video frame.

Runs with a locally mounted .d64, or the zero-filled test disk in CI.
No copyrighted game is included in the public repository.
"""
import json
import os
import select
import struct
import subprocess
import sys
import time


def read_exact(proc, n, deadline):
    data = bytearray()
    while len(data) < n and time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.2)
        if ready:
            chunk = os.read(proc.stdout.fileno(), n - len(data))
            if not chunk:
                break
            data.extend(chunk)
        elif proc.poll() is not None:
            break
    if len(data) != n:
        raise RuntimeError(f"Short worker stream: {len(data)}/{n} bytes")
    return bytes(data)


def read_packet(proc, deadline):
    header = read_exact(proc, 5, deadline)
    size = struct.unpack(">I", header[1:])[0]
    if size < 1 or size > 2_000_000:
        raise RuntimeError(f"Bad worker packet length {size}")
    return header[:1], read_exact(proc, size, deadline)


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.emulator_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 20
        kind, payload = read_packet(proc, deadline)
        if kind != b"M":
            raise RuntimeError(f"Expected initial metadata, got {kind!r}")
        metadata = json.loads(payload)
        if not 25 <= float(metadata["fps"]) <= 65:
            raise RuntimeError("Invalid reported video refresh rate")
        if not 8000 <= int(metadata["sample_rate"]) <= 192000:
            raise RuntimeError("Invalid reported SID sample rate")
        if metadata.get("primary_joyport") != 1:
            raise RuntimeError(
                "Wizard solo must use C64 joystick port 1: %r" % metadata
            )
        print("VICE worker init: PASS", metadata, flush=True)
        video_seen = False
        audio_seen = False
        while time.monotonic() < deadline:
            kind, payload = read_packet(proc, deadline)
            if kind == b"V":
                if not payload.startswith(b"\xff\xd8"):
                    raise RuntimeError("Video packet was not encoded JPEG")
                video_seen = True
                print(f"VICE rendered first JPEG frame: PASS ({len(payload)} bytes)", flush=True)
            if kind == b"A":
                if len(payload) % 4:
                    raise RuntimeError("Invalid stereo PCM packet length")
                audio_seen = True
            if video_seen and audio_seen:
                print("VICE emitted original PCM audio samples: PASS", flush=True)
                break
        if not video_seen:
            raise RuntimeError("No video frames emitted after initializing VICE")
        # Native callback integration: simulate an extremely short RUN/STOP
        # press/release in a single controller polling window. The worker must
        # survive and continue rendering video and audio afterwards.
        proc.stdin.write(
            b'{"pads":[0,0],"keys":[{"key":"RUN_STOP","down":true},'
            b'{"key":"RUN_STOP","down":false}]}\n'
        )
        proc.stdin.flush()
        frames_after_key = 0
        while time.monotonic() < deadline and frames_after_key < 4:
            kind, payload = read_packet(proc, deadline)
            if kind == b"V":
                if not payload.startswith(b"\xff\xd8"):
                    raise RuntimeError("Frame damaged after C64 key event")
                frames_after_key += 1
        if frames_after_key < 4:
            raise RuntimeError("Emulator stopped rendering after RUN/STOP input")
        print("C64 RUN/STOP short keypress + continued video: PASS", flush=True)
        stats = None
        while time.monotonic() < deadline:
            kind, payload = read_packet(proc, deadline)
            if kind == b"S":
                stats = json.loads(payload)
                break
        if not stats:
            raise RuntimeError("No live emulation FPS statistics")
        if not 1 <= stats["fps"] <= 70:
            raise RuntimeError(f"Unusable emulator speed: {stats}")
        if not 35 <= stats["target_fps"] <= 65:
            raise RuntimeError(f"Invalid target FPS: {stats}")
        if stats["stream_kbps"] <= 0 or stats["luma"] is None:
            raise RuntimeError(f"Missing media throughput or luminance: {stats}")
        print("Live C64 emulation diagnostics: PASS", stats, flush=True)
        return 0
    except Exception as exc:
        print("VICE worker smoke: FAIL:", exc, file=sys.stderr, flush=True)
        return 1
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            _, err = proc.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, err = proc.communicate(timeout=4)
        print(f"Worker returncode: {proc.returncode}", file=sys.stderr, flush=True)
        for line in err.decode("utf-8", errors="replace").splitlines()[-65:]:
            print("worker:", line[:400], file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
