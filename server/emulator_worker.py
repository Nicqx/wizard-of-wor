"""Isolated Libretro VICE process. stdout: [type:1][length:4][payload]."""
import ctypes as C
import io
import json
import os
from pathlib import Path
import select
import struct
import sys
import time

from PIL import Image

# Libretro ABI (https://docs.libretro.com/development/cores/developing-cores/)
ENV = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
BATCH = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
POLL = C.CFUNCTYPE(None)
INPUT = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)

class GameInfo(C.Structure):
    _fields_ = [("path", C.c_char_p), ("data", C.c_void_p),
                ("size", C.c_size_t), ("meta", C.c_char_p)]

class Geometry(C.Structure):
    _fields_ = [("base_width", C.c_uint), ("base_height", C.c_uint),
                ("max_width", C.c_uint), ("max_height", C.c_uint),
                ("aspect_ratio", C.c_float)]

class Timing(C.Structure):
    _fields_ = [("fps", C.c_double), ("sample_rate", C.c_double)]

class SystemAV(C.Structure):
    _fields_ = [("geometry", Geometry), ("timing", Timing)]

class Variable(C.Structure):
    _fields_ = [("key", C.c_char_p), ("value", C.c_char_p)]

def pack(kind, data):
    sys.stdout.buffer.write(kind + struct.pack(">I", len(data)) + data)
    sys.stdout.buffer.flush()

