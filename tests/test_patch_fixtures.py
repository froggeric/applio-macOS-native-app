"""Fixture tests for patcher correctness (history-write order + bounded scan).
Run: venv_macos/bin/python tests/test_patch_fixtures.py
Reads PRISTINE upstream core.py from the repo; guards against a dirty tree."""

import importlib.util
import os
import py_compile
import re
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patched_core(tracking):
    src = open(os.path.join(REPO, "core.py"), encoding="utf8").read()
    assert (
        "_APPLIO_" not in src and "_track_process(" not in src
    ), "core.py is dirty (patched?) - restore first"
    content = src
    ok = 0
    for fn_name in (
        "patch_run_preprocess_script",
        "patch_run_extract_script",
        "patch_run_train_script",
        "patch_run_index_script",
        "patch_voice_conversion",
    ):
        fn = getattr(tracking, fn_name)
        content, patched = fn(content)
        ok += 1 if patched else 0
    assert ok >= 4, f"expected >=4 patched blocks, got {ok} (anchors drifted?)"
    return content


def test_history_written_before_untrack():
    tracking = _load("patch_process_tracking", "patches/patch_process_tracking.py")
    patched = _patched_core(tracking)
    # Anchored regex = CALL sites only: a def line ("    def _untrack_process(")
    # cannot match ^[ \t]*_untrack_process\(. (A plain find() would also hit
    # the injected helper definitions — that false-positive pattern is why
    # this uses the anchor.)
    sites = list(re.finditer(r"(?m)^[ \t]*_untrack_process\(", patched))
    assert len(sites) >= 4, f"expected >=4 untrack call sites, found {len(sites)}"
    for m in sites:
        u = m.start()
        # enclosing function = nearest preceding top-level def
        fstart = patched.rfind("\ndef ", 0, u)
        fend = patched.find("\ndef ", u)
        body = patched[fstart : fend if fend != -1 else len(patched)]
        h = body.find("_add_to_history(")
        assert h != -1 and h < body.find(
            "_untrack_process("
        ), "untrack precedes history-add inside a tracked function"
    # sanity: the patched output compiles
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(patched)
    py_compile.compile(tf.name, doraise=True)
    os.unlink(tf.name)


def test_upload_scan_bounded_to_function_body():
    stop = _load("patch_stop_feedback", "patches/patch_stop_feedback.py")
    synthetic = (
        "def save_to_wav2(bin_file):\n"
        "    uploaded = bin_file.name\n"
        "\n"
        "def later_function(x):\n"
        "    return x\n"
    )
    content, status = stop.patch_upload(synthetic)
    assert status == "miss", "scan must not cross the function boundary"
    assert "gr.Info" not in content
    good = (
        "def save_to_wav2(bin_file):\n"
        "    uploaded = bin_file.name\n"
        "    return uploaded\n"
    )
    content, status = stop.patch_upload(good)
    assert status == "patched" and "gr.Info" in content


def test_progress_routes_patch():
    routes = _load("patch_progress_routes", "patches/patch_progress_routes.py")
    src = open(os.path.join(REPO, "app.py"), encoding="utf8").read()
    assert (
        "_APPLIO_A11Y_ROUTES_" not in src
    ), "app.py is dirty (patched?) - restore first"
    patched, status = routes.patch_app(src)
    assert status in ("patched", "already")
    assert "prevent_thread_lock=True,  # _APPLIO_A11Y_ROUTES_" in patched
    # allowed_paths must resolve at LAUNCH time (frozen cwd is the bundle, so
    # gradio's default cwd+temp set rejects user-dir outputs with
    # InvalidPathError - file written but never served): home covers the
    # default data dir (~/Applio) + user-picked paths under ~; the env entry
    # covers a data location chosen OUTSIDE home (macos_wrapper sets
    # APPLIO_DATA_PATH in-process before Gradio). The `if p` filter matters:
    # gradio's abspath stringifies a None into a bogus `<cwd>/None` entry
    # (no crash; hygiene). Since upstream 3ea5259b ships its own
    # allowed_paths = ["logs"], the patcher EXTENDS that list — a second
    # kwarg would be a SyntaxError (keyword repeated), so pin: exactly one
    # allowed_paths occurrence, upstream's "logs" entry preserved inside it,
    # and both kwargs inside the launch call (upstream order: ptl first).
    assert patched.count("allowed_paths") == 1, "duplicate allowed_paths kwarg"
    assert 'allowed_paths=["logs"]' in patched
    assert 'os.path.expanduser("~")' in patched
    assert 'os.environ.get("APPLIO_DATA_PATH")' in patched
    launch = patched.find("Applio.launch(")
    ptl = patched.find("prevent_thread_lock=True,")
    kw = patched.find("allowed_paths=[")
    assert (
        launch != -1 and launch < ptl < kw
    ), "launch kwargs not ordered inside the launch call"
    block = patched.find("applio_progress_api.register_routes(app)")
    tb = patched.find("from rvc.lib.tools.launch_tensorboard import get_tb_url")
    assert block != -1 and tb != -1 and block < tb
    keepalive = patched.find("while True:", block)
    guard = patched.find("if not client_mode:", block)
    assert guard != -1 and keepalive != -1 and guard < keepalive
    repatched, status2 = routes.patch_app(patched)
    assert status2 == "already" and repatched == patched  # idempotent
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf8"
    ) as tf:
        tf.write(patched)
    try:
        py_compile.compile(tf.name, doraise=True)
    finally:
        os.unlink(tf.name)


