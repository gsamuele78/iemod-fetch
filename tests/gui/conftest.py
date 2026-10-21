"""GUI tests: PySide6 and pytest-qt, with no screen (QT_QPA_PLATFORM=offscreen).
They are skipped where the GUI extra is not installed - except in CI's GUI job,
which sets IEMOD_REQUIRE_GUI so a missing Qt fails instead of skipping."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("IEMOD_REQUIRE_GUI"):
    import PySide6  # noqa: F401
    import pytestqt  # noqa: F401
