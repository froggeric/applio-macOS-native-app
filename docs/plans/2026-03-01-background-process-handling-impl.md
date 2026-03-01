# Background Process Handling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:executing-plans to implement this plan task-by-task.

**Goal:** Track long-running subprocesses and provide user control when closing the app.

**Architecture:** File-based process tracking via `~/.applio/active_processes.json`. Core.py subprocess calls are patched to use Popen and register PIDs. macos_wrapper.py provides close confirmation dialog and progress monitoring window with pause/resume/terminate controls.

**Tech Stack:** Python subprocess, POSIX signals (SIGSTOP/SIGCONT/SIGTERM), psutil, pywebview

**Design Doc:** `docs/plans/2026-03-01-background-process-handling-design.md`

---

## Task 1: Create Process Tracking Helper Module

**Files:**
- Modify: `macos_wrapper.py` (add after line 72, before PreferencesManager class)

**Step 1: Add imports at top of file**

After line 26 (`import runpy`), add:
```python
import signal
import datetime
```

**Step 2: Add ProcessController and helper functions**

Insert after line 72 (after VERSION constants), before the PreferencesManager class:

```python
# =================================================================
# 1.6. Process Tracking for Background Operations
# =================================================================

PROCESS_STATE_FILE = None  # Set after DATA_PATH is known

def _get_process_state_path():
    """Get path to active_processes.json (lazy initialization)."""
    global PROCESS_STATE_FILE
    if PROCESS_STATE_FILE is None:
        data_path = os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))
        PROCESS_STATE_FILE = os.path.join(data_path, ".applio", "active_processes.json")
    return PROCESS_STATE_FILE

def _ensure_process_state_dir():
    """Ensure the .applio directory exists."""
    state_path = _get_process_state_path()
    os.makedirs(os.path.dirname(state_path), exist_ok=True)

def read_active_processes() -> dict:
    """Read the active processes state file."""
    state_path = _get_process_state_path()
    if not os.path.exists(state_path):
        return {"version": 1, "processes": {}}
    try:
        with open(state_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"version": 1, "processes": {}}

def write_active_processes(state: dict):
    """Write the active processes state file."""
    _ensure_process_state_dir()
    state_path = _get_process_state_path()
    # Atomic write
    temp_path = state_path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(state, f, indent=2)
    os.rename(temp_path, state_path)

def write_process(process_type: str, pid: int, **metadata):
    """Register a process in active_processes.json."""
    state = read_active_processes()
    state["processes"][process_type] = {
        "pid": pid,
        "started_at": datetime.datetime.now().isoformat(),
        "status": "running",
        **metadata
    }
    write_active_processes(state)
    logging.info(f"[ProcessTracker] Registered {process_type} with PID {pid}")

def clear_process(process_type: str):
    """Remove a process from active_processes.json."""
    state = read_active_processes()
    if process_type in state["processes"]:
        old_pid = state["processes"][process_type].get("pid")
        state["processes"][process_type] = None
        write_active_processes(state)
        logging.info(f"[ProcessTracker] Cleared {process_type} (was PID {old_pid})")

def update_process_status(process_type: str, status: str):
    """Update status of a tracked process."""
    state = read_active_processes()
    if process_type in state["processes"] and state["processes"][process_type]:
        state["processes"][process_type]["status"] = status
        write_active_processes(state)
        logging.info(f"[ProcessTracker] {process_type} status: {status}")

def has_active_processes() -> bool:
    """Check if any processes are currently active."""
    state = read_active_processes()
    for ptype, info in state.get("processes", {}).items():
        if info and info.get("pid"):
            # Verify process still exists
            try:
                import psutil
                if psutil.pid_exists(info["pid"]):
                    return True
            except ImportError:
                # Fallback: try sending signal 0 (no-op)
                try:
                    os.kill(info["pid"], 0)
                    return True
                except (ProcessLookupError, OSError):
                    pass
    return False

def get_active_process_list() -> list:
    """Get list of active processes with their info."""
    state = read_active_processes()
    active = []
    for ptype, info in state.get("processes", {}).items():
        if info and info.get("pid"):
            try:
                import psutil
                if psutil.pid_exists(info["pid"]):
                    active.append({"type": ptype, **info})
            except (ImportError, ProcessLookupError):
                pass
    return active

class ProcessController:
    """Control tracked processes via POSIX signals."""

    @staticmethod
    def pause(pid: int) -> bool:
        """Pause a process (SIGSTOP)."""
        try:
            os.kill(pid, signal.SIGSTOP)
            logging.info(f"[ProcessController] Paused PID {pid}")
            return True
        except (ProcessLookupError, PermissionError) as e:
            logging.warning(f"[ProcessController] Failed to pause PID {pid}: {e}")
            return False

    @staticmethod
    def resume(pid: int) -> bool:
        """Resume a paused process (SIGCONT)."""
        try:
            os.kill(pid, signal.SIGCONT)
            logging.info(f"[ProcessController] Resumed PID {pid}")
            return True
        except (ProcessLookupError, PermissionError) as e:
            logging.warning(f"[ProcessController] Failed to resume PID {pid}: {e}")
            return False

    @staticmethod
    def terminate(pid: int, force: bool = False) -> bool:
        """Terminate a process (SIGTERM or SIGKILL)."""
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            logging.info(f"[ProcessController] Terminated PID {pid} with {sig}")
            return True
        except (ProcessLookupError, PermissionError) as e:
            logging.warning(f"[ProcessController] Failed to terminate PID {pid}: {e}")
            return False

    @staticmethod
    def terminate_all() -> int:
        """Terminate all tracked processes. Returns count terminated."""
        count = 0
        state = read_active_processes()
        for ptype, info in state.get("processes", {}).items():
            if info and info.get("pid"):
                if ProcessController.terminate(info["pid"]):
                    count += 1
                clear_process(ptype)
        logging.info(f"[ProcessController] Terminated {count} processes")
        return count

    @staticmethod
    def pause_all() -> int:
        """Pause all running processes. Returns count paused."""
        count = 0
        state = read_active_processes()
        for ptype, info in state.get("processes", {}).items():
            if info and info.get("pid") and info.get("status") == "running":
                if ProcessController.pause(info["pid"]):
                    update_process_status(ptype, "paused")
                    count += 1
        return count

    @staticmethod
    def resume_all() -> int:
        """Resume all paused processes. Returns count resumed."""
        count = 0
        state = read_active_processes()
        for ptype, info in state.get("processes", {}).items():
            if info and info.get("pid") and info.get("status") == "paused":
                if ProcessController.resume(info["pid"]):
                    update_process_status(ptype, "running")
                    count += 1
        return count
```

