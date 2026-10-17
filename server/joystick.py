"""C64 physical joystick port mapping for Libretro VICE.

Vice's retro_poll_event maps RetroPad 0 to the selected primary joyport,
and RetroPad 1 to the opposite one (without a userport adapter).

Wizard of Wor uses a FIRE press in C64 port 1 for 1-player mode and
a FIRE press in C64 port 2 for 2-player mode, so host/role 0 must be
C64 port 1. Override only for future games requiring a different port.
"""
def primary_joyport(raw="1"):
    if raw not in ("1", "2"):
        raise ValueError("VICE_PRIMARY_JOYPORT must be 1 or 2")
    return raw.encode("ascii")


def c64_port_for_retropad(retropad, primary="1"):
    """Return the 1-based C64 joystick port selected by the VICE core."""
    if retropad not in (0, 1) or primary not in ("1", "2"):
        raise ValueError("Invalid RetroPad/C64 joystick port")
    chosen = int(primary)
    return chosen if retropad == 0 else 3 - chosen
