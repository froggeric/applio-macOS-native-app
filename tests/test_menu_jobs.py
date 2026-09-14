# tests/test_menu_jobs.py
"""Active-Processes menu helpers (pure-Python; no AppKit UI objects touched).

Run: venv_macos/bin/python tests/test_menu_jobs.py

Covers the Phase 4 menu-jobs helpers in applio_launcher: _merged_live_procs
(one merge for dashboard + menu), _menu_job_title (inference/training title
formats, name + line truncation, paused suffix), and the training title's
caller-supplied epoch param (no log I/O in the title fn itself).
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_launcher


def test_inference_title_format():
    proc = {
        "type": "inference",
        "status": "running",
        "model_name": "",
        "total": 3,
        "processed": 2,
        "converted": 2,
        "started_at": time.time(),
    }
    title = applio_launcher._menu_job_title(proc)
    # Shape, not exact rounding: pct is int(round(processed/total * 100))
    # (2/3 -> 66.7 -> "67%").
    assert re.fullmatch(r"Inference: batch — \d+% \(2/3 files\)", title), title
    # cancelling swaps the pct segment for a stopping marker
    proc["status"] = "cancelling"
    title = applio_launcher._menu_job_title(proc)
    assert title == "Inference: batch — stopping… (2/3 files)", title


def test_training_title():
    proc = {"type": "training", "model_name": "voice", "total_epoch": 200}
    title = applio_launcher._menu_job_title(proc, training_epoch=34)
    assert title == "Training: voice — epoch 34/200", title
    # No status line yet (caller passed no epoch) -> starting marker
    assert applio_launcher._menu_job_title(proc) == "Training: voice — starting…"


def test_merged_live_procs():
    orig_active = applio_launcher.get_active_processes
    orig_synth = applio_launcher._synthesize_inference_proc
    try:
        applio_launcher.get_active_processes = lambda: [{"type": "tts", "pid": 1}]
        applio_launcher._synthesize_inference_proc = lambda: {"type": "inference"}
        merged = applio_launcher._merged_live_procs()
        assert [p["type"] for p in merged] == ["tts", "inference"], merged
        # No live batch -> helper is just the tracked subprocess jobs
        applio_launcher._synthesize_inference_proc = lambda: None
        assert applio_launcher._merged_live_procs() == [{"type": "tts", "pid": 1}]
    finally:
        applio_launcher.get_active_processes = orig_active
        applio_launcher._synthesize_inference_proc = orig_synth


def test_long_name_truncation_and_paused_suffix():
    long_name = "m" * 45
    proc = {
        "type": "training",
        "model_name": long_name,
        "total_epoch": 10,
        "_ps_stopped": True,
    }
    title = applio_launcher._menu_job_title(proc, training_epoch=5)
    # name capped at 30 chars + "…" marker; paused suffix from _ps_stopped
    assert long_name[:30] + "…" in title, title
    assert title.endswith("— paused"), title
    assert len(title) <= 64, title
    # whole-line cap: an extreme epoch span cannot push past 64 chars
    proc["total_epoch"] = 9999999
    title = applio_launcher._menu_job_title(proc, training_epoch=12345)
    assert len(title) <= 64, title
    # name-only types + the bare-tracked tts title (no model_name recorded)
    assert (
        applio_launcher._menu_job_title({"type": "preprocess", "model_name": "ds"})
        == "ds"
    )
    assert applio_launcher._menu_job_title({"type": "tts"}) == "TTS: active job"


if __name__ == "__main__":
    fns = [
        v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll menu_jobs tests passed ({len(fns)}).")