class Emulator:
    def __init__(self):
        core_path = os.environ.get("VICE_CORE_PATH", "/opt/vice/vice_x64_libretro.so")
        disk = Path(os.environ.get("GAME_D64", "/games/game.d64")).resolve()
        if not disk.is_file():
            raise FileNotFoundError("GAME_D64 is missing")
        self.core = C.CDLL(core_path)
        self.pixel_format = 0
        self.video = None
        self.audio = bytearray()
        self.buttons = [0, 0]
        self.want_video = False
        self.last_frame = 0
        self.samples = 48000
        self.strings = []
        directory = os.environ.get("VICE_SYSTEM_DIR", "/tmp/vice")
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.system_dir = os.fsencode(directory)
        self.strings.append(self.system_dir)

        @ENV
        def env(cmd, ptr):
            if cmd in (9, 31):  # GET_SYSTEM_DIRECTORY, GET_SAVE_DIRECTORY
                C.cast(ptr, C.POINTER(C.c_char_p))[0] = self.system_dir
                return True
            if cmd == 10:  # SET_PIXEL_FORMAT; demand XRGB8888
                fmt = C.cast(ptr, C.POINTER(C.c_int))[0]
                if fmt != 1:
                    return False
                self.pixel_format = int(fmt)
                return True
            if cmd == 3:  # GET_CAN_DUPE
                C.cast(ptr, C.POINTER(C.c_bool))[0] = True
                return True
            if cmd == 15:  # GET_VARIABLE
                var = C.cast(ptr, C.POINTER(Variable))[0]
                opts = {b"vice_joyport": b"2", b"vice_autostart": b"enabled",
                        b"vice_turbo_fire": b"disabled"}
                value = opts.get(var.key)
                if value is None:
                    var.value = None
                    return False
                var.value = value
                return True
            if cmd == 17:  # GET_VARIABLE_UPDATE
                C.cast(ptr, C.POINTER(C.c_bool))[0] = False
                return True
            if cmd in (16, 32, 53):  # SET_VARIABLES and core options announcements
                return True
            if cmd == 52:  # GET_CORE_OPTIONS_VERSION (legacy variables)
                C.cast(ptr, C.POINTER(C.c_uint))[0] = 0
                return True
            return False

        @VIDEO
        def on_video(ptr, width, height, pitch):
            if not ptr or not self.want_video or self.pixel_format != 1:
                return
            if width < 64 or height < 64 or width > 1024 or height > 1024:
                return
            raw = C.string_at(ptr, height * pitch)
            frame = Image.frombytes("RGB", (width, height), raw, "raw", "BGRX", pitch, 1)
            out = io.BytesIO()
            frame.save(out, format="JPEG", quality=76, subsampling=0)
            self.video = out.getvalue()

        @AUDIO
        def on_audio(left, right):
            self.audio.extend(struct.pack("<hh", left, right))

        @BATCH
        def on_batch(ptr, count):
            if ptr and count:
                self.audio.extend(C.string_at(ptr, count * 4))
            return count

        @POLL
        def on_poll():
            return

        @INPUT
        def on_input(port, device, index, button):
            if device != 1 or index != 0 or port > 1:
                return 0
            # RetroPad: B=0, UP=4, DOWN=5, LEFT=6, RIGHT=7
            mapping = {4: 0, 5: 1, 6: 2, 7: 3, 0: 4}
            bit = mapping.get(button)
            return int(bool(self.buttons[port] & (1 << bit))) if bit is not None else 0

        self.callbacks = (env, on_video, on_audio, on_batch, on_poll, on_input)
        lib = self.core
        for function, restype, argtypes in (
            ("retro_set_environment", None, [ENV]),
            ("retro_set_video_refresh", None, [VIDEO]),
            ("retro_set_audio_sample", None, [AUDIO]),
            ("retro_set_audio_sample_batch", None, [BATCH]),
            ("retro_set_input_poll", None, [POLL]),
            ("retro_set_input_state", None, [INPUT]),
            ("retro_init", None, []),
            ("retro_get_system_av_info", None, [C.POINTER(SystemAV)]),
            ("retro_load_game", C.c_bool, [C.POINTER(GameInfo)]),
            ("retro_set_controller_port_device", None, [C.c_uint, C.c_uint]),
            ("retro_run", None, []),
            ("retro_unload_game", None, []),
            ("retro_deinit", None, []),
        ):
            func = getattr(lib, function)
            func.restype = restype
            func.argtypes = argtypes
        lib.retro_set_environment(env)
        lib.retro_set_video_refresh(on_video)
        lib.retro_set_audio_sample(on_audio)
        lib.retro_set_audio_sample_batch(on_batch)
        lib.retro_set_input_poll(on_poll)
        lib.retro_set_input_state(on_input)
        lib.retro_init()
        for port in (0, 1):
            lib.retro_set_controller_port_device(port, 1)
        self.game_path = os.fsencode(str(disk))
        info = GameInfo(self.game_path, None, 0, None)
        if not lib.retro_load_game(C.byref(info)):
            raise RuntimeError("VICE core did not load disk image")
        av = SystemAV()
        lib.retro_get_system_av_info(C.byref(av))
        self.fps = float(av.timing.fps or 50)
        self.samples = int(av.timing.sample_rate or 48000)
        if not (25 <= self.fps <= 65 and 8000 <= self.samples <= 192000):
            raise RuntimeError("Unsupported AV parameters: %s Hz" % self.samples)

    def run(self):
        pack(b"M", json.dumps({"sample_rate": self.samples, "fps": self.fps}).encode())
        interval = 1 / self.fps
        deadline = time.monotonic()
        incoming = bytearray()
        count = 0
        while True:
            while select.select([sys.stdin.buffer], [], [], 0)[0]:
                chunk = os.read(sys.stdin.fileno(), 4096)
                if not chunk:
                    return
                incoming.extend(chunk)
                if len(incoming) > 8192:
                    incoming.clear()
                while b"\n" in incoming:
                    line, _, remainder = incoming.partition(b"\n")
                    incoming = bytearray(remainder)
                    try:
                        states = json.loads(line)
                        if isinstance(states, list) and len(states) == 2 and all(
                            type(n) is int and 0 <= n <= 31 for n in states
                        ):
                            self.buttons[:] = states
                    except ValueError:
                        pass
            self.audio.clear()
            self.video = None
            self.want_video = count % 2 == 0
            self.core.retro_run()
            if self.video is not None:
                pack(b"V", self.video)
            if self.audio:
                pack(b"A", bytes(self.audio))
            count += 1
            deadline += interval
            delay = deadline - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.5:
                deadline = time.monotonic()

if __name__ == "__main__":
    try:
        Emulator().run()
    except Exception as exc:
        print("Emulator error: " + repr(exc), file=sys.stderr, flush=True)
        raise
