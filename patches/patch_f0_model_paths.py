#!/usr/bin/env python3
"""
Patcher to fix F0 model paths for frozen app + multiprocessing issues.

Bug: F0 models (rmvpe.pt, fcpe.pt) use relative paths that don't
work in frozen app subprocess workers because CWD changes.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_f0_py(base_path: str) -> bool:
    """Patch rvc/lib/predictors/f0.py to use absolute model paths."""
    f0_py_path = os.path.join(base_path, "f0.py")

    if not os.path.exists(f0_py_path):
        print(f"[patch_f0_model_paths] f0.py not found at {f0_py_path}")
        return False

    with open(f0_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency check
    if "_F0_MODEL_PATH_PATCHED" in content:
        print(f"[patch_f0_model_paths] f0.py already patched")
        return True

    patched = False

    # Pattern 1: RMVPE model path (line 16)
    # Original: os.path.join("rvc", "models", "predictors", model_name)
    old_pattern1 = r'os\.path\.join\("rvc", "models", "predictors", model_name\)'
    new_code1 = r'_get_frozen_base_path("rvc", "models", "predictors", model_name)'

    if re.search(old_pattern1, content):
        content = re.sub(old_pattern1, new_code1, content)
        print(f"[patch_f0_model_paths] Fixed RMVPE model path resolution")
        patched = True

    # Pattern 2: FCPE model path (line 65)
    # Original: os.path.join("rvc", "models", "predictors", "fcpe.pt")
    old_pattern2 = r'os\.path\.join\("rvc", "models", "predictors", "fcpe\.pt"\)'
    new_code2 = r'_get_frozen_base_path("rvc", "models", "predictors", "fcpe.pt")'

    if re.search(old_pattern2, content):
        content = re.sub(old_pattern2, new_code2, content)
        print(f"[patch_f0_model_paths] Fixed FCPE model path resolution")
        patched = True

    if patched:
        # Add helper function at the beginning of the file
        # Uses FILE-BASED configuration (same pattern as patch_pretrained_selector.py)
        helper_func = '''import sys
import json
# Helper to get absolute path in frozen app using FILE-BASED configuration
def _get_frozen_base_path(*path_parts):
    """Get absolute path for model files using file-based path resolution.

    Uses runtime_paths.json for process-safe path resolution across
    multiprocessing spawn boundaries on macOS.
    """
    # In frozen app, try file-based configuration first (PROCESS-SAFE)
    if getattr(sys, "frozen", False):
        config_locations = [
            os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
            os.path.expanduser("~/.applio/runtime_paths.json"),
        ]
        for config_path in config_locations:
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)
                    base_path = config.get("data_path")
                    if base_path and os.path.exists(base_path):
                        return os.path.join(base_path, *path_parts)
                except (json.JSONDecodeError, IOError):
                    pass
        # Fallback: use app bundle Frameworks directory
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, *path_parts)
    # In source mode, use current working directory
    return os.path.join(os.getcwd(), *path_parts)


'''

        # Insert helper function after the imports (before first class)
        class_match = re.search(r'\nclass \w+:', content)
        if class_match:
            insert_pos = class_match.start()
            content = content[:insert_pos] + "\n" + helper_func + content[insert_pos:]

        # Add idempotency marker
        content = "# _F0_MODEL_PATH_PATCHED = True\n" + content

        with open(f0_py_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    print(f"[patch_f0_model_paths] No patterns found in f0.py")
    return False


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_f0_py(base_path)
    sys.exit(0 if success else 1)
