"""Factory + handler behavior for applio_browse_ui (no AppKit; gradio only).
Run: venv_macos/bin/python tests/test_browse_ui.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr

import applio_browse_ui


def test_handler_ok_returns_path():
    h = applio_browse_ui._make_handler("file")
    # Monkeypatch the picker to a canned result.
    applio_browse_ui._picker = lambda mode, prompt=None: ("ok", "/tmp/x.wav")
    assert h("/old") == "/tmp/x.wav"


def test_handler_expands_tilde():
    applio_browse_ui._picker = lambda mode, prompt=None: ("ok", "~/audios/out.wav")
    h = applio_browse_ui._make_handler("file")
    assert h("/old").startswith("/") and "~" not in h("/old")


def test_handler_cancel_keeps_current():
    applio_browse_ui._picker = lambda mode, prompt=None: ("cancel", None)
    h = applio_browse_ui._make_handler("folder")
    assert h("/keep/me") == "/keep/me"  # gr.Info fired as a side effect; value kept


def test_handler_unavailable_keeps_current():
    applio_browse_ui._picker = lambda mode, prompt=None: ("unavailable", None)
    h = applio_browse_ui._make_handler("pth")
    assert h("/keep") == "/keep"


def test_browse_button_creates_and_wires():
    applio_browse_ui._picker = lambda mode, prompt=None: ("cancel", None)
    with gr.Blocks():
        box = gr.Textbox(label="x")
        btn = applio_browse_ui.browse_button("file", box, elem_id="browse-test")
        assert isinstance(btn, gr.Button)
        assert (
            btn.elem_id == "browse-test"
        )  # falsible: the factory must pass it through


def _with_recorded_warnings(fn):
    import gradio as gr

    calls = []
    orig = gr.Warning
    gr.Warning = lambda msg, *a, **k: calls.append(msg)
    try:
        result, warnings = fn(), calls
    finally:
        gr.Warning = orig
    return result, warnings


def test_validator_expands_tilde_and_self_heals():
    import os

    v = applio_browse_ui._make_validator("folder")
    home = os.path.expanduser("~")
    out, warnings = _with_recorded_warnings(lambda: v("~"))
    assert out == home and warnings == []  # home IS a folder -> clean self-heal
    out2, warnings2 = _with_recorded_warnings(lambda: v("   "))
    assert out2 == "   " and warnings2 == []  # blank -> untouched, no warning


def test_validator_warns_on_missing_path():
    v = applio_browse_ui._make_validator("file")
    out, warnings = _with_recorded_warnings(lambda: v("/no/such/path.abc"))
    assert out == "/no/such/path.abc"
    assert warnings and warnings[0].startswith("Path does not exist")


def test_validator_warns_on_wrong_type():
    import os

    here = os.path.abspath(__file__)
    v_folder = applio_browse_ui._make_validator("folder")
    out, warnings = _with_recorded_warnings(lambda: v_folder(here))  # file, not folder
    assert warnings and warnings[0].startswith("Not a folder")
    assert out == here
    v_file = applio_browse_ui._make_validator("file")
    out2, warnings2 = _with_recorded_warnings(lambda: v_file(os.path.dirname(here)))
    assert warnings2 and warnings2[0].startswith("Not a file")  # dir, not file
    assert out2 == os.path.dirname(here)


def test_attach_validation_wires_blur_on_both_kinds():
    # Construction-time wiring on BOTH component kinds used by the 13 fields
    # (Textbox + Dropdown both expose .blur in gradio 6.20.0). Same pattern as
    # test_browse_button_creates_and_wires — no server needed.
    with gr.Blocks():
        tb = gr.Textbox()
        dd = gr.Dropdown(choices=["a"], allow_custom_value=True)
        applio_browse_ui.attach_path_validation(tb, "file")
        applio_browse_ui.attach_path_validation(dd, "pth")


def run_all():
    test_handler_ok_returns_path()
    test_handler_expands_tilde()
    test_handler_cancel_keeps_current()
    test_handler_unavailable_keeps_current()
    test_browse_button_creates_and_wires()
    test_validator_expands_tilde_and_self_heals()
    test_validator_warns_on_missing_path()
    test_validator_warns_on_wrong_type()
    test_attach_validation_wires_blur_on_both_kinds()
    print("All browse UI tests passed (9).")


if __name__ == "__main__":
    run_all()
