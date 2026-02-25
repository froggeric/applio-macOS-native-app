#!/usr/bin/env python3
"""
Patcher to redirect static resource paths to use APPLIO_BASE_PATH environment variable.

This allows static resources (configs, themes, i18n) to be loaded from the app bundle
via APPLIO_BASE_PATH instead of being copied to the user's data location.

Applied at build time by build_macos.py.
"""

import os
import re
import sys
from typing import List, Tuple


def patch_file(
    file_path: str, patterns: List[Tuple[str, str]], description: str
) -> Tuple[bool, int]:
    """
    Apply regex pattern replacements to a file.

    Args:
        file_path: Path to the file to patch
        patterns: List of (pattern, replacement) tuples
        description: Description for logging

    Returns:
        Tuple of (success, num_changes)
    """
    if not os.path.exists(file_path):
        print(f"[patch_static_resources] {description} not found at {file_path}")
        return False, 0

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    original_content = content
    total_changes = 0

    for pattern, replacement in patterns:
        matches = re.findall(pattern, content)
        if matches:
            content = re.sub(pattern, replacement, content)
            total_changes += len(matches)

    if content == original_content:
        if total_changes == 0:
            print(f"[patch_static_resources] {description}: no patterns found (may already be patched)")
        return True, total_changes

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[patch_static_resources] {description}: {total_changes} replacement(s)")
    return True, total_changes


def patch_i18n(base_path: str) -> bool:
    """
    Patch assets/i18n/i18n.py to use APPLIO_BASE_PATH for:
    - assets/i18n/languages/
    - assets/config.json
    """
    file_path = os.path.join(base_path, "assets", "i18n", "i18n.py")

    patterns = [
        # LANGUAGE_PATH = os.path.join(now_dir, "assets", "i18n", "languages")
        (
            r'LANGUAGE_PATH\s*=\s*os\.path\.join\(now_dir,\s*"assets",\s*"i18n",\s*"languages"\)',
            'LANGUAGE_PATH = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "i18n", "languages")',
        ),
        # os.path.join(now_dir, "assets", "config.json")
        (
            r'os\.path\.join\(now_dir,\s*"assets",\s*"config\.json"\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
        ),
    ]

    success, _ = patch_file(file_path, patterns, "assets/i18n/i18n.py")
    return success


def patch_load_themes(base_path: str) -> bool:
    """
    Patch assets/themes/loadThemes.py to use APPLIO_BASE_PATH for:
    - assets/themes/
    - assets/config.json
    """
    file_path = os.path.join(base_path, "assets", "themes", "loadThemes.py")

    patterns = [
        # config_file = os.path.join(now_dir, "assets", "config.json")
        (
            r'config_file\s*=\s*os\.path\.join\(now_dir,\s*"assets",\s*"config\.json"\)',
            'config_file = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
        ),
    ]

    success, _ = patch_file(file_path, patterns, "assets/themes/loadThemes.py")
    return success


def patch_version_checker(base_path: str) -> bool:
    """
    Patch assets/version_checker.py to use APPLIO_BASE_PATH for:
    - assets/config.json
    """
    file_path = os.path.join(base_path, "assets", "version_checker.py")

    patterns = [
        # config_file = os.path.join(now_dir, "assets", "config.json")
        (
            r'config_file\s*=\s*os\.path\.join\(now_dir,\s*"assets",\s*"config\.json"\)',
            'config_file = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
        ),
    ]

    success, _ = patch_file(file_path, patterns, "assets/version_checker.py")
    return success


def patch_app_py(base_path: str) -> bool:
    """
    Patch app.py to use APPLIO_BASE_PATH for:
    - tabs/realtime/main.js
    """
    file_path = os.path.join(base_path, "app.py")

    patterns = [
        # os.path.join(now_dir, "tabs", "realtime", "main.js")
        (
            r'os\.path\.join\(now_dir,\s*"tabs",\s*"realtime",\s*"main\.js"\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "realtime", "main.js")',
        ),
    ]

    success, _ = patch_file(file_path, patterns, "app.py")
    return success


def patch_rvc_lib_utils(base_path: str) -> bool:
    """
    Patch rvc/lib/utils.py to use APPLIO_BASE_PATH for:
    - rvc/models/formant/stftpitchshift
    """
    file_path = os.path.join(base_path, "rvc", "lib", "utils.py")

    patterns = [
        # base_path = os.path.join(now_dir, "rvc", "models", "formant", "stftpitchshift")
        (
            r'base_path\s*=\s*os\.path\.join\(now_dir,\s*"rvc",\s*"models",\s*"formant",\s*"stftpitchshift"\)',
            'base_path = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "rvc", "models", "formant", "stftpitchshift")',
        ),
    ]

    success, _ = patch_file(file_path, patterns, "rvc/lib/utils.py")
    return success


