# tests/test_progress_api.py
"""Pure-payload tests for applio_progress_api (no AppKit, no launcher import).
Run: venv_macos/bin/python tests/test_progress_api.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_progress_api as api


def _training_job():
    return {
        "key": "training:voice:123",
        "type": "training",
        "name": "voice",
        "status": "running",
        "word_key": "training:voice",
        "log_tail": (
            "Starting Preprocess\n"
            "2026-08-21 15:00:00 | epoch=34 | step=21000 | time=00:12:34 | "
            "training_speed=0:34:56 | lowest_value=0.123 (epoch 30 and step 19000)\n"
            "Epoch: 34/200\n"
        ),
    }


def test_inference_stats_enrichment():
    jobs = [
        {
            "key": "inference:batch:app",
            "type": "inference",
            "name": "batch",
            "status": "running",
            "word_key": "inference:batch",
            "total": 10,
            "processed": 5,
            "converted": 5,
            "started_at": 100.0,
        }
    ]
    enriched = api.enrich_jobs(jobs, now=200.0)
    j = enriched[0]
    assert j["pct"] == 50.0
    assert j["detail"] == "5 of 10"
    assert "eta" in j and j["eta"] >= 0


def test_training_metrics_enrichment():
    enriched = api.enrich_jobs([_training_job()], now=1.0)
    j = enriched[0]
    assert j["epoch"] == [34, 200]
    assert j["best_loss"] == 0.123
    assert j["phase"] == "Preprocessing"  # detect_phase_name over the tail


def test_payload_shape_and_settings_echo():
    payload = api.build_progress_payload(
        jobs=[_training_job()],
        settings={"verbosity": "verbose", "sound": True},
        announce_owner="native",
        now=123.5,
        words={"training:voice": "failed"},
    )
    assert payload["now"] == 123.5
    assert payload["announce"] == {"owner": "native"}
    assert payload["settings"] == {"verbosity": "verbose", "sound": True}
    assert payload["words"] == {"training:voice": "failed"}
    assert payload["jobs"][0]["key"] == "training:voice:123"
    assert "log_tail" not in payload["jobs"][0]  # never leaked to the wire


def test_settings_echo_no_announce_mode():
    # Auto-a11y (2026-08-23): announce_mode is GONE from the settings echo
    # (the window-level AX post path was removed; the per-request owner rule
    # keeps its module default "web"). The pre-push default is SILENT speech
    # with sound cues ON.
    payload = api.build_progress_payload(
        jobs=[], settings=api.DEFAULT_SETTINGS, announce_owner="web", now=1.0
    )
    assert "announce_mode" not in payload["settings"], payload["settings"]
    assert api.DEFAULT_SETTINGS == {"verbosity": "off", "sound": True}
    api.set_settings(api.DEFAULT_SETTINGS)
    echoed = api.handle_progress(nav=None, now=1.0)["settings"]
    assert "announce_mode" not in echoed and echoed["sound"] is True


def test_collect_jobs_forwards_inference_scope():
    # The scope written by patch_inference_progress ("single" for a one-file
    # conversion; absent for a batch) must survive into the payload job so
    # the web jobLabel can say "conversion" vs "batch inference". The job's
    # type stays "inference" — enrich_jobs keys on it.
    class FakeLauncher:
        def get_active_processes(self):
            return []

        def _synthesize_inference_proc(self):
            return {
                "type": "inference",
                "status": "running",
                "model_name": "voice.pt",
                "scope": "single",
                "total": 1,
                "processed": 0,
            }

    orig = api._resolve_launcher
    api._resolve_launcher = lambda: FakeLauncher()
    try:
        jobs = api._collect_jobs()
    finally:
        api._resolve_launcher = orig
    assert len(jobs) == 1
    assert jobs[0]["type"] == "inference"
    assert jobs[0]["scope"] == "single"


def test_nav_token_fires_callback_once():
    fired = []
    api.set_layout_changed_callback(lambda: fired.append(1))
    api._state["last_nav"] = None
    api._state["last_nav_fire"] = 0.0
    api.handle_progress(nav="tab-a", now=1000.0)
    assert len(fired) == 1
    api.handle_progress(nav="tab-a", now=1001.0)  # same token: no re-fire
    assert len(fired) == 1
    api.handle_progress(nav="tab-b", now=1002.0)  # within debounce window...
    assert len(fired) == 1  # ...so still throttled
    api.handle_progress(nav="tab-c", now=1000.0 + api.NAV_FIRE_MIN_INTERVAL_S)
    assert len(fired) == 2


def test_owner_per_request():
    api.set_announce_owner("native")
    assert (
        api.handle_progress(client="native", now=1.0)["announce"]["owner"] == "native"
    )
    # external browser (no client flag) hears web announcements
    assert api.handle_progress(client=None, now=1.0)["announce"]["owner"] == "web"


def test_log_tail_read_by_seek():
    import os
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as tf:
        for i in range(3000):
            tf.write(f"line {i}\n")
        path = tf.name
    tail = api.read_log_tail(path, max_bytes=4096)
    assert "line 2999" in tail and "line 0\n" not in tail
    assert len(tail.splitlines()) < 3000
    os.unlink(path)


def test_handle_progress_never_raises():
    api.set_layout_changed_callback(None)
    payload = api.handle_progress(nav=None, now=1.0)
    assert "jobs" in payload and "settings" in payload


def test_terminal_words_from_history_shared_helper():
    entries = [
        {"type": "training", "model_name": "voice", "status": "failed"},
        {"type": "training", "model_name": "voice", "status": "completed"},  # older
        {"type": "extract", "model_name": "", "status": "completed"},  # incomplete
        {"type": "tts", "model_name": "x"},  # incomplete
        None,
    ]
    words = api.terminal_words_from_history(entries)
    assert words == {"training:voice": "failed"}  # setdefault keeps newest; skips gaps
    assert api.terminal_words_from_history(None) == {}
    assert api.terminal_words_from_history([]) == {}


def _fake_launcher(history):
    class L:
        def get_recent_processes(self, limit=20):
            return history

    return L()


def test_recent_error_tails_bounded_and_filtered(tmp_path=None):
    import os
    import tempfile

    logdir = tempfile.mkdtemp()
    log = os.path.join(logdir, "train.log")
    with open(log, "w", encoding="utf8") as fh:
        fh.write("x" * 9000 + "TAIL-MARKER")
    history = [
        {
            "type": "training",
            "model_name": "voice",
            "status": "failed",
            "log_path": log,
        },
        {
            "type": "extract",
            "model_name": "e",
            "status": "completed",
            "log_path": log,
        },  # not an error -> excluded
        {
            "type": "tts",
            "model_name": "t",
            "status": "error",
            "log_path": os.path.join(logdir, "missing.log"),
        },  # no file -> empty tail
    ]
    errors = api._recent_error_tails(_fake_launcher(history))
    assert [e["name"] for e in errors] == ["voice", "t"]
    assert errors[0]["tail"].endswith("TAIL-MARKER")
    assert len(errors[0]["tail"]) <= 1200
    assert errors[1]["tail"] == ""


def test_recent_error_tails_limit_two():
    history = [
        {"type": "t", "model_name": f"n{i}", "status": "failed", "log_path": None}
        for i in range(5)
    ]
    errors = api._recent_error_tails(_fake_launcher(history))
    assert len(errors) == 2 and errors[0]["name"] == "n0"  # newest-first, capped


def test_payload_carries_errors_key():
    payload = api.build_progress_payload(
        jobs=[],
        settings={},
        announce_owner="web",
        now=1.0,
        words=None,
        errors=[
            {"type": "training", "name": "voice", "status": "failed", "tail": "boom"}
        ],
    )
    assert payload["errors"][0]["tail"] == "boom"
    assert "errors" in api.build_progress_payload(
        jobs=[], settings={}, announce_owner="web", now=1.0
    )  # default empty list


def run_all():
    test_inference_stats_enrichment()
    test_training_metrics_enrichment()
    test_payload_shape_and_settings_echo()
    test_settings_echo_no_announce_mode()
    test_collect_jobs_forwards_inference_scope()
    test_nav_token_fires_callback_once()
    test_owner_per_request()
    test_log_tail_read_by_seek()
    test_handle_progress_never_raises()
    test_terminal_words_from_history_shared_helper()
    test_recent_error_tails_bounded_and_filtered()
    test_recent_error_tails_limit_two()
    test_payload_carries_errors_key()
    print("All progress API tests passed (13).")


if __name__ == "__main__":
    run_all()
