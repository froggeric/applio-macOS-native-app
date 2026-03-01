#!/usr/bin/env python3
"""
Applio macOS Native App Wrapper

Handles PyInstaller-specific requirements including:
- Multiprocessing support via freeze_support()
- Subprocess script execution mode detection
- Native macOS window management via pywebview
"""

# =================================================================
# 0. Multiprocessing Safety (MUST BE FIRST)
# =================================================================
# CRITICAL: This must run before any other imports or code.

import multiprocessing
multiprocessing.freeze_support()

# =================================================================
# 1. Minimal Imports & Environment Setup
# =================================================================
# These are needed for both script execution mode and GUI mode.

import os
import sys
import runpy
import signal
import datetime
import json
import logging
import urllib.request
import urllib.error

# macOS native APIs for preferences and dialogs
# These are conditional imports - only needed for GUI mode
try:
    from Foundation import NSUserDefaults, NSURL
    from AppKit import NSOpenPanel, NSWorkspace, NSModalResponseOK
    from PyObjCTools import AppHelper
    NATIVE_APIS_AVAILABLE = True
except ImportError:
    NATIVE_APIS_AVAILABLE = False

# Performance tuning for Apple Silicon
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["PYTORCH_ENABLE_METAL_ACCELERATOR"] = "1"

# GRADIO SECURITY & FILE ACCESS
os.environ["GRADIO_ALLOWED_PATHS"] = "/,/,/private/var/folders,/var/folders,/tmp,/private/tmp"
os.environ["GRADIO_TEMP_DIR"] = os.path.expanduser("~/Library/Caches/Applio/gradio")
os.makedirs(os.environ["GRADIO_TEMP_DIR"], exist_ok=True)

# Redirect Cache Directories to User Library
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/Applio")
os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
os.environ["HF_HOME"] = os.path.join(APP_SUPPORT_DIR, "huggingface")
os.environ["HF_DATASETS_CACHE"] = os.path.join(APP_SUPPORT_DIR, "huggingface", "datasets")
os.environ["TRANSFORMERS_CACHE"] = os.path.join(APP_SUPPORT_DIR, "huggingface", "models")
os.environ["MPLCONFIGDIR"] = os.path.join(APP_SUPPORT_DIR, "matplotlib")
os.environ["TORCH_HOME"] = os.path.join(APP_SUPPORT_DIR, "torch")

# Path Hygiene for PyInstaller
if getattr(sys, "frozen", False):
    BASE_PATH = sys._MEIPASS
    os.chdir(BASE_PATH)
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# =================================================================
# 1.4. Version Configuration
# =================================================================
# Version format: {APPLIO_VERSION}.{BUILD_NUMBER}
# Must match build_macos.py VERSION