**Step 3: Add psutil to requirements**

psutil is used for reliable PID existence checking. Check if it's already in requirements:
```bash
grep "psutil" requirements_macos.txt
```

**Note:** psutil is likely NOT present in requirements_macos.txt. It must be added for this feature to work reliably.

Append to `requirements_macos.txt`:
```
psutil>=5.9.0
```

**Why psutil?** The fallback using `os.kill(pid, 0)` doesn't handle all edge cases (permission errors, zombie processes). psutil is the industry standard for process management.

**Step 4: Commit**

```bash
git add macos_wrapper.py requirements_macos.txt
git commit -m "feat: add process tracking helper module for background operations"
```

---

## Task 2: Create patch_process_tracking.py

**Files:**
- Create: `patches/patch_process_tracking.py`
- Modify: `build_macos.py` (add to patches_to_apply)

**Step 1: Create the patch file**

```python
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
    Patch run_preprocess_script to track subprocess.

    Line 448: subprocess.run(command)
    """
    if IDEMPOTENCY_MARKER in content:
        return content, True  # Already patched

    # Pattern: subprocess.run(command) followed by return statement
    old_pattern = r'(\n\s+)(subprocess\.run\(command\))\n(\s+)(return f"Model \{model_name\} preprocessed successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] preprocess pattern not found")
        return content, False

    replacement = r'''\1# Track preprocess process
\1_proc = subprocess.Popen(command)
\1_track_process("preprocess", _proc.pid, model_name=model_name)
\1_proc.wait()
\1_untrack_process("preprocess")
\1if _proc.returncode != 0:
\1    return f"Error: Preprocessing failed with code {_proc.returncode}"
\3\4'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def patch_run_extract_script(content: str) -> tuple[str, bool]:
    """
    Patch run_extract_script to track subprocess.

    Line 485: subprocess.run(command_1)
    """
    if IDEMPOTENCY_MARKER in content:
        return content, True

    # Pattern: subprocess.run(command_1) followed by blank line and return
    old_pattern = r'(\n\s+)(subprocess\.run\(command_1\))\n\n(\s+)(return f"Model \{model_name\} extracted successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] extract pattern not found")
        return content, False

    replacement = r'''\1# Track extract process
\1_proc = subprocess.Popen(command_1)
\1_track_process("extract", _proc.pid, model_name=model_name)
\1_proc.wait()
\1_untrack_process("extract")
\1if _proc.returncode != 0:
\1    return f"Error: Feature extraction failed with code {_proc.returncode}"

\3\4'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True


def patch_run_train_script(content: str) -> tuple[str, bool]:
    """
    Patch run_train_script to track subprocess.

    Line 553: subprocess.run(command)
    """
    if IDEMPOTENCY_MARKER in content:
        return content, True

    # Pattern: subprocess.run(command) followed by run_index_script call
    old_pattern = r'(\n\s+)(subprocess\.run\(command\))\n(\s+)(run_index_script\(model_name, index_algorithm\))\n(\s+)(return f"Model \{model_name\} trained successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] train pattern not found")
        return content, False

    replacement = r'''\1# Track training process
\1_proc = subprocess.Popen(command)
\1_track_process("training", _proc.pid, model_name=model_name, total_epoch=total_epoch)
\1_proc.wait()
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
    if IDEMPOTENCY_MARKER in content:
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
    if IDEMPOTENCY_MARKER in content:
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
```

