#!/usr/bin/env python3
"""
Patcher to add pre-flight dataset path validation in core.py.

Checks if dataset path exists BEFORE launching subprocess.
Provides immediate feedback in UI rather than waiting for subprocess to fail.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_run_preprocess_script(content: str) -> tuple[str, bool]:
    """
    Add pre-flight validation before subprocess.run in run_preprocess_script.

    Args:
        content: The content of core.py

    Returns:
        Tuple of (patched_content, success)
    """
    # Idempotency marker
    if "# Pre-flight: validate dataset path" in content:
        return content, True  # Already patched

    # Pattern to find the end of command list and subprocess.run call
    # Matches: ]
    #         subprocess.run(command)
    pattern = r'(\s+\]\s*\n)(\s+)(subprocess\.run\(command\))'

    if not re.search(pattern, content):
        print("[patch_preflight_validation] Pattern not found - code may have been modified")
        return content, False

    # Insert validation before subprocess.run
    # \1 = ]\n
    # \2 = indentation before subprocess.run
    # \3 = subprocess.run(command)
    validation_code = r'''\1\2# Pre-flight: validate dataset path exists
\2if not os.path.exists(dataset_path):
\2    abs_path = os.path.abspath(dataset_path)
\2    if os.path.exists(abs_path):
\2        dataset_path = abs_path
\2    else:
\2        return f"Error: Dataset path does not exist: {dataset_path}. Use an absolute path to your dataset folder."

\2\3'''

    new_content = re.sub(pattern, validation_code, content, count=1)
    return new_content, True


def patch_core_py(base_path: str) -> bool:
    """
    Apply pre-flight validation patch to core.py.

    Args:
        base_path: Path to the directory containing core.py

    Returns:
        True if patching succeeded
    """
    core_py_path = os.path.join(base_path, "core.py")

    if not os.path.exists(core_py_path):
        print(f"[patch_preflight_validation] core.py not found at {core_py_path}")
        return False

    try:
        with open(core_py_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[patch_preflight_validation] Error reading core.py: {e}")
        return False

    original_content = content
    content, success = patch_run_preprocess_script(content)

    if not success:
        return False

    if content == original_content:
        print("[patch_preflight_validation] No changes needed - already patched")
        return True

    try:
        with open(core_py_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[patch_preflight_validation] Error writing core.py: {e}")
        return False

    print("[patch_preflight_validation] Added pre-flight validation to core.py")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_core_py(base_path)
    sys.exit(0 if success else 1)
