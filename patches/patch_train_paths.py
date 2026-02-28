#!/usr/bin/env python3
"""
Patcher to redirect training paths using FILE-BASED configuration.

This is required because PyTorch training uses torch.multiprocessing.spawn
which creates NEW processes that:
1. Don't go through the wrapper's subprocess detection
2. Don't inherit environment variables (macOS spawn mode)
3. Use default CWD instead of the wrapper's changed CWD

Applied at build time by build_macos.py.
"""

import os
import re


def patch_train_py(base_path: str) -> bool:
    """
    Patch rvc/train/train.py to use file-based path resolution.

    Args:
        base_path: Path to the directory containing train.py (rvc/train/)
    """
    train_py_path = os.path.join(base_path, "train.py")

    if not os.path.exists(train_py_path):
        print(f"[patch_train_paths] train.py not found at {train_py_path}")
        return False

    with open(train_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if already patched
    if "_get_applio_logs_path" in content:
        print(f"[patch_train_paths] Already patched")
        return True

    # Pattern: current_dir = os.getcwd()
    original_pattern = "current_dir = os.getcwd()"

    if original_pattern not in content:
        print(f"[patch_train_paths] Pattern 'current_dir = os.getcwd()' not found")
        return False

    # Replacement: file-based path resolution function
    path_resolution_code = '''def _get_applio_logs_path():
    """Get logs path using FILE-BASED configuration (process-safe).

    This works across all process boundaries including PyTorch multiprocessing.
    """
    import os
    import json

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
                            _df.write(f"=== _get_applio_logs_path (train.py): using config file: {result}\\n")
                        return result
            except (json.JSONDecodeError, IOError, KeyError):
                pass

    # === Try environment variable ===
    env_path = os.environ.get("APPLIO_DATA_PATH")
    if env_path and os.path.exists(env_path):
        with open("/tmp/applio_debug.txt", "a") as _df:
            _df.write(f"=== _get_applio_logs_path (train.py): using env var: {env_path}\\n")
        return env_path

    # === Try known data locations ===
    known_paths = [
        os.path.expanduser("~/Applio"),
        os.path.expanduser("~/Library/Application Support/Applio/data"),
    ]

    for path in known_paths:
        if os.path.exists(path):
            with open("/tmp/applio_debug.txt", "a") as _df:
                _df.write(f"=== _get_applio_logs_path (train.py): using known path: {path}\\n")
            return path

    # === Last resort: use CWD ===
    cwd = os.getcwd()
    with open("/tmp/applio_debug.txt", "a") as _df:
        _df.write(f"=== _get_applio_logs_path (train.py): fallback to CWD: {cwd}\\n")
    return cwd

current_dir = _get_applio_logs_path()'''

    new_content = content.replace(original_pattern, path_resolution_code)

    with open(train_py_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[patch_train_paths] Applied file-based patch to rvc/train/train.py")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_train_py(base_path)
    sys.exit(0 if success else 1)
