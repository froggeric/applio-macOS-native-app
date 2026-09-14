# tests/test_inference_progress.py
"""Pure-Python gate for inference-progress stats + batch-toast injection.

Run: venv_macos/bin/python -m pytest tests/test_inference_progress.py -v

Imports ONLY from applio_inference_stats (AppKit-free). The launcher itself
imports AppKit at module top, so it is NOT headless-importable; that is exactly
why the stats math lives in applio_inference_stats.py.

The batch-toast + single-conversion tests run patches/patch_inference_progress.py
against a temp copy of the PRISTINE rvc/infer/infer.py (never the repo file) and
assert on the generated engine code; the single-conversion helpers are also exec'd
standalone (pure stdlib) to behaviorally verify the batch guard + terminal writes.
"""

import importlib.util
import py_compile
import shutil
import sys, os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from applio_inference_stats import compute_inference_stats

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _patched_infer_source():
    """Run patch_infer_py on a temp copy of pristine rvc/infer/infer.py."""
    spec = importlib.util.spec_from_file_location(
        "patch_inference_progress",
        os.path.join(REPO, "patches", "patch_inference_progress.py"),
    )
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    src_path = os.path.join(REPO, "rvc", "infer", "infer.py")
    src = open(src_path, encoding="utf-8").read()
    assert (
        "Inference Progress Tracking" not in src
    ), "rvc/infer/infer.py is dirty (patched?) - restore first"
    with tempfile.TemporaryDirectory() as td:
        shutil.copy(src_path, os.path.join(td, "infer.py"))
        assert patcher.patch_infer_py(td), "patcher anchor missed (upstream drift?)"
        with open(os.path.join(td, "infer.py"), encoding="utf-8") as f:
            patched = f.read()
    # The generated engine code must at least be syntactically valid.
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(patched)
    try:
        py_compile.compile(tf.name, doraise=True)
    finally:
        os.unlink(tf.name)
    return patched


def test_progress_pct_and_eta():
    r = {
        "total": 10,
        "processed": 4,
        "converted": 4,
        "skipped": 0,
        "started_at": 1000.0,
    }
    s = compute_inference_stats(r, now=1010.0)
    assert s["pct"] == 40.0 and s["elapsed"] == 10.0
    assert s["eta"] == 15.0  # (10-4)*(10/4)
    assert s["speed"] == 24.0  # 4/(10/60)


def test_zero_converted_no_divzero():
    r = {"total": 5, "processed": 0, "converted": 0, "skipped": 0, "started_at": 1000.0}
    s = compute_inference_stats(r, now=1003.0)
    assert s["eta"] == 0.0 and s["speed"] == 0.0 and s["pct"] == 0.0


def test_completed_uses_ended_at_eta_zero():
    r = {
        "total": 3,
        "processed": 3,
        "converted": 2,
        "skipped": 1,
        "started_at": 1000.0,
        "ended_at": 1010.0,
    }
    s = compute_inference_stats(r, now=9999.0)
    assert s["pct"] == 100.0 and s["eta"] == 0.0 and s["elapsed"] == 10.0


def test_zero_total():
    r = {"total": 0, "processed": 0, "converted": 0, "skipped": 0, "started_at": 1000.0}
    s = compute_inference_stats(r, now=1001.0)
    assert s["pct"] == 0.0 and s["eta"] == 0.0


def test_skip_semantics_eta_uses_converted_only():
    r = {
        "total": 10,
        "processed": 4,
        "converted": 2,
        "skipped": 2,
        "started_at": 1000.0,
    }
    s = compute_inference_stats(r, now=1010.0)
    assert s["pct"] == 40.0  # processed/total (skips count as processed)
    assert (
        s["eta"] == 30.0
    )  # (10-4) * (10/2) — avg from converted, remaining from processed
    assert s["speed"] == 12.0  # 2/(10/60)


