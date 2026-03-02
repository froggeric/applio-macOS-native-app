# Launcher Process Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:executing-plans to implement this plan task-by-task.

**Goal:** Refactor Applio.app to use a launcher process that spawns and monitors the wrapper, enabling proper log visibility and process control.

**Architecture:** A parent launcher process (`applio_launcher.py`) runs as the main entry point, spawning `macos_wrapper.py` as a child. Training logs are written to files and tailed by the launcher's progress window. Each process has its own event loop.

**Tech Stack:** Python 3.10, PyObjC (NSApplication, NSMenu, NSWindow), subprocess, signal handling, file tailing

---

## Task 0: Create Log File Redirection Patch

**Goal:** Modify the process tracking patch to redirect training stdout/stderr to log files.

**Files:**
- Modify: `patches/patch_process_tracking.py`

**Step 1: Update the patch pattern for training**

In `patch_run_train_script()`, change from:

```python
old_pattern = r'(\n\s+)(subprocess\.run\(command\))\n(\s+)(run_index_script\(model_name, index_algorithm\))\n(\s+)(return f"Model \{model_name\} trained successfully\."\n)'
```

To new pattern that captures the logs_path context and redirects output:

```python
def patch_run_train_script(content: str) -> tuple[str, bool]:
    """Patch run_train_script to track subprocess and redirect logs."""
    if '_track_process("training"' in content:
        return content, True

    # Find and replace subprocess.run(command) with log file redirection
    old_pattern = r'(\n\s+)(subprocess\.run\(command\))\n(\s+)(run_index_script\(model_name, index_algorithm\))\n(\s+)(return f"Model \{model_name\} trained successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] train pattern not found")
        return content, False

    replacement = r'''\1# Redirect training output to log file
\1log_file_path = os.path.join(logs_path, model_name, "training.log")
\1os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
\1log_file = open(log_file_path, "a")
\1_proc = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)
\1_track_process("training", _proc.pid, model_name=model_name, total_epoch=total_epoch, log_file=log_file_path)
\1_proc.wait()
\1log_file.close()
\1_untrack_process("training")
\1if _proc.returncode != 0:
\1    return f"Error: Training failed with code {_proc.returncode}"
\3\4
\5\6'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True
```

**Step 2: Update preprocess patch similarly**

```python
def patch_run_preprocess_script(content: str) -> tuple[str, bool]:
    """Patch run_preprocess_script to track subprocess and redirect logs."""
    if '_track_process("preprocess"' in content:
        return content, True

    old_pattern = r'(\n\s+)(subprocess\.run\(command\))\n(\s+)(return f"Model \{model_name\} preprocessed successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] preprocess pattern not found")
        return content, False

    replacement = r'''\1# Redirect preprocess output to log file
\1log_file_path = os.path.join(logs_path, model_name, "preprocess.log")
\1os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
\1log_file = open(log_file_path, "a")
\1_proc = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)
\1_track_process("preprocess", _proc.pid, model_name=model_name, log_file=log_file_path)
\1_proc.wait()
\1log_file.close()
\1_untrack_process("preprocess")
\1if _proc.returncode != 0:
\1    return f"Error: Preprocessing failed with code {_proc.returncode}"
\3\4'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True
```

**Step 3: Update extract patch similarly**

```python
def patch_run_extract_script(content: str) -> tuple[str, bool]:
    """Patch run_extract_script to track subprocess and redirect logs."""
    if '_track_process("extract"' in content:
        return content, True

    old_pattern = r'(\n\s+)(subprocess\.run\(command_1\))\n\n(\s+)(return f"Model \{model_name\} extracted successfully\."\n)'

    if not re.search(old_pattern, content):
        print("[patch_process_tracking] extract pattern not found")
        return content, False

    replacement = r'''\1# Redirect extract output to log file
\1log_file_path = os.path.join(logs_path, model_name, "extract.log")
\1os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
\1log_file = open(log_file_path, "a")
\1_proc = subprocess.Popen(command_1, stdout=log_file, stderr=subprocess.STDOUT)
\1_track_process("extract", _proc.pid, model_name=model_name, log_file=log_file_path)
\1_proc.wait()
\1log_file.close()
\1_untrack_process("extract")
\1if _proc.returncode != 0:
\1    return f"Error: Feature extraction failed with code {_proc.returncode}"

\3\4'''

    new_content = re.sub(old_pattern, replacement, content)
    return new_content, True
```

