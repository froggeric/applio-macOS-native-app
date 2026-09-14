"""Pure-config + fallback tests for applio_native_picker (no AppKit needed).
Run: venv_macos/bin/python tests/test_native_picker.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_native_picker as picker


def test_pick_ui_config_modes():
    assert picker.pick_ui_config("folder") == {
        "files": False,
        "dirs": True,
        "allowed": None,
    }
    assert picker.pick_ui_config("file") == {
        "files": True,
        "dirs": False,
        "allowed": None,
    }
    assert picker.pick_ui_config("pth") == {
        "files": True,
        "dirs": False,
        "allowed": ["pth"],
    }


def test_unknown_mode_raises():
    try:
        picker.pick_ui_config("weird")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown mode must raise ValueError")


def test_unavailable_without_native_loop():
    # The availability flag is unset in this process (only the launcher sets
    # it) -> immediate ("unavailable", None). Empirically necessary: PyObjC
    # materializes a non-None NSApp proxy even with no run loop, so an
    # NSApp-based check would queue the panel for a loop that never runs and
    # block for the full timeout.
    picker._native_loop_available = False
    status, path = picker.native_browse("file", timeout=0.5)
    assert status == "unavailable"
    assert path is None


def run_all():
    test_pick_ui_config_modes()
    test_unknown_mode_raises()
    test_unavailable_without_native_loop()
    print("All native picker tests passed (3).")


if __name__ == "__main__":
    run_all()