def _get_applio_version():
    """Read version from assets/config.json (same as build_macos.py)."""
    import json
    config_path = os.path.join(BASE_PATH, "assets", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("version", "3.6.2")
    except Exception:
        return "3.6.2"

BUILD_NUMBER = 3  # Must match build_macos.py BUILD_NUMBER
APPLIO_VERSION = _get_applio_version()
VERSION = f"{APPLIO_VERSION}.{BUILD_NUMBER}"
GITHUB_REPO = "froggeric/applio-macOS-native-app"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

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


# =================================================================
# 1.7. Close Confirmation Dialog for Active Processes (Native macOS)
# =================================================================

# Global references to prevent garbage collection
_main_window_ref = None
_shutting_down = False  # Global flag to prevent multiple shutdown attempts
_progress_window_controller = None  # Native progress window controller


def show_close_confirmation_dialog():
    """Show native macOS confirmation dialog for active processes."""
    if not NATIVE_APIS_AVAILABLE:
        logging.warning("[CloseDialog] Native APIs not available, exiting")
        os._exit(0)
        return

    from AppKit import NSAlert, NSAlertFirstButtonReturn, NSAlertSecondButtonReturn

    # Get active processes for display
    processes = get_active_process_list()

    # Build process info text
    process_lines = []
    for p in processes:
        ptype = p.get("type", "unknown").capitalize()
        model = p.get("model_name") or p.get("details", "Running")
        process_lines.append(f"• {ptype}: {model}")

    process_info = "\n".join(process_lines) if process_lines else "Unknown processes"

    # Create native alert
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Active Processes Running")
    alert.setInformativeText_(
        f"The following processes are still running:\n\n{process_info}\n\n"
        "What would you like to do?"
    )
    alert.addButtonWithTitle_("Terminate & Quit")
    alert.addButtonWithTitle_("Keep Running in Background")
    alert.setAlertStyle_(2)  # NSAlertStyleWarning

    logging.info("[CloseDialog] Showing native NSAlert")
    response = alert.runModal()
    logging.info(f"[CloseDialog] User response: {response}")

    if response == NSAlertFirstButtonReturn:
        # Terminate & Quit
        logging.info("[CloseDialog] User chose to terminate and quit")
        ProcessController.terminate_all()
        os._exit(0)
    else:
        # Keep Running in Background
        logging.info("[CloseDialog] User chose to keep running")
        show_progress_window()


class ProgressWindowController:
    """Native macOS progress monitoring window."""

    def __init__(self, process_type, process_info):
        from AppKit import (
            NSWindow, NSButton, NSTextField, NSProgressIndicator,
            NSMakeRect, NSTitledWindowMask, NSClosableWindowMask,
            NSBackingStoreBuffered, NSCenterTextAlignment, NSFont,
            NSFontBoldSystemFont, NSFontSystemFontOfSize, NSColor
        )

        self.process_type = process_type
        self.process_info = process_info
        self.paused = False
        self.start_time = datetime.datetime.now()
        self.timer = None

        # Create window (400x300)
        style = NSTitledWindowMask | NSClosableWindowMask
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 400, 300),
            style,
            NSBackingStoreBuffered,
            False
        )
        self.window.setTitle_(f"Applio - {process_type.capitalize()}")
        self.window.center()
        self.window.setDelegate_(self)

        # Build UI elements
        y = 260  # Start from top
        label_height = 20
        button_height = 28
        padding = 12

        # Process type label (bold)
        self.type_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - label_height, 368, label_height)
        )
        self.type_label.setStringValue_(f"{process_type.capitalize()} Process")
        self.type_label.setBezeled_(False)
        self.type_label.setDrawsBackground_(False)
        self.type_label.setEditable_(False)
        self.type_label.setSelectable_(False)
        self.type_label.setAlignment_(NSCenterTextAlignment)
        bold_font = NSFont.boldSystemFontOfSize_(16)
        self.type_label.setFont_(bold_font)
        self.window.contentView().addSubview_(self.type_label)

        y -= label_height + padding

        # Details label (model name or other info)
        details = process_info.get("model_name") or process_info.get("details", "Running...")
        self.details_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - label_height, 368, label_height)
        )
        self.details_label.setStringValue_(details)
        self.details_label.setBezeled_(False)
        self.details_label.setDrawsBackground_(False)
        self.details_label.setEditable_(False)
        self.details_label.setSelectable_(False)
        self.details_label.setAlignment_(NSCenterTextAlignment)
        self.window.contentView().addSubview_(self.details_label)

        y -= label_height + padding

        # Elapsed time label
        self.time_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - label_height, 368, label_height)
        )
        self.time_label.setStringValue_("Elapsed: 00:00:00")
        self.time_label.setBezeled_(False)
        self.time_label.setDrawsBackground_(False)
        self.time_label.setEditable_(False)
        self.time_label.setSelectable_(False)
        self.time_label.setAlignment_(NSCenterTextAlignment)
        self.window.contentView().addSubview_(self.time_label)

        y -= label_height + padding

        # Status label
        self.status_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - label_height, 368, label_height)
        )
        self.status_label.setStringValue_("Status: Running")
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        self.status_label.setEditable_(False)
        self.status_label.setSelectable_(False)
        self.status_label.setAlignment_(NSCenterTextAlignment)
        self.window.contentView().addSubview_(self.status_label)

        y -= label_height + padding

        # Progress indicator (indeterminate)
        self.progress = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(100, y - 20, 200, 20)
        )
        self.progress.setIndeterminate_(True)
        self.progress.startAnimation_(None)
        self.window.contentView().addSubview_(self.progress)

        y -= 30 + padding

        # Buttons row
        button_width = 115
        button_spacing = 10
        total_buttons_width = (button_width * 3) + (button_spacing * 2)
        start_x = (400 - total_buttons_width) / 2

        # Terminate button
        self.terminate_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(start_x, y - button_height, button_width, button_height)
        )
        self.terminate_btn.setTitle_("Terminate")
        self.terminate_btn.setBezelStyle_(1)  # Rounded
        self.terminate_btn.setAction_("terminate:")
        self.terminate_btn.setTarget_(self)
        self.window.contentView().addSubview_(self.terminate_btn)

        # Pause/Resume button
        self.pause_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(start_x + button_width + button_spacing, y - button_height, button_width, button_height)
        )
        self.pause_btn.setTitle_("Pause")
        self.pause_btn.setBezelStyle_(1)  # Rounded
        self.pause_btn.setAction_("togglePause:")
        self.pause_btn.setTarget_(self)
        self.window.contentView().addSubview_(self.pause_btn)

        # Relaunch button
        self.relaunch_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(start_x + (button_width + button_spacing) * 2, y - button_height, button_width, button_height)
        )
        self.relaunch_btn.setTitle_("Relaunch App")
        self.relaunch_btn.setBezelStyle_(1)  # Rounded
        self.relaunch_btn.setAction_("relaunch:")
        self.relaunch_btn.setTarget_(self)
        self.window.contentView().addSubview_(self.relaunch_btn)

        # Start elapsed time updater
        self._start_timer()

    def _start_timer(self):
        """Start timer to update elapsed time."""
        from Foundation import NSTimer
        # Use started_at from process info if available
        started_at = self.process_info.get("started_at")
        if started_at:
            try:
                self.start_time = datetime.datetime.fromisoformat(started_at)
            except:
                pass

        # Create a recurring timer
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0,  # 1 second interval
            self,
            "updateElapsedTime:",
            None,
            True
        )

    def updateElapsedTime_(self, sender):
        """Update the elapsed time label."""
        elapsed = datetime.datetime.now() - self.start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.time_label.setStringValue_(f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}")

        # Update status based on process state
        state = read_active_processes()
        info = state.get("processes", {}).get(self.process_type)
        if info:
            status = info.get("status", "running")
            self.status_label.setStringValue_(f"Status: {status.capitalize()}")

    def terminate_(self, sender):
        """Terminate the process and exit."""
        logging.info(f"[ProgressWindow] Terminating {self.process_type}")
        pid = self.process_info.get("pid")
        if pid:
            ProcessController.terminate(pid)
            clear_process(self.process_type)
        self._cleanup()
        os._exit(0)

    def togglePause_(self, sender):
        """Toggle pause/resume for the process."""
        pid = self.process_info.get("pid")
        if not pid:
            return

        if self.paused:
            logging.info(f"[ProgressWindow] Resuming {self.process_type}")
            ProcessController.resume(pid)
            update_process_status(self.process_type, "running")
            sender.setTitle_("Pause")
            self.progress.startAnimation_(None)
            self.paused = False
        else:
            logging.info(f"[ProgressWindow] Pausing {self.process_type}")
            ProcessController.pause(pid)
            update_process_status(self.process_type, "paused")
            sender.setTitle_("Resume")
            self.progress.stopAnimation_(None)
            self.paused = True

    def relaunch_(self, sender):
        """Relaunch the full app."""
        import subprocess
        logging.info("[ProgressWindow] Relaunching app")
        if getattr(sys, 'frozen', False):
            # Frozen app: use 'open' command to launch the .app bundle
            app_path = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
            subprocess.Popen(['open', app_path])
        else:
            # Development: just run the script
            subprocess.Popen([sys.executable, os.path.join(BASE_PATH, 'macos_wrapper.py')])

    def windowWillClose_(self, notification):
        """Handle window close - exit app."""
        logging.info("[ProgressWindow] Window closing, exiting")
        self._cleanup()
        os._exit(0)

    def _cleanup(self):
        """Clean up timer and resources."""
        if self.timer:
            self.timer.invalidate()
            self.timer = None

    def show(self):
        """Display the window."""
        self.window.makeKeyAndOrderFront_(None)


def show_progress_window():
    """Show the native progress monitoring window."""
    global _progress_window_controller, _main_window_ref

    if not NATIVE_APIS_AVAILABLE:
        logging.warning("[ProgressWindow] Native APIs not available, exiting")
        os._exit(0)
        return

    # Determine which process to monitor
    processes = get_active_process_list()
    if not processes:
        logging.warning("[ProgressWindow] No active processes to monitor")
        os._exit(0)
        return

    # Prioritize training, then extract, then preprocess
    priority = ["training", "extract", "preprocess", "tts", "inference"]
    process_type = None
    process_info = None
    for ptype in priority:
        for p in processes:
            if p["type"] == ptype:
                process_type = ptype
                process_info = p
                break
        if process_type:
            break

    if not process_type:
        process_type = processes[0]["type"]
        process_info = processes[0]

    logging.info(f"[ProgressWindow] Creating native window for {process_type}")

    # Close main window if still open
    if _main_window_ref:
        try:
            _main_window_ref.destroy()
        except:
            pass

    # Create and show native progress window
    _progress_window_controller = ProgressWindowController(process_type, process_info)
    _progress_window_controller.show()
    logging.info("[ProgressWindow] Window shown, starting Cocoa event loop")

    # CRITICAL: Start Cocoa event loop to keep the window alive.
    # This blocks until the window is closed (which calls os._exit(0)).
    # Without this, the function returns and the app exits immediately.
    from PyObjCTools import AppHelper
    AppHelper.runConsoleEventLoop(installInterrupt=True)