def patch_extract_model(base_path: str) -> bool:
    """
    Patch rvc/train/process/extract_model.py to use APPLIO_BASE_PATH for:
    - assets/config.json
    """
    file_path = os.path.join(base_path, "rvc", "train", "process", "extract_model.py")

    patterns = [
        # os.path.join(now_dir, "assets", "config.json")
        (
            r'os\.path\.join\(now_dir,\s*"assets",\s*"config\.json"\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
        ),
    ]

    success, _ = patch_file(file_path, patterns, "rvc/train/process/extract_model.py")
    return success


def patch_report(base_path: str) -> bool:
    """
    Patch tabs/report/report.py to use APPLIO_BASE_PATH for:
    - tabs/report/recorder.js
    - tabs/report/main.js
    - tabs/report/record_button.js
    """
    file_path = os.path.join(base_path, "tabs", "report", "report.py")

    patterns = [
        # recorder_js_path = os.path.join(now_dir, "tabs", "report", "recorder.js")
        (
            r'recorder_js_path\s*=\s*os\.path\.join\(now_dir,\s*"tabs",\s*"report",\s*"recorder\.js"\)',
            'recorder_js_path = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "report", "recorder.js")',
        ),
        # main_js_path = os.path.join(now_dir, "tabs", "report", "main.js")
        (
            r'main_js_path\s*=\s*os\.path\.join\(now_dir,\s*"tabs",\s*"report",\s*"main\.js"\)',
            'main_js_path = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "report", "main.js")',
        ),
        # record_button_js_path = os.path.join(now_dir, "tabs", "report", "record_button.js")
        (
            r'record_button_js_path\s*=\s*os\.path\.join\(now_dir,\s*"tabs",\s*"report",\s*"record_button\.js"\)',
            'record_button_js_path = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "report", "record_button.js")',
        ),
    ]

    success, _ = patch_file(file_path, patterns, "tabs/report/report.py")
    return success


def patch_plugins_core(base_path: str) -> bool:
    """
    Patch tabs/plugins/plugins_core.py to use APPLIO_BASE_PATH for:
    - tabs/plugins/installed
    - assets/config.json
    """
    file_path = os.path.join(base_path, "tabs", "plugins", "plugins_core.py")

    patterns = [
        # plugins_path = os.path.join(now_dir, "tabs", "plugins", "installed")
        (
            r'plugins_path\s*=\s*os\.path\.join\(now_dir,\s*"tabs",\s*"plugins",\s*"installed"\)',
            'plugins_path = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "plugins", "installed")',
        ),
        # json_file_path = os.path.join(now_dir, "assets", "config.json")
        (
            r'json_file_path\s*=\s*os\.path\.join\(now_dir,\s*"assets",\s*"config\.json"\)',
            'json_file_path = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
        ),
    ]

    success, _ = patch_file(file_path, patterns, "tabs/plugins/plugins_core.py")
    return success


def patch_settings_sections(base_path: str) -> bool:
    """
    Patch tabs/settings/sections/*.py files to use APPLIO_BASE_PATH for:
    - assets/config.json
    """
    sections_dir = os.path.join(base_path, "tabs", "settings", "sections")
    files_to_patch = ["filter.py", "presence.py", "lang.py", "precision.py", "model_author.py"]

    all_success = True

    for filename in files_to_patch:
        file_path = os.path.join(sections_dir, filename)

        patterns = [
            # config_file = os.path.join(now_dir, "assets", "config.json")
            (
                r'config_file\s*=\s*os\.path\.join\(now_dir,\s*"assets",\s*"config\.json"\)',
                'config_file = os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
            ),
            # os.path.join(now_dir, "assets", "config.json") inline
            (
                r'os\.path\.join\(now_dir,\s*"assets",\s*"config\.json"\)',
                'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
            ),
        ]

        success, _ = patch_file(file_path, patterns, f"tabs/settings/sections/{filename}")
        if not success:
            all_success = False

    return all_success


def patch_all(base_path: str) -> bool:
    """
    Apply all static resource patches.

    Args:
        base_path: Path to the source directory

    Returns:
        True if all patches succeeded, False otherwise
    """
    print(f"[patch_static_resources] Applying patches to {base_path}")
    print("-" * 60)

    results = []

    # Patch all files
    results.append(("assets/i18n/i18n.py", patch_i18n(base_path)))
    results.append(("assets/themes/loadThemes.py", patch_load_themes(base_path)))
    results.append(("assets/version_checker.py", patch_version_checker(base_path)))
    results.append(("app.py", patch_app_py(base_path)))
    results.append(("rvc/lib/utils.py", patch_rvc_lib_utils(base_path)))
    results.append(("rvc/train/process/extract_model.py", patch_extract_model(base_path)))
    results.append(("tabs/report/report.py", patch_report(base_path)))
    results.append(("tabs/plugins/plugins_core.py", patch_plugins_core(base_path)))
    results.append(("tabs/settings/sections/*.py", patch_settings_sections(base_path)))

    print("-" * 60)

    # Summary
    failed = [name for name, success in results if not success]
    if failed:
        print(f"[patch_static_resources] Failed to patch: {', '.join(failed)}")
        return False

    print("[patch_static_resources] All patches applied successfully")
    return True


if __name__ == "__main__":
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_all(base_path)
    sys.exit(0 if success else 1)
