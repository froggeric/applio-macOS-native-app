# tests/test_applio_i18n.py
"""Tests for applio_i18n (pure; injectable paths; no AppKit).
Run: venv_macos/bin/python tests/test_applio_i18n.py"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_i18n


def _make_tree(locale, extra_keys=None):
    tmp = tempfile.mkdtemp()
    lang_dir = os.path.join(tmp, "assets", "i18n", "languages")
    os.makedirs(lang_dir)
    data = {"Started {label}": "Cominciato {label}", "finished": "finito"}
    if extra_keys:
        data.update(extra_keys)
    with open(os.path.join(lang_dir, f"{locale}.json"), "w", encoding="utf8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    with open(os.path.join(tmp, "assets", "config.json"), "w", encoding="utf8") as fh:
        json.dump({"lang": {"override": True, "selected_lang": locale}}, fh)
    return tmp


def test_override_locale_and_format():
    tmp = _make_tree("xx_XX")
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert (
        tr("Started {label}").format(label="training: voice")
        == "Cominciato training: voice"
    )
    assert tr("finished") == "finito"


def test_missing_key_falls_back_to_key():
    tmp = _make_tree("xx_XX")
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("Quit Applio?") == "Quit Applio?"


def test_missing_language_file_falls_back_english():
    tmp = _make_tree("xx_XX")
    tr = applio_i18n.NativeI18n(base_paths=[tmp], locale="zz_ZZ")
    assert tr("finished") == "finished"


def test_policy_translator():
    import applio_a11y

    tmp = _make_tree("xx_XX")
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    pol = applio_a11y.AnnouncementPolicy(translator=tr)
    events = pol.events({"t:a:1": {"type": "t", "name": "a", "status": "running"}})
    assert ("start", "Cominciato t: a") in events


def test_overrides_layer_over_locale_map():
    tmp = _make_tree("xx_XX", extra_keys={"finished": "finito (override)"})
    # Simulate the fork-owned overrides file on top of the locale tree.
    with open(
        os.path.join(tmp, "assets", "applio_i18n_overrides.json"), "w", encoding="utf8"
    ) as fh:
        json.dump({"xx_XX": {"finished": "finito (fork)"}}, fh, ensure_ascii=False)
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("finished") == "finito (fork)"  # overrides win
    assert tr("Quit Applio?") == "Quit Applio?"  # genuinely missing -> English key
    # ("Started {label}" IS in the xx_XX fixture map, so it is NOT a
    # missing-key probe — use a key the locale file does not define)


def test_system_locale_prefix_glob():
    # Upstream semantics (assets/i18n/i18n.py:24-30): first AVAILABLE language
    # whose name startswith(locale[:2]) wins. xx_ZZ must resolve to xx_YY.
    import applio_i18n as _mod

    tmp = _make_tree("en_US")
    lang_dir = os.path.join(tmp, "assets", "i18n", "languages")
    with open(os.path.join(lang_dir, "xx_YY.json"), "w", encoding="utf8") as fh:
        json.dump({"finished": "finito xx"}, fh, ensure_ascii=False)
    with open(os.path.join(tmp, "assets", "config.json"), "w", encoding="utf8") as fh:
        json.dump({"lang": {}}, fh)  # no override -> system-locale path
    orig = _mod._locale.getdefaultlocale
    _mod._locale.getdefaultlocale = lambda: ("xx_ZZ", "UTF-8")
    try:
        tr = applio_i18n.NativeI18n(base_paths=[tmp])
        assert tr.language == "xx_YY", tr.language
        assert tr("finished") == "finito xx"
    finally:
        _mod._locale.getdefaultlocale = orig


def test_corrupt_locale_json_falls_back():
    tmp = _make_tree("xx_XX")
    # Overwrite the locale file with a JSON list -> not a dict.
    with open(
        os.path.join(tmp, "assets", "i18n", "languages", "xx_XX.json"),
        "w",
        encoding="utf8",
    ) as fh:
        fh.write("[1, 2, 3]")
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr.language == "en_US"
    assert tr("finished") == "finished"  # English key fallback, no crash


def test_corrupt_overrides_json_falls_back():
    tmp = _make_tree("xx_XX")
    with open(
        os.path.join(tmp, "assets", "applio_i18n_overrides.json"), "w", encoding="utf8"
    ) as fh:
        fh.write('["not", "an", "object"]')
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("finished") == "finito"  # locale map still loads; overrides skipped
    # A dict overrides file whose per-locale layer is a list is skipped too.
    with open(
        os.path.join(tmp, "assets", "applio_i18n_overrides.json"), "w", encoding="utf8"
    ) as fh:
        json.dump({"xx_XX": ["bad", "layer"]}, fh)
    tr2 = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr2("finished") == "finito"


CLUSTER_KEYS = [
    ("macos_wrapper.py", "Initializing environment..."),
    ("macos_wrapper.py", "Loading Neural Networks..."),
    ("applio_launcher.py", "Status: Running"),
    ("applio_launcher.py", "Stopping…"),
    ("applio_launcher.py", "Based on RVC (Retrieval-Based Voice Conversion)"),
]

# Wrapped-form expectations: (file, snippet that must exist after wrapping).
# This is the FAILING half of the test pre-implementation.
WRAPPED_FORMS = [
    ("macos_wrapper.py", '_t("Initializing environment...")'),
    ("macos_wrapper.py", '_t("Loading Neural Networks...")'),
    ("macos_wrapper.py", '_t("Launching User Interface...")'),
    ("macos_wrapper.py", '_t("Unpacking {basename}")'),
    ("macos_wrapper.py", '_t("Synchronizing Assets")'),
    ("applio_launcher.py", '_t("Status: Running")'),
    ("applio_launcher.py", '_t("Pause")'),
    ("applio_launcher.py", '_t("Stopping…")'),
    ("applio_launcher.py", '_t("Failed")'),
    ("applio_launcher.py", '_t("Voice Conversion Application")'),
]


def test_native_clusters_translatable_and_stable():
    tmp = _make_tree("en_US", extra_keys={})
    overrides = {
        "en_US": {
            "Initializing environment...": "Inicializando entorno...",
            "Loading Neural Networks...": "Cargando redes neuronales...",
        }
    }
    with open(
        os.path.join(tmp, "assets", "applio_i18n_overrides.json"), "w", encoding="utf8"
    ) as fh:
        json.dump(overrides, fh, ensure_ascii=False)
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("Initializing environment...") == "Inicializando entorno..."
    assert tr("Loading Neural Networks...") == "Cargando redes neuronales..."
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # (b) raw literals stay verbatim in their owning files so the keys (and
    # any overrides written against them) never drift.
    for fname, literal in CLUSTER_KEYS:
        with open(os.path.join(repo, fname), encoding="utf8") as fh:
            assert literal in fh.read(), f"{fname} lost key {literal!r}"
    # (c) the wrapping itself exists — representative sites in wrapped form.
    for fname, snippet in WRAPPED_FORMS:
        with open(os.path.join(repo, fname), encoding="utf8") as fh:
            assert snippet in fh.read(), f"{fname} missing wrapped form {snippet!r}"


def run_all():
    test_override_locale_and_format()
    test_missing_key_falls_back_to_key()
    test_missing_language_file_falls_back_english()
    test_policy_translator()
    test_overrides_layer_over_locale_map()
    test_system_locale_prefix_glob()
    test_corrupt_locale_json_falls_back()
    test_corrupt_overrides_json_falls_back()
    test_native_clusters_translatable_and_stable()
    print("All applio_i18n tests passed (9).")


if __name__ == "__main__":
    run_all()