**Step 2: Register patch in build_macos.py**

Find the `patches_to_apply` list and add the new patch. Look for the pattern:

```bash
grep -n "patches_to_apply" /Volumes/ssd/ai/github/applio-macOS-native-app/build_macos.py
```

Add this entry to the list **BEFORE** `patch_subprocess_validation.py` (the validation patch expects `subprocess.run` to exist, so process tracking must run first):
```python
    ("patches/patch_process_tracking.py", "core.py", "core.py - process tracking for subprocesses", "dir"),
```

**CRITICAL:** This patch must be applied BEFORE `patch_subprocess_validation.py` because:
- `patch_process_tracking.py` changes `subprocess.run()` → `subprocess.Popen()`
- `patch_subprocess_validation.py` looks for `subprocess.run()` patterns
- Wrong order will cause patch failures

**Step 3: Commit**

```bash
git add patches/patch_process_tracking.py build_macos.py
git commit -m "feat: add patch for process tracking in core.py subprocess calls"
```

---

## Task 3: Create Close Confirmation Dialog

**Files:**
- Modify: `macos_wrapper.py` (add dialog function, modify window events)

**Step 1: Create the close confirmation dialog HTML**

Create `assets/close_confirmation.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 24px;
            text-align: center;
        }
        h2 { color: #ff6b6b; margin-bottom: 16px; font-size: 18px; }
        .process-list {
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
            padding: 16px;
            margin: 16px 0;
            text-align: left;
        }
        .process-item {
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .process-item:last-child { border-bottom: none; }
        .process-type { color: #4ecdc4; font-weight: 600; }
        .process-detail { color: #888; font-size: 12px; margin-top: 4px; }
        .buttons { display: flex; gap: 12px; justify-content: center; margin-top: 20px; }
        button {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-terminate { background: #ff6b6b; color: #fff; }
        .btn-terminate:hover { background: #ee5a5a; }
        .btn-keep { background: #4ecdc4; color: #1a1a2e; }
        .btn-keep:hover { background: #3dbdb5; }
    </style>
</head>
<body>
    <h2>⚠️ Active Processes</h2>
    <p>The following processes are still running:</p>
    <div class="process-list" id="processList">
        <!-- Populated by JavaScript -->
    </div>
    <p>What would you like to do?</p>
    <div class="buttons">
        <button class="btn-terminate" onclick="terminate()">Terminate & Quit</button>
        <button class="btn-keep" onclick="keepRunning()">Keep Running in Background</button>
    </div>
    <script>
        const processes = {{PROCESSES_JSON}};
        const listEl = document.getElementById('processList');

        if (processes.length === 0) {
            listEl.innerHTML = '<div class="process-item">No active processes</div>';
        } else {
            processes.forEach(p => {
                const item = document.createElement('div');
                item.className = 'process-item';
                item.innerHTML = `
                    <div class="process-type">${p.type.charAt(0).toUpperCase() + p.type.slice(1)}</div>
                    <div class="process-detail">${p.model_name || 'In progress...'}</div>
                `;
                listEl.appendChild(item);
            });
        }

        function terminate() {
            pywebview.api.terminate_and_quit();
        }

        function keepRunning() {
            pywebview.api.keep_running();
        }
    </script>
</body>
</html>
```

