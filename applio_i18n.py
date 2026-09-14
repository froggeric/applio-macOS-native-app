"""Native-string i18n for the Applio fork (AppKit-free).

Mirrors assets/i18n/i18n.py's locale resolution (config lang.override /
selected_lang / system locale) but resolves config + language files across
dev cwd and the frozen bundle (sys._MEIPASS). Missing keys return the key
(English source text) — graceful degradation, repo convention.

Keys are the natural English strings themselves (repo convention), so English
needs no entries: the fallback IS the text. Real translations land in the
OPTIONAL fork-owned assets/applio_i18n_overrides.json ({locale: {key: tr}})
layered over the loaded locale map — upstream language files stay pristine.
"""

import json
import locale as _locale
import os
import sys
import threading

_LOCK = threading.Lock()
_INSTANCE = None

DEFAULT_LOCALE = "en_US"


def _candidate_base_paths():
    paths = []
    cwd = os.getcwd()
    paths.append(cwd)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass != cwd:
        paths.append(meipass)
    return paths


class NativeI18n:
    def __init__(self, base_paths=None, locale=None):
        self._map = {}
        self.language = DEFAULT_LOCALE
        bases = base_paths if base_paths is not None else _candidate_base_paths()
        chosen = locale or self._resolve_from_config(bases)
        for base in bases:
            path = os.path.join(base, "assets", "i18n", "languages", f"{chosen}.json")
            try:
                with open(path, "r", encoding="utf8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    raise ValueError(f"language file is not an object: {path}")
                self._map = data
                self.language = chosen
                break
            except (OSError, ValueError):
                continue
        # Optional fork-owned overrides layer (absent until real translations
        # exist; upstream locale files stay pristine).
        for base in bases:
            override_path = os.path.join(base, "assets", "applio_i18n_overrides.json")
            try:
                with open(override_path, "r", encoding="utf8") as fh:
                    overrides = json.load(fh)
                if not isinstance(overrides, dict):
                    raise ValueError(
                        f"overrides file is not an object: {override_path}"
                    )
                layer = overrides.get(self.language, {})
                if isinstance(layer, dict):
                    self._map.update(layer)
                break
            except (OSError, ValueError):
                continue

    @staticmethod
    def _resolve_from_config(bases):
        for base in bases:
            try:
                with open(
                    os.path.join(base, "assets", "config.json"), encoding="utf8"
                ) as fh:
                    lang = json.load(fh).get("lang", {})
                if lang.get("override"):
                    return lang.get("selected_lang") or DEFAULT_LOCALE
                sys_locale = (_locale.getdefaultlocale()[0] or "").replace("-", "_")
                if sys_locale:
                    # Upstream semantics (assets/i18n/i18n.py:24-30): first
                    # available language whose name startswith(locale[:2]).
                    prefix = sys_locale.split("_")[0][:2]
                    languages_dir = os.path.join(base, "assets", "i18n", "languages")
                    try:
                        available = sorted(
                            f[:-5]
                            for f in os.listdir(languages_dir)
                            if f.endswith(".json")
                        )
                    except OSError:
                        available = []
                    matching = [lang for lang in available if lang.startswith(prefix)]
                    if matching:
                        return matching[0]
                break
            except (OSError, ValueError):
                continue
        return DEFAULT_LOCALE

    def __call__(self, key):
        return self._map.get(key, key)


def native_tr(key):
    """Module-level singleton translator: translated string or the key itself."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = NativeI18n()
        return _INSTANCE(key)
