#!/usr/bin/env python3
"""
Patcher to redirect logs_path using FILE-BASED configuration.

This approach is PROCESS-SAFE: works across all subprocess boundaries
because it reads from a file instead of relying on environment variables.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_core_py(base_path: str) -> bool:
    """
    Patch core.py to use file-based logs_path resolution.
    """
    core_py_path = os.path.join(base_path, "core.py")

    if not os.path.exists(core_py_path):
        print(f"[patch_data_paths] core.py not found at {core_py_path}")
        return False

    with open(core_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if already patched with file-based approach
    if "_APPLIO_RUNTIME_CONFIG" in content:
        print(f"[patch_data_paths] Already patched with file-based approach")
        return True

    # Pattern 1: Original upstream code
    original_pattern1 = 'logs_path = os.path.join(current_script_directory, "logs")'

    # Pattern 2: Previous lazy-evaluated patch
    if "_get_logs_path()" in content:
        # Already has lazy evaluation, need to replace the function body
        old_function_pattern = r'def _get_logs_path\(\):.*?return result\n'
        new_function = '''def _get_logs_path():
    """Get logs path using FILE-BASED configuration (process-safe)."""
    import os
    import json

    # === Try environment variable first (backward compatibility) ===
    env_path = os.environ.get("APPLIO_LOGS_PATH")
    if env_path:
        parent_dir = os.path.dirname(env_path)
        if os.path.exists(parent_dir):
            return env_path

    # === Try file-based configuration (PROCESS-SAFE) ===
    # This works across all process boundaries
    config_locations = [
        # Primary: Application Support directory
        os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
        # Fallback: Hidden directory in home
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
                        return logs_path
            except (json.JSONDecodeError, IOError, KeyError):
                pass

    # === Try known data locations ===
    known_data_paths = [
        os.environ.get("APPLIO_DATA_PATH"),
        os.path.expanduser("~/Applio"),
        os.path.expanduser("~/Library/Application Support/Applio/data"),
    ]

    for data_path in known_data_paths:
        if data_path:
            logs_path = os.path.join(data_path, "logs")
            if os.path.exists(data_path):
                return logs_path

    # === Last resort: use CWD ===
    return os.path.join(os.getcwd(), "logs")

'''
        # Check if function exists
        if re.search(old_function_pattern, content, re.DOTALL):
            new_content = re.sub(old_function_pattern, new_function, content, flags=re.DOTALL)
            with open(core_py_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"[patch_data_paths] Updated _get_logs_path() to file-based approach")
            return True
        else:
            print(f"[patch_data_paths] Found _get_logs_path but pattern doesn't match")
            # Try to find and replace just the function
            pattern = r'(def _get_logs_path\(\):.*?)(logs_path = _get_logs_path\(\))'
            match = re.search(pattern, content, re.DOTALL)
            if match:
                new_content = content[:match.start(1)] + new_function + content[match.start(2):]
                with open(core_py_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"[patch_data_paths] Replaced _get_logs_path function")
                return True

    # Pattern matching for original code
    if original_pattern1 in content:
        lazy_logs_code = '''# DEBUG: Confirm core.py is being loaded
with open("/tmp/applio_debug.txt", "a") as _f:
    _f.write("=== CORE.PY IS BEING LOADED ===\\n")
    _f.write(f"__file__={__file__}\\n")

_APPLIO_RUNTIME_CONFIG = None

def _get_logs_path():
    """Get logs path using FILE-BASED configuration (process-safe)."""
    import os
    import json
    global _APPLIO_RUNTIME_CONFIG

    # === Try environment variable first (backward compatibility) ===
    env_path = os.environ.get("APPLIO_LOGS_PATH")
    if env_path:
        parent_dir = os.path.dirname(env_path)
        if os.path.exists(parent_dir):
            with open("/tmp/applio_debug.txt", "a") as _df:
                _df.write(f"=== _get_logs_path: using env var: {env_path}\\n")
            return env_path

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
                        with open("/tmp/applio_debug.txt", "a") as _df:
                            _df.write(f"=== _get_logs_path: using config file: {logs_path}\\n")
                        return logs_path
            except (json.JSONDecodeError, IOError, KeyError):
                pass

    # === Try known data locations ===
    known_data_paths = [
        os.environ.get("APPLIO_DATA_PATH"),
        os.path.expanduser("~/Applio"),
    ]

    for data_path in known_data_paths:
        if data_path:
            logs_path = os.path.join(data_path, "logs")
            if os.path.exists(data_path):
                with open("/tmp/applio_debug.txt", "a") as _df:
                    _df.write(f"=== _get_logs_path: using known path: {logs_path}\\n")
                return logs_path

    # === Last resort: use CWD ===
    cwd = os.getcwd()
    result = os.path.join(cwd, "logs")
    with open("/tmp/applio_debug.txt", "a") as _df:
        _df.write(f"=== _get_logs_path: fallback to CWD: {result}\\n")
        _df.write(f"APPLIO_LOGS_PATH env={os.environ.get('APPLIO_LOGS_PATH')}\\n")
        _df.write(f"config files checked: {config_locations}\\n")
    return result

logs_path = _get_logs_path()
'''
        new_content = content.replace(original_pattern1, lazy_logs_code)
        with open(core_py_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"[patch_data_paths] Applied file-based patch to core.py")
        return True

    print(f"[patch_data_paths] No known pattern found in core.py")
    return False


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_core_py(base_path)
    sys.exit(0 if success else 1)
