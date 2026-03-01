#!/usr/bin/env python3
"""
Patcher to fix pretrained_selector to use FILE-BASED configuration.

This uses the EXACT SAME pattern as patch_train_paths.py which has been
proven to work correctly in the frozen app.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_pretrained_selector(base_path: str) -> bool:
    """
    Patch pretrained_selector.py to use FILE-BASED path resolution.

    This follows the EXACT SAME pattern as train.py:_get_applio_logs_path()
    """
    selector_path = os.path.join(base_path, "pretrained_selector.py")

    if not os.path.exists(selector_path):
        print(f"[patch_pretrained_selector] pretrained_selector.py not found at {selector_path}")
        return False

    with open(selector_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if already patched (look for unique marker)
    if "_APPLIO_GET_DATA_PATH" in content:
        print(f"[patch_pretrained_selector] Already patched with file-based approach")
        return True

    # The new implementation - EXACT SAME PATTERN as train.py:_get_applio_logs_path()
    new_content = '''import os
import json

# Marker to detect if patch was applied
_APPLIO_GET_DATA_PATH = True


def _get_data_path():
    """Get data path using FILE-BASED configuration (process-safe).

    This uses the EXACT SAME pattern as train.py:_get_applio_logs_path()
    which has been proven to work across all process boundaries.
    """
    # === Try file-based configuration (PROCESS-SAFE) ===
    config_locations = [
        os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
        os.path.expanduser("~/.applio/runtime_paths.json"),
    ]

    for config_path in config_locations:
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                logs_path = config.get("logs_path")
                if logs_path:
                    parent_dir = os.path.dirname(logs_path)
                    if os.path.exists(parent_dir):
                        result = os.path.dirname(logs_path)  # Return data_path (parent of logs)
                        with open("/tmp/applio_debug.txt", "a") as _df:
                            _df.write(f"=== _get_data_path (pretrained_selector): using config file: {result}\\n")
                        return result
            except (json.JSONDecodeError, IOError, KeyError):
                pass

    # === Try environment variable ===
    env_path = os.environ.get("APPLIO_DATA_PATH")
    if env_path and os.path.exists(env_path):
        with open("/tmp/applio_debug.txt", "a") as _df:
            _df.write(f"=== _get_data_path (pretrained_selector): using env var: {env_path}\\n")
        return env_path

    # === Try known data locations ===
    known_paths = [
        os.path.expanduser("~/Applio"),
        os.path.expanduser("~/Library/Application Support/Applio/data"),
    ]

    for path in known_paths:
        if os.path.exists(path):
            with open("/tmp/applio_debug.txt", "a") as _df:
                _df.write(f"=== _get_data_path (pretrained_selector): using known path: {path}\\n")
            return path

    # === Last resort: use CWD ===
    cwd = os.getcwd()
    with open("/tmp/applio_debug.txt", "a") as _df:
        _df.write(f"=== _get_data_path (pretrained_selector): fallback to CWD: {cwd}\\n")
    return cwd


def pretrained_selector(vocoder, sample_rate):
    """Select pretrained model paths for the given vocoder and sample rate.

    Returns absolute paths to the pretrained G and D model files.
    Returns ("", "") if files don't exist.
    """
    data_path = _get_data_path()
    vocoder_path = os.path.join(data_path, "rvc", "models", "pretraineds", f"{vocoder.lower()}")

    path_g = os.path.join(vocoder_path, f"f0G{str(sample_rate)[:2]}k.pth")
    path_d = os.path.join(vocoder_path, f"f0D{str(sample_rate)[:2]}k.pth")

    # Debug output
    with open("/tmp/applio_debug.txt", "a") as _df:
        _df.write(f"=== pretrained_selector({vocoder}, {sample_rate}) ===\\n")
        _df.write(f"  data_path={data_path}\\n")
        _df.write(f"  vocoder_path={vocoder_path}\\n")
        _df.write(f"  path_g={path_g}, exists={os.path.exists(path_g)}\\n")
        _df.write(f"  path_d={path_d}, exists={os.path.exists(path_d)}\\n")

    if os.path.exists(path_g) and os.path.exists(path_d):
        return path_g, path_d
    else:
        return "", ""
'''

    with open(selector_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[patch_pretrained_selector] Applied file-based patch to pretrained_selector.py")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_pretrained_selector(base_path)
    sys.exit(0 if success else 1)