**Step 2: Add dialog functions to macos_wrapper.py**

Add after the `ProcessController` class (around line 200):

```python
# Global reference to prevent garbage collection
_close_confirmation_window = None
_progress_window = None
_main_window_ref = None

class CloseConfirmationApi:
    """API for close confirmation dialog."""

    def terminate_and_quit(self):
        """Terminate all processes and quit."""
        logging.info("[CloseDialog] User chose to terminate and quit")
        ProcessController.terminate_all()
        os._exit(0)

    def keep_running(self):
        """Keep processes running, show progress window."""
        logging.info("[CloseDialog] User chose to keep running")
        global _close_confirmation_window
        if _close_confirmation_window:
            _close_confirmation_window.destroy()
        show_progress_window()

def show_close_confirmation_dialog():
    """Show the close confirmation dialog."""
    global _close_confirmation_window

    # Get active processes
    processes = get_active_process_list()

    # Read the HTML template
    html_path = os.path.join(BASE_PATH, "assets", "close_confirmation.html")
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except Exception as e:
        logging.error(f"Failed to load close_confirmation.html: {e}")
        # Fallback: just terminate
        os._exit(0)
        return

    # Inject processes JSON
    import json
    html_content = html_content.replace("{{PROCESSES_JSON}}", json.dumps(processes))

    _close_confirmation_window = webview.create_window(
        "Active Processes",
        html=html_content,
        width=450,
        height=350,
        resizable=False,
        minimizable=False,
        maximizable=False,
        fullscreenable=False,
        js_api=CloseConfirmationApi()
    )

def on_window_closing():
    """Handle main window closing event."""
    if has_active_processes():
        logging.info("[Window] Active processes detected, showing confirmation")
        show_close_confirmation_dialog()
        return False  # Prevent close, dialog will handle exit
    else:
        logging.info("[Window] No active processes, exiting")
        os._exit(0)
        # Note: os._exit(0) never returns, so no unreachable code after it
```

**Step 3: Modify window events in ApplioApp.run()**

Find line ~1092 and change:
```python
# FROM:
self.window.events.closed += lambda: os._exit(0)

# TO:
global _main_window_ref
_main_window_ref = self.window
self.window.events.closing += lambda: on_window_closing()
```

**Step 4: Commit**

```bash
git add assets/close_confirmation.html macos_wrapper.py
git commit -m "feat: add close confirmation dialog for active processes"
```

---

## Task 4: Create Progress Monitoring Window

**Files:**
- Create: `assets/progress_monitor.html`
- Modify: `macos_wrapper.py` (add show_progress_window function)

**Step 1: Create the progress monitor HTML**