def on_window_closing():
    """Handle main window closing event.

    CRITICAL: pywebview's closing event honors return False to prevent closing.
    The Event.set() method returns True if any handler returns False.
    """
    global _shutting_down

    # Prevent multiple shutdown attempts
    if _shutting_down:
        logging.info("[Window] Already shutting down, ignoring duplicate close event")
        return

    # CRITICAL: Add logging immediately to verify this is called
    logging.info("[Window] on_window_closing() CALLED")

    # Check for active processes with detailed diagnostics
    state = read_active_processes()
    logging.info(f"[Window] Process state: {state}")

    # Debug: Check each process type
    for ptype, info in state.get("processes", {}).items():
        logging.info(f"[Window] Process type '{ptype}': {info}")
        if info and info.get("pid"):
            pid = info["pid"]
            try:
                import psutil
                exists = psutil.pid_exists(pid)
                logging.info(f"[Window]   PID {pid} exists: {exists}")
            except ImportError:
                try:
                    os.kill(pid, 0)
                    exists = True
                except (ProcessLookupError, OSError):
                    exists = False
                logging.info(f"[Window]   PID {pid} exists: {exists}")

    if has_active_processes():
        logging.info("[Window] Active processes detected, showing confirmation")

        # IMPORTANT: Show native confirmation dialog immediately
        # The dialog will handle the actual exit decision
        show_close_confirmation_dialog()

        # CRITICAL: Return False to prevent window from closing
        # pywebview's Event.set() returns True if any handler returns False
        logging.info("[Window] Returning False to prevent close")
        return False
    else:
        logging.info("[Window] No active processes, exiting cleanly")
        os._exit(0)


# =================================================================
# 1.5. Preferences Manager for External Data Location
# =================================================================

class PreferencesManager:
    """Manages user preferences using macOS NSUserDefaults."""
    KEY_DATA_PATH = "userDataPath"
    KEY_FIRST_RUN_DONE = "firstRunCompleted"

    def __init__(self):
        if NATIVE_APIS_AVAILABLE:
            self.defaults = NSUserDefaults.standardUserDefaults()
        else:
            self.defaults = None

    def get_data_path(self) -> str | None:
        """Get the user's selected data storage path."""
        if self.defaults:
            path = self.defaults.stringForKey_(self.KEY_DATA_PATH)
            return path
        return None

    def set_data_path(self, path: str):
        """Save the data storage path preference."""
        if self.defaults:
            self.defaults.setObject_forKey_(path, self.KEY_DATA_PATH)
            self.defaults.synchronize()

    def is_first_run(self) -> bool:
        """Check if this is the first run (no preferences set)."""
        if self.defaults:
            return not self.defaults.boolForKey_(self.KEY_FIRST_RUN_DONE)
        return True  # If APIs not available, treat as first run

    def mark_first_run_complete(self):
        """Mark that first run setup has been completed."""
        if self.defaults:
            self.defaults.setBool_forKey_(True, self.KEY_FIRST_RUN_DONE)
            self.defaults.synchronize()


def select_data_folder(default_path: str = None) -> str | None:
    """
    Show native macOS folder selection dialog.

    Args:
        default_path: Initial directory to show in dialog

    Returns:
        Selected path or None if cancelled
    """
    if not NATIVE_APIS_AVAILABLE:
        return default_path

    panel = NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    panel.setCanCreateDirectories_(True)
    panel.setTitle_("Select Applio Data Location")
    panel.setPrompt_("Select")
    panel.setMessage_("Choose where Applio will store models, datasets, and training data.")

    if default_path:
        expanded = os.path.expanduser(default_path)
        if os.path.exists(expanded):
            panel.setDirectoryURL_(NSURL.fileURLWithPath_(expanded))

    result = panel.runModal()
    if result == NSModalResponseOK:
        return str(panel.URLs()[0].path())
    return None


def create_data_structure(base_path: str):
    """
    Create required directory structure in user's data location.

    Args:
        base_path: Root path for user data
    """
    dirs = [
        # Training outputs and voice models
        "logs",
        "logs/zips",

        # User assets
        "assets/datasets",
        "assets/audios",
        "assets/presets",

        # Downloaded models
        "rvc/models/pretraineds/hifi-gan",
        "rvc/models/pretraineds/refinegan",
        "rvc/models/pretraineds/custom",
        "rvc/models/embedders/contentvec",
        "rvc/models/embedders/embedders_custom",
        "rvc/models/predictors",
        "rvc/models/formant",
    ]

    for d in dirs:
        full_path = os.path.join(base_path, d)
        os.makedirs(full_path, exist_ok=True)


class FinderHelper:
    """Helper class for opening paths in Finder."""

    @staticmethod
    def open_path(path: str):
        """
        Open a path in Finder, creating it if necessary.

        Args:
            path: Path to open in Finder
        """
        if not NATIVE_APIS_AVAILABLE:
            return

        # Ensure path exists
        os.makedirs(path, exist_ok=True)

        # Open in Finder
        NSWorkspace.sharedWorkspace().selectFile_inFileViewerRootedAtPath_(path, "")


