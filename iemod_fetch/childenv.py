"""
The environment a program started by this one gets (review of #70).

Inside a PyInstaller bundle on Linux, the bootloader puts the bundle's own
library folder first on LD_LIBRARY_PATH (macOS: DYLD_LIBRARY_PATH), and a
child inherits it: `git`, `gh`, 7-Zip or unrar would load the bundle's
OpenSSL, zlib or liblzma instead of the system's, and fail on a system whose
tools want newer ones - `git credential fill` failing that way leaves the run
anonymous without a word. PyInstaller keeps the value from before it started
in `<NAME>_ORIG`; a child gets that back, or nothing. Outside a bundle the
environment is inherited unchanged.
"""
import os
import sys
from collections.abc import Mapping

_PATHS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """The `env=` for subprocess.run: None (inherit) unless frozen or `extra`."""
    if not getattr(sys, "frozen", False):
        return dict(os.environ, **extra) if extra else None
    env = dict(os.environ)
    for name in _PATHS:
        original = env.pop(name + "_ORIG", None)
        if original is not None:
            env[name] = original
        else:
            env.pop(name, None)
    env.update(extra or {})
    return env