Create `assets/progress_monitor.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
        }
        .header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
        }
        .header h1 { font-size: 16px; color: #4ecdc4; }
        .progress-container { margin: 16px 0; }
        .progress-bar {
            background: rgba(255,255,255,0.1);
            border-radius: 4px;
            height: 8px;
            overflow: hidden;
        }
        .progress-fill {
            background: linear-gradient(90deg, #4ecdc4, #45b7aa);
            height: 100%;
            transition: width 0.3s;
        }
        .progress-text {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #888;
            margin-top: 4px;
        }
        .status { margin: 12px 0; }
        .status-label { color: #888; font-size: 12px; }
        .status-value { color: #eee; font-size: 14px; margin-top: 2px; }
        .buttons {
            display: flex;
            gap: 8px;
            margin-top: 16px;
        }
        button {
            flex: 1;
            padding: 10px;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-terminate { background: #ff6b6b; color: #fff; }
        .btn-terminate:hover { background: #ee5a5a; }
        .btn-pause { background: #ffd93d; color: #1a1a2e; }
        .btn-pause:hover { background: #f5cf2e; }
        .btn-pause.paused { background: #4ecdc4; }
        .btn-relaunch { background: rgba(255,255,255,0.1); color: #eee; border: 1px solid rgba(255,255,255,0.2); }
        .btn-relaunch:hover { background: rgba(255,255,255,0.15); }
        .log-toggle {
            margin-top: 16px;
            text-align: center;
        }
        .log-toggle a {
            color: #4ecdc4;
            text-decoration: none;
            font-size: 12px;
            cursor: pointer;
        }
        .log-toggle a:hover { text-decoration: underline; }
        .log-container {
            margin-top: 12px;
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
            padding: 12px;
            max-height: 200px;
            overflow-y: auto;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 11px;
            display: none;
        }
        .log-container.visible { display: block; }
        .log-line {
            padding: 2px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            white-space: pre-wrap;
            word-break: break-all;
        }
        .log-line:last-child { border-bottom: none; }
    </style>
</head>
<body>
    <div class="header">
        <span style="font-size: 20px;">⚙️</span>
        <h1>Applio Process Monitor</h1>
    </div>

    <div class="progress-container">
        <div class="progress-bar">
            <div class="progress-fill" id="progressFill" style="width: 0%"></div>
        </div>
        <div class="progress-text">
            <span id="progressPercent">0%</span>
            <span id="progressETA">--</span>
        </div>
    </div>

    <div class="status">
        <div class="status-label">Process</div>
        <div class="status-value" id="processType">--</div>
    </div>

    <div class="status">
        <div class="status-label">Details</div>
        <div class="status-value" id="processDetails">--</div>
    </div>

    <div class="status">
        <div class="status-label">Elapsed</div>
        <div class="status-value" id="elapsedTime">--</div>
    </div>

    <div class="buttons">
        <button class="btn-terminate" onclick="terminate()">Terminate</button>
        <button class="btn-pause" id="pauseBtn" onclick="togglePause()">Pause</button>
        <button class="btn-relaunch" onclick="relaunch()">Relaunch App</button>
    </div>

    <div class="log-toggle">
        <a id="logToggle" onclick="toggleLog()">▼ Show Log Output</a>
    </div>

    <div class="log-container" id="logContainer"></div>

    <script>
        let isPaused = false;
        let logLines = [];
        const MAX_LOG_LINES = 100;

        function updateProgress(percent, eta, details, processType) {
            document.getElementById('progressFill').style.width = percent + '%';
            document.getElementById('progressPercent').textContent = percent + '%';
            if (eta) document.getElementById('progressETA').textContent = eta;
            if (details) document.getElementById('processDetails').textContent = details;
            if (processType) document.getElementById('processType').textContent = processType;
        }

        function updateElapsed(elapsed) {
            document.getElementById('elapsedTime').textContent = elapsed;
        }

        function addLogLine(line) {
            logLines.push(line);
            if (logLines.length > MAX_LOG_LINES) {
                logLines.shift();
            }
            const container = document.getElementById('logContainer');
            const lineEl = document.createElement('div');
            lineEl.className = 'log-line';
            lineEl.textContent = line;
            container.appendChild(lineEl);
            container.scrollTop = container.scrollHeight;
        }

        function terminate() {
            if (confirm('Are you sure you want to terminate the process?')) {
                pywebview.api.terminate();
            }
        }

        function togglePause() {
            const btn = document.getElementById('pauseBtn');
            if (isPaused) {
                pywebview.api.resume();
                btn.textContent = 'Pause';
                btn.classList.remove('paused');
                isPaused = false;
            } else {
                pywebview.api.pause();
                btn.textContent = 'Resume';
                btn.classList.add('paused');
                isPaused = true;
            }
        }

        function relaunch() {
            pywebview.api.relaunch();
        }

        function toggleLog() {
            const container = document.getElementById('logContainer');
            const toggle = document.getElementById('logToggle');
            if (container.classList.contains('visible')) {
                container.classList.remove('visible');
                toggle.textContent = '▼ Show Log Output';
                pywebview.api.resize_window(480, 280);
            } else {
                container.classList.add('visible');
                toggle.textContent = '▲ Hide Log Output';
                pywebview.api.resize_window(600, 480);
            }
        }

        // Initialize from pywebview
        window.addEventListener('pywebviewready', function() {
            pywebview.api.get_initial_state().then(function(state) {
                updateProgress(state.progress, state.eta, state.details, state.processType);
                updateElapsed(state.elapsed);
            });
        });
    </script>
</body>
</html>
```

