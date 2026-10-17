import pytest

from server.app import Room
from server.keyboard import KEYCODES, KeyboardDriver, key_event


def test_c64_run_stop_is_escape():
    assert KEYCODES["RUN_STOP"] == 27
    assert KEYCODES["RETURN"] == 13
    assert KEYCODES["SHIFT"] == 304
    assert KEYCODES["A"] == 97


@pytest.mark.parametrize("payload", [
    {"type": "key", "key": "RUN_STOP", "down": "true"},
    {"type": "key", "key": "BREAK_SYSTEM", "down": True},
    {"type": "key", "key": 27, "down": True},
    {"type": "key", "key": "RUN_STOP", "down": 1},
    {"type": "input", "key": "RUN_STOP", "down": True},
    None,
])
def test_keyboard_validation_denies_malformed_commands(payload):
    assert key_event(payload) is None


def test_keyboard_validation_allows_down_up():
    assert key_event({"type": "key", "key": "RUN_STOP", "down": True}) == {
        "key": "RUN_STOP", "down": True
    }
    assert key_event({"type": "key", "key": "RUN_STOP", "down": False}) == {
        "key": "RUN_STOP", "down": False
    }


def test_room_delivers_fast_taps_and_releases_on_disconnect():
    room = Room("12345", "owner")
    room.change_key(0, {"key": "RUN_STOP", "down": True})
    room.change_key(0, {"key": "RUN_STOP", "down": False})
    assert list(room.key_events) == [
        {"key": "RUN_STOP", "down": True},
        {"key": "RUN_STOP", "down": False},
    ]
    room.change_key(0, {"key": "A", "down": True})
    room.release_keys(0)
    assert room.key_events[-1] == {"key": "A", "down": False}


def test_room_combines_duplicate_pressed_key_across_players():
    room = Room("12345", "owner")
    room.change_key(0, {"key": "A", "down": True})
    room.change_key(1, {"key": "A", "down": True})
    room.release_keys(0)
    assert list(room.key_events) == [{"key": "A", "down": True}]
    room.release_keys(1)
    assert list(room.key_events) == [
        {"key": "A", "down": True},
        {"key": "A", "down": False},
    ]


def test_keyboard_driver_keeps_quick_tap_for_two_frames():
    callbacks = []
    driver = KeyboardDriver(lambda down, code, char, mod:
                            callbacks.append((down, code, char, mod)))
    driver.input([
        {"key": "RUN_STOP", "down": True},
        {"key": "RUN_STOP", "down": False},
    ])
    assert callbacks == [(True, 27, 27, 0)]
    for _ in range(2):
        driver.before_frame()
        driver.after_frame()
        assert len(callbacks) == 1
    driver.before_frame()
    assert callbacks[-1] == (False, 27, 0, 0)


def test_keyboard_driver_persistent_hold_and_release():
    callbacks = []
    driver = KeyboardDriver(lambda down, code, char, mod: callbacks.append((down, code)))
    driver.input([{"key": "A", "down": True}])
    for _ in range(5):
        driver.before_frame()
        driver.after_frame()
    assert callbacks == [(True, 97)]
    driver.input([{"key": "A", "down": False}])
    driver.before_frame()
    assert callbacks == [(True, 97), (False, 97)]


def test_keyboard_driver_repress_cancels_pending_release():
    callbacks = []
    driver = KeyboardDriver(lambda down, code, char, mod: callbacks.append((down, code)))
    driver.input([
        {"key": "SHIFT", "down": True},
        {"key": "SHIFT", "down": False},
        {"key": "SHIFT", "down": True},
    ])
    for _ in range(6):
        driver.before_frame()
        driver.after_frame()
    assert callbacks == [(True, 304)]
    driver.input([{"key": "SHIFT", "down": False}])
    driver.before_frame()
    assert callbacks[-1] == (False, 304)
