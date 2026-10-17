import pytest

from server.app import Room
from server.joystick import primary_joyport, c64_port_for_retropad


def test_wizard_player_one_uses_original_c64_joystick_port_one():
    assert primary_joyport() == b"1"
    assert c64_port_for_retropad(0, "1") == 1
    assert c64_port_for_retropad(1, "1") == 2


def test_future_c64_games_can_override_primary_port():
    assert primary_joyport("2") == b"2"
    assert c64_port_for_retropad(0, "2") == 2
    assert c64_port_for_retropad(1, "2") == 1
    for bad in ("0", "3", "PORT 1", "", 1, None):
        with pytest.raises(ValueError):
            primary_joyport(bad)


def test_only_authenticated_players_have_active_pads():
    room = Room("12345", "owner")
    room.input[0] = 16
    room.input[1] = 16
    assert room.active_pad_states() == [0, 0]
    room.sockets[0] = object()
    assert room.active_pad_states() == [16, 0]
    room.sockets[1] = object()
    assert room.active_pad_states() == [16, 16]
    room.sockets.pop(1)
    assert room.active_pad_states() == [16, 0]
    room.sockets.pop(0)
    assert room.active_pad_states() == [0, 0]