def check_for_updates():
    """
    Check for updates by querying the GitHub API.

    Compares the current VERSION with the latest release tag_name.
    Shows a native NSAlert dialog with the result:
    - Up to date: confirmation message
    - Update available: option to open releases page
    - Error: graceful error message
    """
    logging.info("[Update Menu] check_for_updates() called")
    logging.info(f"[Update Menu] Current version: {VERSION}")
    logging.info(f"[Update Menu] API URL: {API_URL}")

    latest_version = None
    release_url = RELEASES_URL
    error_message = None

    try:
        # Create request with User-Agent header (GitHub API requires this)
        request = urllib.request.Request(
            API_URL,
            headers={"User-Agent": f"Applio/{VERSION}"}
        )

        # Make the request with timeout
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

            # Get tag_name and strip 'v' prefix if present
            tag_name = data.get("tag_name", "")
            latest_version = tag_name.lstrip("v")

            # Get release URL (prefer html_url, fallback to releases page)
            release_url = data.get("html_url", RELEASES_URL)

            logging.info(f"Update check: current={VERSION}, latest={latest_version}")

    except urllib.error.HTTPError as e:
        error_message = f"HTTP {e.code}: {e.reason}"
        logging.warning(f"Update check failed (HTTP): {error_message}")
    except urllib.error.URLError as e:
        error_message = f"Network error: {e.reason}"
        logging.warning(f"Update check failed (network): {error_message}")
    except json.JSONDecodeError as e:
        error_message = "Invalid response from server"
        logging.warning(f"Update check failed (JSON): {e}")
    except Exception as e:
        error_message = str(e)
        logging.warning(f"Update check failed: {error_message}")

    # Show native NSAlert
    if not NATIVE_APIS_AVAILABLE:
        logging.warning("[Update Menu] Native APIs not available")
        return

    from AppKit import NSAlert, NSAlertFirstButtonReturn, NSWorkspace, NSURL
    import subprocess

    alert = NSAlert.alloc().init()

    if error_message:
        # Error case
        alert.setMessageText_("Could Not Check for Updates")
        alert.setInformativeText_(
            f"An error occurred while checking for updates.\n\n"
            f"Error: {error_message}\n\n"
            "You can manually check for updates on GitHub."
        )
        alert.addButtonWithTitle_("Open GitHub Releases")
        alert.addButtonWithTitle_("OK")
        alert.setAlertStyle_(2)  # NSAlertStyleWarning

        response = alert.runModal()
        if response == NSAlertFirstButtonReturn:
            subprocess.Popen(['open', release_url])

    elif latest_version and latest_version != VERSION:
        # Update available
        alert.setMessageText_("Update Available")
        alert.setInformativeText_(
            f"A new version of Applio is available.\n\n"
            f"Current version: v{VERSION}\n"
            f"Latest version: v{latest_version}\n\n"
            "Would you like to download the update?"
        )
        alert.addButtonWithTitle_("Download Update")
        alert.addButtonWithTitle_("Later")
        alert.setAlertStyle_(1)  # NSAlertStyleInformational

        response = alert.runModal()
        if response == NSAlertFirstButtonReturn:
            subprocess.Popen(['open', release_url])

    else:
        # Up to date
        alert.setMessageText_("You're Up to Date")
        alert.setInformativeText_(f"Applio is running the latest version.\n\nVersion {VERSION}")
        alert.addButtonWithTitle_("OK")
        alert.setAlertStyle_(1)  # NSAlertStyleInformational

        alert.runModal()


# =================================================================
# 1.6. Early Data Path Setup (BEFORE subprocess mode detection)

# =================================================================
# 1.6. Early Data Path Setup (BEFORE subprocess mode detection)
# =================================================================
# CRITICAL: This must happen before subprocess mode detection so that
# APPLIO_LOGS_PATH is available to subprocess scripts. When a subprocess
# script is detected, it runs via runpy.run_path() BEFORE the GUI mode
# setup (section 4) would normally set these environment variables.

if getattr(sys, "frozen", False):
    _early_prefs = PreferencesManager()
    _early_data_path = _early_prefs.get_data_path() or os.path.expanduser("~/Applio")
    # Debug: write to file since logging not set up yet
    with open("/tmp/applio_debug.txt", "a") as f:
        f.write(f"=== Early env setup ===\n")
        f.write(f"_early_data_path={_early_data_path}\n")
        f.write(f"APPLIO_LOGS_PATH={os.path.join(_early_data_path, 'logs')}\n")
        f.write(f"PID={os.getpid()}\n")
    os.environ["APPLIO_DATA_PATH"] = _early_data_path
    os.environ["APPLIO_LOGS_PATH"] = os.path.join(_early_data_path, "logs")
    # Also set these for subprocess scripts that may need them
    os.environ["APPLIO_DATASETS_PATH"] = os.path.join(_early_data_path, "assets", "datasets")
    os.environ["APPLIO_AUDIOS_PATH"] = os.path.join(_early_data_path, "assets", "audios")

# =================================================================
# 1.7. Write Runtime Configuration File (PROCESS-SAFE)
# =================================================================
# This file is the SOURCE OF TRUTH for path configuration.
# All processes (main GUI, subprocesses, multiprocessing workers)
# read from this file to get the correct paths.

def _write_runtime_config():
    """
    Write runtime paths to configuration file.

    This is PROCESS-SAFE: unlike environment variables, file-based
    configuration works across all process boundaries on macOS.
    """
    import json

    data_path = os.environ.get("APPLIO_DATA_PATH") or os.path.expanduser("~/Applio")

    config = {
        "version": 1,  # For future migration support
        "data_path": data_path,
        "logs_path": os.path.join(data_path, "logs"),
        "datasets_path": os.path.join(data_path, "assets", "datasets"),
        "audios_path": os.path.join(data_path, "assets", "audios"),
        "timestamp": time.time() if 'time' in dir() else 0
    }

    # Write to multiple locations for redundancy
    config_locations = [
        os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
        os.path.expanduser("~/.applio/runtime_paths.json"),
    ]

    for config_path in config_locations:
        try:
            config_dir = os.path.dirname(config_path)
            os.makedirs(config_dir, exist_ok=True)

            # Write atomically: write to temp file, then rename
            temp_path = config_path + ".tmp"
            with open(temp_path, "w") as f:
                json.dump(config, f, indent=2)
            os.rename(temp_path, config_path)

            # Use print since logging may not be set up yet
            print(f"[runtime_config] Wrote config to: {config_path}")
        except Exception as e:
            print(f"[runtime_config] Failed to write config to {config_path}: {e}")

# Write config in frozen mode (ensures it's available for all subprocesses)
if getattr(sys, "frozen", False):
    _write_runtime_config()

# =================================================================
# 2. Logging Configuration (BEFORE script execution)
# =================================================================
# CRITICAL: Logging must be set up before script execution mode detection
# so that training script output is captured.

import logging
import time

