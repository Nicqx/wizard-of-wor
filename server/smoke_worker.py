"""Integration smoke probe: launch the *real* VICE worker with an existing local D64.

Usage inside container: python -m server.smoke_worker
It checks for the worker's initial media header. It does not redistribute
game files or claim the game actually started.
"""
import json
import os
import select
import struct
import subprocess
import sys
import time


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.emulator_worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    data = bytearray()
    try:
        deadline = time.monotonic() + 20
        while len(data) < 5 and time.monotonic() < deadline:
            r, _, _ = select.select([proc.stdout], [], [], 0.25)
            if r:
                chunk = os.read(proc.stdout.fileno(), 5 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            elif proc.poll() is not None:
                break
        if len(data) != 5:
            raise RuntimeError(f"No worker media header; got {len(data)} bytes")
        if data[:1] != b"M":
            raise RuntimeError(f"Unexpected worker frame type {data[:1]!r}")
        size = struct.unpack(">I", data[1:])[0]
        if size <= 0 or size > 4096:
            raise RuntimeError(f"Invalid worker media header size: {size}")
        body = bytearray()
        while len(body) < size and time.monotonic() < deadline:
            r, _, _ = select.select([proc.stdout], [], [], 0.25)
            if r:
                chunk = os.read(proc.stdout.fileno(), size - len(body))
                if not chunk:
                    break
                body.extend(chunk)
            elif proc.poll() is not None:
                break
        if len(body) != size:
            raise RuntimeError(f"Short media header: {len(body)}/{size}")
        info = json.loads(body)
        assert 25 <= float(info["fps"]) <= 65, info
        assert 8000 <= int(info["sample_rate"]) <= 192000, info
        print("VICE worker initialization: PASS", info)
        return 0
    except Exception as exc:
        print("VICE worker initialization: FAIL:", exc, file=sys.stderr)
        return 1
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            _, err = proc.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, err = proc.communicate(timeout=4)
        print(f"Worker returncode: {proc.returncode}", file=sys.stderr)
        for line in err.decode("utf-8", errors="replace").splitlines()[-60:]:
            print("worker:", line[:400], file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
