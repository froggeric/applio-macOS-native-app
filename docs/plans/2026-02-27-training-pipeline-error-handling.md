# Training Pipeline Error Handling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:executing-plans to implement this plan task-by-task.

**Goal:** Fix the training pipeline to properly detect and report errors when preprocessing finds no audio files, preventing silent failures that lead to cryptic "need at least one array to concatenate" errors.

**Architecture:** Multi-layer defense with error detection at four levels: (1) UI dropdown returns absolute paths in frozen app, (2) pre-flight validation before subprocess, (3) wrapper path resolution, (4) post-subprocess output validation. All errors returned as strings (not exceptions) for Gradio visibility.

**Tech Stack:** Python 3.10, PyInstaller, Gradio, regex-based patching

---

## Task 0: Fix patch_subprocess_validation.py - Return Error Strings

**Files:**
- Modify: `patches/patch_subprocess_validation.py:49-76, 110-131, 165-202`

**Problem:** The patcher injects `raise RuntimeError(...)` which Gradio doesn't display in the output text box. Users see "success" even when validation fails.

**Solution:** Replace all `raise RuntimeError(...)` with `return "Error: ..."` statements.

### Step 1: Update patch_run_preprocess_script replacement code

In `patches/patch_subprocess_validation.py`, replace the `replacement` variable in `patch_run_preprocess_script` (lines 49-76):

```python
    replacement = r'''result = subprocess.run(command)
\1if result.returncode != 0:
\1    return f"Error: Preprocessing failed with code {result.returncode}"

\1# Validate output was produced
\1model_dir = os.path.join(logs_path, model_name)
\1model_info_path = os.path.join(model_dir, "model_info.json")

\1if not os.path.exists(model_info_path):
\1    return f"Error: No model_info.json found. Dataset path may be empty or incorrect: {dataset_path}"

\1try:
\1    with open(model_info_path, "r", encoding="utf-8") as f:
\1        model_info = json.load(f)
\1except (json.JSONDecodeError, IOError) as e:
\1    return f"Error: Could not read model_info.json: {e}"

\1total_seconds = model_info.get("total_seconds", 0)
\1if total_seconds <= 0:
\1    return f"Error: No audio processed (duration=0s). Check dataset path contains audio files (.wav, .mp3, .flac, .ogg): {dataset_path}"

\1return f"Model {model_name} preprocessed successfully."'''
```

### Step 2: Update patch_run_extract_script replacement code

Replace the `replacement` variable in `patch_run_extract_script` (lines 110-131):

```python
    replacement = r'''result = subprocess.run(command_1)
\1if result.returncode != 0:
\1    return f"Error: Feature extraction failed with code {result.returncode}"

\1# Validate extracted files exist
\1extracted_dir = os.path.join(model_path, "extracted")
\1if not os.path.exists(extracted_dir):
\1    return f"Error: No extracted directory. Run preprocessing first for model '{model_name}'"

\1# Check that extracted directory is not empty
\1extracted_files = os.listdir(extracted_dir)
\1if not extracted_files:
\1    return f"Error: No features extracted. Preprocessing may have failed - check dataset has audio files"

\1return f"Model {model_name} extracted successfully."'''
```

### Step 3: Update patch_run_train_script validation code

Replace the `validation_code` variable in `patch_run_train_script` (lines 165-202):

```python
    validation_code = r'''\2# Validate preprocessing and extraction before training
\2model_dir = os.path.join(logs_path, model_name)
\2model_info_path = os.path.join(model_dir, "model_info.json")

\2if not os.path.exists(model_info_path):
\2    return f"Error: Model not found. Run preprocessing first for model '{model_name}'"

\2try:
\2    with open(model_info_path, "r", encoding="utf-8") as f:
\2        model_info = json.load(f)
\2except (json.JSONDecodeError, IOError) as e:
\2    return f"Error: Could not read model info: {e}"

\2total_seconds = model_info.get("total_seconds", 0)
\2if total_seconds <= 0:
\2    return f"Error: No audio data (duration=0s). Re-run preprocessing with a valid dataset"

\2extracted_dir = os.path.join(model_dir, "extracted")
\2if not os.path.exists(extracted_dir):
\2    return f"Error: No extracted features. Run feature extraction first for model '{model_name}'"

\2extracted_files = os.listdir(extracted_dir)
\2if not extracted_files:
\2    return f"Error: Extracted directory empty. Re-run feature extraction for model '{model_name}'"

\2'''
```

