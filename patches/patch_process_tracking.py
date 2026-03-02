#!/usr/bin/env python3
"""
Patcher to add process tracking to core.py subprocess calls.

This patcher transforms subprocess.run() calls to subprocess.Popen() and
registers process PIDs in ~/.applio/active_processes.json for tracking.

Applied at build time by build_macos.py.
"""

import os
import re
import shutil


# Process tracking helper code to inject
PROCESS_TRACKER_IMPORT = '''
# === Process Tracking (injected by patch) ===
import json
import datetime

_PROCESS_STATE_FILE = None

def _get_process_state_path():
    global _PROCESS_STATE_FILE
    if _PROCESS_STATE_FILE is None:
        data_path = os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))
        _PROCESS_STATE_FILE = os.path.join(data_path, ".applio", "active_processes.json")
    return _PROCESS_STATE_FILE

def _read_process_state():
    path = _get_process_state_path()
    if not os.path.exists(path):
        return {"version": 1, "processes": {}}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"version": 1, "processes": {}}

def _write_process_state(state):
    path = _get_process_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as f:
        json.dump(state, f, indent=2)
    os.rename(temp, path)

def _track_process(process_type, pid, **metadata):
    state = _read_process_state()
    state["processes"][process_type] = {
        "pid": pid,
        "started_at": datetime.datetime.now().isoformat(),
        "status": "running",
        **metadata
    }
    _write_process_state(state)

def _update_process_status(process_type, status):
    state = _read_process_state()
    if process_type in state["processes"] and state["processes"][process_type]:
        state["processes"][process_type]["status"] = status
        _write_process_state(state)

def _untrack_process(process_type):
    state = _read_process_state()
    if process_type in state["processes"]:
        state["processes"][process_type] = None
        _write_process_state(state)

# === End Process Tracking ===

'''

# Idempotency marker
IDEMPOTENCY_MARKER = "# === Process Tracking (injected by patch) ==="


def patch_run_preprocess_script(content: str) -> tuple[str, bool]:
    """
    Patch run_preprocess_script to track subprocess and redirect output to log file.

    Line 448: subprocess.run(command)
    """
    # Specific idempotency check: has this specific patch been applied?
    if '_track_process("preprocess"' in content:
        return content, True  # Already patched

    # Pattern: subprocess.run(command) followed by return statement
    old_pattern = r'(\n\s+)(subprocess\.run\(command\))\n(\s+)(return f"Model \{model_name\} preprocessed successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] preprocess pattern not found")
        return content, False

    replacement = r'''\1# Track preprocess process with log redirection
\1_log_dir = os.path.join(logs_path, model_name)
\1os.makedirs(_log_dir, exist_ok=True)
\1_log_file_path = os.path.join(_log_dir, "preprocess.log")
\1_log_file = open(_log_file_path, "w")
\1_proc = subprocess.Popen(command, stdout=_log_file, stderr=subprocess.STDOUT)
\1_track_process("preprocess", _proc.pid, model_name=model_name, log_file=_log_file_path)
\1_proc.wait()
\1_log_file.close()
\1_untrack_process("preprocess")
\1if _proc.returncode != 0:
\1    return f"Error: Preprocessing failed with code {_proc.returncode}"
\3\4'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def patch_run_extract_script(content: str) -> tuple[str, bool]:
    """
    Patch run_extract_script to track subprocess and redirect output to log file.

    Line 485: subprocess.run(command_1)
    """
    # Specific idempotency check: has this specific patch been applied?
    if '_track_process("extract"' in content:
        return content, True

    # Pattern: subprocess.run(command_1) followed by blank line and return
    old_pattern = r'(\n\s+)(subprocess\.run\(command_1\))\n\n(\s+)(return f"Model \{model_name\} extracted successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] extract pattern not found")
        return content, False

    replacement = r'''\1# Track extract process with log redirection
\1_log_dir = os.path.join(logs_path, model_name)
\1os.makedirs(_log_dir, exist_ok=True)
\1_log_file_path = os.path.join(_log_dir, "extract.log")
\1_log_file = open(_log_file_path, "w")
\1_proc = subprocess.Popen(command_1, stdout=_log_file, stderr=subprocess.STDOUT)
\1_track_process("extract", _proc.pid, model_name=model_name, log_file=_log_file_path)
\1_proc.wait()
\1_log_file.close()
\1_untrack_process("extract")
\1if _proc.returncode != 0:
\1    return f"Error: Feature extraction failed with code {_proc.returncode}"