def setup_logging():
    log_dir = os.path.expanduser("~/Library/Logs/Applio")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "applio_wrapper.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='a'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    # Redirect stdout/stderr to log for frozen builds
    if getattr(sys, "frozen", False):
        sys.stdout = open(log_file, 'a')
        sys.stderr = open(log_file, 'a')

    logging.info("--- Applio macOS Native Session Start ---")
    logging.info(f"Version: 1.7.4 (Simplified Local)")
    logging.info(f"CWD: {os.getcwd()}")
    logging.info(f"Base Path: {BASE_PATH}")
    logging.info(f"sys.frozen: {getattr(sys, 'frozen', False)}")
    logging.info(f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")

setup_logging()

# =================================================================
# 3. Subprocess Script Execution Mode Detection
# =================================================================
# In PyInstaller frozen apps, sys.executable points to the app binary.
# When subprocess.run([sys.executable, "script.py"]) is called, it
# re-launches the entire app. We detect this and run the script instead.
# This must happen AFTER logging setup so script output is captured.

if len(sys.argv) > 1:
    potential_script = sys.argv[1]

    # Check if it's a Python script path
    if potential_script.endswith('.py'):
        script_path = None

        # First try: relative to current working directory
        if os.path.exists(potential_script):
            script_path = potential_script
        # Second try: relative to BASE_PATH (app bundle)
        # This is needed for subprocess calls after cwd change to DATA_PATH
        elif os.path.exists(os.path.join(BASE_PATH, potential_script)):
            script_path = os.path.join(BASE_PATH, potential_script)

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
                    # Second check: try resolving relative path from DATA_PATH (user's data location)
                    if not os.path.isabs(dataset_path):
                        data_path = os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))
                        resolved_from_data = os.path.normpath(os.path.join(data_path, dataset_path))
                        if os.path.exists(resolved_from_data):
                            dataset_path = resolved_from_data
                            script_args[1] = resolved_from_data
                            logging.info(f"Dataset path resolved from DATA_PATH: {original_path} -> {resolved_from_data}")
                        else:
                            # Third check: try resolving relative path from BASE_PATH (app bundle)
                            resolved_from_base = os.path.normpath(os.path.join(BASE_PATH, dataset_path))
                            if os.path.exists(resolved_from_base):
                                dataset_path = resolved_from_base
                                script_args[1] = resolved_from_base
                                logging.info(f"Dataset path resolved from BASE_PATH: {original_path} -> {resolved_from_base}")
                            else:
                                logging.error(f"Dataset path not found: {original_path}")
                                logging.error(f"  Tried DATA_PATH: {resolved_from_data}")
                                logging.error(f"  Tried BASE_PATH: {resolved_from_base}")
                                print(f"Error: Dataset path does not exist: {original_path}")
                                print(f"  Tried: {resolved_from_data}")
                                print(f"  Tried: {resolved_from_base}")
                                print(f"  Please use an absolute path to your dataset folder.")
                                sys.exit(1)
                    else:
                        logging.error(f"Dataset path not found: {dataset_path}")
                        print(f"Error: Dataset path does not exist: {dataset_path}")
                        sys.exit(1)
                else:
                    logging.info(f"Dataset path validated: {dataset_path}")
            # === END PATH VALIDATION ===

            # Convert script_path to ABSOLUTE path BEFORE any CWD changes
            # This is critical - the script lives in the app bundle (BASE_PATH),
            # not in the user's data directory. If we change CWD first, the
            # relative path will resolve incorrectly.
            script_path_abs = os.path.abspath(script_path)

            # Adjust sys.argv for the script's perspective
            sys.argv = [script_path_abs] + script_args

            # Add script's directory to sys.path for relative imports
            # This mimics the behavior of `python script.py` which adds the script's dir to sys.path
            script_dir = os.path.dirname(script_path_abs)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

            # Change CWD to data path for correct path resolution in subprocess
            # This ensures os.getcwd() returns DATA_PATH, not BASE_PATH
            _data_path = os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))
            _original_cwd = os.getcwd()
            os.chdir(_data_path)
            logging.info(f"Changed CWD for subprocess: {_data_path}")

            # Ensure config file is written before running subprocess script
            # This handles the case where subprocess starts before main GUI
            _write_runtime_config()

            try:
                runpy.run_path(script_path_abs, run_name='__main__')
                logging.info(f"Script completed successfully: {script_path_abs}")
                sys.exit(0)
            except SystemExit as e:
                # SystemExit is raised by sys.exit() in the script
                # Non-zero exit codes indicate failure
                if e.code != 0 and e.code is not None:
                    logging.error(f"Script exited with code {e.code}: {script_path_abs}")
                else:
                    logging.info(f"Script exited normally: {script_path_abs}")
                sys.exit(e.code if e.code is not None else 0)
            except Exception as e:
                logging.error(f"Script execution failed: {script_path_abs}")
                logging.exception(e)
                sys.exit(1)
            finally:
                os.chdir(_original_cwd)  # Restore original CWD

# =================================================================
# 4. External Data Location Setup (GUI mode only)
# =================================================================
# This section only runs in GUI mode (not in subprocess mode)

# Initialize preferences
_prefs = PreferencesManager()
DATA_PATH = _prefs.get_data_path()

if not DATA_PATH:
    # First run - prompt for location
    default_location = os.path.expanduser("~/Applio")
    DATA_PATH = select_data_folder(default_location)

    if not DATA_PATH:
        # User cancelled - use default
        DATA_PATH = default_location
        logging.info(f"User cancelled folder selection, using default: {DATA_PATH}")

    # Validate path is writable
    try:
        os.makedirs(DATA_PATH, exist_ok=True)
        test_file = os.path.join(DATA_PATH, ".write_test")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
    except (IOError, OSError) as e:
        logging.error(f"Selected path not writable: {DATA_PATH}, error: {e}")
        DATA_PATH = default_location
        os.makedirs(DATA_PATH, exist_ok=True)

    # Save preference
    _prefs.set_data_path(DATA_PATH)
    _prefs.mark_first_run_complete()
    logging.info(f"Data location set to: {DATA_PATH}")

# Create directory structure
create_data_structure(DATA_PATH)

# Change working directory to user data location
# This causes all relative paths (now_dir = os.getcwd()) to resolve here
os.chdir(DATA_PATH)
logging.info(f"Working directory changed to: {DATA_PATH}")

# Set APPLIO_LOGS_PATH environment variable for core.py
# This ensures logs_path is set correctly regardless of import timing
os.environ["APPLIO_LOGS_PATH"] = os.path.join(DATA_PATH, "logs")

# =================================================================
# 5. GUI Mode Initialization
# =================================================================
# Only reached if not in script execution mode

import threading
import socket
import http.server
import socketserver
import webview

# =================================================================
# 1.5. Copy bundled static resources to user's data location
# =================================================================