**Step 4: Verify patch file syntax**

Run: `python -c "import patches.patch_process_tracking"`
Expected: No errors

**Step 5: Commit**

```bash
git add patches/patch_process_tracking.py
git commit -m "feat(patches): add log file redirection for training subprocesses"
```

---

## Task 1: Create applio_launcher.py Foundation

**Goal:** Create the new launcher entry point with basic process spawning.

**Files:**
- Create: `applio_launcher.py`

**Step 1: Create the file with core structure**

```python
#!/usr/bin/env python3
"""
Applio Launcher - Process Group Leader

Main entry point for Applio.app. Spawns macos_wrapper.py as a child process
and hosts the native progress monitoring window.

Architecture:
    applio_launcher.py (parent, process group leader)
        └── macos_wrapper.py (child)
                └── training subprocesses (grandchildren)
"""

# =================================================================
# 0. Multiprocessing Safety (MUST BE FIRST)
# =================================================================
import multiprocessing
multiprocessing.freeze_support()

# =================================================================
# 1. Imports & Environment Setup
# =================================================================
import os
import sys
import signal
import subprocess
import threading
import json
import logging
import datetime
from pathlib import Path

# macOS native APIs
try:
    from AppKit import (
        NSApplication, NSApp, NSMenu, NSMenuItem, NSWindow,
        NSButton, NSTextField, NSProgressIndicator, NSScrollView,
        NSTextView, NSMakeRect, NSTitledWindowMask, NSClosableWindowMask,
        NSBackingStoreBuffered, NSCenterTextAlignment, NSFont,
        NSBezelBorder, NSApplicationActivationPolicyRegular,
        NSMenu addItem_, NSMenuItem separatorItem
    )
    from Foundation import NSRunLoop, NSDate, NSNotificationCenter
    from PyObjCTools import AppHelper
    NATIVE_APIS_AVAILABLE = True
except ImportError:
    NATIVE_APIS_AVAILABLE = False
    print("WARNING: Native APIs not available. Install pyobjc.")

# Performance tuning for Apple Silicon
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["PYTORCH_ENABLE_METAL_ACCELERATOR"] = "1"

# Path setup for PyInstaller
if getattr(sys, "frozen", False):
    BASE_PATH = sys._MEIPASS
    os.chdir(BASE_PATH)
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# =================================================================
# 2. Constants & Configuration
# =================================================================
PROCESS_STATE_FILE = os.path.expanduser("~/.applio/active_processes.json")
LOG_TAIL_INTERVAL = 0.5  # seconds

# Logging setup
log_dir = os.path.expanduser("~/Library/Logs/Applio")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, "applio_launcher.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.info("[Launcher] Starting Applio Launcher")

# =================================================================
# 3. Process State Management
# =================================================================

def get_process_state_path():
    """Get path to active_processes.json."""
    data_path = os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))
    return os.path.join(data_path, ".applio", "active_processes.json")


def load_process_state():
    """Load process state from file."""
    path = get_process_state_path()
    if not os.path.exists(path):
        return {"version": 1, "processes": {}}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"version": 1, "processes": {}}


def save_process_state(state):
    """Save process state to file."""
    path = get_process_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as f:
        json.dump(state, f, indent=2)
    os.rename(temp, path)


def validate_process_state(state):
    """Remove stale entries where process has died."""
    import psutil
    cleaned = False

    for process_type, info in list(state.get("processes", {}).items()):
        if info is None:
            continue
        pid = info.get("pid")
        if pid and not psutil.pid_exists(pid):
            logging.info(f"[Launcher] Cleaning stale entry: {process_type} PID {pid}")
            state["processes"][process_type] = None
            cleaned = True

    return state, cleaned


def get_active_processes():
    """Get list of active processes."""
    state = load_process_state()
    state, _ = validate_process_state(state)
    return [
        {"type": ptype, **info}
        for ptype, info in state.get("processes", {}).items()
        if info and info.get("status") == "running"
    ]


# =================================================================
# 4. Progress Window Controller (moved from macos_wrapper.py)
# =================================================================

class ProgressWindowController:
    """Native macOS progress monitoring window with log tailing."""

    def __init__(self, process_type, process_info):
        if not NATIVE_APIS_AVAILABLE:
            raise RuntimeError("Native APIs not available")

        self.process_type = process_type
        self.process_info = process_info
        self.paused = False
        self.start_time = datetime.datetime.now()
        self.timer = None
        self._observer = None
        self.log_lines = []
        self.max_log_lines = 200
        self._last_file_pos = 0
        self._last_file_size = 0

        # Log file path
        self.log_file_path = process_info.get("log_file")

        # Create window
        self._create_window()
        self._create_ui()

    def _create_window(self):
        """Create the native window."""
        style = NSTitledWindowMask | NSClosableWindowMask
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 500, 500),
            style,
            NSBackingStoreBuffered,
            False
        )
        self.window.setTitle_(f"Applio - {self.process_type.capitalize()}")
        self.window.center()
        self.window.setReleasedWhenClosed_(False)

        # Register for close notification
        notification_center = NSNotificationCenter.defaultCenter()
        self._observer = notification_center.addObserver_selector_name_object_(
            self,
            "windowWillClose:",
            "NSWindowWillCloseNotification",
            self.window
        )

    def _create_ui(self):
        """Create UI elements."""
        window_width = 500
        padding = 15
        y = 500 - padding

        # Process type label (bold, larger)
        self.type_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 24, window_width - 2*padding, 24)
        )
        self.type_label.setStringValue_(f"{self.process_type.capitalize()}: {self.process_info.get('model_name', 'Unknown')}")
        self.type_label.setBezeled_(False)
        self.type_label.setDrawsBackground_(False)
        self.type_label.setEditable_(False)
        self.type_label.setFont_(NSFont.boldSystemFontOfSize_(16))
        self.window.contentView().addSubview_(self.type_label)
        y -= 30

        # Status label
        self.status_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 20, window_width - 2*padding, 20)
        )
        self.status_label.setStringValue_("Status: Running")
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        self.status_label.setEditable_(False)
        self.window.contentView().addSubview_(self.status_label)
        y -= 25

        # Elapsed time label
        self.time_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 18, window_width - 2*padding, 18)
        )
        self.time_label.setStringValue_("Elapsed: 00:00:00")
        self.time_label.setBezeled_(False)
        self.time_label.setDrawsBackground_(False)
        self.time_label.setEditable_(False)
        self.window.contentView().addSubview_(self.time_label)
        y -= 25

        # Progress bar (indeterminate)
        self.progress_bar = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(padding, y - 20, window_width - 2*padding, 20)
        )
        self.progress_bar.setIndeterminate_(True)
        self.progress_bar.startAnimation_(None)
        self.window.contentView().addSubview_(self.progress_bar)
        y -= 30

        # Log scroll view
        log_height = 250
        self.log_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(padding, y - log_height, window_width - 2*padding, log_height)
        )
        self.log_scroll.setHasVerticalScroller_(True)
        self.log_scroll.setBorderType_(NSBezelBorder)

        self.log_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, window_width - 2*padding - 20, log_height)
        )
        self.log_view.setEditable_(False)
        self.log_view.setFont_(NSFont.systemFontOfSize_(11))
        self.log_view.setString_("Waiting for log output...")
        self.log_scroll.setDocumentView_(self.log_view)
        self.window.contentView().addSubview_(self.log_scroll)
        y -= log_height + padding

        # Buttons row
        button_width = 100
        button_height = 28
        button_y = padding

        # Terminate button (left)
        self.terminate_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(padding, button_y, button_width, button_height)
        )
        self.terminate_btn.setTitle_("Terminate")
        self.terminate_btn.setTarget_(self)
        self.terminate_btn.setAction_("terminateProcess:")
        self.window.contentView().addSubview_(self.terminate_btn)

        # Pause/Resume button (center-left)
        self.pause_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(padding + button_width + 10, button_y, button_width, button_height)
        )
        self.pause_btn.setTitle_("Pause")
        self.pause_btn.setTarget_(self)
        self.pause_btn.setAction_("togglePause:")
        self.window.contentView().addSubview_(self.pause_btn)

        # Open Logs button (center-right)
        self.logs_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(padding + 2*(button_width + 10), button_y, button_width, button_height)
        )
        self.logs_btn.setTitle_("Open Logs")
        self.logs_btn.setTarget_(self)
        self.logs_btn.setAction_("openLogsFolder:")
        self.window.contentView().addSubview_(self.logs_btn)

        # Relaunch button (right)
        self.relaunch_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(padding + 3*(button_width + 10), button_y, button_width, button_height)
        )
        self.relaunch_btn.setTitle_("Relaunch App")
        self.relaunch_btn.setTarget_(self)
        self.relaunch_btn.setAction_("relaunchApp:")
        self.window.contentView().addSubview_(self.relaunch_btn)

        # Start elapsed time timer
        self._start_timer()

    def _start_timer(self):
        """Start the elapsed time update timer."""
        from AppKit import NSTimer
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "updateElapsedTime:", None, True
        )

    def updateElapsedTime_(self, timer):
        """Update elapsed time display."""
        elapsed = datetime.datetime.now() - self.start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.time_label.setStringValue_(f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}")

        # Also poll log file
        self.pollLogFile_(None)

        # Check if process still running
        import psutil
        pid = self.process_info.get("pid")
        if pid and not psutil.pid_exists(pid):
            self.status_label.setStringValue_("Status: Completed")
            self.progress_bar.stopAnimation_(None)

    def pollLogFile_(self, timer):
        """Poll log file for new content."""
        if not self.log_file_path or not os.path.exists(self.log_file_path):
            return

        try:
            current_size = os.path.getsize(self.log_file_path)
            if current_size > self._last_file_size:
                with open(self.log_file_path, "r") as f:
                    f.seek(self._last_file_pos)
                    new_content = f.read()
                    self._last_file_pos = f.tell()
                    self._last_file_size = current_size

                    for line in new_content.splitlines():
                        self._add_log_line(line)
        except Exception as e:
            logging.warning(f"[ProgressWindow] Error tailing log: {e}")

    def _add_log_line(self, line):
        """Add a line to the log view."""
        self.log_lines.append(line)
        if len(self.log_lines) > self.max_log_lines:
            self.log_lines = self.log_lines[-self.max_log_lines:]
        self.log_view.setString_("\n".join(self.log_lines))
        # Scroll to bottom
        self.log_scroll.reflectScrolledClipView_(self.log_scroll.contentView())

    def show(self):
        """Show the window and start log tailing."""
        self.window.makeKeyAndOrderFront_(None)
        logging.info(f"[ProgressWindow] Showing window for {self.process_type}")

        # Initial log read
        if self.log_file_path and os.path.exists(self.log_file_path):
            try:
                with open(self.log_file_path, "r") as f:
                    content = f.read()
                    self._last_file_pos = f.tell()
                    self._last_file_size = os.path.getsize(self.log_file_path)
                    for line in content.splitlines()[-50:]:  # Last 50 lines
                        self._add_log_line(line)
            except Exception as e:
                logging.warning(f"[ProgressWindow] Error reading initial log: {e}")

    def terminateProcess_(self, sender):
        """Terminate the process."""
        import psutil
        pid = self.process_info.get("pid")
        if pid and psutil.pid_exists(pid):
            psutil.Process(pid).terminate()
            self.status_label.setStringValue_("Status: Terminated")
            self._add_log_line(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process terminated by user")

    def togglePause_(self, sender):
        """Toggle pause/resume."""
        import psutil
        pid = self.process_info.get("pid")
        if not pid or not psutil.pid_exists(pid):
            return

        if self.paused:
            os.kill(pid, signal.SIGCONT)
            self.pause_btn.setTitle_("Pause")
            self.status_label.setStringValue_("Status: Running")
            self._add_log_line(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process resumed")
        else:
            os.kill(pid, signal.SIGSTOP)
            self.pause_btn.setTitle_("Resume")
            self.status_label.setStringValue_("Status: Paused")
            self._add_log_line(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process paused")
        self.paused = not self.paused

    def openLogsFolder_(self, sender):
        """Open logs folder in Finder."""
        model_name = self.process_info.get("model_name", "")
        if model_name:
            data_path = os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))
            logs_folder = os.path.join(data_path, "logs", model_name)
            if os.path.exists(logs_folder):
                subprocess.run(["open", logs_folder])
            else:
                subprocess.run(["open", os.path.join(data_path, "logs")])

    def relaunchApp_(self, sender):
        """Relaunch the main app."""
        if getattr(sys, 'frozen', False):
            app_path = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
            subprocess.Popen(['open', app_path])
        else:
            subprocess.Popen([sys.executable, os.path.join(BASE_PATH, 'applio_launcher.py')])

    def windowWillClose_(self, notification):
        """Handle window close."""
        self._cleanup()

    def _cleanup(self):
        """Clean up resources."""
        if self.timer:
            self.timer.invalidate()
            self.timer = None
        if self._observer:
            NSNotificationCenter.defaultCenter().removeObserver_(self._observer)
            self._observer = None


# =================================================================
# 5. Main Launcher Class
# =================================================================

class ApplioLauncher:
    """Main launcher managing wrapper process and UI."""

    def __init__(self):
        self.wrapper_process = None
        self.progress_window = None
        self._setup_signal_handlers()

    def start(self):
        """Main entry point."""
        logging.info("[Launcher] Starting...")

        # 1. Validate existing processes
        state = load_process_state()
        state, cleaned = validate_process_state(state)
        if cleaned:
            save_process_state(state)

        active = get_active_processes()

        # 2. Setup native menu
        self._setup_menu()

        # 3. If processes running, show progress window
        if active:
            logging.info(f"[Launcher] Found {len(active)} active processes")
            self._show_progress_window_for_processes(active)

        # 4. Spawn wrapper process
        self._spawn_wrapper()

        # 5. Run event loop
        logging.info("[Launcher] Starting event loop")
        AppHelper.runConsoleEventLoop(installInterrupt=True)

    def _setup_signal_handlers(self):
        """Setup signal handlers."""
        signal.signal(signal.SIGCHLD, self._handle_child_exit)
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_terminate)

    def _handle_child_exit(self, signum, frame):
        """Handle child process exit."""
        try:
            while True:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
                logging.info(f"[Launcher] Child process {pid} exited")
        except ChildProcessError:
            pass

    def _handle_interrupt(self, signum, frame):
        """Handle interrupt signal."""
        logging.info("[Launcher] Interrupt received, shutting down")
        self._cleanup()
        sys.exit(0)

    def _handle_terminate(self, signum, frame):
        """Handle terminate signal."""
        logging.info("[Launcher] Terminate received, shutting down")
        self._cleanup()
        sys.exit(0)

    def _spawn_wrapper(self):
        """Spawn macos_wrapper.py as child process."""
        wrapper_path = self._find_wrapper_path()
        if not wrapper_path:
            logging.error("[Launcher] Could not find macos_wrapper.py")
            sys.exit(1)

        logging.info(f"[Launcher] Spawning wrapper: {wrapper_path}")

        self.wrapper_process = subprocess.Popen(
            [sys.executable, wrapper_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )

        # Save wrapper PID
        state = load_process_state()
        state["wrapper_pid"] = self.wrapper_process.pid
        save_process_state(state)

        logging.info(f"[Launcher] Wrapper spawned with PID {self.wrapper_process.pid}")

        # Start thread to read wrapper output
        threading.Thread(target=self._read_wrapper_output, daemon=True).start()

    def _find_wrapper_path(self):
        """Find macos_wrapper.py path."""
        candidates = [
            os.path.join(BASE_PATH, "macos_wrapper.py"),
            os.path.join(os.path.dirname(BASE_PATH), "macos_wrapper.py"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def _read_wrapper_output(self):
        """Read stdout from wrapper."""
        for line in iter(self.wrapper_process.stdout.readline, ''):
            if line:
                logging.info(f"[Wrapper] {line.rstrip()}")

    def _setup_menu(self):
        """Setup native macOS menu."""
        if not NATIVE_APIS_AVAILABLE:
            return

        # Create app menu
        app_menu = NSMenu.alloc().init()

        # Add menu items...
        # (Full menu implementation here)

        NSApp.setMainMenu_(app_menu)

    def _show_progress_window_for_processes(self, processes):
        """Show progress window for the first active process."""
        if not processes:
            return

        proc = processes[0]
        self.progress_window = ProgressWindowController(
            proc["type"],
            {k: v for k, v in proc.items() if k != "type"}
        )
        self.progress_window.show()

    def _cleanup(self):
        """Clean up on exit."""
        if self.wrapper_process and self.wrapper_process.poll() is None:
            self.wrapper_process.terminate()


# =================================================================
# 6. Entry Point
# =================================================================

if __name__ == "__main__":
    launcher = ApplioLauncher()
    launcher.start()
```

