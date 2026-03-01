#!/usr/bin/env python3
"""
Patcher to resolve custom pretrained paths to absolute paths in core.py.

When custom_pretrained=True, the paths g_pretrained_path and d_pretrained_path
come from the Gradio UI as relative paths (e.g., rvc/models/pretraineds/custom/...).
These need to be resolved to absolute paths based on the data_path before being
passed to the training subprocess.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_core_py(base_path: str) -> bool:
    """
    Patch core.py to resolve custom pretrained paths to absolute paths.
    """
    core_py_path = os.path.join(base_path, "core.py")

    if not os.path.exists(core_py_path):
        print(f"[patch_custom_pretrained_paths] core.py not found at {core_py_path}")
        return False

    with open(core_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if already patched
    if "_resolve_custom_pretrained_path" in content:
        print(f"[patch_custom_pretrained_paths] Already patched")
        return True

    # Pattern to find: pg, pd = g_pretrained_path, d_pretrained_path
    old_pattern = r'pg, pd = g_pretrained_path, d_pretrained_path'

    if old_pattern not in content:
        print(f"[patch_custom_pretrained_paths] Pattern not found in core.py")
        return False

    # Helper function to add
    helper_function = '''
def _resolve_custom_pretrained_path(path: str) -> str:
    """Resolve custom pretrained path to absolute path.

    The UI may return relative paths (rvc/models/...) which need to be
    resolved relative to the data_path, not CWD.
    """
    if not path:
        return path

    # Already absolute
    if os.path.isabs(path):
        return path

    # Try file-based configuration first
    config_locations = [
        os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
        os.path.expanduser("~/.applio/runtime_paths.json"),
    ]

    for config_path in config_locations:
        if os.path.exists(config_path):
            try:
                import json
                with open(config_path, "r") as f:
                    config = json.load(f)
                logs_path = config.get("logs_path")
                if logs_path:
                    data_path = os.path.dirname(logs_path)
                    abs_path = os.path.join(data_path, path)
                    if os.path.exists(abs_path):
                        return abs_path
            except (json.JSONDecodeError, IOError, KeyError):
                pass

    # Try environment variable
    env_data_path = os.environ.get("APPLIO_DATA_PATH")
    if env_data_path:
        abs_path = os.path.join(env_data_path, path)
        if os.path.exists(abs_path):
            return abs_path

    # Try known data locations
    known_paths = [
        os.path.expanduser("~/Applio"),
        os.path.expanduser("~/Library/Application Support/Applio/data"),
    ]

    for data_path in known_paths:
        if os.path.exists(data_path):
            abs_path = os.path.join(data_path, path)
            if os.path.exists(abs_path):
                return abs_path

    # Fallback: return path as-is (may fail, but at least we tried)
    return path

'''

    # Find a good insertion point (after imports, before first function)
    # Look for the first function definition
    insert_pattern = r'(from functools import lru_cache\n)'
    if insert_pattern not in content:
        insert_pattern = r'(from distutils.util import strtobool\n)'

    if insert_pattern in content:
        content = content.replace(insert_pattern, insert_pattern + '\n' + helper_function)
    else:
        # Last resort: insert after the initial imports block
        lines = content.split('\n')
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('from ') or line.startswith('import '):
                insert_idx = i + 1
            elif insert_idx > 0 and line.strip() and not line.startswith('#'):
                break
        lines.insert(insert_idx, helper_function)
        content = '\n'.join(lines)

    # Replace the direct assignment with resolved paths
    new_code = '''pg, pd = _resolve_custom_pretrained_path(g_pretrained_path), _resolve_custom_pretrained_path(d_pretrained_path)'''

    content = content.replace(old_pattern, new_code)

    with open(core_py_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[patch_custom_pretrained_paths] Applied custom pretrained path resolution")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_core_py(base_path)
    sys.exit(0 if success else 1)