def test_batch_toast_calls_in_patched_engine():
    patched = _patched_infer_source()
    # Start toast (upstream #1271): after the counters (+ milestone init),
    # before the initial write. Upstream's _toast helper carries the call -
    # the fork injects no toast helper of its own.
    counters = patched.index("processed = converted = skipped = 0")
    milestone_init = patched.index("_next_milestone = 25")
    start_toast = patched.index('_toast(f"Batch conversion started: {total} files")')
    initial_write = patched.index('"processed": 0, "converted": 0, "skipped": 0,')
    assert counters < milestone_init < start_toast < initial_write
    # Milestone toast (upstream #1275): threshold-first-crossing guard at the
    # loop tail (after the per-file write). total>=8 keeps small batches
    # spam-free; the processed<total term suppresses the 100% milestone
    # double-announcement.
    per_file_write = patched.index('"current_file": nxt,')
    guard = patched.index("and processed * 100 // total >= _next_milestone")
    assert per_file_write < guard
    assert "total >= 8" in patched and "and processed < total" in patched
    milestone_msg = 'f"{processed}/{total} files converted ({_next_milestone}%)"'
    assert milestone_msg in patched
    assert patched.index(milestone_msg) < patched.index("_next_milestone += 25")
    # Terminal toast: after the terminal write, before the history append.
    # {status} renders as upstream's "completed" wording on normal runs and
    # carries "cancelled" for fork-canceled ones.
    terminal_write = patched.index(
        '"ended_at": ended_at, "elapsed": elapsed, "error": None,'
    )
    terminal_toast = patched.index(
        'f"Batch conversion {status}: {converted} converted, "'
    )
    first_hist_call = patched.index("_infer_add_to_history({")
    assert terminal_write < terminal_toast < first_hist_call
    # Error site 1: the except handler, BEFORE the re-raise (variable is
    # _infer_exc — never e; warning=True matches upstream's helper).
    exc_toast = patched.index(
        '_toast(f"Batch conversion failed: {_infer_exc}", warning=True)'
    )
    assert patched.index("except Exception as _infer_exc:") < exc_toast
    # Error site 2: the concurrent-run raise sits BEFORE the body's try, so the
    # except handler can never cover it — the toast must precede that raise.
    conc_toast = patched.index("another batch inference is already running.")
    conc_raise = patched.index("raise RuntimeError(")
    assert conc_toast < conc_raise
    # The fork no longer injects a toast helper: upstream's _toast (present
    # exactly once, pristine) carries every announcement above.
    assert "def _infer_toast(" not in patched
    assert patched.count("def _toast(") == 1


def test_gradio_import_only_inside_toast_helper():
    patched = _patched_infer_source()
    gradio_lines = [ln for ln in patched.splitlines() if "import gradio" in ln]
    assert len(gradio_lines) == 1, (
        f"expected exactly 1 gradio import (lazy, inside upstream's _toast), "
        f"got {gradio_lines}"
    )
    assert gradio_lines[0] == "        import gradio as gr"  # indented = function-local
    # ...and it lives inside upstream's _toast body (never at module top of
    # the generated engine code): after its def, before the class injection
    # point (the fork's helpers block sits between _toast and the class).
    toast_def = patched.index("def _toast(")
    gradio_imp = patched.index("import gradio as gr")
    class_idx = patched.index("class VoiceConverter:")
    assert toast_def < gradio_imp < class_idx
    assert patched[:toast_def].count("import gradio") == 0
    assert "(gr.Warning if warning else gr.Info)(message)" in patched
    assert "def _infer_toast(" not in patched


def _load_helpers():
    """Exec the injected helper block standalone (pure stdlib, AppKit-free)."""
    spec = importlib.util.spec_from_file_location(
        "patch_inference_progress",
        os.path.join(REPO, "patches", "patch_inference_progress.py"),
    )
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    ns = {}
    exec(patcher.INFER_PROGRESS_HELPERS, ns)
    return ns