### Step 4: Verify patcher runs without errors

```bash
source venv_macos/bin/activate
python patches/patch_subprocess_validation.py .
```

Expected: No errors, patcher reports status

### Step 5: Commit

```bash
git add patches/patch_subprocess_validation.py
git commit -m "fix: return error strings instead of RuntimeError for Gradio visibility"
```

---

## Task 1: Create patch_preflight_validation.py

**Files:**
- Create: `patches/patch_preflight_validation.py`

**Purpose:** Add pre-flight check in core.py that validates dataset path exists BEFORE launching subprocess.

### Step 1: Create the patcher file

```python
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

    # Pattern: find where command is built, insert validation before subprocess.run
    # Look for: command = [...] followed by result = subprocess.run(command)
    pattern = r'(\s+)(command = \[\s*.*?\s*\]\s*\n)(\s+)(result = subprocess\.run\(command\))'

    if not re.search(pattern, content, re.DOTALL):
        # Try alternate pattern without result capture (unpatched version)
        pattern = r'(\s+)(command = \[\s*.*?\s*\]\s*\n)(\s+)(subprocess\.run\(command\))'

        if not re.search(pattern, content, re.DOTALL):
            print("[patch_preflight_validation] Pattern not found - code may have been modified")
            return content, False

    # Insert validation before subprocess.run
    # Note: We inject before the subprocess.run line, after command definition
    validation_code = r'''\1\2\3# Pre-flight: validate dataset path exists
\3if not os.path.exists(dataset_path):
\3    # Try resolving as absolute path
\3    abs_path = os.path.abspath(dataset_path)
\3    if os.path.exists(abs_path):
\3        dataset_path = abs_path
\3    else:
\3        return f"Error: Dataset path does not exist: {dataset_path}. Use an absolute path to your dataset folder."

\3\4'''

    new_content = re.sub(pattern, validation_code, content, count=1, flags=re.DOTALL)
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
```

### Step 2: Make patcher executable

```bash
chmod +x patches/patch_preflight_validation.py
```

### Step 3: Test patcher locally

```bash
source venv_macos/bin/activate
python patches/patch_preflight_validation.py .
```

Expected: "[patch_preflight_validation] Added pre-flight validation to core.py" or "already patched"

### Step 4: Restore source core.py (patcher should only run on bundled files)

```bash
git checkout core.py
```

### Step 5: Commit

```bash
git add patches/patch_preflight_validation.py
git commit -m "feat: add pre-flight dataset path validation patcher"
```

---

## Task 2: Create patch_preprocess_warning.py

**Files:**
- Create: `patches/patch_preprocess_warning.py`

**Purpose:** Print a prominent warning in preprocess.py when no audio files are found.

### Step 1: Create the patcher file

