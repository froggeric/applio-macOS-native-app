#!/usr/bin/env python3
"""
Patcher to add subprocess return code checking and output validation to core.py.

This patcher addresses a training failure issue where preprocessing produced no
output (empty dataset path), but this wasn't detected. The patches add:

1. Return code checking for subprocess calls
2. Validation that preprocessing produced output (model_info.json with total_seconds > 0)
3. Validation that feature extraction produced output (extracted/ directory not empty)
4. Validation that preprocessing was done before allowing training

Applied at build time by build_macos.py.
"""

import os
import re


def patch_run_preprocess_script(content: str) -> tuple[str, bool]:
    """
    Patch run_preprocess_script to check return code and validate model_info.json.

    Args:
        content: The content of core.py

    Returns:
        Tuple of (patched_content, success)
    """
    # Pattern to find the subprocess.run call and return statement
    old_pattern = r'subprocess\.run\(command\)\n(    return f"Model \{model_name\} preprocessed successfully\.")'

    # Check if already patched
    if "Validate preprocessing output" in content:
        return content, True  # Already patched

    # Check if pattern exists
    if not re.search(old_pattern, content):
        print("[patch_subprocess_validation] preprocess pattern not found - may already be patched")
        return content, True

    # Replacement code that checks return code and validates output
    replacement = r'''result = subprocess.run(command)
    if result.returncode != 0:
        return f"Error: Preprocessing failed with code {result.returncode}"

    # Validate preprocessing output
    model_dir = os.path.join(logs_path, model_name)
    model_info_path = os.path.join(model_dir, "model_info.json")

    if not os.path.exists(model_info_path):
        raise RuntimeError(
            f"Preprocessing failed: model_info.json not found at {model_info_path}. "
            f"Check that the dataset path '{dataset_path}' contains valid audio files."
        )

    try:
        with open(model_info_path, "r", encoding="utf-8") as f:
            model_info = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise RuntimeError(f"Preprocessing failed: could not read model_info.json: {e}")

    total_seconds = model_info.get("total_seconds", 0)
    if total_seconds <= 0:
        raise RuntimeError(
            f"Preprocessing failed: no audio data was processed (total_seconds={total_seconds}). "
            f"Check that the dataset path '{dataset_path}' contains valid audio files."
        )

\1'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def patch_run_extract_script(content: str) -> tuple[str, bool]:
    """
    Patch run_extract_script to check return code and validate extracted/ directory.

    Args:
        content: The content of core.py

    Returns:
        Tuple of (patched_content, success)
    """
    # Pattern to find the subprocess.run call and return statement
    old_pattern = r'subprocess\.run\(command_1\)\n\n(    return f"Model \{model_name\} extracted successfully\.")'

    # Check if already patched
    if "Validate extraction output" in content:
        return content, True  # Already patched

    # Check if pattern exists
    if not re.search(old_pattern, content):
        print("[patch_subprocess_validation] extract pattern not found - may already be patched")
        return content, True

    # Replacement code that checks return code and validates extracted directory
    replacement = r'''result = subprocess.run(command_1)
    if result.returncode != 0:
        return f"Error: Feature extraction failed with code {result.returncode}"

    # Validate extraction output
    extracted_dir = os.path.join(model_path, "extracted")
    if not os.path.exists(extracted_dir):
        raise RuntimeError(
            f"Feature extraction failed: extracted directory not found at {extracted_dir}. "
            f"Ensure preprocessing was completed successfully before running extraction."
        )

    # Check that extracted directory is not empty
    extracted_files = os.listdir(extracted_dir)
    if not extracted_files:
        raise RuntimeError(
            f"Feature extraction failed: extracted directory is empty at {extracted_dir}. "
            f"Ensure preprocessing was completed successfully before running extraction."
        )

\1'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def patch_run_train_script(content: str) -> tuple[str, bool]:
    """
    Patch run_train_script to validate preprocessing was done before training.

    Args:
        content: The content of core.py

    Returns:
        Tuple of (patched_content, success)
    """
    # Pattern to find where pg, pd are set and train_script_path begins
    insert_pattern = r'(pg, pd = "", ""\n\n)(    train_script_path = os\.path\.join)'

    # Check if already patched
    if "Validate preprocessing before training" in content:
        return content, True  # Already patched

    # Check if pattern exists
    if not re.search(insert_pattern, content):
        print("[patch_subprocess_validation] train pattern not found - may already be patched")
        return content, True

    # Validation code to insert
    validation_code = '''    # Validate preprocessing before training
    model_dir = os.path.join(logs_path, model_name)
    model_info_path = os.path.join(model_dir, "model_info.json")

    if not os.path.exists(model_info_path):
        raise RuntimeError(
            f"Training failed: preprocessing not found. "
            f"Run preprocessing first for model '{model_name}'."
        )

    try:
        with open(model_info_path, "r", encoding="utf-8") as f:
            model_info = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise RuntimeError(f"Training failed: could not read model_info.json: {e}")

    total_seconds = model_info.get("total_seconds", 0)
    if total_seconds <= 0:
        raise RuntimeError(
            f"Training failed: no audio data was preprocessed (total_seconds={total_seconds}). "
            f"Re-run preprocessing with a valid dataset."
        )

    extracted_dir = os.path.join(model_dir, "extracted")
    if not os.path.exists(extracted_dir):
        raise RuntimeError(
            f"Training failed: feature extraction not found. "
            f"Run feature extraction first for model '{model_name}'."
        )

    extracted_files = os.listdir(extracted_dir)
    if not extracted_files:
        raise RuntimeError(
            f"Training failed: extracted directory is empty. "
            f"Re-run feature extraction for model '{model_name}'."
        )

'''

    # Insert validation code between pg, pd assignment and train_script_path
    replacement = r'\1' + validation_code + r'\2'

    new_content = re.sub(insert_pattern, replacement, content)
    return new_content, True


def patch_core_py(base_path: str) -> bool:
    """
    Apply all subprocess validation patches to core.py.

    Args:
        base_path: Path to the source directory containing core.py

    Returns:
        True if patching succeeded, False otherwise
    """
    core_py_path = os.path.join(base_path, "core.py")

    if not os.path.exists(core_py_path):
        print(f"[patch_subprocess_validation] core.py not found at {core_py_path}")
        return False

    try:
        with open(core_py_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[patch_subprocess_validation] Error reading core.py: {e}")
        return False

    original_content = content

    # Apply all patches
    content, success = patch_run_preprocess_script(content)
    if not success:
        print("[patch_subprocess_validation] Failed to patch run_preprocess_script")
        return False

    content, success = patch_run_extract_script(content)
    if not success:
        print("[patch_subprocess_validation] Failed to patch run_extract_script")
        return False

    content, success = patch_run_train_script(content)
    if not success:
        print("[patch_subprocess_validation] Failed to patch run_train_script")
        return False

    # Check if any changes were made
    if content == original_content:
        print("[patch_subprocess_validation] No changes needed - all patches already applied")
        return True

    try:
        with open(core_py_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[patch_subprocess_validation] Error writing core.py: {e}")
        return False

    print("[patch_subprocess_validation] Patched core.py with subprocess validation")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_core_py(base_path)
    sys.exit(0 if success else 1)
