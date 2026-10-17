"""Explicitly allowed Libretro keyboard input for the C64 worker.

RUN/STOP on the C64 is RETROK_ESCAPE (27), as defined by the VICE
Libretro positional keyboard mapping. All input originates from
authenticated room participants; never accept arbitrary numeric keycodes.
"""
import string

KEYCODES = {
    "RUN_STOP": 27, "RETURN": 13, "SPACE": 32, "DEL": 8,
    "HOME": 278, "RESTORE": 280, "SHIFT": 304,
    "CTRL": 9, "COMMODORE": 306, "SHIFT_LOCK": 301,
    "F1": 282, "F2": 283, "F3": 284, "F4": 285,
    "F5": 286, "F6": 287, "F7": 288, "F8": 289,
    "UP": 273, "DOWN": 274, "LEFT": 276, "RIGHT": 275,
    "AT": 91, "ASTERISK": 93, "PLUS": 43, "MINUS": 45,
    "EQUALS": 92, "COLON": 58, "SEMICOLON": 59,
    "COMMA": 44, "PERIOD": 46, "SLASH": 47,
    "POUND": 277, "BACKARROW": 96, "UPARROW": 127,
}
KEYCODES.update({letter: ord(letter.lower()) for letter in string.ascii_uppercase})
KEYCODES.update({digit: ord(digit) for digit in string.digits})


def key_event(data):
    """Validate a single network key transition (never commands or scancodes)."""
    if type(data) is not dict or data.get("type") != "key":
        return None
    key = data.get("key")
    down = data.get("down")
    if type(key) is not str or key not in KEYCODES or type(down) is not bool:
        return None
    return {"key": key, "down": down}


class KeyboardDriver:
    """Feed VICE native keyboard callback, including very brief touch taps.

    Two emulator frames of minimum key-down time ensure that a fast browser
    tap which sends down+up before one polling tick remains visible to the C64.
    """
    def __init__(self, callback):
        self.callback = callback
        self.frame = 0
        self.pressed = {}          # key name -> first pressed emulator frame
        self.release_due = {}      # key name -> earliest frame to release

    def input(self, events):
        for event in events:
            validated = key_event({"type": "key", **event}) if isinstance(event, dict) else None
            if validated is None:
                continue
            key, down = validated["key"], validated["down"]
            if down:
                self.release_due.pop(key, None)
                if key not in self.pressed:
                    code = KEYCODES[key]
                    self.callback(True, code, code if code < 128 else 0, 0)
                    self.pressed[key] = self.frame
            elif key in self.pressed:
                self.release_due[key] = max(self.frame, self.pressed[key] + 2)

    def before_frame(self):
        for key, frame in list(self.release_due.items()):
            if frame <= self.frame:
                code = KEYCODES[key]
                self.callback(False, code, 0, 0)
                self.release_due.pop(key, None)
                self.pressed.pop(key, None)

    def after_frame(self):
        self.frame += 1
