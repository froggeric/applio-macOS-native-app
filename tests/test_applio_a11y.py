# tests/test_applio_a11y.py
"""Pure-Python gate for applio_a11y (no GUI, no AppKit needed for the policy).
Run: venv_macos/bin/python tests/test_applio_a11y.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_a11y
from applio_a11y import AnnouncementPolicy

SNAP = {
    "myvoice": {"type": "training", "name": "myvoice", "status": "running"},
}


def test_new_running_announces_start():
    p = AnnouncementPolicy()
    evts = p.events(SNAP)
    assert ("start", "Started training: myvoice") in evts, evts


def test_steady_state_no_events():
    p = AnnouncementPolicy()
    p.events(SNAP)
    assert p.events(SNAP) == [], "no announcements without a state change"


def test_terminal_transition():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events(
        {"myvoice": {"type": "training", "name": "myvoice", "status": "completed"}}
    )
    assert evts == [("terminal", "training: myvoice completed")], evts


def test_failed_is_terminal():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events(
        {"myvoice": {"type": "training", "name": "myvoice", "status": "failed"}}
    )
    assert evts[0][0] == "terminal" and "failed" in evts[0][1]


def test_pause_resume():
    p = AnnouncementPolicy()
    p.events(SNAP)
    paused = {"myvoice": {"type": "training", "name": "myvoice", "status": "paused"}}
    assert p.events(paused) == [("info", "training: myvoice paused")]
    assert p.events(SNAP) == [("info", "training: myvoice resumed")]


def test_disappeared_running_announces_finished():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events({})
    assert evts == [("terminal", "training: myvoice finished")], evts


def test_disappeared_paused_announces_finished():
    p = AnnouncementPolicy()
    p.events(SNAP)
    p.events({"myvoice": {"type": "training", "name": "myvoice", "status": "paused"}})
    evts = p.events({})
    assert evts == [("terminal", "training: myvoice finished")], evts


def test_disappeared_terminal_no_event():
    p = AnnouncementPolicy()
    p.events({"m": {"type": "tts", "name": "m", "status": "completed"}})
    assert p.events({}) == []


def test_disappeared_with_terminal_words():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events({}, terminal_words={"myvoice": "failed"})
    assert evts == [("terminal", "training: myvoice failed")], evts


def test_prime_then_steady_no_start():
    p = AnnouncementPolicy()
    p.prime(SNAP)
    assert p.events(SNAP) == [], "primed snapshot must not announce Started"


def test_live_statuses_disjoint_from_terminal():
    import applio_a11y

    assert applio_a11y.LIVE_STATUSES == {"running", "paused"}
    assert not (applio_a11y.LIVE_STATUSES & applio_a11y.TERMINAL_STATUSES)


def test_count_live_includes_paused():
    snap = {
        "training:a:1": {"type": "training", "name": "a", "status": "running"},
        "training:b:2": {"type": "training", "name": "b", "status": "paused"},
        "tts:c:3": {"type": "tts", "name": "c", "status": "completed"},
    }
    assert applio_a11y.count_live(snap) == 2


def test_word_key_overrides_snapshot_key_for_terminal_word():
    pol = applio_a11y.AnnouncementPolicy()
    pol.prime(
        {
            "training:voice:123": {
                "type": "training",
                "name": "voice",
                "status": "running",
                "word_key": "training:voice",
            }
        }
    )
    events = pol.events({}, terminal_words={"training:voice": "failed"})
    assert ("terminal", "training: voice failed") in events


def test_missing_keys_is_readonly():
    pol = applio_a11y.AnnouncementPolicy()
    pol.prime({"a:1": {"type": "a", "name": "x", "status": "running"}})
    missing = pol.missing_keys({})
    assert missing == {"a:1"}
    assert set(pol._seen) == {"a:1"}  # _seen untouched
    # steady state: nothing missing
    assert (
        pol.missing_keys({"a:1": {"type": "a", "name": "x", "status": "running"}})
        == set()
    )


def test_two_jobs_same_type_name_distinct_keys():
    pol = applio_a11y.AnnouncementPolicy()
    pol.prime({})
    snap = {
        "training:voice:111": {
            "type": "training",
            "name": "voice",
            "status": "running",
        },
        "training:voice:222": {
            "type": "training",
            "name": "voice",
            "status": "running",
        },
    }
    starts = [e for e in pol.events(snap) if e[0] == "start"]
    assert len(starts) == 2


def test_disappeared_unknown_status_silent():
    # prev status in neither LIVE nor TERMINAL (e.g. a raw "cancelling" leak):
    # documented behavior — no event (same as today's tuple guard, now derived)
    pol = applio_a11y.AnnouncementPolicy()
    pol._seen = {"tts:x:1": ("cancelling", "tts: x", "tts:x")}
    assert pol.events({}) == []


def test_disappeared_key_popped_single_announcement():
    pol = applio_a11y.AnnouncementPolicy()
    pol._seen = {"training:a:1": ("running", "training: a", "training:a")}
    first = pol.events({})
    assert ("terminal", "training: a finished") in first
    # second call must NOT re-announce (key was popped, not kept)
    assert pol.events({}) == []
    assert pol.missing_keys({}) == set()


if __name__ == "__main__":
    fns = [
        v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll applio_a11y tests passed ({len(fns)}).")
