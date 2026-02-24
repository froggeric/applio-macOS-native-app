#!/usr/bin/env python3
"""
Patcher to redirect logs_path from __file__-based to now_dir-based.

This allows training data to be stored in user's external data location
instead of inside the app bundle.

Applied at build time by build_macos.py.
"""

import os


def patch_core_py(base_path: str) -> bool:
    """
    Patch core.py to use now_dir instead of current_script_directory for logs_path.

    Args:
        base_path: Path to the source directory containing core.py

    Returns:
        True if patching succeeded, False otherwise
    """
    core_py_path = os.path.join(base_path, "core.py")

    if not os.path.exists(core_py_path):
        print(f"[patch_data_paths] core.py not found at {core_py_path}")
        return False

    with open(core_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # The original line uses current_script_directory
    original = 'logs_path = os.path.join(current_script_directory, "logs")'
    patched = 'logs_path = os.path.join(now_dir, "logs")'

    if original not in content:
        print(f"[patch_data_paths] Pattern not found - may already be patched")
        return True  # Assume already patched

    if patched in content:
        print(f"[patch_data_paths] Already patched")
        return True

    new_content = content.replace(original, patched)

    with open(core_py_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[patch_data_paths] Patched logs_path in core.py")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_core_py(base_path)
    sys.exit(0 if success else 1)