def setup_bundled_resources():
    """Copy bundled static resources to user's data location.

    These files are accessed via relative paths from cwd.
    When cwd is changed to user's data location, these files must exist there.
    """
    import shutil

    def copy_file(bundled_rel, dest_rel, desc):
        """Copy a single file if destination doesn't exist."""
        bundled_path = os.path.join(BASE_PATH, bundled_rel)
        dest_path = os.path.join(DATA_PATH, dest_rel)

        if os.path.exists(bundled_path):
            dest_dir = os.path.dirname(dest_path)
            os.makedirs(dest_dir, exist_ok=True)
            if not os.path.exists(dest_path):
                try:
                    shutil.copy2(bundled_path, dest_path)
                    logging.info(f"Copied {desc} to {dest_path}")
                except Exception as e:
                    logging.warning(f"Failed to copy {desc}: {e}")
            else:
                logging.debug(f"{desc} already exists at {dest_path}, skipping")
        else:
            logging.debug(f"No bundled {desc} found at {bundled_path}")

    def copy_dir(bundled_rel, dest_rel, desc):
        """Copy a directory if destination doesn't exist."""
        bundled_path = os.path.join(BASE_PATH, bundled_rel)
        dest_path = os.path.join(DATA_PATH, dest_rel)

        if os.path.exists(bundled_path):
            if not os.path.exists(dest_path):
                try:
                    shutil.copytree(bundled_path, dest_path)
                    logging.info(f"Copied {desc} to {dest_path}")
                except Exception as e:
                    logging.warning(f"Failed to copy {desc}: {e}")
            else:
                logging.debug(f"{desc} already exists at {dest_path}, skipping")
        else:
            logging.debug(f"No bundled {desc} found at {bundled_path}")

    # Copy individual files
    files_to_copy = [
        # Main app config
        ("assets/config.json", "assets/config.json", "App config"),
        # TTS voices list
        ("rvc/lib/tools/tts_voices.json", "rvc/lib/tools/tts_voices.json", "TTS voices list"),
        # Config files for different sample rates
        ("rvc/configs/48000.json", "rvc/configs/48000.json", "48kHz config"),
        ("rvc/configs/44100.json", "rvc/configs/44100.json", "44.1kHz config"),
        ("rvc/configs/40000.json", "rvc/configs/40000.json", "40kHz config"),
        ("rvc/configs/32000.json", "rvc/configs/32000.json", "32kHz config"),
        ("rvc/configs/24000.json", "rvc/configs/24000.json", "24kHz config"),
        # Pretrains download list
        ("assets/pretrains.json", "rvc/models/pretraineds/custom/pretrains.json", "Pretrains list"),
        # JavaScript files for tabs
        ("tabs/report/recorder.js", "tabs/report/recorder.js", "Report tab recorder JS"),
        ("tabs/report/main.js", "tabs/report/main.js", "Report tab main JS"),
        ("tabs/report/record_button.js", "tabs/report/record_button.js", "Report tab button JS"),
        ("tabs/realtime/main.js", "tabs/realtime/main.js", "Realtime tab main JS"),
    ]

    for bundled_rel, dest_rel, desc in files_to_copy:
        copy_file(bundled_rel, dest_rel, desc)

    # Copy directories (only if destination doesn't exist)
    dirs_to_copy = [
        ("assets/i18n", "assets/i18n", "Internationalization files"),
        ("assets/themes", "assets/themes", "Gradio themes"),
        ("assets/presets", "assets/presets", "Effect presets"),
        ("assets/formant_shift", "assets/formant_shift", "Formant shift presets"),
    ]

    for bundled_rel, dest_rel, desc in dirs_to_copy:
        copy_dir(bundled_rel, dest_rel, desc)

setup_bundled_resources()

# =================================================================
# 2. UI Support & Native Menu
# =================================================================

class AboutWindowController:
    """Native macOS About window using NSPanel."""

    def __init__(self):
        from AppKit import (
            NSPanel, NSTextField, NSButton, NSMakeRect,
            NSTitledWindowMask, NSClosableWindowMask,
            NSBackingStoreBuffered, NSCenterTextAlignment,
            NSFont, NSFontBoldSystemFont, NSButtonBezelStyleRounded,
            NSWorkspace, NSURL
        )

        # Create panel (380x260)
        style = NSTitledWindowMask | NSClosableWindowMask
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 380, 280),
            style,
            NSBackingStoreBuffered,
            False
        )
        self.panel.setTitle_("About Applio")
        self.panel.center()

        y = 250
        padding = 20
        content_width = 340

        # App name (bold, large)
        self.title_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 36, content_width, 36)
        )
        self.title_label.setStringValue_("APPLIO")
        self.title_label.setBezeled_(False)
        self.title_label.setDrawsBackground_(False)
        self.title_label.setEditable_(False)
        self.title_label.setSelectable_(False)
        self.title_label.setAlignment_(NSCenterTextAlignment)
        bold_font = NSFont.boldSystemFontOfSize_(28)
        self.title_label.setFont_(bold_font)
        self.panel.contentView().addSubview_(self.title_label)

        y -= 50

        # Version
        self.version_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 18, content_width, 18)
        )
        self.version_label.setStringValue_(f"Version {VERSION}")
        self.version_label.setBezeled_(False)
        self.version_label.setDrawsBackground_(False)
        self.version_label.setEditable_(False)
        self.version_label.setSelectable_(False)
        self.version_label.setAlignment_(NSCenterTextAlignment)
        self.panel.contentView().addSubview_(self.version_label)

        y -= 30

        # Description
        self.desc_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 32, content_width, 32)
        )
        self.desc_label.setStringValue_("Voice conversion application built on RVC\n(Retrieval-Based Voice Conversion)")
        self.desc_label.setBezeled_(False)
        self.desc_label.setDrawsBackground_(False)
        self.desc_label.setEditable_(False)
        self.desc_label.setSelectable_(False)
        self.desc_label.setAlignment_(NSCenterTextAlignment)
        self.panel.contentView().addSubview_(self.desc_label)

        y -= 40

        # Copyright
        self.copyright_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 16, content_width, 16)
        )
        self.copyright_label.setStringValue_("© 2026 Frédéric Guigand")
        self.copyright_label.setBezeled_(False)
        self.copyright_label.setDrawsBackground_(False)
        self.copyright_label.setEditable_(False)
        self.copyright_label.setSelectable_(False)
        self.copyright_label.setAlignment_(NSCenterTextAlignment)
        self.panel.contentView().addSubview_(self.copyright_label)

        y -= 25

        # GitHub link button
        self.github_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(padding, y - 24, content_width, 24)
        )
        self.github_btn.setTitle_("github.com/froggeric/applio-macOS-native-app")
        self.github_btn.setBezelStyle_(NSButtonBezelStyleRounded)
        self.github_btn.setAction_("openGithub:")
        self.github_btn.setTarget_(self)
        self.panel.contentView().addSubview_(self.github_btn)

        y -= 35

        # Check for Updates button
        self.update_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(110, y - 28, 160, 28)
        )
        self.update_btn.setTitle_("Check for Updates")
        self.update_btn.setBezelStyle_(NSButtonBezelStyleRounded)
        self.update_btn.setAction_("checkUpdates:")
        self.update_btn.setTarget_(self)
        self.panel.contentView().addSubview_(self.update_btn)

    def openGithub_(self, sender):
        """Open GitHub repository in browser."""
        import subprocess
        subprocess.Popen(['open', RELEASES_URL])

    def checkUpdates_(self, sender):
        """Check for updates."""
        self.panel.close()
        check_for_updates()

    def show(self):
        """Display the panel."""
        self.panel.makeKeyAndOrderFront_(None)


