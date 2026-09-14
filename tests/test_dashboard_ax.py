# tests/test_dashboard_ax.py
"""Dashboard row-AX summary builder (pure-Python; no AppKit UI objects touched).

Run: venv_macos/bin/python tests/test_dashboard_ax.py

Covers the Phase 4 dashboard-readability builders in applio_launcher:
_row_ax_summary's three shapes — the training metrics summary (epoch/total,
best loss :.4g with the "--" no-evaluation-yet fallback, ETA), the inference
pct summary (compute_inference_stats math, :.0f percent), and the
unknown/missing "" fallback — plus _row_display_text, the visible cell-text
builder the runs-list dataSource calls (re-test round 3: active rows carry
the metrics IN the cell text because VoiceOver does not reliably speak the
row view's accessibilityValue; history rows keep the plain shape). The
builders are AppKit-free and do no I/O, so they are testable headlessly;
applio_i18n falls back to the English key when no override exists (none does
in this repo).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_launcher


def test_training_summary():
    metrics = {
        "epoch": 34,
        "step": 8200,
        "training_speed": "0:01:30",
        "best_loss": 0.5234,
        "best_epoch": 30,
        "best_step": 7300,
    }
    proc = {"type": "training", "model_name": "voice", "total_epoch": 200}
    summary = applio_launcher._row_ax_summary(
        proc, metrics=metrics, total_epoch=200, eta="2h 5m"
    )
    assert summary == "epoch 34 of 200, best loss 0.5234, ETA 2h 5m", summary
    # First epoch: no evaluation yet -> best loss "--"; eta defaults "--"
    # (the CONTROLLER caller derives it via _derive_eta; a bare call doesn't).
    metrics["best_loss"] = None
    summary = applio_launcher._row_ax_summary(proc, metrics=metrics, total_epoch=200)
    assert summary == "epoch 34 of 200, best loss --, ETA --", summary


def test_inference_summary():
    proc = {
        "type": "inference",
        "status": "running",
        "total": 3,
        "processed": 2,
        "converted": 2,
        "started_at": time.time(),
    }
    summary = applio_launcher._row_ax_summary(proc)
    # pct via compute_inference_stats: 2/3 -> 66.7 rounded, :.0f -> 67
    assert summary == "2 of 3 files converted, 67 percent", summary


def test_unknown_or_missing_returns_empty():
    # Unknown proc types carry no metrics -> "" (callers skip stamping a value)
    assert applio_launcher._row_ax_summary({"type": "tts"}) == ""
    # Training without metrics (no log / nothing logged yet) -> ""
    assert applio_launcher._row_ax_summary({"type": "training"}) == ""
    # Degenerate inputs -> ""
    assert applio_launcher._row_ax_summary(None) == ""
    assert applio_launcher._row_ax_summary({}) == ""


def test_row_display_text_training_with_metrics():
    # Re-test round 3: VoiceOver does not reliably speak the row view's
    # accessibilityValue, so ACTIVE rows must carry the metrics IN the
    # visible cell text: "<status> — <Type>: <name> — <summary>".
    metrics = {
        "epoch": 34,
        "step": 8200,
        "training_speed": "0:01:30",
        "best_loss": 0.5234,
        "best_epoch": 30,
        "best_step": 7300,
    }
    proc = {"type": "training", "model_name": "voice", "total_epoch": 200}
    summary = applio_launcher._row_ax_summary(
        proc, metrics=metrics, total_epoch=200, eta="2h 5m"
    )
    text = applio_launcher._row_display_text(proc, "Running", summary=summary)
    assert text == (
        "Running — Training: voice — epoch 34 of 200, best loss 0.5234, ETA 2h 5m"
    ), text


def test_row_display_text_inference():
    proc = {
        "type": "inference",
        "status": "running",
        "model_name": "voice",
        "total": 3,
        "processed": 2,
        "converted": 2,
        "started_at": time.time(),
    }
    text = applio_launcher._row_display_text(
        proc, "Running", summary=applio_launcher._row_ax_summary(proc)
    )
    assert text == (
        "Running — Inference: voice — 2 of 3 files converted, 67 percent"
    ), text


def test_row_display_text_history_fallback():
    # History rows have no live metrics: summary "" keeps the plain
    # "Status — Type: name" shape (also the shape for active rows whose
    # type carries no metrics, e.g. preprocess/extract/tts).
    text = applio_launcher._row_display_text(
        {"type": "training", "model_name": "voice"}, "Completed"
    )
    assert text == "Completed — Training: voice", text
    # Degenerate proc -> "" (mirrors _row_ax_summary).
    assert applio_launcher._row_display_text(None, "Running") == ""


def test_row_display_text_truncation():
    proc = {"type": "training", "model_name": "a-really-long-model-name", "total": 200}
    text = applio_launcher._row_display_text(
        proc,
        "Running",
        summary="epoch 199 of 200, best loss 0.1234, ETA 2h 5m",
    )
    # Long name + summary: truncate the tail at ~80 chars, keep the head.
    assert len(text) <= 80, text
    assert text.endswith("…"), text
    assert text.startswith("Running — Training: a-really-long-model-name"), text


if __name__ == "__main__":
    fns = [
        v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll dashboard_ax tests passed ({len(fns)}).")