```python
#!/usr/bin/env python3
"""
Patcher to add empty dataset warning in preprocess.py.

Prints a prominent warning when no audio files are found during preprocessing.
Helps diagnose path resolution issues.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_preprocess_py(content: str) -> tuple[str, bool]:
    """
    Add warning when files list is empty after os.walk.

    Args:
        content: The content of preprocess.py

    Returns:
        Tuple of (patched_content, success)
    """
    # Idempotency marker
    if "# Empty dataset warning" in content:
        return content, True  # Already patched

    # Pattern: find where files list is built and ProcessPoolExecutor starts
    # Look for the audio_length = [] followed by with tqdm
    pattern = r'(\s+)(audio_length = \[\]\n)(\s+)(with tqdm\(total=len\(files\)\) as pbar:)'

    if not re.search(pattern, content):
        print("[patch_preprocess_warning] Pattern not found - code may have been modified")
        return content, False

    warning_code = r'''\1\2\1# Empty dataset warning
\1if not files:
\1    print("=" * 60)
\1    print("WARNING: No audio files found in dataset path:")
\1    print(f"  {input_root}")
\1    print("Supported formats: .wav, .mp3, .flac, .ogg")
\1    print("Please check:")
\1    print("  1. The path is correct")
\1    print("  2. Audio files exist in the directory")
\1    print("  3. Files have supported extensions")
\1    print("=" * 60)

\3\4'''

    new_content = re.sub(pattern, warning_code, content)
    return new_content, True


def patch_preprocess(base_path: str) -> bool:
    """
    Apply empty dataset warning patch to preprocess.py.

    Args:
        base_path: Path to the source directory

    Returns:
        True if patching succeeded (or already patched)
    """
    preprocess_path = os.path.join(base_path, "rvc", "train", "preprocess", "preprocess.py")

    if not os.path.exists(preprocess_path):
        print(f"[patch_preprocess_warning] preprocess.py not found at {preprocess_path}")
        return False

    try:
        with open(preprocess_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[patch_preprocess_warning] Error reading preprocess.py: {e}")
        return False

    original_content = content
    content, success = patch_preprocess_py(content)

    if not success:
        return False

    if content == original_content:
        print("[patch_preprocess_warning] No changes needed - already patched")
        return True

    try:
        with open(preprocess_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[patch_preprocess_warning] Error writing preprocess.py: {e}")
        return False

    print("[patch_preprocess_warning] Added empty dataset warning to preprocess.py")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_preprocess(base_path)
    sys.exit(0 if success else 1)
```

### Step 2: Make patcher executable

```bash
chmod +x patches/patch_preprocess_warning.py
```

### Step 3: Test patcher locally

```bash
source venv_macos/bin/activate
python patches/patch_preprocess_warning.py .
```

### Step 4: Restore source files

```bash
git checkout rvc/train/preprocess/preprocess.py
```

### Step 5: Commit

```bash
git add patches/patch_preprocess_warning.py
git commit -m "feat: add empty dataset warning patcher for preprocess.py"
```

---

## Task 3: Fix macos_wrapper.py - Add Path Validation

**Files:**
- Modify: `macos_wrapper.py:246-261` (subprocess mode section)

**Purpose:** Validate dataset paths in subprocess mode before running preprocessing script.

### Step 1: Add path validation in subprocess mode

In `macos_wrapper.py`, find the subprocess mode section (around line 246) and add validation after `script_args = sys.argv[2:]`:

```python
        if script_path:
            script_args = sys.argv[2:]

            logging.info(f"Subprocess mode detected: script={script_path}")
            logging.info(f"Script arguments: {script_args}")

            # === PATH VALIDATION FOR PREPROCESSING ===
            # Detect preprocessing script by exact path match
            if script_path.endswith('rvc/train/preprocess/preprocess.py') and len(script_args) >= 2:
                dataset_path = script_args[1]
                original_path = dataset_path

                # First check: does path exist as-is?
                if not os.path.exists(dataset_path):
                    # Second check: try resolving relative path from BASE_PATH
                    if not os.path.isabs(dataset_path):
                        resolved = os.path.normpath(os.path.join(BASE_PATH, dataset_path))
                        if os.path.exists(resolved):
                            dataset_path = resolved
                            script_args[1] = resolved
                            logging.info(f"Dataset path resolved: {original_path} -> {resolved}")
                        else:
                            logging.error(f"Dataset path not found: {original_path} (also tried: {resolved})")
                            print(f"Error: Dataset path does not exist: {original_path}")
                            print(f"  Also tried resolving to: {resolved}")
                            print(f"  Please use an absolute path to your dataset folder.")
                            sys.exit(1)
                    else:
                        logging.error(f"Dataset path not found: {dataset_path}")
                        print(f"Error: Dataset path does not exist: {dataset_path}")
                        sys.exit(1)
                else:
                    logging.info(f"Dataset path validated: {dataset_path}")
            # === END PATH VALIDATION ===

            # Adjust sys.argv for the script's perspective
            sys.argv = [script_path] + script_args
```

### Step 2: Test by running a preprocessing command manually

```bash
# This is for manual verification - not a unit test
python macos_wrapper.py rvc/train/preprocess/preprocess.py /path/to/model /nonexistent/path 48000 2 Simple
```

Expected: "Error: Dataset path does not exist: /nonexistent/path" and exit code 1

### Step 3: Commit

```bash
git add macos_wrapper.py
git commit -m "feat: add dataset path validation in subprocess mode"
```