**Step 2: Verify syntax**

Run: `python -m py_compile applio_launcher.py`
Expected: No errors

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat: add applio_launcher.py as new entry point"
```

---

## Task 2: Update build_macos.py Entry Point

**Goal:** Change PyInstaller entry point from macos_wrapper.py to applio_launcher.py.

**Files:**
- Modify: `build_macos.py`

**Step 1: Find the entry point configuration**

Look for `entry_point` or `script` setting in build_macos.py, change:

```python
# OLD
script='macos_wrapper.py',

# NEW
script='applio_launcher.py',
```

**Step 2: Verify spec file generation includes both files**

Ensure both applio_launcher.py and macos_wrapper.py are included in the bundle:

```python
# In datas or hiddenimports
datas=[
    ('applio_launcher.py', '.'),
    ('macos_wrapper.py', '.'),
    # ... other files
],
```

**Step 3: Test build**

Run: `venv_macos/bin/python build_macos.py`
Expected: Build succeeds, Applio.app created

**Step 4: Commit**

```bash
git add build_macos.py
git commit -m "feat(build): change entry point to applio_launcher.py"
```

---

## Task 3: Refactor macos_wrapper.py - Remove Progress Window

**Goal:** Remove progress window code from wrapper since it's now in launcher.

**Files:**
- Modify: `macos_wrapper.py`

**Step 1: Remove ProgressWindowController class**

Delete the entire `ProgressWindowController` class (~350 lines).

**Step 2: Remove show_progress_window() function**

Delete the `show_progress_window()` function.

**Step 3: Simplify on_window_closing()**

Replace the complex close logic with simple hide:

```python
def on_window_closing():
    """Handle window close - just hide, launcher handles the rest."""
    global window

    logging.info("[Window] Close requested, hiding window")

    # Check for active processes
    processes = get_active_process_list()
    if processes:
        logging.info(f"[Window] {len(processes)} active processes, hiding window")

    # Just hide - launcher will show progress window if needed
    window.hide()
    return False  # Don't destroy
