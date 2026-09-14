# tests/test_menu_spec.py
"""Pure-Python gate for menu_spec (no GUI, no AppKit). Run: python tests/test_menu_spec.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from menu_spec import (
    MENU,
    APP_NAME,
    APP_MENU_TITLE,
    PYWEBVIEW_APP_KEY,
    LAUNCHER_ACTION_KEYS,
    WRAPPER_ACTION_KEYS,
    DISPLAY_KEYS,
    TAXONOMY,
    EDIT_KEYS,
    iter_leaves,
)

EXPECTED_TOP_LEVEL = ["Applio", "Edit", "File", "Process", "Window", "Help"]


def _titles_top_level():
    out = []
    for top in MENU:
        title = top.title or (APP_MENU_TITLE if _is_app_menu(top) else "")
        out.append(title)
    return out


def _is_app_menu(top):
    return top is MENU[0]


def test_top_level_order():
    titles = _titles_top_level()
    assert titles == EXPECTED_TOP_LEVEL, f"top-level order wrong: {titles}"


def test_no_settings_menu():
    for leaf in iter_leaves(MENU):
        assert leaf.key != "app.settings", "app.settings must not exist"


def test_edit_menu_present():
    edit = next(t for t in MENU if t.title == "Edit")
    keys = [leaf.key for leaf in iter_leaves(edit.submenu)]
    assert keys == [
        "edit.undo",
        "edit.redo",
        "edit.cut",
        "edit.copy",
        "edit.paste",
        "edit.select_all",
    ], keys
    from menu_spec import STANDARD_SELECTOR_KEYS

    for k in keys:
        assert k in STANDARD_SELECTOR_KEYS, f"{k} needs a responder-chain selector"
        assert STANDARD_SELECTOR_KEYS[k].endswith(
            ":"
        ), f"{k} selector must be an action"


def test_frequent_action_shortcuts():
    by_key = {leaf.key: leaf for leaf in iter_leaves(MENU)}
    expected = {
        "process.open_logs": ("l", ("cmd",)),
        "file.set_data_location": ("d", ("cmd", "shift")),
        "window.show_main": ("0", ("cmd",)),
        "file.reveal_root": ("r", ("cmd", "shift")),
    }
    for key, (sc, mods) in expected.items():
        leaf = by_key[key]
        assert (leaf.shortcut, leaf.mods) == (
            sc,
            mods,
        ), f"{key}: {leaf.shortcut} {leaf.mods}"
    edit = next(t for t in MENU if t.title == "Edit")
    edit_expected = {
        "edit.undo": ("z", ("cmd",)),
        "edit.redo": ("z", ("cmd", "shift")),
        "edit.cut": ("x", ("cmd",)),
        "edit.copy": ("c", ("cmd",)),
        "edit.paste": ("v", ("cmd",)),
        "edit.select_all": ("a", ("cmd",)),
    }
    for leaf in iter_leaves(edit.submenu):
        assert (leaf.shortcut, leaf.mods) == edit_expected[
            leaf.key
        ], f"{leaf.key}: {leaf.shortcut} {leaf.mods}"


def test_keys_are_known():
    # Action keys live in TAXONOMY; display-only items (e.g. process.status)
    # live in DISPLAY_KEYS. A leaf may belong to either.
    for leaf in iter_leaves(MENU):
        if not leaf.key:
            continue
        assert (
            leaf.key in TAXONOMY or leaf.key in DISPLAY_KEYS
        ), f"unknown key {leaf.key!r}"


def test_action_key_contracts():
    leaves = {leaf.key for leaf in iter_leaves(MENU) if leaf.key}
    for k in leaves:
        assert k in LAUNCHER_ACTION_KEYS or k in DISPLAY_KEYS, f"orphan key {k!r}"
    assert (
        LAUNCHER_ACTION_KEYS <= leaves
    ), f"launcher keys missing from MENU: {LAUNCHER_ACTION_KEYS - leaves}"
    injected = {
        "app.about",
        "app.hide",
        "app.hide_others",
        "app.quit",
        "window.zoom",
        "window.bring_all_to_front",
    }
    assert (
        WRAPPER_ACTION_KEYS == LAUNCHER_ACTION_KEYS - injected - EDIT_KEYS
    ), "wrapper contract mismatch (Edit items are launcher-only)"
    assert injected <= LAUNCHER_ACTION_KEYS, "injected keys must be in launcher set"


def test_display_keys_are_dynamic():
    for leaf in iter_leaves(MENU):
        if leaf.key in DISPLAY_KEYS:
            assert leaf.dynamic, f"display key {leaf.key!r} must be dynamic"


def test_a11y_menu_gone():
    # 2026-08-23 auto-a11y owner ruling: the Accessibility submenu is REMOVED
    # (speech is zero-config — VoiceOver-gated; hidden NSUserDefaults keys
    # are the only escape hatch, with no UI). Guard against regressions in
    # both the MENU tree and the key-set machinery.
    import menu_spec

    for leaf in iter_leaves(menu_spec.MENU):
        assert not (leaf.key or "").startswith(
            "a11y."
        ), f"stale a11y menu item {leaf.key!r}"
    assert not hasattr(menu_spec, "A11Y_CHILD_KEYS"), "stale a11y key-set machinery"
    assert not hasattr(menu_spec, "A11Y_KEYS"), "stale a11y key-set machinery"
    assert not any(k.startswith("a11y.") for k in menu_spec.TAXONOMY)
    assert not any(k.startswith("a11y.") for k in menu_spec.DISPLAY_KEYS)


def test_app_menu_const():
    assert PYWEBVIEW_APP_KEY == "__app__"
    assert APP_NAME == "Applio"


# ---- version-compare tests (applio_update_check) ----
from applio_update_check import is_update_available


def test_update_available_basic():
    assert is_update_available("3.6.9", "3.6.10")[0] is True


def test_update_equal():
    assert is_update_available("3.6.9", "3.6.9")[0] is False


def test_update_downgrade():
    assert is_update_available("3.6.9", "3.6.8")[0] is False


def test_update_double_digit():
    # lexical string compare would get this wrong: "3.6.10" > "3.6.9"
    assert is_update_available("3.6.9", "3.6.10")[0] is True
    assert is_update_available("3.6.10", "3.6.9")[0] is False


def test_update_malformed_tag_failsafe():
    assert is_update_available("3.6.9", "v3.6.3-rc1")[0] is False
    assert is_update_available("3.6.9", "latest")[0] is False


if __name__ == "__main__":
    fns = [
        v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll menu_spec tests passed ({len(fns)}).")