\3\4'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def patch_run_train_script(content: str) -> tuple[str, bool]:
    """
    Patch run_train_script to track subprocess and redirect output to log file.

    Line 553: subprocess.run(command)
    """
    # Specific idempotency check: has this specific patch been applied?
    if '_track_process("training"' in content:
        return content, True

    # Pattern: subprocess.run(command) followed by run_index_script call
    old_pattern = r'(\n\s+)(subprocess\.run\(command\))\n(\s+)(run_index_script\(model_name, index_algorithm\))\n(\s+)(return f"Model \{model_name\} trained successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] train pattern not found")
        return content, False

    replacement = r'''\1# Track training process with log redirection
\1_log_dir = os.path.join(logs_path, model_name)
\1os.makedirs(_log_dir, exist_ok=True)
\1_log_file_path = os.path.join(_log_dir, "training.log")
\1_log_file = open(_log_file_path, "w")
\1_proc = subprocess.Popen(command, stdout=_log_file, stderr=subprocess.STDOUT)
\1_track_process("training", _proc.pid, model_name=model_name, total_epoch=total_epoch, log_file=_log_file_path)
\1_proc.wait()
\1_log_file.close()
\1_untrack_process("training")
\1if _proc.returncode != 0:
\1    return f"Error: Training failed with code {_proc.returncode}"
\3\4
\5\6'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def patch_run_index_script(content: str) -> tuple[str, bool]:
    """
    Patch run_index_script to track subprocess.

    Line 568: subprocess.run(command)
    """
    # Specific idempotency check: has this specific patch been applied?
    # Note: index script doesn't track processes (short-running, optional)
    # We check for the patched error handling pattern instead
    if 'Error: Index generation failed with code' in content:
        return content, True

    # Pattern: subprocess.run(command) followed by return
    old_pattern = r'(\n\s+)(subprocess\.run\(command\))\n(\s+)(return f"Index file for \{model_name\} generated successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] index pattern not found")
        return content, False

    replacement = r'''\1# Track index process (short-running, optional)
\1_proc = subprocess.Popen(command)
\1_proc.wait()
\1if _proc.returncode != 0:
\1    return f"Error: Index generation failed with code {_proc.returncode}"
\3\4'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def patch_voice_conversion(content: str) -> tuple[str, bool]:
    """
    Patch voice_conversion to track TTS subprocess.

    Line 368: subprocess.run(command_tts)
    """
    # Specific idempotency check: has this specific patch been applied?
    if '_track_process("tts"' in content:
        return content, True

    # This one is trickier - it runs TTS then does inference
    # We track it as "inference" type
    old_pattern = r'(\n\s+)(subprocess\.run\(command_tts\))\n(\s+)(infer_pipeline = import_voice_converter\(\))'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] voice_conversion pattern not found")
        return content, False

    replacement = r'''\1# Track TTS process
\1_proc = subprocess.Popen(command_tts)
\1_track_process("tts", _proc.pid)
\1_proc.wait()
\1_untrack_process("tts")
\3\4'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def inject_process_tracker_helpers(content: str) -> str:
    """Inject the process tracking helper functions after imports."""
    if IDEMPOTENCY_MARKER in content:
        return content  # Already injected

    # Find a good insertion point - after the imports, before first function
    # Look for the first function definition
    match = re.search(r'\n\ndef ', content)
    if match:
        insert_pos = match.start()
        content = content[:insert_pos] + PROCESS_TRACKER_IMPORT + content[insert_pos:]

    return content


def patch_core_py(base_path: str) -> bool:
    """Apply all process tracking patches to core.py."""
    core_py_path = os.path.join(base_path, "core.py")
    backup_path = core_py_path + ".bak"

    if not os.path.exists(core_py_path):
        print(f"[patch_process_tracking] core.py not found at {core_py_path}")
        return False

    try:
        with open(core_py_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[patch_process_tracking] Error reading core.py: {e}")
        return False

    original_content = content
    patches_applied = []

    # Inject helper functions first
    content = inject_process_tracker_helpers(content)

    # Apply all patches
    for patch_func, patch_name in [
        (patch_run_preprocess_script, "run_preprocess_script"),
        (patch_run_extract_script, "run_extract_script"),
        (patch_run_train_script, "run_train_script"),
        (patch_run_index_script, "run_index_script"),
        (patch_voice_conversion, "voice_conversion"),
    ]:
        content_before = content
        content, success = patch_func(content)

        if not success:
            print(f"[patch_process_tracking] {patch_name} patch failed")
        elif content != content_before:
            patches_applied.append(patch_name)

    # Check if any changes were made
    if content == original_content:
        print("[patch_process_tracking] No changes needed - already patched")
        return True

    # Create backup
    try:
        shutil.copy2(core_py_path, backup_path)
        print(f"[patch_process_tracking] Created backup at {backup_path}")
    except Exception as e:
        print(f"[patch_process_tracking] Warning: Could not create backup: {e}")

    try:
        with open(core_py_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[patch_process_tracking] Error writing core.py: {e}")
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, core_py_path)
        return False

    print(f"[patch_process_tracking] Patched core.py: {', '.join(patches_applied)}")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_core_py(base_path)
    sys.exit(0 if success else 1)