```

**Step 4: Remove related globals and imports**

Remove:
- `_progress_window_controller` global
- Unused PyObjC imports for progress window

**Step 5: Test wrapper still launches Gradio**

Run: `python macos_wrapper.py`
Expected: Gradio UI opens normally

**Step 6: Commit**

```bash
git add macos_wrapper.py
git commit -m "refactor(wrapper): remove progress window code moved to launcher"
```

---

## Task 4: Implement Full Menu in Launcher

**Goal:** Add complete native menu with Window → Progress Monitor option.

**Files:**
- Modify: `applio_launcher.py`

**Step 1: Implement _setup_menu method**

```python
def _setup_menu(self):
    """Setup native macOS menu bar."""
    from AppKit import (
        NSMenu, NSMenuItem, NSApp, NSApplicationActivationPolicyRegular
    )

    # Set app activation policy
    NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    # Create main menu bar
    main_menu = NSMenu.alloc().init()

    # App menu (Applio)
    app_menu = NSMenu.alloc().init()

    app_item = NSMenuItem.alloc().init()
    app_item.setSubmenu_(app_menu)
    main_menu.addItem_(app_item)

    # About
    about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "About Applio", "showAbout:", ""
    )
    app_menu.addItem_(about_item)

    # Check for Updates
    update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Check for Updates...", "checkUpdates:", ""
    )
    app_menu.addItem_(update_item)

    app_menu.addItem_(NSMenuItem.separatorItem())

    # Quit
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit Applio", "terminate:", "q"
    )
    app_menu.addItem_(quit_item)

    # File menu
    file_menu = NSMenu.alloc().initWithTitle_("File")

    file_item = NSMenuItem.alloc().init()
    file_item.setSubmenu_(file_menu)
    main_menu.addItem_(file_item)

    # Set Data Location
    data_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Set Data Location...", "setDataLocation:", ""
    )
    file_menu.addItem_(data_item)

    # Window menu
    window_menu = NSMenu.alloc().initWithTitle_("Window")

    window_item = NSMenuItem.alloc().init()
    window_item.setSubmenu_(window_menu)
    main_menu.addItem_(window_item)

    # Progress Monitor
    self.progress_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Progress Monitor", "showProgressMonitor:", "m"
    )
    self.progress_menu_item.setEnabled_(False)
    window_menu.addItem_(self.progress_menu_item)

    window_menu.addItem_(NSMenuItem.separatorItem())

    # Show Main Window
    main_window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Show Main Window", "showMainWindow:", "w"
    )
    window_menu.addItem_(main_window_item)

    # Minimize
    minimize_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Minimize", "performMiniaturize:", "m"
    )
    minimize_item.setKeyEquivalentModifierMask_(1048576)  # Command
    window_menu.addItem_(minimize_item)

    NSApp.setMainMenu_(main_menu)

    # Update progress menu item state
    self._update_menu_state()