**Step 2: Add progress window functions to macos_wrapper.py**

Add after `show_close_confirmation_dialog()`:

```python
class ProgressMonitorApi:
    """API for progress monitoring window."""

    def __init__(self, process_type):
        self.process_type = process_type

    def get_initial_state(self):
        """Get current process state."""
        state = read_active_processes()
        info = state.get("processes", {}).get(self.process_type, {})
        return {
            "processType": self.process_type.capitalize(),
            "progress": 0,  # Would need log parsing
            "eta": "--",
            "details": info.get("model_name", "Running..."),
            "elapsed": self._get_elapsed(info.get("started_at"))
        }

    def _get_elapsed(self, started_at):
        if not started_at:
            return "--"
        try:
            start = datetime.datetime.fromisoformat(started_at)
            elapsed = datetime.datetime.now() - start
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        except:
            return "--"

    def terminate(self):
        """Terminate the process."""
        state = read_active_processes()
        info = state.get("processes", {}).get(self.process_type)
        if info and info.get("pid"):
            ProcessController.terminate(info["pid"])
            clear_process(self.process_type)
        os._exit(0)

    def pause(self):
        """Pause the process."""
        state = read_active_processes()
        info = state.get("processes", {}).get(self.process_type)
        if info and info.get("pid"):
            ProcessController.pause(info["pid"])
            update_process_status(self.process_type, "paused")

    def resume(self):
        """Resume the process."""
        state = read_active_processes()
        info = state.get("processes", {}).get(self.process_type)
        if info and info.get("pid"):
            ProcessController.resume(info["pid"])
            update_process_status(self.process_type, "running")

    def relaunch(self):
        """Relaunch the full app."""
        import subprocess
        if getattr(sys, 'frozen', False):
            # Frozen app: use 'open' command to launch the .app bundle
            app_path = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
            subprocess.Popen(['open', app_path])
        else:
            # Development: just run the script
            subprocess.Popen([sys.executable, os.path.join(BASE_PATH, 'macos_wrapper.py')])
        # Don't exit - let user close progress window

    def resize_window(self, width, height):
        """Resize the window."""
        global _progress_window
        if _progress_window:
            _progress_window.resize(width, height)

def show_progress_window():
    """Show the progress monitoring window."""
    global _progress_window, _main_window_ref

    # Determine which process to monitor
    processes = get_active_process_list()
    if not processes:
        logging.warning("[ProgressWindow] No active processes to monitor")
        os._exit(0)
        return

    # Prioritize training, then extract, then preprocess
    priority = ["training", "extract", "preprocess", "tts", "inference"]
    process_type = None
    for ptype in priority:
        for p in processes:
            if p["type"] == ptype:
                process_type = ptype
                break
        if process_type:
            break

    if not process_type:
        process_type = processes[0]["type"]

    # Close main window if still open
    if _main_window_ref:
        try:
            _main_window_ref.destroy()
        except:
            pass

    # Read HTML template
    html_path = os.path.join(BASE_PATH, "assets", "progress_monitor.html")
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except Exception as e:
        logging.error(f"Failed to load progress_monitor.html: {e}")
        os._exit(0)
        return

    _progress_window = webview.create_window(
        "Applio Process Monitor",
        html=html_content,
        width=480,
        height=280,
        resizable=True,
        min_size=(400, 250),
        js_api=ProgressMonitorApi(process_type)
    )

    # When progress window closes, just exit
    _progress_window.events.closed += lambda: os._exit(0)
```