def test_browse_buttons_patch():
    browse = _load("patch_browse_buttons", "patches/patch_browse_buttons.py")
    for rel, fields in browse.FIELDS.items():
        src = open(os.path.join(REPO, rel), encoding="utf8").read()
        assert (
            "_APPLIO_BROWSE_" not in src
        ), f"{rel} is dirty (patched?) - restore first"
        patched, status = browse.patch_file(src, fields, browse.MARKERS[rel])
        # A skip here means a field var drifted upstream and its button would
        # silently never ship - fail loudly (patcher's skip warnings print above).
        assert status == "patched", f"{rel}: status={status}"
        assert patched.count("_applio_browse_") == len(fields), (
            f"{rel}: expected {len(fields)} inserted lines, "
            f"got {patched.count('_applio_browse_')}"
        )
        i18n_idx = patched.find("i18n = I18nAuto()")
        imp_idx = patched.find("import applio_browse_ui  # _APPLIO_BROWSE_IMPORT_")
        assert (
            i18n_idx != -1 and imp_idx > i18n_idx
        ), f"{rel}: import not after i18n anchor"
        for var, mode in fields:
            line = f'_applio_browse_{var} = applio_browse_ui.browse_button("{mode}", {var},'
            assert line in patched, f"{rel}: wrong mode/target on {var}"
            # The validation-attach line must NOT contain "_applio_browse_"
            # (the count assertion above pins that substring to exactly one
            # carrier per field: the assignment var).
            vline = f'applio_browse_ui.attach_path_validation({var}, "{mode}")'
            assert vline in patched, f"{rel}: validation not attached to {var}"
            m = re.search(
                rf"^(?P<indent>[ \t]*){re.escape(var)} = gr\.(?:Textbox|Dropdown)\(",
                patched,
                re.MULTILINE,
            )
            assert m, f"{rel}: definition for {var} vanished"
            end = browse._find_statement_end(patched, m.end() - 1)
            ins = patched.find(f"_applio_browse_{var} = ")
            assert (
                end != -1 and ins > end
            ), f"{rel}: {var} browse line before its definition"
            # Only whitespace (the blank line + indent) between the closing
            # paren and the factory line = immediately after the statement,
            # before the next one.
            assert patched[end:ins].strip() == "", f"{rel}: {var} browse line misplaced"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf8"
        ) as tf:
            tf.write(patched)
        try:
            py_compile.compile(tf.name, doraise=True)
        finally:
            os.unlink(tf.name)
    # Synthetic negative: one field definition missing -> that field skipped,
    # the file still patches with the remaining fields.
    synthetic = (
        "i18n = I18nAuto()\n"
        "\n"
        "def tts_tab():\n"
        "    with gr.Column():\n"
        "        input_tts_path = gr.Textbox(\n"
        '            label=i18n("Input path"),\n'
        "            interactive=True,\n"
        "        )\n"
        "        output_tts_path = gr.Textbox(\n"
        '            label=i18n("Output path"),\n'
        "            interactive=True,\n"
        "        )\n"
    )
    patched, status = browse.patch_file(
        synthetic, browse.FIELDS["tabs/tts/tts.py"], browse.MARKERS["tabs/tts/tts.py"]
    )
    assert status == "patched"
    assert "_applio_browse_input_tts_path" in patched
    assert "_applio_browse_output_tts_path" in patched
    assert "_applio_browse_output_rvc_path" not in patched


def test_web_payload_patch():
    payload = _load("patch_web_a11y_payload", "patches/patch_web_a11y_payload.py")
    src = open(os.path.join(REPO, "app.py"), encoding="utf8").read()
    assert "_APPLIO_A11Y_JS_" not in src, "app.py is dirty (patched?) - restore first"
    patched, status = payload.patch_app(src)
    assert status in ("patched", "already")
    assert "def _applio_a11y_js(" in patched and "_APPLIO_A11Y_JS_" in patched
    assert '"js": _applio_a11y_js(client_mode),' in patched
    # Only the GRADIO_6 entry inside launch_gradio is replaced; the dead
    # `if not GRADIO_6` fallback keeps its inline js=, and css stays put.
    helper_idx = patched.index("def _applio_a11y_js(")
    launch_idx = patched.index("def launch_gradio(")
    call_idx = patched.index('"js": _applio_a11y_js(client_mode),')
    assert helper_idx < launch_idx < call_idx
    assert '"css": "footer{display:none !important}",' in patched
    repatched, status2 = payload.patch_app(patched)
    assert status2 == "already" and repatched == patched  # idempotent
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf8"
    ) as tf:
        tf.write(patched)
    try:
        py_compile.compile(tf.name, doraise=True)
    finally:
        os.unlink(tf.name)


def run_all():
    test_history_written_before_untrack()
    test_upload_scan_bounded_to_function_body()
    test_progress_routes_patch()
    test_browse_buttons_patch()
    test_web_payload_patch()
    print("All patch fixture tests passed (5).")


if __name__ == "__main__":
    run_all()