def test_single_conversion_seam_in_patched_engine():
    patched = _patched_infer_source()
    # Seam head: begin AFTER get_vc (a get_vc failure must leave NO record
    # behind) and BEFORE start_time; the body moves one indent level into a try.
    get_vc = patched.index("self.get_vc(model_path, sid)")
    begin = patched.index("_infer_single_ctx = _infer_single_begin(")
    start_time = patched.index("\n        start_time = time.time()\n")
    try_kw = patched.index("\n        try:\n", begin)
    assert get_vc < begin < start_time < try_kw
    # The body is genuinely wrapped: sf.write (8-space in pristine) now at 12.
    assert "\n            sf.write(audio_output_path, audio_opt" in patched
    # Error terminal BEFORE the bare re-raise (preserves the pristine
    # traceback); success terminal after the except arm, before the tail.
    except_kw = patched.index("except Exception as _infer_single_exc:")
    err_end = patched.index(
        "_infer_single_end(_infer_single_ctx, error=str(_infer_single_exc))"
    )
    bare_raise = patched.index("\n            raise\n", err_end)
    ok_end = patched.index("\n        _infer_single_end(_infer_single_ctx)\n")
    tail = patched.index("elapsed_time = time.time() - start_time")
    assert try_kw < except_kw < err_end < bare_raise < ok_end < tail
    # Batch guard lives in the begin helper: skip every single-conversion
    # write while a NON-single record is running/cancelling (one atomic-write
    # owner at a time; the batch loop's nested self.convert_audio calls hit
    # exactly this guard - the batch record carries no scope).
    begin_def = patched.index("def _infer_single_begin(")
    end_def = patched.index("def _infer_single_end(")
    guard = patched.index('existing.get("status") in ("running", "cancelling")')
    scope_guard = patched.index('existing.get("scope") != "single"')
    assert begin_def < guard < scope_guard < end_def
    # Start record: distinguishing scope + total=1/processed=0 (line packing is
    # deliberately split so the batch tests' first-occurrence substrings keep
    # pointing at the BATCH body, which sits later in the file).
    assert '"scope": "single"' in patched[begin_def:end_def]
    assert '"total": 1,' in patched[begin_def:end_def]
    assert '"processed": 0,' in patched[begin_def:end_def]
    # Exactly ONE begin call site: the batch's nested convert_audio calls go
    # through the SAME seam (skipped by the guard), not a second injection.
    assert patched.count("_infer_single_ctx = _infer_single_begin(") == 1


def test_single_helpers_guard_and_terminal_writes(tmp_path, monkeypatch):
    """Behavioral: exec the helpers and drive the single-conversion state
    machine + batch guard against a real temp progress/history file."""
    import json

    ns = _load_helpers()
    monkeypatch.setenv("APPLIO_DATA_PATH", str(tmp_path))
    applio_dir = tmp_path / ".applio"
    applio_dir.mkdir()
    prog = applio_dir / "inference_progress.json"
    hist = applio_dir / "process_history.json"

    # A running BATCH record (no scope => != "single") must not be clobbered:
    # begin refuses (None) and end(None) is a no-op.
    prog.write_text(
        json.dumps({"version": 1, "type": "inference", "status": "running", "total": 9})
    )
    ctx = ns["_infer_single_begin"]("/x/model.pth", "in.wav", "o/out.wav")
    assert ctx is None
    ns["_infer_single_end"](ctx)
    assert json.loads(prog.read_text())["total"] == 9

    # No competing live record => begin claims the file: running/single/total 1.
    prog.write_text(json.dumps({"version": 1, "status": "completed"}))
    ctx = ns["_infer_single_begin"]("/x/model.pth", "in.wav", "odir/out.wav")
    assert ctx and ctx["model_name"] == "model.pth"
    live = json.loads(prog.read_text())
    assert live["status"] == "running" and live["scope"] == "single"
    assert live["total"] == 1 and live["processed"] == 0

    # Success terminal: completed, processed/converted 1, ended_at + elapsed,
    # and a schema-compatible history entry (type/started_at/completed_at).
    ns["_infer_single_end"](ctx)
    done = json.loads(prog.read_text())
    assert done["status"] == "completed" and done["scope"] == "single"
    assert done["processed"] == 1 and done["converted"] == 1
    assert done["ended_at"] and done["elapsed"] >= 0 and done["error"] is None
    h = json.loads(hist.read_text())["history"]
    assert h[0]["type"] == "inference" and h[0]["status"] == "completed"
    assert h[0]["total"] == 1 and h[0]["scope"] == "single"
    assert h[0]["started_at"] and h[0]["completed_at"]

    # Error terminal lands in both files too.
    ctx = ns["_infer_single_begin"]("/x/model.pth", "in.wav", "o/out.wav")
    ns["_infer_single_end"](ctx, error="boom")
    done = json.loads(prog.read_text())
    assert done["status"] == "error" and done["error"] == "boom"
    assert done["processed"] == 0 and done["converted"] == 0
    assert json.loads(hist.read_text())["history"][0]["status"] == "error"
