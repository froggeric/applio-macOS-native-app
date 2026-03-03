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
import queue
import json
import logging
import datetime
import fcntl
import time
from pathlib import Path
from collections import deque

# macOS native APIs
try:
    from AppKit import (
        NSApplication, NSApp, NSMenu, NSMenuItem, NSWindow,
        NSButton, NSTextField, NSProgressIndicator, NSScrollView,
        NSTextView, NSMakeRect, NSTitledWindowMask, NSClosableWindowMask,
        NSBackingStoreBuffered, NSCenterTextAlignment, NSFont,
        NSBezelBorder, NSApplicationActivationPolicyRegular,
        NSAccessibilityAnnouncementRequestedNotification,
        NSCommandKeyMask, NSShiftKeyMask, NSBox, NSColor,
        NSFontWeightMedium,
    )
    from Foundation import NSRunLoop, NSDate, NSNotificationCenter, NSURL
    from PyObjCTools import AppHelper

    NATIVE_APIS_AVAILABLE = True
except ImportError:
    NATIVE_APIS_AVAILABLE = False
    print("WARNING: Native APIs not available. Install pyobjc.")


# Define accessibility announcement function based on API availability
# CRITICAL: Define ONCE, not redefined in nested try/except
if NATIVE_APIS_AVAILABLE:
    try:
        from AppKit import NSAccessibilityPostNotification

        def _announce_for_accessibility(element, message):
            """Post an accessibility announcement for VoiceOver users."""
            try:
                # Use userInfo dictionary for the announcement message
                userInfo = {"AXAnnouncementKey": message}
                NSAccessibilityPostNotification(
                    element,
                    NSAccessibilityAnnouncementRequestedNotification,
                    userInfo
                )
            except Exception:
                pass  # Silently fail if accessibility not available
    except ImportError:
        # Fallback for older PyObjC versions without NSAccessibilityPostNotification
        def _announce_for_accessibility(element, message):
            """Post an accessibility announcement using NSNotificationCenter."""
            try:
                NSNotificationCenter.defaultCenter().postNotificationName_object_userInfo_(
                    "AXAnnouncementRequested", element, {"AXAnnouncementKey": message}
                )
            except Exception:
                pass
else:
    # Fallback when native APIs are not available at all
    def _announce_for_accessibility(element, message):
        """No-op fallback when native APIs are unavailable."""
        pass

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
# 2. Subprocess Mode Detection (MUST BE BEFORE LOGGING)
# =================================================================
# In PyInstaller frozen apps, sys.executable points to this launcher.
# When subprocesses are spawned via subprocess.Popen([sys.executable, "script.py"]),
# this launcher is re-executed with the script path as argv[1].
# We detect this and delegate to the script via runpy.
#
# This handles:
# - macos_wrapper.py (spawner for Gradio UI)
# - rvc/train/train.py (training)
# - rvc/train/preprocess/preprocess.py (preprocessing)
# - rvc/train/extract/extract.py (feature extraction)
# - Any other Python scripts spawned by core.py

if len(sys.argv) > 1:
    potential_script = sys.argv[1]
    # Accept any .py script, not just macos_wrapper.py
    if potential_script.endswith('.py') and not potential_script.startswith('-'):
        # Find the script - check both absolute path and relative to BASE_PATH
        script_path = None
        if os.path.exists(potential_script):
            script_path = potential_script
        elif os.path.exists(os.path.join(BASE_PATH, potential_script)):
            script_path = os.path.join(BASE_PATH, potential_script)

        if script_path:
            # Add script's directory to sys.path so relative imports work
            # This is needed because runpy.run_path doesn't add the script's dir to path
            script_dir = os.path.dirname(os.path.abspath(script_path))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

            # Delegate to script via runpy
            import runpy
            sys.argv = [script_path] + sys.argv[2:]
            runpy.run_path(script_path, run_name="__main__")
            sys.exit(0)

# =================================================================
# 3. Constants & Configuration
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
# 4. Process State Management (with file locking)
# =================================================================

# Thread lock for in-memory state access
_state_lock = threading.Lock()

# File lock timeout in seconds
FILE_LOCK_TIMEOUT = 5.0


def get_process_state_path():
    """Get path to active_processes.json.

    Checks multiple sources for the data path:
    1. APPLIO_DATA_PATH environment variable
    2. runtime_paths.json (written by wrapper)
    3. Default ~/Applio
    """
    # First check environment variable
    data_path = os.environ.get("APPLIO_DATA_PATH")
    if data_path:
        return os.path.join(data_path, ".applio", "active_processes.json")

    # Check runtime_paths.json (written by wrapper at startup)
    runtime_config_paths = [
        os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
        os.path.expanduser("~/.applio/runtime_paths.json"),
    ]
    for config_path in runtime_config_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                    data_path = config.get("data_path")
                    if data_path:
                        return os.path.join(data_path, ".applio", "active_processes.json")
            except (json.JSONDecodeError, IOError):
                pass

    # Fallback to default
    data_path = os.path.expanduser("~/Applio")
    return os.path.join(data_path, ".applio", "active_processes.json")


def _acquire_file_lock(lock_file, timeout=FILE_LOCK_TIMEOUT):
    """Acquire exclusive file lock with timeout."""
    start_time = time.time()
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            if time.time() - start_time > timeout:
                return False
            time.sleep(0.05)


def _release_file_lock(lock_file):
    """Release file lock."""
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except (IOError, OSError):
        pass


def load_process_state():
    """Load process state from file with locking."""
    path = get_process_state_path()
    if not os.path.exists(path):
        return {"version": 1, "processes": {}}

    lock_path = path + ".lock"
    try:
        # Use "a" mode to avoid truncating before lock is acquired
        with open(lock_path, "a") as lock_file:
            if not _acquire_file_lock(lock_file):
                logging.warning("[Launcher] Could not acquire lock for reading, proceeding anyway")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            finally:
                _release_file_lock(lock_file)
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"[Launcher] Error reading process state: {e}")
        return {"version": 1, "processes": {}}


