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
from server.keyboard import KeyboardDriver
from server.joystick import primary_joyport, c64_port_for_retropad

# Keep the binary protocol on the original stdout FD. Native VICE printf goes to stderr.
IPC = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)

# Libretro ABI (https://docs.libretro.com/development/cores/developing-cores/)
ENV = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
BATCH = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
POLL = C.CFUNCTYPE(None)
INPUT = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)
KEYBOARD = C.CFUNCTYPE(None, C.c_bool, C.c_uint, C.c_uint32, C.c_uint16)

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

def stage(message):
    print(f"[worker] {message}", file=sys.stderr, flush=True)

def pack(kind, data):
    IPC.write(kind + struct.pack(">I", len(data)) + data)

class Emulator:
    def __init__(self):
        core_path = os.environ.get("VICE_CORE_PATH", "/opt/vice/vice_x64_libretro.so")
        disk = Path(os.environ.get("GAME_D64", "/games/game.d64")).resolve()
        if not disk.is_file():
            raise FileNotFoundError("GAME_D64 is missing")
        stage("Loading Libretro core")
        self.core = C.CDLL(core_path)
        stage("Libretro core mapped")
        # The core log interface is a *variadic C function pointer*. It cannot
        # safely be implemented with CFUNCTYPE, so the callback lives in a
        # separately compiled C bridge, held alive as long as this worker.
        bridge_path = os.environ.get(
            "VICE_LOG_BRIDGE_PATH", "/opt/vice/libretro_log_bridge.so"
        )
        self.log_bridge = C.CDLL(bridge_path)
        self.log_address = C.cast(
            self.log_bridge.retro_log_bridge, C.c_void_p
        ).value
        if not self.log_address:
            raise RuntimeError("VICE log bridge has no entry point")
        stage("Libretro native logging bridge ready")
        self.pixel_format = 0
        self.video = None
        self.luma = None
        self.frame_signature = None
        self.changed_since_stats = 0
        self.previous_signature = None
        self.audio = bytearray()
        self.buttons = [0, 0]
        self.keyboard_cb = None
        self.keys = None
        self.want_video = False
        self.last_frame = 0
        self.samples = 48000
        self.strings = []
        # Defaults are announced through SET_VARIABLES during
        # retro_set_environment. Missing defaults such as
        # vice_sound_sample_rate leave the VICE core at 0 Hz and cause SIGFPE.
        self.core_options = {}
        # RetroPad 0 is the room owner. Wizard of Wor expects C64
        # JOYSTICK PORT 1 for one-player mode (port 2 starts two players).
        # The core routes RetroPad 1 to the other physical port.
        selected_joyport = os.environ.get("VICE_PRIMARY_JOYPORT", "1")
        self.primary_joyport = primary_joyport(selected_joyport)
        stage("Joystick routing: room player 1 -> C64 port %d; "
              "room player 2 -> C64 port %d" % (
                  c64_port_for_retropad(0, selected_joyport),
                  c64_port_for_retropad(1, selected_joyport),
              ))
        self.option_overrides = {
            b"vice_joyport": self.primary_joyport,
            b"vice_autostart": b"enabled",
            b"vice_turbo_fire": b"disabled",
            b"vice_sound_sample_rate": b"48000",
        }
        directory = os.environ.get("VICE_SYSTEM_DIR", "/tmp/vice")
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.system_dir = os.fsencode(directory)
        self.strings.append(self.system_dir)

        @ENV
        def env(cmd, ptr):
            if cmd == 12 and ptr:  # SET_KEYBOARD_CALLBACK, supplied by VICE
                fn = C.cast(ptr, C.POINTER(C.c_void_p))[0]
                if not fn:
                    return False
                self.keyboard_cb = KEYBOARD(fn)
                self.keys = KeyboardDriver(self.keyboard_cb)
                return True
            if cmd == 27:  # RETRO_ENVIRONMENT_GET_LOG_INTERFACE
                if not ptr:
                    return False
                # retro_log_callback contains exactly one variadic function
                # pointer. Store the native function address directly.
                C.cast(ptr, C.POINTER(C.c_void_p))[0] = self.log_address
                return True
            if cmd in (9, 31):  # GET_SYSTEM_DIRECTORY, GET_SAVE_DIRECTORY
                C.cast(ptr, C.POINTER(C.c_char_p))[0] = self.system_dir
                return True
            if cmd == 10:  # SET_PIXEL_FORMAT; XRGB8888 / RGB565 / 0RGB1555
                fmt = C.cast(ptr, C.POINTER(C.c_int))[0]
                if fmt not in (0, 1, 2):
                    return False
                self.pixel_format = int(fmt)
                return True
            if cmd == 3:  # GET_CAN_DUPE
                C.cast(ptr, C.POINTER(C.c_bool))[0] = True
                return True
            if cmd == 16 and ptr:  # SET_VARIABLES (legacy core option table)
                # VICE advertises NUL-terminated Variable[] entries with values
                # "Description; default|alternative|...". The first value is
                # explicitly placed first by the VICE core.
                entries = C.cast(ptr, C.POINTER(Variable))
                new_options = {}
                for i in range(512):
                    item = entries[i]
                    if not item.key:
                        break
                    desc = item.value or b""
                    first = desc.partition(b";")[2].strip().split(b"|", 1)[0].strip()
                    if first:
                        new_options[bytes(item.key)] = bytes(first)
                else:
                    return False
                self.core_options = new_options
                stage(f"Loaded {len(new_options)} VICE core defaults")
                return True
            if cmd == 15 and ptr:  # GET_VARIABLE
                var = C.cast(ptr, C.POINTER(Variable))[0]
                value = self.option_overrides.get(
                    var.key, self.core_options.get(var.key)
                )
                if value is None:
                    var.value = None
                    return False
                var.value = value  # self-owned bytes stay alive after callback
                return True
            if cmd == 17 and ptr:  # GET_VARIABLE_UPDATE
                C.cast(ptr, C.POINTER(C.c_bool))[0] = False
                return True
            if cmd in (32, 53):  # SET_SYSTEM_AV_INFO, SET_CORE_OPTIONS
                return True
            if cmd == 52:  # GET_CORE_OPTIONS_VERSION (legacy variables)
                C.cast(ptr, C.POINTER(C.c_uint))[0] = 0
                return True
            return False

        @VIDEO
        def on_video(ptr, width, height, pitch):
            if not ptr or not self.want_video:
                return
            if width < 64 or height < 64 or width > 1024 or height > 1024:
                return
            raw = C.string_at(ptr, height * pitch)
            decoder = {0: "BGR;15", 1: "BGRX", 2: "BGR;16"}[self.pixel_format]
            frame = Image.frombytes("RGB", (width, height), raw, "raw", decoder, pitch, 1)
            # Tiny subsample to distinguish dark/static emulated screens from
            # transport/rendering issues without streaming a framebuffer dump.
            signature = frame.resize((16, 16)).convert("L").tobytes()
            self.luma = round(sum(signature) / len(signature), 1)
            if signature != self.previous_signature:
                self.changed_since_stats += 1
                self.previous_signature = signature
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
        stage("Calling retro_init")
        lib.retro_init()
        stage("retro_init returned")
        for port in (0, 1):
            lib.retro_set_controller_port_device(port, 1)
        self.game_path = os.fsencode(str(disk))
        info = GameInfo(self.game_path, None, 0, None)
        stage("Calling retro_load_game")
        if not lib.retro_load_game(C.byref(info)):
            raise RuntimeError("VICE core did not load disk image")
        stage("retro_load_game returned")
        av = SystemAV()
        stage("Calling retro_get_system_av_info")
        lib.retro_get_system_av_info(C.byref(av))
        stage("retro_get_system_av_info returned")
        self.fps = float(av.timing.fps or 50)
        self.samples = int(av.timing.sample_rate or 48000)
        if not (25 <= self.fps <= 65 and 8000 <= self.samples <= 192000):
            raise RuntimeError("Unsupported AV parameters: %s Hz" % self.samples)

    def run(self):
        stage(f"Emulation starting: fps={self.fps:.3f}; audio rate={self.samples}")
        pack(b"M", json.dumps({
            "sample_rate": self.samples,
            "fps": self.fps,
            "primary_joyport": int(self.primary_joyport),
        }).encode())
        interval = 1 / self.fps
        deadline = time.monotonic()
        incoming = bytearray()
        count = 0
        window_start = time.monotonic()
        window_frames = 0
        window_video_frames = 0
        window_bytes = 0
        window_work_ms = 0.0
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
                        if isinstance(states, list):  # Legacy pad-only protocol
                            states = {"pads": states, "keys": []}
                        if isinstance(states, dict):
                            pads = states.get("pads")
                            if isinstance(pads, list) and len(pads) == 2 and all(
                                type(n) is int and 0 <= n <= 31 for n in pads
                            ):
                                self.buttons[:] = pads
                            events = states.get("keys")
                            if self.keys and isinstance(events, list) and len(events) <= 64:
                                self.keys.input(events)
                    except ValueError:
                        pass
            work_start = time.monotonic()
            self.audio.clear()
            self.video = None
            self.want_video = count % 2 == 0
            if self.keys:
                self.keys.before_frame()
            self.core.retro_run()
            if self.keys:
                self.keys.after_frame()
            if self.video is not None:
                pack(b"V", self.video)
                window_video_frames += 1
                window_bytes += len(self.video)
            if self.audio:
                pack(b"A", bytes(self.audio))
                window_bytes += len(self.audio)
            window_frames += 1
            window_work_ms += (time.monotonic() - work_start) * 1000
            count += 1
            now = time.monotonic()
            elapsed = now - window_start
            if elapsed >= 2:
                # These values are measured inside the emulation process:
                # if fps << target, the NUC/core is not keeping real-time pace.
                pack(b"S", json.dumps({
                    "fps": round(window_frames / elapsed, 1),
                    "target_fps": round(self.fps, 1),
                    "video_fps": round(window_video_frames / elapsed, 1),
                    "work_percent": round(min(999, window_work_ms / (elapsed * 10)), 1),
                    "stream_kbps": round(window_bytes * 8 / elapsed / 1000, 1),
                    "luma": self.luma,
                    "changed_frames": self.changed_since_stats,
                }).encode())
                window_start = now
                window_frames = window_video_frames = window_bytes = 0
                window_work_ms = 0.0
                self.changed_since_stats = 0
            deadline += interval
            delay = deadline - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.5:
                deadline = time.monotonic()

if __name__ == "__main__":
    try:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        Emulator().run()
    except Exception as exc:
        print("Emulator error: " + repr(exc), file=sys.stderr, flush=True)
        raise
