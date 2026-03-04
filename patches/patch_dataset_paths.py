#!/usr/bin/env python3
"""
Patcher to fix dataset path handling - always use absolute paths.

Bug: Dataset paths were being stored/returned as relative paths,
causing preprocessing to fail when CWD differs from now_dir.

Root causes:
1. get_datasets_list() returns relative paths when not frozen
2. save_drop_dataset_audio() returns relative path
3. run_preprocess_script() builds command before resolving path

Applied at build time by build_macos.py.
"""

import os
import re
import sys


def patch_train_py(base_path: str) -> bool:
    """Patch tabs/train/train.py to always return absolute paths."""
    train_py_path = os.path.join(base_path, "tabs", "train", "train.py")

    if not os.path.exists(train_py_path):
        print(f"[patch_dataset_paths] train.py not found at {train_py_path}")
        return False

    with open(train_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency check
    if "_DATASET_PATH_ABSOLUTE_PATCHED" in content:
        print(f"[patch_dataset_paths] train.py already patched")
        return True

    patched = False

    # Fix 1: get_datasets_list() - always return absolute paths
    # Original (lines 102-104):
    #     if is_frozen:
    #         datasets.append(os.path.abspath(dirpath))
    #     else:
    #         datasets.append(dirpath)
    #
    # Patched: Always use absolute path
    old_pattern1 = r'(if is_frozen:\s*\n\s*# In frozen app, return absolute path\s*\n\s*datasets\.append\(os\.path\.abspath\(dirpath\)\)\s*\n\s*else:\s*\n\s*# In source run, return relative path \(existing behavior\)\s*\n\s*)datasets\.append\(dirpath\)'

    if re.search(old_pattern1, content):
        content = re.sub(old_pattern1, r'\1datasets.append(os.path.abspath(dirpath))  # Always use absolute path', content)
        print(f"[patch_dataset_paths] Fixed get_datasets_list() to always return absolute paths")
        patched = True
    else:
        # Try simpler pattern as fallback
        simple_pattern = r'datasets\.append\(dirpath\)\s*\n\s*#\s*In source run'
        if re.search(simple_pattern, content):
            # Find the else block and replace the relative path append
            content = re.sub(
                r'(else:\s*\n\s*# In source run, return relative path.*?\n\s*)datasets\.append\(dirpath\)',
                r'\1datasets.append(os.path.abspath(dirpath))  # Always use absolute path',
                content,
                flags=re.DOTALL
            )
            print(f"[patch_dataset_paths] Fixed get_datasets_list() (fallback pattern)")
            patched = True

    # Fix 2: save_drop_dataset_audio() - return absolute path instead of relative
    # Original (lines 197-200):
    #     dataset_path = os.path.dirname(destination_path)
    #     relative_dataset_path = os.path.relpath(dataset_path, now_dir)
    #     return None, relative_dataset_path
    #
    # Patched: Return absolute path directly
    old_pattern2 = r'dataset_path = os\.path\.dirname\(destination_path\)\s*\n\s*relative_dataset_path = os\.path\.relpath\(dataset_path,\s*now_dir\)\s*\n\s*return None,\s*relative_dataset_path'

    new_code2 = '''dataset_path = os.path.dirname(destination_path)
            # Return absolute path to fix subprocess resolution
            return None, dataset_path'''

    if re.search(old_pattern2, content):
        content = re.sub(old_pattern2, new_code2, content)
        print(f"[patch_dataset_paths] Fixed save_drop_dataset_audio() to return absolute path")
        patched = True

    if patched:
        # Add idempotency marker at top of file
        content = "# _DATASET_PATH_ABSOLUTE_PATCHED = True\n" + content
        with open(train_py_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    print(f"[patch_dataset_paths] No patterns found in train.py")
    return False


def patch_core_py(base_path: str) -> bool:
    """Patch core.py to resolve dataset_path before building command.

    The issue: command list is built with dataset_path, then later
    there's a check that resolves to absolute path, but the command
    already has the relative path baked in.

    Fix: Resolve to absolute path BEFORE building the command list.
    """
    core_py_path = os.path.join(base_path, "core.py")

    if not os.path.exists(core_py_path):
        print(f"[patch_dataset_paths] core.py not found at {core_py_path}")
        return False

    with open(core_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency check
    if "_DATASET_PATH_RESOLVE_PATCHED" in content:
        print(f"[patch_dataset_paths] core.py already patched")
        return True

    # Find run_preprocess_script function
    if "def run_preprocess_script(" not in content:
        print(f"[patch_dataset_paths] run_preprocess_script not found in core.py")
        return False

    # Look for the pattern where command is built
    # We need to insert path resolution BEFORE command construction
    # Pattern: preprocess_script_path = ... followed by command = [...]

    # Find the position right before "command = ["
    match = re.search(
        r'(preprocess_script_path = os\.path\.join\("rvc", "train", "preprocess", "preprocess\.py"\)\s*\n)(    command = \[)',
        content
    )

    if match:
        insert_pos = match.start(2)  # Position of "command = ["

        path_resolution = '''    # CRITICAL: Resolve to absolute path BEFORE building command
    # Fixes bug where relative paths failed in subprocess with different CWD
    if dataset_path and not os.path.isabs(dataset_path):
        abs_path = os.path.abspath(dataset_path)
        if os.path.exists(abs_path):
            dataset_path = abs_path

'''

        new_content = content[:insert_pos] + path_resolution + content[insert_pos:]

        # Add idempotency marker at top of file
        new_content = "# _DATASET_PATH_RESOLVE_PATCHED = True\n" + new_content

        with open(core_py_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        print(f"[patch_dataset_paths] Fixed core.py to resolve path before command construction")
        return True

    print(f"[patch_dataset_paths] Could not find expected pattern in core.py")
    return False


if __name__ == "__main__":
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success1 = patch_train_py(base_path)
    success2 = patch_core_py(base_path)

    if success1 or success2:
        print(f"[patch_dataset_paths] Patch applied successfully")
        sys.exit(0)
    else:
        print(f"[patch_dataset_paths] No patches applied")
        sys.exit(1)