def _update_menu_state(self):
    """Update menu item states based on running processes."""
    active = get_active_processes()
    has_active = len(active) > 0
    self.progress_menu_item.setEnabled_(has_active)
    if has_active:
        self.progress_menu_item.setTitle_(f"Progress Monitor ({len(active)} active)")
    else:
        self.progress_menu_item.setTitle_("Progress Monitor")

def showProgressMonitor_(self, sender):
    """Show progress monitor window."""
    active = get_active_processes()
    if active:
        self._show_progress_window_for_processes(active)

def showMainWindow_(self, sender):
    """Show main Gradio window (wrapper handles this)."""
    pass  # Window is managed by wrapper
```

**Step 2: Test menu appears**

Run: `python applio_launcher.py`
Expected: Menu bar appears with Applio, File, Window menus

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(launcher): add native menu with Progress Monitor option"
```

---

## Task 5: Integration Testing

**Goal:** Verify the complete launcher architecture works end-to-end.

**Files:**
- Test: Manual testing

**Step 1: Build the app**

Run: `venv_macos/bin/python build_macos.py`
Expected: Build succeeds

**Step 2: Launch app and verify Gradio opens**

Run: `open dist/Applio.app`
Expected: Gradio UI opens in pywebview window

**Step 3: Start training and verify log file created**

