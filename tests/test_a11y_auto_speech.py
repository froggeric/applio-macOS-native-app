# tests/test_a11y_auto_speech.py
"""Zero-config speech policy (Phase 4c, 2026-08-23 owner ruling).

Run: venv_macos/bin/python tests/test_a11y_auto_speech.py

Covers the launcher's pure decision helpers — effective_speech (VO-gated
verbosity from the hidden a11y.speech override) and inference_job_type
(scope-aware announcement label) — plus their wiring: scope forwarding through
_synthesize_inference_proc into _a11y_snapshot's label. The web side of the
label chain (payload scope + JS jobLabel) is pinned in test_progress_api.py
and test_a11y_js_invariants.py.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_launcher


def test_effective_speech_truth_table():
    f = applio_launcher.effective_speech
    # auto (the default): speak exactly when VoiceOver runs
    assert f("auto", True) == "verbose"
    assert f("auto", False) == "off"
    assert f(None, True) == "verbose"  # unset override behaves as auto
    assert f(None, False) == "off"
    assert f("bogus", True) == "verbose"  # unknown value falls back to auto
    assert f("bogus", False) == "off"
    # on: always speak; off: never (VO state irrelevant either way)
    assert f("on", False) == "verbose"
    assert f("on", True) == "verbose"
    assert f("off", True) == "off"
    assert f("off", False) == "off"


def test_inference_job_type_scope_aware():
    f = applio_launcher.inference_job_type
    assert f("single") == "conversion"
    assert f(None) == "batch inference"  # batch records carry no scope
    assert f("") == "batch inference"
    assert f("batch") == "batch inference"


def test_synthesize_forwards_scope():
    orig = applio_launcher._read_inference_progress
    try:
        applio_launcher._read_inference_progress = lambda: {
            "status": "running",
            "scope": "single",
            "model_name": "voice.pt",
            "total": 1,
            "processed": 0,
        }
        proc = applio_launcher._synthesize_inference_proc()
        assert proc and proc["scope"] == "single"
    finally:
        applio_launcher._read_inference_progress = orig


def test_snapshot_label_scope_aware():
    # __new__ skips __init__ (no timers/signal handlers); _a11y_snapshot only
    # touches module-level sources, which we monkeypatch (test_menu_jobs
    # pattern).
    launcher = applio_launcher.ApplioLauncher.__new__(applio_launcher.ApplioLauncher)
    orig_active = applio_launcher.get_active_processes
    orig_synth = applio_launcher._synthesize_inference_proc
    try:
        applio_launcher.get_active_processes = lambda: []
        applio_launcher._synthesize_inference_proc = lambda: {
            "type": "inference",
            "status": "running",
            "model_name": "voice.pt",
            "scope": "single",
        }
        snap = launcher._a11y_snapshot()
        assert snap[next(iter(snap))]["type"] == "conversion"

        applio_launcher._synthesize_inference_proc = lambda: {
            "type": "inference",
            "status": "running",
            "model_name": "voice.pt",
        }
        snap = launcher._a11y_snapshot()
        assert snap[next(iter(snap))]["type"] == "batch inference"
    finally:
        applio_launcher.get_active_processes = orig_active
        applio_launcher._synthesize_inference_proc = orig_synth


def test_policy_message_for_single_conversion():
    # End-to-end native wording: the scope-aware type flows into the policy's
    # "{type}: {name}" label, so a single conversion announces "Started
    # conversion: X" (the 2026-08-23 re-test mislabel said "batch inference").
    pol = applio_launcher.applio_a11y.AnnouncementPolicy()
    snap = {
        "inference:voice.pt:app": {
            "type": applio_launcher.inference_job_type("single"),
            "name": "voice.pt",
            "status": "running",
            "word_key": "inference:voice.pt",
        }
    }
    assert ("start", "Started conversion: voice.pt") in pol.events(snap)


def test_play_sound_cue_channels():
    # Re-test round 2, fix A: NSSound system sounds ride the ALERT volume
    # slider (muted while speech on the regular channel still worked), so
    # the terminal chime must go through afplay = the regular output device.
    # _runner is the injectable seam (defaults to subprocess.Popen).
    import subprocess as _sp

    calls = []

    def fake_runner(args, stdout=None, stderr=None):
        calls.append((tuple(args), stdout, stderr))

    assert applio_launcher._play_sound_cue(True, _runner=fake_runner) == "afplay"
    assert applio_launcher._play_sound_cue(False, _runner=fake_runner) == "afplay"
    assert calls[0][0] == ("/usr/bin/afplay", "/System/Library/Sounds/Basso.aiff")
    assert calls[1][0] == ("/usr/bin/afplay", "/System/Library/Sounds/Glass.aiff")
    assert (
        calls[0][1] == _sp.DEVNULL and calls[0][2] == _sp.DEVNULL
    ), "the afplay child must be detached and quiet (main thread never blocks)"

    # afplay (or the .aiff) missing -> NSSound fallback branch, still no raise
    calls.clear()
    played = []
    real_appkit = sys.modules.get("AppKit")
    fake_appkit = types.ModuleType("AppKit")

    class _Sound:
        def __init__(self, name):
            self.name = name

        def play(self):
            played.append(self.name)

    fake_appkit.NSSound = type(
        "NSSound", (), {"soundNamed_": staticmethod(lambda n: _Sound(n))}
    )
    sys.modules["AppKit"] = fake_appkit
    orig_bin = applio_launcher._AFPLAY_PATH
    applio_launcher._AFPLAY_PATH = "/nonexistent/afplay"
    try:
        assert applio_launcher._play_sound_cue(True, _runner=fake_runner) == "nssound"
        assert applio_launcher._play_sound_cue(False, _runner=fake_runner) == "nssound"
    finally:
        applio_launcher._AFPLAY_PATH = orig_bin
        sys.modules.pop("AppKit", None)
        if real_appkit is not None:
            sys.modules["AppKit"] = real_appkit
    assert calls == [], "runner must not fire on the fallback path"
    assert played == ["Basso", "Glass"]


if __name__ == "__main__":
    fns = [
        v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll auto-speech tests passed ({len(fns)}).")