def save_process_state(state):
    """Save process state to file with locking."""
    path = get_process_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    lock_path = path + ".lock"
    try:
        # Use "a" mode to avoid truncating before lock is acquired
        with open(lock_path, "a") as lock_file:
            if not _acquire_file_lock(lock_file):
                logging.warning("[Launcher] Could not acquire lock for writing, proceeding anyway")
            try:
                temp = path + ".tmp"
                with open(temp, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
                os.rename(temp, path)
            finally:
                _release_file_lock(lock_file)
    except IOError as e:
        logging.error(f"[Launcher] Error saving process state: {e}")


def verify_process_identity(pid, expected_start_time=None):
    """
    Verify a process is still the same one we started.

    PID recycling on macOS means a PID can be reassigned after a process dies.
    We verify by checking that the process creation time matches what we expect.

    Args:
        pid: Process ID to verify
        expected_start_time: ISO format datetime string or datetime object of when we started the process

    Returns:
        bool: True if process exists AND is the same process we started
    """
    import psutil

    if not pid:
        return False

    try:
        proc = psutil.Process(pid)

        # If we have an expected start time, verify it matches
        if expected_start_time:
            if isinstance(expected_start_time, str):
                expected = datetime.datetime.fromisoformat(expected_start_time)
            else:
                expected = expected_start_time

            # Allow 2 second tolerance for timing differences
            actual = datetime.datetime.fromtimestamp(proc.create_time())
            delta = abs((actual - expected).total_seconds())

            if delta > 2.0:
                logging.warning(f"[Launcher] PID {pid} recycled (time delta: {delta}s)")
                return False

        return True

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def validate_process_state(state):
    """Remove stale entries where process has died (with PID recycling protection)."""
    import psutil
    cleaned = False

    for process_type, info in list(state.get("processes", {}).items()):
        if info is None:
            continue
        pid = info.get("pid")
        started_at = info.get("started_at")

        # Use identity verification instead of just pid_exists
        if pid and not verify_process_identity(pid, started_at):
            logging.info(f"[Launcher] Cleaning stale entry: {process_type} PID {pid}")
            state["processes"][process_type] = None
            cleaned = True

    return state, cleaned


def get_active_processes():
    """Get list of active processes (thread-safe)."""
    with _state_lock:
        state = load_process_state()
        state, _ = validate_process_state(state)
        return [
            {"type": ptype, **info}
            for ptype, info in state.get("processes", {}).items()
            if info and info.get("status") == "running"
        ]


# =================================================================
# 5. Progress Window Controller (moved from macos_wrapper.py)
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
        self.log_lines = deque(maxlen=200)  # Efficient O(1) append with auto-trimming
        self._last_file_pos = 0
        self._last_file_size = 0
        # Smart log display state
        self._live_phase = None          # Current phase name
        self._live_phase_start = None    # Timestamp when phase started
        self._last_tqdm_time = None      # Timestamp of last tqdm activity
        self._last_non_tqdm_line = ""    # For phase name detection
        # Epoch tracking for progress bar
        self._total_epoch = process_info.get('total_epoch')
        self._current_epoch = 0
        self.window = None  # Initialize to None for safe cleanup

        # Log file path
        self.log_file_path = process_info.get("log_file")

        # Create window with exception safety
        try:
            self._create_window()
            self._create_ui()
        except Exception:
            # Ensure observer is removed if initialization fails
            self._cleanup()
            raise

    def _create_window(self):
        """Create the native window."""
        style = NSTitledWindowMask | NSClosableWindowMask
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 500, 580),
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
        """Create UI elements with accessibility support."""
        window_width = 500
        padding = 15
        y = 580 - padding

        # Set window accessibility
        self.window.setAccessibilityLabel_(f"Applio {self.process_type.capitalize()} Progress")
        self.window.setAccessibilityHelp_(f"Monitoring window for {self.process_type} process")

        # Process type label (bold, larger)
        self.type_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 24, window_width - 2*padding, 24)
        )
        model_name = self.process_info.get('model_name', 'Unknown')
        self.type_label.setStringValue_(f"{self.process_type.capitalize()}: {model_name}")
        self.type_label.setBezeled_(False)
        self.type_label.setDrawsBackground_(False)
        self.type_label.setEditable_(False)
        self.type_label.setFont_(NSFont.boldSystemFontOfSize_(16))
        # Accessibility
        self.type_label.setAccessibilityLabel_(f"{self.process_type.capitalize()} process for model {model_name}")
        self.type_label.setAccessibilityIdentifier_("process_type_label")
        self.window.contentView().addSubview_(self.type_label)

        # Status badge (pill-shaped, right side)
        badge_width = 80
        badge_height = 22
        self.status_badge = NSTextField.alloc().initWithFrame_(
            NSMakeRect(window_width - padding - badge_width, y - 22, badge_width, badge_height)
        )
        self.status_badge.setStringValue_("Running")
        self.status_badge.setBezeled_(False)
        self.status_badge.setDrawsBackground_(True)
        self.status_badge.setBackgroundColor_(NSColor.systemGreenColor().colorWithAlphaComponent_(0.2))
        self.status_badge.setEditable_(False)
        self.status_badge.setFont_(NSFont.systemFontOfSize_weight_(11, NSFontWeightMedium))
        self.status_badge.setTextColor_(NSColor.systemGreenColor())
        self.status_badge.setAlignment_(NSCenterTextAlignment)
        self.status_badge.setWantsLayer_(True)
        self.status_badge.layer().setCornerRadius_(11)
        self.status_badge.setAccessibilityLabel_("Process status badge")
        self.status_badge.setAccessibilityIdentifier_("status_badge")
        self.window.contentView().addSubview_(self.status_badge)
        y -= 30

        # Status label
        self.status_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 20, window_width - 2*padding, 20)
        )
        self.status_label.setStringValue_("Status: Running")
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        self.status_label.setEditable_(False)
        # Accessibility
        self.status_label.setAccessibilityLabel_("Process status")
        self.status_label.setAccessibilityHelp_("Current status of the process: Running, Paused, Completed, or Terminated")
        self.status_label.setAccessibilityIdentifier_("status_label")
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
        # Accessibility
        self.time_label.setAccessibilityLabel_("Elapsed time")
        self.time_label.setAccessibilityHelp_("Time elapsed since the process started")
        self.time_label.setAccessibilityIdentifier_("elapsed_time_label")
        self.window.contentView().addSubview_(self.time_label)
        y -= 25

        # Progress bar - use determinate mode if we have epoch info
        total_epoch = self.process_info.get('total_epoch', 0)
        self.progress_bar = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(padding, y - 20, window_width - 2*padding, 20)
        )
        if total_epoch and total_epoch > 0:
            self.progress_bar.setIndeterminate_(False)
            self.progress_bar.setMinValue_(0)
            self.progress_bar.setMaxValue_(total_epoch)
            self._total_epoch = total_epoch
            self._current_epoch = 0
        else:
            self.progress_bar.setIndeterminate_(True)
            self.progress_bar.startAnimation_(None)
            self._total_epoch = None
            self._current_epoch = None
        # Accessibility
        self.progress_bar.setAccessibilityLabel_("Progress indicator")
        if total_epoch and total_epoch > 0:
            self.progress_bar.setAccessibilityHelp_(f"Training progress: 0 of {total_epoch} epochs")
        else:
            self.progress_bar.setAccessibilityHelp_("Shows that the process is actively running")
        self.progress_bar.setAccessibilityIdentifier_("progress_bar")
        self.window.contentView().addSubview_(self.progress_bar)
        y -= 30

        # Live zone separator (top)
        self.live_separator_top = NSBox.alloc().initWithFrame_(
            NSMakeRect(padding, y - 2, window_width - 2*padding, 2)
        )
        self.live_separator_top.setBoxType_(1)  # NSBoxSeparator = 1
        self.window.contentView().addSubview_(self.live_separator_top)
        y -= 4

        # Live zone - single line for active tqdm progress
        LIVE_ZONE_HEIGHT = 24
        self.live_zone = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - LIVE_ZONE_HEIGHT, window_width - 2*padding, LIVE_ZONE_HEIGHT)
        )
        self.live_zone.setStringValue_("Waiting for progress...")  # Placeholder until tqdm detected
        self.live_zone.setBezeled_(False)
        self.live_zone.setDrawsBackground_(True)
        self.live_zone.setBackgroundColor_(NSColor.controlBackgroundColor())
        self.live_zone.setEditable_(False)
        self.live_zone.setFont_(NSFont.systemFontOfSize_weight_(12, NSFontWeightMedium))
        self.live_zone.setTextColor_(NSColor.systemBlueColor())
        self.live_zone.setAlignment_(NSCenterTextAlignment)
        self.live_zone.setAccessibilityLabel_("Live progress")
        self.live_zone.setAccessibilityHelp_("Current operation progress")
        self.live_zone.setAccessibilityIdentifier_("live_zone")
        self.window.contentView().addSubview_(self.live_zone)
        y -= LIVE_ZONE_HEIGHT

        # Live zone separator (bottom)
        self.live_separator_bottom = NSBox.alloc().initWithFrame_(
            NSMakeRect(padding, y - 2, window_width - 2*padding, 2)
        )
        self.live_separator_bottom.setBoxType_(1)  # NSBoxSeparator = 1
        self.window.contentView().addSubview_(self.live_separator_bottom)
        y -= 6

        # Log scroll view
        log_height = 216  # Reduced from 250 to make room for live zone
        self.log_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(padding, y - log_height, window_width - 2*padding, log_height)
        )
        self.log_scroll.setHasVerticalScroller_(True)
        self.log_scroll.setBorderType_(NSBezelBorder)
        # Accessibility
        self.log_scroll.setAccessibilityLabel_("Log output")
        self.log_scroll.setAccessibilityHelp_("Real-time log output from the training process")
        self.log_scroll.setAccessibilityIdentifier_("log_scroll_view")

        self.log_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, window_width - 2*padding - 20, log_height)
        )
        self.log_view.setEditable_(False)
        self.log_view.setFont_(NSFont.systemFontOfSize_(11))
        self.log_view.setString_("Waiting for log output...")
        # Accessibility - enable explicitly and set attributes
        self.log_view.setAccessibilityEnabled_(True)
        self.log_view.setAccessibilityLabel_("Log output")
        self.log_view.setAccessibilityHelp_("Training and processing log messages")
        self.log_view.setAccessibilityIdentifier_("log_text_view")
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
        # Accessibility
        self.terminate_btn.setAccessibilityLabel_("Terminate process")
        self.terminate_btn.setAccessibilityHelp_("Stop the process immediately. The process will not complete its current task.")
        self.terminate_btn.setAccessibilityIdentifier_("terminate_button")
        self.window.contentView().addSubview_(self.terminate_btn)

        # Pause/Resume button (center-left)
        self.pause_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(padding + button_width + 10, button_y, button_width, button_height)
        )
        self.pause_btn.setTitle_("Pause")
        self.pause_btn.setTarget_(self)
        self.pause_btn.setAction_("togglePause:")
        # Accessibility
        self.pause_btn.setAccessibilityLabel_("Pause or resume process")
        self.pause_btn.setAccessibilityHelp_("Temporarily pause the process or resume a paused process")
        self.pause_btn.setAccessibilityIdentifier_("pause_button")
        self.window.contentView().addSubview_(self.pause_btn)

        # Open Logs button (center-right)
        self.logs_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(padding + 2*(button_width + 10), button_y, button_width, button_height)
        )
        self.logs_btn.setTitle_("Open Logs")
        self.logs_btn.setTarget_(self)
        self.logs_btn.setAction_("openLogsFolder:")
        # Accessibility
        self.logs_btn.setAccessibilityLabel_("Open logs folder")
        self.logs_btn.setAccessibilityHelp_("Open the folder containing log files in Finder")
        self.logs_btn.setAccessibilityIdentifier_("open_logs_button")
        self.window.contentView().addSubview_(self.logs_btn)

        # Relaunch button (right)
        self.relaunch_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(padding + 3*(button_width + 10), button_y, button_width, button_height)
        )
        self.relaunch_btn.setTitle_("Relaunch App")
        self.relaunch_btn.setTarget_(self)
        self.relaunch_btn.setAction_("relaunchApp:")
        # Accessibility
        self.relaunch_btn.setAccessibilityLabel_("Relaunch application")
        self.relaunch_btn.setAccessibilityHelp_("Open a new instance of Applio while this process continues in the background")
        self.relaunch_btn.setAccessibilityIdentifier_("relaunch_button")
        self.window.contentView().addSubview_(self.relaunch_btn)

        # Start background file polling thread
        self._file_thread = None
        self._file_queue = None
        self._start_file_thread()
        self._start_timer()  # Start timer to process queue updates

    def _start_file_thread(self):
        """Start background thread for file polling."""
        import threading
        import queue

        self._file_queue = queue.Queue()
        self._file_thread = threading.Thread(target=self._file_poll_worker, daemon=True)
        self._file_thread.start()

    def _file_poll_worker(self):
        """Background worker thread for file polling."""
        MAX_INITIAL_LINES = 50  # Only show last 50 lines on initial read

        while True:
            time.sleep(0.5)  # Poll every 500ms

            if not self.log_file_path or not os.path.exists(self.log_file_path):
                continue

            try:
                current_size = os.path.getsize(self.log_file_path)
                if current_size > self._last_file_size:
                    with open(self.log_file_path, "r", encoding="utf-8", errors="replace") as f:
                        # If this is the first read (position 0), only read last portion
                        if self._last_file_pos == 0 and current_size > 0:
                            # Read from end of file, limiting to ~50 lines
                            # Estimate ~200 bytes per line on average
                            estimated_start = max(0, current_size - (MAX_INITIAL_LINES * 200))
                            f.seek(estimated_start)
                            content = f.read()
                            # Skip partial first line (we started mid-file)
                            if estimated_start > 0 and content:
                                first_newline = content.find('\n')
                                if first_newline >= 0:
                                    content = content[first_newline + 1:]
                            lines = content.splitlines()
                        else:
                            # Normal incremental read
                            f.seek(self._last_file_pos)
                            content = f.read()
                            lines = content.splitlines()

                        self._last_file_pos = f.tell()
                        self._last_file_size = current_size

                        # Parse lines and queue updates
                        for line in lines:
                            if not line.strip():
                                continue

                            # Check if this is a tqdm line
                            if self._is_tqdm_line(line):
                                # Parse tqdm and queue for live zone
                                tqdm_data = self._parse_tqdm_line(line)
                                if tqdm_data:
                                    # Detect phase from previous non-tqdm line
                                    phase_name = self._detect_phase_name(self._last_non_tqdm_line)
                                    self._file_queue.put(("tqdm", {"data": tqdm_data, "phase": phase_name}))
                            else:
                                # Non-tqdm line - store for phase detection and queue for logging
                                self._last_non_tqdm_line = line
                                # Parse epoch progress (for progress bar)
                                self._parse_epoch_progress_bg(line)
                                # Queue log line for main thread
                                self._file_queue.put(("log_line", line))
            except Exception as e:
                logging.warning(f"[ProgressWindow] Error in file poll worker: {e}")

    def _parse_epoch_progress_bg(self, line):
        """Parse epoch progress in background thread (no UI updates)."""
        if not self._total_epoch:
            return

        import re
        match = re.search(r'[Ee]poch[:\s]*(\d+)\s*/\s*(\d+)', line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            if total > 0 and current <= total:
                self._current_epoch = current
                if not self._total_epoch:
                    self._total_epoch = total
                # Queue progress update for main thread
                self._file_queue.put(("progress", {"current": current, "total": total}))

    def _is_tqdm_line(self, line):
        """Check if line is a tqdm progress bar update."""
        import re
        # Match patterns like: "  5%|▍         | 16/333 [00:18<04:36,  1.16it/s]"
        return bool(re.match(r'^\s*\d+%\|.*\|\s*\d+/\d+\s*\[', line))

    def _parse_tqdm_line(self, line):
        """Extract progress info from tqdm line.

        Returns dict with: percent, current, total, eta, rate, rate_unit
        or None if parsing fails.
        """
        import re
        # Pattern: "  5%|▍         | 16/333 [00:18<04:36,  1.16it/s]"
        match = re.match(
            r'^\s*(\d+)%\|.*\|\s*(\d+)/(\d+)\s*\[([^\]]+)\]',
            line
        )
        if not match:
            return None

        percent = int(match.group(1))
        current = int(match.group(2))
        total = int(match.group(3))
        bracket_content = match.group(4)

        # Parse bracket content: "00:18<04:36,  1.16it/s" or "00:18<04:36,  5.38s/it"
        eta = None
        rate = None
        rate_unit = None

        # Extract ETA (after <)
        eta_match = re.search(r'<\s*([\d:]+)', bracket_content)
        if eta_match:
            eta = eta_match.group(1)

        # Extract rate (after comma or at end)
        rate_match = re.search(r'([\d.]+)\s*(it/s|s/it)', bracket_content)
        if rate_match:
            rate = float(rate_match.group(1))
            rate_unit = rate_match.group(2)

        return {
            'percent': percent,
            'current': current,
            'total': total,
            'eta': eta,
            'rate': rate,
            'rate_unit': rate_unit
        }

    def _detect_phase_name(self, line):
        """Extract phase name from a log line.

        Looks for patterns like:
        - "Starting preprocessing..."
        - "[11:02:15] Starting preprocessing..."
        - "Preprocessing audio files..."
        - "Extracting features..."
        """
        import re

        # Strip timestamp prefix if present (e.g., "[11:02:15] ")
        stripped = re.sub(r'^\[\d{2}:\d{2}:\d{2}\]\s*', '', line)

        # Common phase patterns
        phase_patterns = [
            r'[Ss]tarting\s+(\w+)',
            r'^(\w+ing)\s+',  # "Preprocessing", "Extracting", "Training"
            r'^(\w+)\s+started',
        ]

        for pattern in phase_patterns:
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                phase = match.group(1).capitalize()
                # Normalize common variations
                phase_map = {
                    'Preprocess': 'Preprocessing',
                    'Extract': 'Extracting',
                    'Train': 'Training',
                    'Feature': 'Feature extraction',
                }
                return phase_map.get(phase, phase)

        return None

    def _update_live_zone(self, tqdm_data, phase_name=None):
        """Update the live zone display with current tqdm progress."""
        if phase_name and phase_name != self._live_phase:
            # Phase changed - log completion of previous phase
            if self._live_phase and self._live_phase_start:
                self._log_phase_completion()
            # Start new phase
            self._live_phase = phase_name
            self._live_phase_start = datetime.datetime.now()
            # Log phase start
            total_label = "files" if "preprocess" in phase_name.lower() else "items"
            self._add_log_line(f"{phase_name} started ({tqdm_data['total']} {total_label})")

        # Build display string
        phase = self._live_phase or "Processing"
        current = tqdm_data['current']
        total = tqdm_data['total']
        total_label = "files" if "preprocess" in phase.lower() else "items"

        parts = [f"  {phase}: {current}/{total} {total_label}"]

        if tqdm_data.get('eta'):
            parts.append(f"ETA: {tqdm_data['eta']}")

        if tqdm_data.get('rate'):
            parts.append(f"{tqdm_data['rate']:.2f}{tqdm_data['rate_unit']}")

        display_text = "  |  ".join(parts)
        self.live_zone.setStringValue_(display_text)

        # Update last activity time
        self._last_tqdm_time = datetime.datetime.now()

    def _log_phase_completion(self):
        """Log the completion of the current phase.

        Returns True if a phase was logged, False if no phase was active.
        """
        if not self._live_phase or not self._live_phase_start:
            return False

        # Calculate duration
        duration = datetime.datetime.now() - self._live_phase_start
        total_seconds = int(duration.total_seconds())
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if hours > 0:
            duration_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = f"{seconds}s"

        # Log completion
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        self._add_log_line(f"[{timestamp}] {self._live_phase} complete ({duration_str})")

        # Clear phase tracking
        self._live_phase = None
        self._live_phase_start = None
        return True

    def _start_timer(self):
        """Start a lightweight timer for UI updates from queue."""
        from AppKit import NSTimer
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "processQueueUpdates:", None, True
        )

    def processQueueUpdates_(self, timer):
        """Process pending updates from background thread (runs on main thread)."""
        # Update elapsed time
        elapsed = datetime.datetime.now() - self.start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.time_label.setStringValue_(f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}")

        # Process all pending updates from queue
        updates_processed = 0
        while updates_processed < 20:  # Limit to prevent blocking
            try:
                update_type, data = self._file_queue.get(block=False)
                updates_processed += 1

                if update_type == "log_line":
                    self._add_log_line(data)
                elif update_type == "tqdm":
                    # Update live zone with tqdm progress
                    self._update_live_zone(data["data"], data.get("phase"))
                elif update_type == "progress":
                    # Update progress bar
                    self.progress_bar.setDoubleValue_(data["current"])
                    self.progress_bar.setAccessibilityHelp_(
                        f"Training progress: Epoch {data['current']} of {data['total']}"
                    )
            except queue.Empty:
                break  # Queue empty
            except Exception as e:
                logging.error(f"[ProgressWindow] Error processing queue update: {e}")
                break

        # Check if process still running (with PID recycling protection)
        pid = self.process_info.get("pid")
        started_at = self.process_info.get("started_at")
        if pid and not verify_process_identity(pid, started_at):
            current_status = self.status_label.stringValue()
            if "Running" in current_status or "Paused" in current_status:
                self.status_label.setStringValue_("Status: Completed")
                if self._total_epoch:
                    self.progress_bar.setDoubleValue_(self._total_epoch)
                else:
                    self.progress_bar.stopAnimation_(None)
                _announce_for_accessibility(self.status_label, f"{self.process_type.capitalize()} process completed")

        # Check for live zone timeout (no tqdm for 2+ seconds)
        if self._last_tqdm_time and self._live_phase:
            elapsed = (datetime.datetime.now() - self._last_tqdm_time).total_seconds()
            if elapsed > 2.0:
                # Phase likely complete - log completion and clear live zone
                # _log_phase_completion returns True only if a phase was active
                if self._log_phase_completion():
                    self.live_zone.setStringValue_("Waiting for progress...")
                self._last_tqdm_time = None

    def _parse_epoch_progress(self, line):
        """Parse epoch progress from log line and update progress bar."""
        if not self._total_epoch:
            return

        import re
        # Match patterns like "Epoch 1/100" or "epoch 1/100" or "Epoch: 1/100"
        match = re.search(r'[Ee]poch[:\s]*(\d+)\s*/\s*(\d+)', line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            if total > 0 and current <= total:
                self._current_epoch = current
                if not self._total_epoch:
                    self._total_epoch = total
                # Update progress bar
                self.progress_bar.setDoubleValue_(current)
                # Update accessibility
                self.progress_bar.setAccessibilityHelp_(
                    f"Training progress: Epoch {current} of {total}"
                )

    def _add_log_line(self, line):
        """Add a line to the log view with buffer limit to prevent slowdowns."""
        MAX_LOG_LINES = 100  # Limit to prevent performance issues

        self.log_lines.append(line)

        # Trim old lines if buffer is too large
        if len(self.log_lines) > MAX_LOG_LINES:
            # Remove oldest lines and update text storage
            lines_to_remove = len(self.log_lines) - MAX_LOG_LINES
            self.log_lines = self.log_lines[lines_to_remove:]

            # Reset text storage with trimmed content (batch update)
            text_storage = self.log_view.textStorage()
            text_storage.beginEditing()
            text_storage.deleteCharactersInRange_((0, text_storage.length()))
            text_storage.appendString_("\n".join(self.log_lines))
            text_storage.endEditing()
        else:
            # Incremental update for small additions
            text_storage = self.log_view.textStorage()
            current_length = text_storage.length()

            # Add newline if not first line
            if current_length > 0 and not text_storage.string().endswith("\n"):
                text_storage.replaceCharactersInRange_withString_(
                    (current_length, 0), "\n"
                )
                current_length += 1

            # Append new line
            text_storage.replaceCharactersInRange_withString_(
                (current_length, 0), line
            )

        # Scroll to bottom only every 5 lines to reduce overhead
        if len(self.log_lines) % 5 == 0:
            text_storage = self.log_view.textStorage()
            self.log_view.scrollRangeToVisible_(
                (text_storage.length(), 0)
            )

    def show(self):
        """Show the window and start log tailing."""
        # Activate the application to ensure it receives events
        from AppKit import NSApplication, NSApplicationActivationPolicyRegular
        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)

        self.window.makeKeyAndOrderFront_(None)
        logging.info(f"[ProgressWindow] Showing window for {self.process_type}")

        # Initial log read - queue to background thread instead of blocking main thread
        # The background thread will pick up existing content on first poll
        if self.log_file_path and os.path.exists(self.log_file_path):
            try:
                # Just set the file position to 0 so background thread reads from start
                self._last_file_pos = 0
                self._last_file_size = 0
            except Exception as e:
                logging.warning(f"[ProgressWindow] Error setting initial file position: {e}")

    def terminateProcess_(self, sender):
        """Terminate the process."""
        pid = self.process_info.get("pid")
        started_at = self.process_info.get("started_at")
        if pid and verify_process_identity(pid, started_at):
            import psutil
            try:
                psutil.Process(pid).terminate()
                self.status_label.setStringValue_("Status: Terminated")
                self._add_log_line(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process terminated by user")
                # Accessibility announcement
                _announce_for_accessibility(self.status_label, f"{self.process_type.capitalize()} process terminated")
                # Update button accessibility
                self.terminate_btn.setEnabled_(False)
                self.terminate_btn.setAccessibilityHelp_("Process has been terminated")
                self.pause_btn.setEnabled_(False)
                self.pause_btn.setAccessibilityHelp_("Process has been terminated")
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError) as e:
                logging.warning(f"[ProgressWindow] Could not terminate process: {e}")
                self.status_label.setStringValue_("Status: Already terminated")

    def togglePause_(self, sender):
        """Toggle pause/resume."""
        pid = self.process_info.get("pid")
        started_at = self.process_info.get("started_at")
        if not pid or not verify_process_identity(pid, started_at):
            return

        try:
            if self.paused:
                os.kill(pid, signal.SIGCONT)
                self.pause_btn.setTitle_("Pause")
                self.pause_btn.setAccessibilityLabel_("Pause process")
                self.status_label.setStringValue_("Status: Running")
                self._add_log_line(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process resumed")
                # Accessibility announcement
                _announce_for_accessibility(self.status_label, f"{self.process_type.capitalize()} process resumed")
            else:
                os.kill(pid, signal.SIGSTOP)
                self.pause_btn.setTitle_("Resume")
                self.pause_btn.setAccessibilityLabel_("Resume process")
                self.status_label.setStringValue_("Status: Paused")
                self._add_log_line(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process paused")
                # Accessibility announcement
                _announce_for_accessibility(self.status_label, f"{self.process_type.capitalize()} process paused")
            self.paused = not self.paused
        except (ProcessLookupError, PermissionError, OSError) as e:
            logging.warning(f"[ProgressWindow] Could not toggle pause: {e}")
            self.status_label.setStringValue_("Status: Error controlling process")

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
        # Reset smart log display state
        self._live_phase = None
        self._live_phase_start = None
        self._last_tqdm_time = None
        self._last_non_tqdm_line = ""


# =================================================================
# 6. Main Launcher Class
# =================================================================

class ApplioLauncher:
    """Main launcher managing wrapper process and UI."""

    def __init__(self):
        self.wrapper_process = None
        self.progress_window = None
        self.progress_menu_item = None  # Reference to update state
        self._menu_update_timer = None
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
        AppHelper.runEventLoop(installInterrupt=True)

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

        # Set environment variable so wrapper knows it's running under launcher
        env = os.environ.copy()
        env["APPLIO_LAUNCHED_BY_LAUNCHER"] = "1"

        self.wrapper_process = subprocess.Popen(
            [sys.executable, wrapper_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
            env=env,  # Pass modified environment
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
        """Setup native macOS menu bar."""
        if not NATIVE_APIS_AVAILABLE:
            logging.warning("[Launcher] Native APIs not available, skipping menu setup")
            return

        from AppKit import NSApplicationActivationPolicyRegular, NSApplication

        # Ensure NSApplication is initialized
        app = NSApplication.sharedApplication()

        # Set app activation policy to show in Dock and menu bar
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

        # Create main menu bar
        main_menu = NSMenu.alloc().init()

        # =====================================================================
        # App menu (named "Applio" in menu bar)
        # =====================================================================
        app_menu = NSMenu.alloc().init()

        app_item = NSMenuItem.alloc().init()
        app_item.setSubmenu_(app_menu)
        main_menu.addItem_(app_item)

        # About Applio
        about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "About Applio", "showAbout:", ""
        )
        about_item.setAccessibilityHelp_("Show information about Applio version and credits")
        app_menu.addItem_(about_item)

        # Check for Updates...
        update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Check for Updates...", "checkUpdates:", ""
        )
        update_item.setAccessibilityHelp_("Open the releases page to check for new versions")
        app_menu.addItem_(update_item)

        app_menu.addItem_(NSMenuItem.separatorItem())

        # Quit Applio (Cmd+Q)
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Applio", "terminate:", "q"
        )
        quit_item.setAccessibilityHelp_("Exit Applio (Command Q)")
        app_menu.addItem_(quit_item)

        # =====================================================================
        # File menu
        # =====================================================================
        file_menu = NSMenu.alloc().initWithTitle_("File")

        file_item = NSMenuItem.alloc().init()
        file_item.setSubmenu_(file_menu)
        main_menu.addItem_(file_item)

        # Set Data Location...
        data_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Set Data Location...", "setDataLocation:", ""
        )
        data_item.setAccessibilityHelp_("Choose a folder to store Applio data including models and training files")
        file_menu.addItem_(data_item)

        # =====================================================================
        # Window menu
        # =====================================================================
        window_menu = NSMenu.alloc().initWithTitle_("Window")

        window_item = NSMenuItem.alloc().init()
        window_item.setSubmenu_(window_menu)
        main_menu.addItem_(window_item)

        # Progress Monitor (Cmd+Shift+P) - enabled only when processes active
        # Note: Using Cmd+Shift+P to avoid conflict with system Cmd+M (Minimize)
        self.progress_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Progress Monitor", "showProgressMonitor:", "P"
        )
        self.progress_menu_item.setKeyEquivalentModifierMask_(
            NSCommandKeyMask | NSShiftKeyMask
        )
        self.progress_menu_item.setEnabled_(False)
        self.progress_menu_item.setAccessibilityHelp_("Open the progress monitoring window for active training or inference processes")
        window_menu.addItem_(self.progress_menu_item)

        window_menu.addItem_(NSMenuItem.separatorItem())

        # Show Main Window (Cmd+Shift+W)
        main_window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Main Window", "showMainWindow:", "w"
        )
        # Cmd+Shift+W modifier
        main_window_item.setKeyEquivalentModifierMask_(1048576 | 131072)  # Command | Shift
        main_window_item.setAccessibilityHelp_("Bring the main Applio window to front (Command Shift W)")
        window_menu.addItem_(main_window_item)

        # Minimize (Cmd+M would conflict, use no shortcut or different)
        minimize_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Minimize", "performMiniaturize:", ""
        )
        minimize_item.setAccessibilityHelp_("Minimize the current window")
        window_menu.addItem_(minimize_item)

        # Set the menu
        NSApp.setMainMenu_(main_menu)

        # Update progress menu item state based on active processes
        self._update_menu_state()

        # Start periodic menu state updates
        self._start_menu_update_timer()

        logging.info("[Launcher] Menu bar setup complete")

    def _start_menu_update_timer(self):
        """Start timer to periodically update menu state."""
        if not NATIVE_APIS_AVAILABLE:
            return
        from AppKit import NSTimer
        self._menu_update_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0,  # Update every 2 seconds
            self,
            "menuUpdateTimerFired:",
            None,
            True
        )

    def menuUpdateTimerFired_(self, timer):
        """Periodic menu state update."""
        self._update_menu_state()

    def _check_wrapper_window_hidden(self):
        """Check if wrapper window was hidden (Keep Running clicked).

        Returns True if wrapper_window_visible is False in runtime config.
        Also resets the flag to True to prevent repeated triggers.
        """
        import json

        config_locations = [
            os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
            os.path.expanduser("~/.applio/runtime_paths.json"),
        ]

        for config_path in config_locations:
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)

                    # Check if wrapper window was hidden
                    if config.get("wrapper_window_visible") is False:
                        logging.info("[Launcher] Detected wrapper window hidden, showing progress window")

                        # Reset the flag to prevent repeated triggers
                        config["wrapper_window_visible"] = True
                        temp_path = config_path + ".tmp"
                        with open(temp_path, "w") as f:
                            json.dump(config, f, indent=2)
                        os.rename(temp_path, config_path)

                        return True
                except Exception as e:
                    logging.warning(f"[Launcher] Failed to check runtime config: {e}")

        return False

    def _update_menu_state(self):
        """Update menu item states based on running processes."""
        if not self.progress_menu_item:
            return

        # Check if wrapper window was hidden - if so, show progress window
        if self._check_wrapper_window_hidden():
            active = get_active_processes()
            logging.info(f"[Launcher] Wrapper hidden detected, found {len(active)} active processes")
            if active:
                try:
                    self._show_progress_window_for_processes(active)
                    logging.info("[Launcher] Progress window creation completed")
                except Exception as e:
                    logging.error(f"[Launcher] Failed to show progress window: {e}")
                    import traceback
                    traceback.print_exc()

        active = get_active_processes()
        has_active = len(active) > 0

        # Enable/disable Progress Monitor menu item
        self.progress_menu_item.setEnabled_(has_active)

        # Update title to show count
        if has_active:
            self.progress_menu_item.setTitle_(f"Progress Monitor ({len(active)} active)")
        else:
            self.progress_menu_item.setTitle_("Progress Monitor")

    # =====================================================================
    # Menu Action Methods
    # =====================================================================

    def showAbout_(self, sender):
        """Show About dialog."""
        if not NATIVE_APIS_AVAILABLE:
            return

        from AppKit import NSAlert, NSAlertStyleInformational

        # Load version from config
        version = "Unknown"
        try:
            import json
            config_path = os.path.join(BASE_PATH, "assets", "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                    version = config.get("version", "Unknown")
        except Exception:
            pass

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Applio")
        alert.setInformativeText_(
            f"Version {version}\n\n"
            "Voice Conversion Application\n"
            "Based on RVC (Retrieval-Based Voice Conversion)\n\n"
            "© 2024-2025 IA Hispano"
        )
        alert.setAlertStyle_(NSAlertStyleInformational)
        alert.addButtonWithTitle_("OK")
        # Accessibility - NSAlert is already accessible, but add help text
        alert.setAccessibilityHelp_("About Applio dialog showing version and copyright information")
        alert.runModal()

    def checkUpdates_(self, sender):
        """Check for updates."""
        if not NATIVE_APIS_AVAILABLE:
            return

        from AppKit import NSAlert, NSAlertStyleInformational

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Check for Updates")
        alert.setInformativeText_(
            "To check for updates, visit:\n\n"
            "https://github.com/froggeric/applio-macOS-native-app/releases"
        )
        alert.setAlertStyle_(NSAlertStyleInformational)
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    def setDataLocation_(self, sender):
        """Open dialog to set data location."""
        if not NATIVE_APIS_AVAILABLE:
            return

        from AppKit import NSOpenPanel, NSFileHandlingPanelOKButton

        # Create open panel configured to select folders
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setMessage_("Select a folder to store Applio data (models, training, logs):")
        panel.setPrompt_("Choose")

        # Get current data path as starting point
        current_path = os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))
        panel.setDirectoryURL_(NSURL.fileURLWithPath_(current_path))

        # Show panel
        result = panel.runModal()

        if result == NSFileHandlingPanelOKButton:
            urls = panel.URLs()
            if urls:
                new_path = urls[0].path()
                logging.info(f"[Launcher] User selected new data location: {new_path}")

                # Save preference via NSUserDefaults
                from Foundation import NSUserDefaults
                defaults = NSUserDefaults.standardUserDefaults()
                defaults.setObject_forKey_(new_path, "dataPath")

                # Notify user they need to restart
                from AppKit import NSAlert, NSAlertStyleWarning
                alert = NSAlert.alloc().init()
                alert.setMessageText_("Restart Required")
                alert.setInformativeText_(
                    f"Data location set to:\n{new_path}\n\n"
                    "Please restart Applio for this change to take effect."
                )
                alert.setAlertStyle_(NSAlertStyleWarning)
                alert.addButtonWithTitle_("OK")
                alert.runModal()

    def showProgressMonitor_(self, sender):
        """Show progress monitor window for active processes."""
        active = get_active_processes()
        if active:
            logging.info(f"[Launcher] Showing progress monitor for {len(active)} processes")
            self._show_progress_window_for_processes(active)
        else:
            logging.info("[Launcher] No active processes to monitor")

    def showMainWindow_(self, sender):
        """Show main Gradio window.

        Note: The main window is managed by macos_wrapper.py running in a subprocess.
        This menu item is primarily for user awareness; the wrapper handles window visibility.
        """
        logging.info("[Launcher] Show Main Window requested (window managed by wrapper subprocess)")
        # The main window is controlled by the wrapper subprocess
        # We could send a signal or use IPC to tell it to show, but for now just log

    def _show_progress_window_for_processes(self, processes):
        """Show progress window for the first active process."""
        logging.info(f"[Launcher] _show_progress_window_for_processes called with {len(processes)} processes")
        if not processes:
            logging.info("[Launcher] No processes to show, returning early")
            return

        # Clean up existing progress window before creating new one
        if self.progress_window:
            logging.info("[Launcher] Cleaning up existing progress window")
            self.progress_window._cleanup()
            if self.progress_window.window:
                self.progress_window.window.close()
            self.progress_window = None

        proc = processes[0]
        logging.info(f"[Launcher] Creating ProgressWindowController for {proc['type']}: {proc.get('model_name', 'Unknown')}")
        self.progress_window = ProgressWindowController(
            proc["type"],
            {k: v for k, v in proc.items() if k != "type"}
        )
        logging.info("[Launcher] Calling progress_window.show()")
        self.progress_window.show()
        logging.info("[Launcher] progress_window.show() completed")

    def _cleanup(self):
        """Clean up on exit."""
        # Stop menu update timer
        if self._menu_update_timer:
            self._menu_update_timer.invalidate()
            self._menu_update_timer = None

        # Clean up progress window (invalidates its timer and observer)
        if self.progress_window:
            self.progress_window._cleanup()
            self.progress_window = None

        # Terminate wrapper process
        if self.wrapper_process and self.wrapper_process.poll() is None:
            self.wrapper_process.terminate()


# =================================================================
# 7. Entry Point
# =================================================================

if __name__ == "__main__":
    launcher = ApplioLauncher()
    launcher.start()