1. Go to Train tab
2. Configure and start training
3. Check `~/Applio/logs/{model_name}/training.log` exists
Expected: Log file contains training output

**Step 4: Close window and verify progress monitor appears**

1. Close the main window (Cmd+W)
2. Expected: Progress monitor window appears with log tailing

**Step 5: Test pause/resume/terminate**

1. Click Pause - training should pause
2. Click Resume - training should resume
3. Click Terminate - training should stop

**Step 6: Test relaunch while training**

1. Start training
2. Close app completely (Cmd+Q)
3. Re-open Applio.app
4. Expected: Progress monitor shows automatically

**Step 7: Commit final state**

```bash
git add -A
git commit -m "test: verify launcher architecture integration"
```

---

## Summary

| Task | Description | Estimated Time |
|------|-------------|----------------|
| 0 | Create log file redirection patch | 15 min |
| 1 | Create applio_launcher.py foundation | 30 min |
| 2 | Update build_macos.py entry point | 10 min |
| 3 | Refactor macos_wrapper.py | 20 min |
| 4 | Implement full menu in launcher | 20 min |
| 5 | Integration testing | 30 min |

**Total: ~2 hours**

## Dependencies

```
Task 0 (patch) ──► Task 1 (launcher) ──► Task 2 (build) ──► Task 3 (refactor) ──► Task 4 (menu) ──► Task 5 (test)
```
