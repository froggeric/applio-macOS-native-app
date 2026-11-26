#!/usr/bin/env python3
"""
Patcher to validate training inputs in core.py before a training run is launched.

Sub-patches, each reported as applied / already applied / skipped:

1. run_train_script, "train gate" (REQUIRED): before the train command is built, check
   that preprocessing and extraction produced their output: logs/<model>/model_info.json
   with total_seconds > 0, and a non-empty logs/<model>/extracted/. Upstream 3.7.2
   launches the training script without looking; the script then exits when its
   config.json is missing, and it never checks for an empty dataset or an empty
   extraction.

2. run_preprocess_script output check (optional): the same model_info.json check right
   after preprocessing.

3. run_extract_script output check (optional): the non-empty extracted/ check right
   after extraction.

The two output checks are not required. Upstream now checks every child's return code
(`if result.returncode != 0:` after each run_quiet call), its preprocess script exits
non-zero on a missing or empty dataset, and the required train gate re-validates the
same conditions before training. When their anchors are missing they are skipped.

Failure messages start with upstream's own prefixes ("Training failed", "Preprocessing
failed", "Feature extraction failed"). tabs/train/train.py `_run_training_step` relies
on them to raise a warning and to block the steps that depend on the failed one; any
other string is shown as a plain info toast.

The anchors are the `pg, pd = "", ""` line and the two success-return lines. None of
them is touched by patch_process_tracking.py, which only swaps the run_quiet launch
lines, so the order of the two patchers no longer matters.

Exit codes: 0 = the required sub-patch is applied or already applied (optional ones
applied or skipped); 2 = the required sub-patch did not land or the patched file failed
verification (nothing is written then).

Applied at build time by build_macos.py.
"""

import os
import sys

EXIT_OK = 0
EXIT_FAILED = 2

TAG = "[patch_subprocess_validation]"

# --- 1. train gate (required) -----------------------------------------------------
TRAIN_GATE_MARKER = "# Validate preprocessing and extraction before training"
TRAIN_GATE_COMMAND_LINE = "    train_script_path = os.path.join("
TRAIN_GATE_ANCHOR = '        pg, pd = "", ""\n' "\n" + TRAIN_GATE_COMMAND_LINE
TRAIN_GATE_INSERT = (
    "    # Validate preprocessing and extraction before training\n"
    "    model_dir = os.path.join(logs_path, model_name)\n"
    '    model_info_path = os.path.join(model_dir, "model_info.json")\n'
    "\n"
    "    if not os.path.exists(model_info_path):\n"
    '        return f"Training failed for model {model_name}: preprocessing not found. Run preprocessing first."\n'
    "\n"
    "    try:\n"
    '        with open(model_info_path, "r", encoding="utf-8") as f:\n'
    "            model_info = json.load(f)\n"
    "    except (json.JSONDecodeError, IOError) as e:\n"
    '        return f"Training failed for model {model_name}: could not read model_info.json: {e}."\n'
    "\n"
    '    total_seconds = model_info.get("total_seconds", 0)\n'
    "    if total_seconds <= 0:\n"
    "        return (\n"
    '            f"Training failed for model {model_name}: no audio data was preprocessed "\n'
    '            f"(total_seconds={total_seconds}). Re-run preprocessing with a valid dataset."\n'
    "        )\n"
    "\n"
    '    extracted_dir = os.path.join(model_dir, "extracted")\n'
    "    if not os.path.exists(extracted_dir):\n"
    '        return f"Training failed for model {model_name}: feature extraction not found. Run feature extraction first."\n'
    "\n"
    "    extracted_files = os.listdir(extracted_dir)\n"
    "    if not extracted_files:\n"
    '        return f"Training failed for model {model_name}: extracted directory is empty. Re-run feature extraction."\n'
    "\n"
)
TRAIN_GATE_REPLACEMENT = (
    TRAIN_GATE_ANCHOR[: -len(TRAIN_GATE_COMMAND_LINE)]
    + TRAIN_GATE_INSERT
    + TRAIN_GATE_COMMAND_LINE
)

# --- 2. preprocess output check (optional) ----------------------------------------
PREPROCESS_MARKER = "# Validate output was produced"
PREPROCESS_ANCHOR = '    return f"Model {model_name} preprocessed successfully."\n'
PREPROCESS_INSERT = (
    "    # Validate output was produced\n"
    "    model_dir = os.path.join(logs_path, model_name)\n"
    '    model_info_path = os.path.join(model_dir, "model_info.json")\n'
    "\n"
    "    if not os.path.exists(model_info_path):\n"
    "        return f\"Preprocessing failed for model {model_name}: model_info.json not found at {model_info_path}. Check that the dataset path '{dataset_path}' contains valid audio files.\"\n"
    "\n"
    "    try:\n"
    '        with open(model_info_path, "r", encoding="utf-8") as f:\n'
    "            model_info = json.load(f)\n"
    "    except (json.JSONDecodeError, IOError) as e:\n"
    '        return f"Preprocessing failed for model {model_name}: could not read model_info.json: {e}."\n'
    "\n"
    '    total_seconds = model_info.get("total_seconds", 0)\n'
    "    if total_seconds <= 0:\n"
    "        return (\n"
    '            f"Preprocessing failed for model {model_name}: no audio data was processed "\n'
    "            f\"(total_seconds={total_seconds}). Check that the dataset path '{dataset_path}' \"\n"
    '            "contains valid audio files (WAV, MP3, FLAC, OGG)."\n'
    "        )\n"
    "\n"
)
PREPROCESS_REPLACEMENT = PREPROCESS_INSERT + PREPROCESS_ANCHOR