def show_about_dialog():
    """Display native About Applio dialog."""
    logging.info("[About Menu] show_about_dialog() called")

    if not NATIVE_APIS_AVAILABLE:
        logging.warning("[About Menu] Native APIs not available")
        return

    about_controller = AboutWindowController()
    about_controller.show()

# =================================================================
# Menu Callback Wrappers
# =================================================================
# These module-level functions are used as menu callbacks to avoid
# issues with lambda serialization in pywebview's menu system.

def _menu_callback_about():
    """Menu callback for About Applio.

    CRITICAL: This runs in a background thread (pywebview menu handler).
    We must use AppHelper.callAfter() to schedule UI work on the main thread.
    """
    logging.info("[About Menu] _menu_callback_about() called")

    def _show_on_main_thread():
        """Execute show_about_dialog() on the main thread."""
        try:
            show_about_dialog()
            logging.info("[About Menu] _menu_callback_about() completed successfully")
        except Exception as e:
            logging.error(f"[About Menu] _menu_callback_about() failed: {e}")
            logging.exception(e)

    # Schedule on main thread using AppHelper
    if NATIVE_APIS_AVAILABLE:
        AppHelper.callAfter(_show_on_main_thread)
    else:
        # Fallback for non-macOS platforms
        _show_on_main_thread()

def _menu_callback_check_updates():
    """Menu callback for Check for Updates.

    CRITICAL: This runs in a background thread (pywebview menu handler).
    We must use AppHelper.callAfter() to schedule UI work on the main thread.
    """
    logging.info("[Update Menu] _menu_callback_check_updates() called")

    def _check_on_main_thread():
        """Execute check_for_updates() on the main thread."""
        try:
            check_for_updates()
            logging.info("[Update Menu] _menu_callback_check_updates() completed successfully")
        except Exception as e:
            logging.error(f"[Update Menu] _menu_callback_check_updates() failed: {e}")
            logging.exception(e)

    # Schedule on main thread using AppHelper
    if NATIVE_APIS_AVAILABLE:
        AppHelper.callAfter(_check_on_main_thread)
    else:
        # Fallback for non-macOS platforms
        _check_on_main_thread()

def get_native_menu():
    from webview.menu import Menu, MenuAction, MenuSeparator
    def open_in_finder(subpath: str):
        """Open a subpath of DATA_PATH in Finder."""
        if ApplioApp.DATA_PATH:
            full_path = os.path.join(ApplioApp.DATA_PATH, subpath)
            FinderHelper.open_path(full_path)
    def change_data_location():
        """Show dialog to change data location."""
        new_path = select_data_folder(ApplioApp.DATA_PATH)
        if new_path and new_path != ApplioApp.DATA_PATH:
            prefs = PreferencesManager()
            prefs.set_data_path(new_path)
            logging.info(f"Data location changed to: {new_path}")
            logging.info("Please restart Applio for changes to take effect.")
    return [
        Menu("File", [
            MenuAction("Set Data Location...", change_data_location),
            MenuSeparator(),
            Menu("Open in Finder", [
                MenuAction("Training Models", lambda: open_in_finder("logs")),
                MenuAction("Datasets", lambda: open_in_finder("assets/datasets")),
                MenuAction("Pretrained Models", lambda: open_in_finder("rvc/models/pretraineds")),
                MenuAction("Inference Outputs", lambda: open_in_finder("assets/audios")),
                MenuSeparator(),
                MenuAction("Root Data Folder", lambda: open_in_finder("")),
            ]),
        ]),
        Menu("Applio", [
            MenuAction("About Applio", _menu_callback_about),
            MenuAction("Check for Updates...", _menu_callback_check_updates),
            MenuSeparator(),
            MenuAction("Services", lambda: None),
            MenuSeparator(),
            MenuAction("Hide Applio", lambda: None),
            MenuAction("Hide Others", lambda: None),
            MenuSeparator(),
            MenuAction("Quit Applio", lambda: os._exit(0))
        ]),
        Menu("Edit", [
            MenuAction("Undo", lambda: None),
            MenuAction("Redo", lambda: None),
            MenuSeparator(),
            MenuAction("Cut", lambda: None),
            MenuAction("Copy", lambda: None),
            MenuAction("Paste", lambda: None),
            MenuAction("Select All", lambda: None)
        ]),
        Menu("Window", [
            MenuAction("Minimize", lambda: None),
            MenuAction("Zoom", lambda: None),
        ])
    ]

# =================================================================
# 3. App Core Class
# =================================================================