---

## Task 4: Fix get_datasets_list() for Frozen App

**Files:**
- Modify: `tabs/train/train.py:86-91`

**Purpose:** Return absolute paths in frozen app so the dropdown provides working paths.

### Step 1: Update get_datasets_list() function

Replace the function at line 86-91:

```python
def get_datasets_list():
    """Get list of datasets with audio files.

    In frozen app (PyInstaller bundle), returns absolute paths to ensure
    paths work correctly regardless of working directory.
    """
    import sys

    is_frozen = getattr(sys, 'frozen', False)

    datasets = []
    for dirpath, _, filenames in os.walk(datasets_path_relative):
        if any(filename.endswith(tuple(sup_audioext)) for filename in filenames):
            if is_frozen:
                # In frozen app, return absolute path
                datasets.append(os.path.abspath(dirpath))
            else:
                # In source run, return relative path (existing behavior)
                datasets.append(dirpath)

    return datasets
```

### Step 2: Commit

```bash
git add tabs/train/train.py
git commit -m "fix: return absolute paths from get_datasets_list in frozen app"
```

---

## Task 5: Integrate New Patchers into build_macos.py

**Files:**
- Modify: `build_macos.py:518-620` (apply_patches function)

**Purpose:** Add new patchers to the build process in correct order.

### Step 1: Update apply_patches() function

Replace the `apply_patches()` function (starting at line 518) to include new patchers in correct order:

```python
def apply_patches():
    """Apply all fork-specific patches to bundled files."""
    print("\nApplying fork patches to bundled files...")

    bundled_core_py = os.path.join("dist", "Applio.app", "Contents", "Frameworks", "core.py")

    # =================================================================
    # Patch 1: core.py - redirect logs_path to use now_dir
    # =================================================================
    print("  Patching: core.py data paths...")
    data_paths_patcher = "patches/patch_data_paths.py"
    if os.path.exists(data_paths_patcher):
        dp_result = subprocess.run(
            [sys.executable, data_paths_patcher, os.path.dirname(bundled_core_py)],
            capture_output=True,
            text=True
        )
        for line in dp_result.stdout.strip().split('\n'):
            if line:
                print(f"    {line}")
        if dp_result.returncode != 0:
            print(f"    WARNING: Data paths patcher returned {dp_result.returncode}")
    else:
        print(f"    WARNING: Data paths patcher not found at {data_paths_patcher}")

    # =================================================================
    # Patch 1b: core.py - pre-flight dataset path validation (BEFORE subprocess)
    # =================================================================
    print("  Patching: core.py pre-flight validation...")
    preflight_patcher = "patches/patch_preflight_validation.py"
    if os.path.exists(preflight_patcher):
        pf_result = subprocess.run(
            [sys.executable, preflight_patcher, os.path.dirname(bundled_core_py)],
            capture_output=True,
            text=True
        )
        for line in pf_result.stdout.strip().split('\n'):
            if line:
                print(f"    {line}")
        if pf_result.returncode != 0:
            print(f"    WARNING: Pre-flight patcher returned {pf_result.returncode}")
    else:
        print(f"    SKIPPED: Pre-flight patcher not found")

    # =================================================================
    # Patch 1c: core.py - subprocess return code and output validation
    # =================================================================
    print("  Patching: core.py subprocess validation...")
    subprocess_patcher_path = "patches/patch_subprocess_validation.py"
    if os.path.exists(subprocess_patcher_path):
        sv_result = subprocess.run(
            [sys.executable, subprocess_patcher_path, os.path.dirname(bundled_core_py)],
            capture_output=True,
            text=True
        )
        for line in sv_result.stdout.strip().split('\n'):
            if line:
                print(f"    {line}")
        if sv_result.returncode != 0:
            print(f"    WARNING: Subprocess validation patcher returned {sv_result.returncode}")
    else:
        print(f"    WARNING: Subprocess validation patcher not found at {subprocess_patcher_path}")

    # =================================================================
    # Patch 2: preprocess.py - empty dataset warning
    # =================================================================
    print("  Patching: preprocess.py empty dataset warning...")
    preprocess_patcher = "patches/patch_preprocess_warning.py"
    if os.path.exists(preprocess_patcher):
        pp_result = subprocess.run(
            [sys.executable, preprocess_patcher, os.path.dirname(bundled_core_py)],
            capture_output=True,
            text=True
        )
        for line in pp_result.stdout.strip().split('\n'):
            if line:
                print(f"    {line}")
        if pp_result.returncode != 0:
            print(f"    WARNING: Preprocess warning patcher returned {pp_result.returncode}")
    else:
        print(f"    SKIPPED: Preprocess warning patcher not found")

    # =================================================================
    # Patch 3: train.py - 44.1kHz sample rate support
    # =================================================================
    print("  Patching: train.py 44.1kHz support...")
    patcher_path = "patches/patch_train_44100.py"
    # ... (rest of existing patch_train_44100.py code remains unchanged)

    # =================================================================
    # Patch 4: extract.py - multiprocessing fix
    # =================================================================
    print("  Patching: extract.py multiprocessing...")
    mp_patcher_path = "patches/patch_multiprocessing.py"
    # ... (rest of existing patch_multiprocessing.py code remains unchanged)
```

