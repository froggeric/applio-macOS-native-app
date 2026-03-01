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
import shutil


def patch_run_preprocess_script(content: str) -> tuple[str, bool]:
    """
    Patch run_preprocess_script to check return code and validate model_info.json.

    Args:
        content: The content of core.py

    Returns:
        Tuple of (patched_content, success)
    """
    # Idempotency marker - must match the comment in injected code
    idempotency_marker = "# Validate output was produced"

    # Pattern to find the subprocess.run call and return statement
    # Use \s* for flexible whitespace handling
    old_pattern = r'subprocess\.run\(command\)\s*\n(\s*)return f"Model \{model_name\} preprocessed successfully\."'

    # Check if already patched by looking for our idempotency marker
    if idempotency_marker in content:
        return content, True  # Already patched

    # Check if pattern exists
    if not re.search(old_pattern, content):
        print("[patch_subprocess_validation] preprocess pattern not found - code may have been modified")
        return content, False

    # Replacement code that checks return code and validates output
    # Note: The idempotency marker "# Validate output was produced" must match the check above
    replacement = r'''result = subprocess.run(command)
\1if result.returncode != 0:
\1    return f"Error: Preprocessing failed with code {result.returncode}"

\1# Validate output was produced
\1model_dir = os.path.join(logs_path, model_name)
\1model_info_path = os.path.join(model_dir, "model_info.json")

\1if not os.path.exists(model_info_path):
\1    return f"Error: model_info.json not found at {model_info_path}. Check that the dataset path '{dataset_path}' contains valid audio files."

\1try:
\1    with open(model_info_path, "r", encoding="utf-8") as f:
\1        model_info = json.load(f)
\1except (json.JSONDecodeError, IOError) as e:
\1    return f"Error: could not read model_info.json: {e}."

\1total_seconds = model_info.get("total_seconds", 0)
\1if total_seconds <= 0:
\1    return f"Error: no audio data was processed (total_seconds={total_seconds}). Check that the dataset path '{dataset_path}' contains valid audio files (WAV, MP3, FLAC, OGG)."

\1return f"Model {model_name} preprocessed successfully."'''

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
    # Idempotency marker - must match the comment in injected code
    idempotency_marker = "# Validate extracted files exist"

    # Pattern to find the subprocess.run call and return statement
    # Use \s* for flexible whitespace handling
    old_pattern = r'subprocess\.run\(command_1\)\s*\n\s*\n(\s*)return f"Model \{model_name\} extracted successfully\."'

    # Check if already patched by looking for our idempotency marker
    if idempotency_marker in content:
        return content, True  # Already patched

    # Check if pattern exists
    if not re.search(old_pattern, content):
        print("[patch_subprocess_validation] extract pattern not found - code may have been modified")
        return content, False

    # Replacement code that checks return code and validates extracted directory
    # Note: The idempotency marker "# Validate extracted files exist" must match the check above
    replacement = r'''result = subprocess.run(command_1)
\1if result.returncode != 0:
\1    return f"Error: Feature extraction failed with code {result.returncode}"

\1# Validate extracted files exist
\1extracted_dir = os.path.join(model_path, "extracted")
\1if not os.path.exists(extracted_dir):
\1    return f"Error: extracted directory not found at {extracted_dir}. Run preprocessing first to generate audio data for extraction."

\1# Check that extracted directory is not empty
\1extracted_files = os.listdir(extracted_dir)
\1if not extracted_files:
\1    return f"Error: extracted directory is empty at {extracted_dir}. Preprocessing may have failed - try re-running it."

\1return f"Model {model_name} extracted successfully."'''

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
    # Idempotency marker - must match the comment in injected code
    idempotency_marker = "# Validate preprocessing and extraction before training"

    # Pattern to find where pg, pd are set and train_script_path begins
    # Use \s* for flexible whitespace handling
    insert_pattern = r'(pg, pd = "", ""\s*\n\s*\n)(\s*)train_script_path = os\.path\.join'

    # Check if already patched by looking for our idempotency marker
    if idempotency_marker in content:
        return content, True  # Already patched

    # Check if pattern exists
    if not re.search(insert_pattern, content):
        print("[patch_subprocess_validation] train pattern not found - code may have been modified")
        return content, False

    # Validation code to insert
    # Note: The idempotency marker "# Validate preprocessing and extraction before training" must match the check above
    # Use the captured indentation (\2) to maintain consistent formatting
    validation_code = r'''\2# Validate preprocessing and extraction before training
\2model_dir = os.path.join(logs_path, model_name)
\2model_info_path = os.path.join(model_dir, "model_info.json")

\2if not os.path.exists(model_info_path):
\2    return f"Error: preprocessing not found. Run preprocessing first for model '{model_name}'."

\2try:
\2    with open(model_info_path, "r", encoding="utf-8") as f:
\2        model_info = json.load(f)
\2except (json.JSONDecodeError, IOError) as e:
\2    return f"Error: could not read model_info.json: {e}."

\2total_seconds = model_info.get("total_seconds", 0)
\2if total_seconds <= 0:
\2    return f"Error: no audio data was preprocessed (total_seconds={total_seconds}). Re-run preprocessing with a valid dataset."

\2extracted_dir = os.path.join(model_dir, "extracted")
\2if not os.path.exists(extracted_dir):
\2    return f"Error: feature extraction not found. Run feature extraction first for model '{model_name}'."

\2extracted_files = os.listdir(extracted_dir)
\2if not extracted_files:
\2    return f"Error: extracted directory is empty. Re-run feature extraction for model '{model_name}'."

'''

    # Insert validation code between pg, pd assignment and train_script_path
    # Note: validation_code ends with just a newline, so we add \2 (indentation) before train_script_path
    replacement = r'\1' + validation_code + r'\2train_script_path = os.path.join'

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
    backup_path = core_py_path + ".bak"

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
    patches_applied = []
    patches_skipped = []

    # Apply all patches
    for patch_func, patch_name in [
        (patch_run_preprocess_script, "run_preprocess_script"),
        (patch_run_extract_script, "run_extract_script"),
        (patch_run_train_script, "run_train_script"),
    ]:
        content_before = content
        content, success = patch_func(content)

        if not success:
            # Pattern not found (different from already patched)
            patches_skipped.append(f"{patch_name} (pattern not found)")
        elif content != content_before:
            patches_applied.append(patch_name)
        # If content unchanged and success=True, it was already patched (idempotent)

    # Check if any changes were made
    if content == original_content:
        if patches_skipped:
            print(f"[patch_subprocess_validation] No changes made. Skipped: {', '.join(patches_skipped)}")
        else:
            print("[patch_subprocess_validation] No changes needed - all patches already applied")
        return True

    # Create backup before modifying
    try:
        shutil.copy2(core_py_path, backup_path)
        print(f"[patch_subprocess_validation] Created backup at {backup_path}")
    except Exception as e:
        print(f"[patch_subprocess_validation] Warning: Could not create backup: {e}")
        # Continue anyway - backup failure shouldn't block patching

    try:
        with open(core_py_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[patch_subprocess_validation] Error writing core.py: {e}")
        # Attempt to restore from backup
        if os.path.exists(backup_path):
            try:
                shutil.copy2(backup_path, core_py_path)
                print(f"[patch_subprocess_validation] Restored from backup")
            except Exception as restore_err:
                print(f"[patch_subprocess_validation] Error restoring from backup: {restore_err}")
        return False

    print(f"[patch_subprocess_validation] Patched core.py: {', '.join(patches_applied)}")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_core_py(base_path)
    sys.exit(0 if success else 1)