class ApplioApp:
    # Class-level data path for menu callbacks
    DATA_PATH = None  # Set after initialization

    def __init__(self):
        self.server_host = "127.0.0.1"
        self.server_port = 6969
        self.loading_port = 5678
        self.window = None
        self.is_ready = False
        self.heading = "System Calibration"
        self.sub_heading = "Initializing environment..."
        self.technical_detail = "Allocating memory..."
        self.progress = 0
        self.stage = "1/4"
        self.log_file = os.path.expanduser("~/Library/Logs/Applio/applio_wrapper.log")
        # Store DATA_PATH for menu access
        ApplioApp.DATA_PATH = DATA_PATH

    def start_loading_server(self):
        """Serves the high-fidelity loading screen and status API."""
        parent = self
        class LoadingHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/status":
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    import json
                    data = {
                        "heading": parent.heading,
                        "sub_heading": parent.sub_heading,
                        "progress": round(parent.progress, 1),
                        "stage": parent.stage,
                        "detail": parent.technical_detail
                    }
                    self.wfile.write(json.dumps(data).encode("utf-8"))
                    return

                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                try:
                    path = os.path.join(BASE_PATH, "assets", "loading.html")
                    with open(path, 'r') as f:
                        self.wfile.write(f.read().encode("utf-8"))
                except Exception as e:
                    self.wfile.write(f"<h1>Loading Applio...</h1><p>{e}</p>".encode("utf-8"))
            def log_message(self, format, *args): pass

        try:
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer((self.server_host, self.loading_port), LoadingHandler) as httpd:
                logging.info(f"Loading UI server active on port {self.loading_port}")
                httpd.serve_forever()
        except Exception as e:
            logging.error(f"Loading UI server failed: {e}")

    def tail_logs(self):
        """Expert Log Observer with Real-Time Technical Feed."""
        import re
        logging.info("Starting Granular Log Observer...")
        
        # Regex patterns for real activity
        # High-level states
        p_dl_percent = re.compile(r"Downloading.* (\d+)%")
        p_dl_file = re.compile(r"Downloading (.*)\.\.\.")
        p_extract = re.compile(r"Extracting (.*)\.\.\.")
        p_req = re.compile(r"Requirement already satisfied: (.*)")
        p_pip_install = re.compile(r"Installing collected packages: (.*)")
        
        # Applio specific
        p_prereq = re.compile(r"run_prerequisites_script")
        p_init_app = re.compile(r"Initializing Gradio boot sequence")
        p_load_model = re.compile(r"Loading (.*) model")
        p_device = re.compile(r"Use (.*) acceleration")
        p_server = re.compile(r"Running on local URL:.*")
        p_responsive = re.compile(r"Gradio backend is responsive")
        
        start_time = time.time()

        while True:
            if not os.path.exists(self.log_file):
                time.sleep(0.1)
                continue
                
            try:
                with open(self.log_file, 'r') as f:
                    f.seek(0, os.SEEK_END)
                    while True:
                        line = f.readline()
                        
                        # ANTI-STALL CREEP: Gentle pulse, no blocking
                        if not self.is_ready and self.progress < 95:
                             creep = (100 - self.progress) / 2000
                             self.progress += creep

                        if not line:
                            time.sleep(0.05)
                            continue
                        
                        line = line.strip()
                        if not line: continue

                        # --- LOGIC MAPPING ---
                        
                        # 1. Downloads
                        if p_dl_percent.search(line):
                            self.stage = "2/4"
                            self.heading = "Synchronizing Assets"
                            match = p_dl_percent.search(line)
                            val = int(match.group(1))
                            if val > self.progress: self.progress = val
                            
                        elif p_dl_file.search(line):
                            self.stage = "2/4"
                            self.heading = "Synchronizing Assets"
                            fname = p_dl_file.search(line).group(1)
                            self.sub_heading = f"Fetching {os.path.basename(fname)}"
                            self.technical_detail = f"Network Request: {fname}"

                        # 2. Operations
                        elif p_extract.search(line):
                            self.stage = "2/4"
                            self.heading = "Decompressing Resources"
                            fname = p_extract.search(line).group(1)
                            self.sub_heading = f"Unpacking {os.path.basename(fname)}"
                            self.technical_detail = f"IO Operation: {fname}"

                        elif p_pip_install.search(line):
                             self.stage = "2/4"
                             self.heading = "Building Environment"
                             pkgs = p_pip_install.search(line).group(1)
                             if len(pkgs) > 30: pkgs = pkgs[:27] + "..."
                             self.sub_heading = f"Installing {pkgs}"
                             self.technical_detail = line

                        # 3. Initialization
                        elif p_prereq.search(line):
                            self.stage = "1/4"
                            self.heading = "System Validation"
                            self.sub_heading = "Checking Prerequisites..."
                            if self.progress < 10: self.progress = 10

                        elif p_device.search(line):
                             self.heading = "Hardware Optimization"
                             device = p_device.search(line).group(1)
                             self.sub_heading = f"Accelerating with {device}"
                             self.technical_detail = f"Device allocation: {device}"

                        # 4. Boot
                        elif p_init_app.search(line):
                            self.stage = "3/4"
                            self.heading = "Booting Inference Engine"
                            self.sub_heading = "Loading Neural Networks..."
                            self.technical_detail = "Initializing pytorch contexts..."
                            if self.progress < 80: self.progress = 80
                            
                        elif p_load_model.search(line):
                             self.heading = "Loading Models"
                             model = p_load_model.search(line).group(1)
                             self.sub_heading = f"Hydrating {model}..."
                             self.technical_detail = f"Memory mapping {model}"

                        # 5. Success
                        elif p_server.search(line) or p_responsive.search(line) or "Gradio backend is responsive" in line:
                            self.stage = "4/4"
                            self.heading = "Initialization Complete"
                            self.sub_heading = "Launching User Interface..."
                            self.progress = 100
                            self.is_ready = True
                            return
                            
                        # GENERIC FALLBACK: Show raw log activity
                        else:
                             clean = line
                             if len(clean) > 8 and "it/s]" not in clean: 
                                 if ":root:" in clean:
                                     clean = clean.split(":root:", 1)[1].strip()
                                 if len(clean) > 60: clean = clean[:57] + "..."
                                 self.technical_detail = clean
                                 if self.stage == "1/4" and self.sub_heading == "Initializing environment...":
                                     self.sub_heading = "Configuring Runtime..."
            except Exception as e:
                logging.error(f"Log observer error: {e}")
                time.sleep(1)

    def wait_for_backend(self, timeout=600):
        """Polls the Gradio backend for readiness."""
        import urllib.request
        url = f"http://{self.server_host}:{self.server_port}"
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        logging.info("Gradio backend is responsive.")
                        self.is_ready = True
                        return True
            except Exception:
                time.sleep(1)
        return False

    def start_backend(self):
        """Launches the actual Applio server."""
        try:
            logging.info(f"CWD before app import: {os.getcwd()}")
            from app import launch_gradio
            logging.info("Initializing Gradio boot sequence...")
            launch_gradio(self.server_host, self.server_port)
        except Exception as e:
            logging.error(f"Backend launch failed: {e}")

    def monitor_transition(self):
        """Switches from loading screen to main app."""
        if self.wait_for_backend():
            # Graceful delay for UI settling
            time.sleep(1.5)
            if self.window:
                logging.info("Transitioning to main UI...")
                self.window.load_url(f"http://{self.server_host}:{self.server_port}")
        else:
            logging.error("Backend timeout period exceeded.")
            if self.window:
                self.window.load_html("<h1>Startup Error</h1><p>The server failed to respond in time.</p>")

    def run(self):
        # 1. Start Helpers
        threading.Thread(target=self.start_loading_server, daemon=True).start()
        threading.Thread(target=self.tail_logs, daemon=True).start()

        # 2. Start Backend direct
        logging.info("Launching Backend directly...")
        threading.Thread(target=self.start_backend, daemon=True).start()
        threading.Thread(target=self.monitor_transition, daemon=True).start()

        # 3. Main Window
        self.window = webview.create_window(
            "Applio",
            url=f"http://{self.server_host}:{self.loading_port}",
            width=1280,
            height=1370,
            min_size=(1024, 720),
            resizable=True,
            text_select=True,
            vibrancy=True
        )
        
        self.window.events.closing += on_window_closing
        global _main_window_ref
        _main_window_ref = self.window

        logging.info("Starting Webview GUI...")
        webview.start(menu=get_native_menu(), debug=False)

if __name__ == "__main__":
    app = ApplioApp()
    app.run()
