#!/usr/bin/env python3
"""
Patcher to fix dataset path handling - always use absolute paths.

Bug: a dataset path can still be relative (get_datasets_list() walks a relative folder
and the Dataset Path dropdown accepts typed input), and run_preprocess_script() puts it
straight into the child's argv, where it only resolves if the child's working directory
is the one the path is relative to.

Two halves, both required:

1. tabs/train/train.py: save_drop_dataset_audio() returns an absolute path. The fork's
   committed edit already carries this (marker "_DATASET_PATH_ABSOLUTE_PATCHED" on line
   1), so this half normally only confirms it; it applies the edit itself when neither
   the marker nor the edit is present.

2. core.py: run_preprocess_script() resolves a relative dataset_path before the command
   list is built. Upstream 3.7.2 builds the script path over three lines
   (`preprocess_script_path = os.path.join(` ... `)`) right before `command = [`.

Exit codes: 0 = applied or already applied; 2 = a required half did not land or a
patched file failed verification (nothing is written then).

Applied at build time by build_macos.py.
"""

import os
import sys

EXIT_OK = 0
EXIT_FAILED = 2

TAG = "[patch_dataset_paths]"

# --- half 1: tabs/train/train.py -------------------------------------------------
TRAIN_MARKER = "# _DATASET_PATH_ABSOLUTE_PATCHED"

TRAIN_ANCHOR = (
    "            dataset_path = os.path.dirname(destination_path)\n"
    "            relative_dataset_path = os.path.relpath(dataset_path, now_dir)\n"
    "\n"
    "            return None, relative_dataset_path\n"
)
TRAIN_REPLACEMENT = (
    "            dataset_path = os.path.dirname(destination_path)\n"
    "            # Return absolute path to fix subprocess resolution\n"
    "            return None, dataset_path\n"
)

# --- half 2: core.py -------------------------------------------------------------
CORE_MARKER = "# CRITICAL: Resolve to absolute path BEFORE building command"

CORE_COMMAND_LINE = "    command = [\n"
CORE_ANCHOR = (
    "    preprocess_script_path = os.path.join(\n"
    '        current_script_directory, "rvc", "train", "preprocess", "preprocess.py"\n'
    "    )\n" + CORE_COMMAND_LINE
)
CORE_REPLACEMENT = (
    CORE_ANCHOR[: -len(CORE_COMMAND_LINE)]
    + "    # CRITICAL: Resolve to absolute path BEFORE building command\n"
    "    # Fixes bug where relative paths failed in subprocess with different CWD\n"
    "    if dataset_path and not os.path.isabs(dataset_path):\n"
    "        abs_path = os.path.abspath(dataset_path)\n"
    "        if os.path.exists(abs_path):\n"
    "            dataset_path = abs_path\n"
    "\n" + CORE_COMMAND_LINE
)


def read_text(path):
    """Return the file's text, or None after reporting why it could not be read."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as error:
        print(f"{TAG} Cannot read {path}: {error}")
        return None


def plan_half(label, path, original, marker, anchor, replacement, prefix=""):
    """Decide what to do with one file.

    The half counts as applied when its marker or its replacement text is already in
    the file. Returns (status, new_content, problem): status is "applied", "already" or
    "failed"; new_content is None when the file must not be written.
    """
    if original is None:
        return "failed", None, f"{label}: {path} could not be read"
    if marker in original or replacement in original:
        print(f"{TAG} {label}: already applied")
        return "already", None, None

    count = original.count(anchor)
    if count != 1:
        first_line = anchor.splitlines()[0].strip()
        return (
            "failed",
            None,
            (
                f"{label}: required anchor not found in {path} (expected exactly 1 match "
                f"starting at `{first_line}`, found {count})"
            ),
        )

    new_content = prefix + original.replace(anchor, replacement, 1)
    problems = []
    if new_content.count(marker) != 1:
        problems.append(f"{label}: marker missing after patching")
    if anchor in new_content:
        problems.append(f"{label}: anchor still present after patching")
    try:
        compile(new_content, os.path.basename(path), "exec")
    except SyntaxError as error:
        problems.append(f"{label}: patched {path} does not compile: {error}")
    if problems:
        return "failed", None, "; ".join(problems)
    return "applied", new_content, None


def write(path, content, originals):
    """Write one file; restore every file written so far if that fails."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as error:
        print(f"{TAG} Error writing {path}: {error}")
        for written_path, original in originals.items():
            try:
                with open(written_path, "w", encoding="utf-8") as f:
                    f.write(original)
                print(f"{TAG} Restored {written_path}")
            except OSError as restore_error:
                print(f"{TAG} Could not restore {written_path}: {restore_error}")
        return False
    return True


def patch(base_path: str) -> int:
    """Apply both halves; returns the process exit code."""
    core_path = os.path.join(base_path, "core.py")
    train_path = os.path.join(base_path, "tabs", "train", "train.py")

    core_original = read_text(core_path)
    train_original = read_text(train_path)

    core_status, core_new, core_problem = plan_half(
        "core.py run_preprocess_script",
        core_path,
        core_original,
        CORE_MARKER,
        CORE_ANCHOR,
        CORE_REPLACEMENT,
    )
    train_status, train_new, train_problem = plan_half(
        "tabs/train/train.py save_drop_dataset_audio",
        train_path,
        train_original,
        TRAIN_MARKER,
        TRAIN_ANCHOR,
        TRAIN_REPLACEMENT,
        prefix=TRAIN_MARKER + " = True\n",
    )

    problems = [problem for problem in (core_problem, train_problem) if problem]
    if problems:
        for problem in problems:
            print(f"{TAG} FAILED - {problem}")
        print(f"{TAG} No file written")
        return EXIT_FAILED

    pending = []
    if core_status == "applied":
        pending.append(
            (
                core_path,
                core_new,
                "core.py: resolves dataset_path before the command is built",
            )
        )
    if train_status == "applied":
        pending.append(
            (
                train_path,
                train_new,
                "tabs/train/train.py: save_drop_dataset_audio returns an absolute path",
            )
        )
    if not pending:
        print(f"{TAG} Already applied, no changes")
        return EXIT_OK

    written = {}
    for path, new_content, description in pending:
        # Registered before writing so that a failed write also restores this file.
        written[path] = core_original if path == core_path else train_original
        if not write(path, new_content, written):
            return EXIT_FAILED
        print(f"{TAG} Applied: {description}")

    print(f"{TAG} Patch applied successfully")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(patch(sys.argv[1] if len(sys.argv) > 1 else "."))