**Step 3: Commit**

```bash
git add assets/progress_monitor.html macos_wrapper.py
git commit -m "feat: add progress monitoring window with pause/resume/terminate"
```

---

## Task 5: Integration and Testing

**Files:**
- Verify all files are in place
- Test full workflow

**Step 1: Verify file structure**

```bash
# Check all files exist
ls -la patches/patch_process_tracking.py
ls -la assets/close_confirmation.html
ls -la assets/progress_monitor.html
grep -c "patch_process_tracking" build_macos.py
```

**Step 2: Build the app**

```bash
cd /Volumes/ssd/ai/github/applio-macOS-native-app
venv_macos/bin/python build_macos.py
```

Expected: Build completes without errors, patches applied.

**Step 3: Test the workflow**

1. Launch the built app: `open dist/Applio.app`
2. Start training a model
3. Try to close the window:
   - Expected: Close confirmation dialog appears
4. Click "Keep Running in Background":
   - Expected: Progress window appears
5. Test Pause/Resume:
   - Expected: Process pauses and resumes
6. Test Terminate:
   - Expected: Process terminated, app exits

**Step 4: Edge case tests**

- Close with no processes: Should exit immediately
- App crash: Processes should continue (check `ps aux | grep python`)
- Stale PID: Manually edit active_processes.json with fake PID, verify cleanup

**Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration fixes for background process handling"
```

---

## Summary

| Task | Description | Blocked By |
|------|-------------|------------|
| 1 | Process tracking helper module | - |
| 2 | patch_process_tracking.py | - |
| 3 | Close confirmation dialog | 1 |
| 4 | Progress monitoring window | 1, 3 |
| 5 | Integration and testing | 1, 2, 3, 4 |

**Files Created:**
- `patches/patch_process_tracking.py`
- `assets/close_confirmation.html`
- `assets/progress_monitor.html`

**Files Modified:**
- `macos_wrapper.py` (process tracking, dialogs, progress window)
- `build_macos.py` (register new patch)
- `requirements_macos.txt` (add psutil if needed)

---

## Critical Integration Notes

### Patch Application Order

The new `patch_process_tracking.py` must be applied **BEFORE** `patch_subprocess_validation.py` in `build_macos.py`:

```python
patches_to_apply = [
    # ... other patches ...
    ("patches/patch_process_tracking.py", "core.py", "core.py - process tracking", "dir"),  # MUST BE FIRST
    ("patches/patch_subprocess_validation.py", "core.py", "core.py - subprocess validation", "python"),  # AFTER
    # ... remaining patches ...
]
```

**Reason:** `patch_subprocess_validation.py` looks for `subprocess.run()` patterns. If `patch_process_tracking.py` runs second, it will fail to find its patterns because they've already been transformed.

### Potential Conflicts

1. **`patch_subprocess_validation.py`** - Already patches the same functions. Must run AFTER process tracking.
2. **`patch_custom_pretrained_paths.py`** - Patches `run_train_script`. No conflict (different lines).

### Window Event Behavior

The `closing` event in pywebview is cancellable. Return `False` to prevent the window from closing:
- Return `False` → Window stays open (dialog shown)
- Don't return / return `True` → Window closes

### Graceful Degradation

If psutil is not available, the code falls back to `os.kill(pid, 0)` for PID checking. This works in most cases but may fail for:
- Zombie processes
- Processes owned by other users
- Permission-denied scenarios

---

## Testing Checklist

- [ ] Build completes without errors
- [ ] psutil is installed in frozen app
- [ ] Training subprocess is tracked in `active_processes.json`
- [ ] Close confirmation dialog appears when training is active
- [ ] "Terminate & Quit" kills process and exits
- [ ] "Keep Running" shows progress window
- [ ] Pause/Resume works (verify with `ps aux | grep python`)
- [ ] Terminate from progress window works
- [ ] Relaunch opens new app instance
- [ ] No processes: window closes immediately
- [ ] Stale PID: cleaned up on next check