### Step 2: Commit

```bash
git add build_macos.py
git commit -m "feat: integrate preflight and preprocess warning patchers into build"
```

---

## Task 6: Build and Verify

**Purpose:** Build the app and verify all patches are applied correctly.

### Step 1: Build the app

```bash
source venv_macos/bin/activate
python build_macos.py 2>&1 | tee build_output.log
```

Expected output includes:
```
Patching: core.py data paths...
Patching: core.py pre-flight validation...
    [patch_preflight_validation] Added pre-flight validation to core.py
Patching: core.py subprocess validation...
    [patch_subprocess_validation] Patched core.py: run_preprocess_script, run_extract_script, run_train_script
Patching: preprocess.py empty dataset warning...
    [patch_preprocess_warning] Added empty dataset warning to preprocess.py
```

### Step 2: Verify patches in bundled core.py

```bash
grep -c "Pre-flight: validate dataset path" dist/Applio.app/Contents/Frameworks/core.py
grep -c "return f\"Error:" dist/Applio.app/Contents/Frameworks/core.py
```

Expected: Both return >= 1

### Step 3: Verify patches in bundled preprocess.py

```bash
grep -c "Empty dataset warning" dist/Applio.app/Contents/Frameworks/rvc/train/preprocess/preprocess.py
```

Expected: Returns 1

---

## Task 7: Manual Verification Tests

**Purpose:** Verify the fix works end-to-end with actual usage scenarios.

### Test 1: Non-existent path

1. Open Applio.app
2. Enter model name: `test-model`
3. Enter dataset path: `/nonexistent/path`
4. Click "Preprocess Dataset"

**Expected:** Immediate error in UI: "Error: Dataset path does not exist: /nonexistent/path"

### Test 2: Empty directory

1. Create empty directory: `mkdir -p /tmp/empty_dataset`
2. Enter dataset path: `/tmp/empty_dataset`
3. Click "Preprocess Dataset"

**Expected:** Warning printed, then error: "Error: No audio processed (duration=0s)"

### Test 3: Valid dataset

1. Use dataset path: `/Volumes/ssd/ai/applio/assets/datasets/Frederic_v6`
2. Click "Preprocess Dataset"

**Expected:** Progress bar, success message, model_info.json shows total_seconds > 0

### Test 4: Full pipeline

1. Preprocess → Extract → Train with valid dataset

**Expected:** All steps complete successfully

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 0 | Fix patch_subprocess_validation.py | `patches/patch_subprocess_validation.py` |
| 1 | Create patch_preflight_validation.py | `patches/patch_preflight_validation.py` |
| 2 | Create patch_preprocess_warning.py | `patches/patch_preprocess_warning.py` |
| 3 | Fix macos_wrapper.py path validation | `macos_wrapper.py` |
| 4 | Fix get_datasets_list() | `tabs/train/train.py` |
| 5 | Integrate patchers into build | `build_macos.py` |
| 6 | Build and verify | - |
| 7 | Manual tests | - |

**Dependencies:**
- Task 1, 2, 3, 4, 5 can run in parallel after Task 0
- Task 6 requires Task 0-5 complete
- Task 7 requires Task 6 complete