# --- 3. extract output check (optional) -------------------------------------------
EXTRACT_MARKER = "# Validate extracted files exist"
EXTRACT_ANCHOR = '    return f"Model {model_name} extracted successfully."\n'
EXTRACT_INSERT = (
    "    # Validate extracted files exist\n"
    '    extracted_dir = os.path.join(model_path, "extracted")\n'
    "    if not os.path.exists(extracted_dir):\n"
    '        return f"Feature extraction failed for model {model_name}: extracted directory not found at {extracted_dir}. Run preprocessing first to generate audio data for extraction."\n'
    "\n"
    "    extracted_files = os.listdir(extracted_dir)\n"
    "    if not extracted_files:\n"
    '        return f"Feature extraction failed for model {model_name}: extracted directory is empty at {extracted_dir}. Preprocessing may have failed - try re-running it."\n'
    "\n"
)
EXTRACT_REPLACEMENT = EXTRACT_INSERT + EXTRACT_ANCHOR

SUB_PATCHES = [
    {
        "name": "run_train_script train gate",
        "required": True,
        "marker": TRAIN_GATE_MARKER,
        "anchor": TRAIN_GATE_ANCHOR,
        "replacement": TRAIN_GATE_REPLACEMENT,
    },
    {
        "name": "run_preprocess_script output check",
        "required": False,
        "marker": PREPROCESS_MARKER,
        "anchor": PREPROCESS_ANCHOR,
        "replacement": PREPROCESS_REPLACEMENT,
    },
    {
        "name": "run_extract_script output check",
        "required": False,
        "marker": EXTRACT_MARKER,
        "anchor": EXTRACT_ANCHOR,
        "replacement": EXTRACT_REPLACEMENT,
    },
]

# Upstream code that must survive the patch (exact text, counted before and after).
PRESERVED_UPSTREAM = [
    TRAIN_GATE_COMMAND_LINE,
    PREPROCESS_ANCHOR.rstrip("\n"),
    EXTRACT_ANCHOR.rstrip("\n"),
    "if result.returncode != 0:",
]


def apply_sub_patch(content, spec):
    """Apply one sub-patch in memory.

    Returns (content, status, reason) with status "applied", "already" or "missing".
    """
    if spec["marker"] in content:
        return content, "already", None
    count = content.count(spec["anchor"])
    if count != 1:
        first_line = spec["anchor"].splitlines()[0].strip()
        return (
            content,
            "missing",
            (f"expected exactly 1 match of its anchor (`{first_line}`), found {count}"),
        )
    return content.replace(spec["anchor"], spec["replacement"], 1), "applied", None


def verify(original, content, landed):
    """Return a list of problems; empty means the patched content is complete."""
    problems = []
    for spec in landed:
        marker = spec["marker"]
        count = content.count(marker)
        if count != 1:
            problems.append(
                f'verification: expected exactly 1 "{marker}", found {count}'
            )
    for text in PRESERVED_UPSTREAM:
        if content.count(text) != original.count(text):
            problems.append(
                f'verification: upstream code was altered: "{text.strip()}"'
            )
    try:
        compile(content, "core.py", "exec")
    except SyntaxError as error:
        problems.append(f"verification: patched core.py does not compile: {error}")
    return problems


def patch_core_py(base_path: str) -> int:
    """Apply the sub-patches to core.py; returns the process exit code."""
    core_py_path = os.path.join(base_path, "core.py")
    try:
        with open(core_py_path, "r", encoding="utf-8") as f:
            original = f.read()
    except OSError as error:
        print(f"{TAG} Cannot read {core_py_path}: {error}")
        return EXIT_FAILED

    content = original
    landed = []
    applied_now = []
    report = []
    failures = []
    for spec in SUB_PATCHES:
        kind = "required" if spec["required"] else "optional"
        content, status, reason = apply_sub_patch(content, spec)
        if status == "missing":
            if spec["required"]:
                failures.append(f"{spec['name']} ({kind}): {reason}")
            else:
                report.append(f"{spec['name']} ({kind}): skipped - {reason}")
        else:
            landed.append(spec)
            report.append(f"{spec['name']} ({kind}): {status}")
            if status == "applied":
                applied_now.append(spec["name"])

    if not failures:
        failures = verify(original, content, landed)
    if failures:
        for failure in failures:
            print(f"{TAG} FAILED - {failure}")
        print(f"{TAG} core.py left unchanged")
        return EXIT_FAILED

    for line in report:
        print(f"{TAG} {line}")

    if content == original:
        print(f"{TAG} Already applied, no changes")
        return EXIT_OK

    try:
        with open(core_py_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as error:
        print(f"{TAG} Error writing core.py: {error}")
        try:
            with open(core_py_path, "w", encoding="utf-8") as f:
                f.write(original)
            print(f"{TAG} Restored original core.py")
        except OSError as restore_error:
            print(f"{TAG} Could not restore original core.py: {restore_error}")
        return EXIT_FAILED

    print(f"{TAG} Patched core.py: {', '.join(applied_now)}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(patch_core_py(sys.argv[1] if len(sys.argv) > 1 else "."))
