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

import multiprocessing  # freeze_support() is called from start_gui(), not at import time

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
import subprocess
import webbrowser

# =================================================================
# 1.1. Activation Policy for Subprocess Mode
# =================================================================
# When running under the launcher, this process should NOT appear in the Dock.
# This MUST be set BEFORE any NSApplication creation (including webview import).
#
# NSApplicationActivationPolicyAccessory (1):
#   - No Dock icon
#   - Window accessible via Cmd+Tab and click
#   - Can be activated programmatically
#
# NSApplicationActivationPolicyRegular (0):
#   - Normal Dock icon (default)
#   - Standard macOS app behavior


def _configure_activation_policy():
    """No-op in single-process mode.

    Activation policy is owned by the launcher process (which is the only
    process now). Retained as a no-op because start_gui() calls it in order
    with the other bootstrap steps.
    """
    return


# Called from start_gui() BEFORE `import webview` (activation-policy ordering
# is load-bearing; see start_gui).

# =================================================================
# 1.2. PyWebView Activation Policy Patch (retained no-op stubs)
# =================================================================
# Historically this section monkey-patched NSApplication.setActivationPolicy_
# so a separate wrapper subprocess could hide its Dock icon under the launcher
# (two-process mode). Two-process mode and the patch logic have both been
# removed; single-process owns activation policy in the launcher. The two
# functions below are retained as no-op stubs because start_gui() calls them in
# order with the other bootstrap steps (see each function's docstring).


def _patch_pywebview_activation_policy():
    """No-op in single-process mode.

    The Accessory-policy monkey-patch was only needed when a separate wrapper
    subprocess had to hide its Dock icon under the launcher. Single-process has
    no subprocess, so the launcher's Regular policy is the only one. Retained as
    a no-op because start_gui() calls it in order with the other bootstrap steps.
    """
    return


def _unpatch_pywebview_activation_policy():
    """No-op in single-process mode.

    With _patch_pywebview_activation_policy() a no-op, nothing is ever patched,
    so there is nothing to restore. Retained as a no-op because start_gui()
    calls it in order with the other teardown steps.
    """
    return


# Applied from start_gui() BEFORE `import webview` (see start_gui).

# macOS native APIs for preferences and dialogs
# These are conditional imports - only needed for GUI mode
try:
    from Foundation import NSUserDefaults, NSURL
    from AppKit import NSOpenPanel, NSWorkspace, NSModalResponseOK
    from PyObjCTools import AppHelper

    NATIVE_APIS_AVAILABLE = True
except ImportError:
    NATIVE_APIS_AVAILABLE = False

# Performance tuning / cache redirection / path hygiene are applied in
# start_gui() (env vars, makedirs, and the frozen os.chdir(BASE_PATH)) so that
# importing this module is side-effect-free. BASE_PATH is resolved read-only
# here because _get_version_info() and bundled-resource lookups need it.

# Path Hygiene for PyInstaller (read-only resolution; frozen os.chdir runs in
# start_gui()).
if getattr(sys, "frozen", False):
    BASE_PATH = sys._MEIPASS
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# Resolved by start_gui() at GUI bootstrap; kept None at import time so the
# name exists for module-level references (setup_bundled_resources, etc.).
DATA_PATH = None

# pywebview is imported inside start_gui() (its import forces Regular activation policy +
# sharedApplication, so it must not run at module import). Kept None at import time so the name
# exists for module-level references (render_pywebview, _focus_main_window, run_until_window_created).
webview = None

# =================================================================
# 1.4. Version Configuration
# =================================================================
# Version is read from build_info.json at runtime (written by build_macos.py at build time)
# This ensures version consistency without manual synchronization.


def _get_version_info():
    """Read the full build version from build_info.json (written by build_macos.py).

    build_macos.py writes build_info.json to Contents/Resources/build_info.json,
    which in the frozen app is BASE_PATH/build_info.json (BASE_PATH == sys._MEIPASS).
    Earlier code looked only under BASE_PATH/assets/ (where the file never landed),
    so it silently fell back to a stale literal. Prefer 'full_version'
    (e.g. '3.6.3.5'); fall back to 'version', then the upstream config version.
    """
    import json

    for _rel in ("build_info.json", os.path.join("assets", "build_info.json")):
        _candidate = os.path.join(BASE_PATH, _rel)
        try:
            with open(_candidate, "r", encoding="utf-8") as f:
                _info = json.load(f)
                _full = _info.get("full_version") or _info.get("version")
                if _full:
                    return _full
        except Exception:
            continue
    # Last resort: upstream version from config (no build number).
    for _cfg in ("assets/config.json", "assets/config_template.json"):
        try:
            with open(os.path.join(BASE_PATH, _cfg), "r", encoding="utf-8") as f:
                return json.load(f).get("version", "3.6.4")
        except Exception:
            continue
    return "3.6.4"


VERSION = _get_version_info()
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
        **metadata,
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
    """Check if any processes are currently active (incl. in-process conversion).

    The quit/close gate in on_window_closing consults this; a live conversion
    must count as active or a window-close mid-conversion quits without a
    prompt and tears Python down under the worker thread (repro 2026-08-27).
    """
    if _launcher_inference_proc():
        return True
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


def _launcher_inference_proc():
    """The launcher's synthesized in-process conversion proc, or None.

    An in-process conversion (single or batch) runs on a gradio worker thread,
    not a subprocess, so it is invisible to active_processes.json — the
    launcher's _synthesize_inference_proc reader (inference_progress.json) is
    the single source of truth. The wrapper cannot import applio_launcher
    (circular; it runs as __main__ frozen), so reach it through the instance
    start_gui exposed. Standalone runs (_launcher_ref None) have no launcher
    to ask — None. Never raises.
    """
    if _launcher_ref is None:
        return None
    try:
        return _launcher_ref.inference_proc()
    except Exception:
        return None


def get_active_process_list() -> list:
    """Get list of active processes with their info (incl. in-process conversion)."""
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
    inference = _launcher_inference_proc()
    if inference:
        active.append(inference)
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
_launcher_ref = (
    None  # Launcher handle exposed by start_gui() for on_window_closing (Phase 2)
)


# Return codes for close confirmation dialog
CLOSE_QUIT = 1  # Terminate all and exit
CLOSE_KEEP_RUNNING = 2  # Hide window, keep processes running
CLOSE_CANCEL = 3  # Cancel close, keep window open


def show_close_confirmation() -> int:
    """Show native confirmation dialog when closing with active processes.

    Returns:
        CLOSE_KEEP_RUNNING (2): User wants to keep processes running in background
        CLOSE_QUIT (1): User wants to terminate and quit
        CLOSE_CANCEL (3): User cancelled the close action
    """
    if not NATIVE_APIS_AVAILABLE:
        return CLOSE_QUIT  # No native APIs, proceed with exit

    from AppKit import (
        NSAlert,
        NSAlertStyleWarning,
        NSAlertFirstButtonReturn,
        NSAlertSecondButtonReturn,
    )

    import applio_i18n

    _t = applio_i18n.native_tr

    active = get_active_process_list()
    if not active:
        return CLOSE_QUIT  # No active processes, allow close

    # Build readable process list
    process_info = "\n".join(
        [
            f"• {p.get('type', 'Unknown').capitalize()}: {p.get('model_name', 'Unknown model')}"
            for p in active[:3]
        ]
    )
    if len(active) > 3:
        process_info += f"\n  ... and {len(active) - 3} more"

    alert = NSAlert.alloc().init()
    alert.setMessageText_(_t("Active Processes Running"))
    alert.setInformativeText_(
        _t(
            "The following processes are still running:\n{procs}\n\n"
            "What would you like to do?"
        ).format(procs=process_info)
    )
    alert.setAlertStyle_(NSAlertStyleWarning)
    alert.addButtonWithTitle_(
        _t("Keep Running")
    )  # First: safe default — auto Return; SIGSTOP'd jobs keep running
    alert.addButtonWithTitle_(
        _t("Terminate & Quit")
    )  # Second: no key equivalent — explicit click only
    alert.addButtonWithTitle_(_t("Cancel"))  # Third: auto Escape (title-based)

    response = alert.runModal()

    if response == NSAlertFirstButtonReturn:
        return CLOSE_KEEP_RUNNING
    elif response == NSAlertSecondButtonReturn:
        return CLOSE_QUIT
    else:
        return CLOSE_CANCEL


def on_window_closing():
    """Handle main window closing event.

    Checks for active processes and shows confirmation dialog with three options:
    - Terminate & Quit: Terminate all processes and exit
    - Keep Running: Hide window, keep processes running in background
    - Cancel: Cancel close, keep window open

    Returns:
        False to cancel the close event (pywebview uses inverted logic!)
        None/True to allow the close to proceed
    """
    global _main_window_ref

    # Check for active processes before closing
    if has_active_processes():
        logging.info("[Window] Active processes detected, showing confirmation")
        choice = show_close_confirmation()

        if choice == CLOSE_CANCEL:
            logging.info("[Window] User cancelled close")
            return False  # Cancel close, keep window open

        elif choice == CLOSE_KEEP_RUNNING:
            logging.info("[Window] User chose to keep running in background")
            # Hide the main window instead of closing
            if _main_window_ref:
                _main_window_ref.hide()
            logging.info(
                "[Window] Main window hidden, processes continue in background"
            )
            return False  # Cancel close, window is just hidden

        # CLOSE_QUIT - fall through to terminate and exit
        logging.info("[Window] User chose to terminate and quit")

    # Quit path. CLOSE_QUIT (user chose to terminate) and the no-active-processes
    # case (no dialog shown) both land here.
    if _launcher_ref is not None:
        # Single-process (Phase 2): on_window_closing runs ON THE MAIN THREAD
        # (inside webview's windowWillClose_ callback). A synchronous
        # NSApp.terminate_() would block this close event for the whole terminate
        # cascade AND re-enter AppKit -> spinning cursor. Defer it to the next
        # run-loop iteration; set the launcher's confirmed-quit flag so
        # applicationShouldTerminate_ skips its modal (no double-prompt); and
        # cancel THIS close (return False) so pywebview does not tear the window
        # down before terminate reaps the process. The run loop stops via the
        # delegate's terminate cascade.
        logging.info("[Window] Single-process quit: deferring NSApp.terminate_")
        _launcher_ref._user_confirmed_quit = True
        # Signal the Gradio supervisor (if mid backoff/retry) to stop so it
        # doesn't restart the backend as we're tearing the process down.
        _applio = getattr(_launcher_ref, "_applio_app", None)
        if _applio is not None:
            _applio._stopping = True

        def _deferred_terminate():
            try:
                from AppKit import NSApp

                NSApp.terminate_(None)
            except Exception as e:
                logging.warning(f"[Window] deferred NSApp.terminate_ failed: {e}")

        AppHelper.callAfter(_deferred_terminate)
        return False


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

    import applio_i18n

    _t = applio_i18n.native_tr

    panel = NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    panel.setCanCreateDirectories_(True)
    panel.setTitle_(_t("Select Applio Data Location"))
    panel.setPrompt_(_t("Select"))
    panel.setMessage_(
        _t("Choose where Applio will store models, datasets, and training data.")
    )

    if default_path:
        expanded = os.path.expanduser(default_path)
        if os.path.exists(expanded):
            panel.setDirectoryURL_(NSURL.fileURLWithPath_(expanded))

    result = panel.runModal()
    if result == NSModalResponseOK:
        return str(panel.URLs()[0].path())
    return None


def confirm_data_location(default_location, message, info):
    """First-run safety net: [Use Default] (Return) / [Choose Again…].

    Returns True when the user chose the default, False to re-run the picker.
    """
    from AppKit import NSAlert, NSApp, NSAlertFirstButtonReturn

    import applio_i18n

    _t = applio_i18n.native_tr

    NSApp.activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    # message/info arrive pre-translated from the call sites (they may embed
    # dynamic paths/errors, so they are template-formatted there, not here).
    alert.setMessageText_(message)
    alert.setInformativeText_(info)
    alert.addButtonWithTitle_(_t("Use Default"))
    alert.addButtonWithTitle_(_t("Choose Again…"))
    return alert.runModal() == NSAlertFirstButtonReturn


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


# =================================================================
# 1.6. Early Data Path Setup (BEFORE subprocess mode detection)
# =================================================================
# CRITICAL: This must happen before subprocess mode detection so that
# APPLIO_LOGS_PATH is available to subprocess scripts. The frozen early-prefs
# block now runs inside start_gui() (before the subprocess-script dispatch)
# so importing this module is side-effect-free.

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
        "timestamp": time.time() if "time" in dir() else 0,
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


# The frozen _write_runtime_config() call now runs inside start_gui() (after
# the early-prefs block, before the subprocess-script dispatch).

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

    # Own the root logger explicitly. logging.basicConfig is a NO-OP if the root
    # logger already has handlers (an AppKit/pyobjc import in the frozen entry
    # configures it first), which silently leaves the wrapper unlogged and
    # applio_wrapper.log stale — swallowing every error (incl. Gradio tracebacks).
    _root = logging.getLogger()
    _root.setLevel(logging.INFO)
    # Additive (Task 2b / §6.11): keep the launcher's existing handlers
    # (e.g. the applio_launcher.log FileHandler) and just add our wrapper
    # FileHandler alongside them. Do NOT wipe root handlers and do NOT
    # reassign stdout/stderr — the launcher owns those and the FileHandler
    # captures the wrapper's output.
    _fh = logging.FileHandler(log_file, mode="a")
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    _root.addHandler(_fh)

    logging.info("--- Applio macOS Native Session Start ---")
    logging.info(f"Version: {VERSION}")
    logging.info(f"CWD: {os.getcwd()}")
    logging.info(f"Base Path: {BASE_PATH}")
    logging.info(f"sys.frozen: {getattr(sys, 'frozen', False)}")
    logging.info(f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")


# setup_logging() is called from start_gui() (after activation-policy setup,
# before the subprocess-script dispatch) so importing this module is a no-op.

# =================================================================
# 3. Subprocess Script Execution Mode Detection
# =================================================================
# In PyInstaller frozen apps, sys.executable points to the app binary.
# When subprocess.run([sys.executable, "script.py"]) is called, it
# re-launches the entire app. We detect this and run the script instead.
# This must happen AFTER logging setup so script output is captured.
#
# The dispatch (if len(sys.argv) > 1: ... runpy.run_path ... sys.exit) now
# runs inside start_gui() after setup_logging() and the frozen early-prefs
# block, so importing this module is side-effect-free (no sys.exit at import).

# =================================================================
# 4. External Data Location Setup (GUI mode only)
# =================================================================
# This section only runs in GUI mode (not in subprocess mode). The data-path
# resolution, first-run picker, create_data_structure, os.chdir(DATA_PATH),
# setup_bundled_resources, env sync, and _write_runtime_config now run inside
# start_gui() so importing this module is side-effect-free (no folder picker,
# no os.chdir at import time).

# =================================================================
# 5. GUI Mode Initialization
# =================================================================
# Only reached if not in script execution mode. webview is imported inside
# start_gui() (after activation-policy configure+patch) because pywebview's
# cocoa.py forces setActivationPolicy_(0) + sharedApplication at import time.
import threading
import http.server
import socketserver

# =================================================================
# 5.1. Post-webview Activation Policy Cleanup
# =================================================================
# pywebview's cocoa.py called setActivationPolicy_(0) at import time.
# Our monkey-patch should have blocked it, but let's ensure Accessory policy
# is set and restore the original method.
#
# The unpatch + Accessory re-assert now run inside start_gui() AFTER
# `import webview` (see start_gui).

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
        # Main app config (config.json is gitignored/generated; bundle ships the
        # template, so copy it out as config.json for the running app)
        ("assets/config_template.json", "assets/config.json", "App config"),
        # TTS voices list
        (
            "rvc/lib/tools/tts_voices.json",
            "rvc/lib/tools/tts_voices.json",
            "TTS voices list",
        ),
        # Config files for different sample rates
        ("rvc/configs/48000.json", "rvc/configs/48000.json", "48kHz config"),
        ("rvc/configs/44100.json", "rvc/configs/44100.json", "44.1kHz config"),
        ("rvc/configs/40000.json", "rvc/configs/40000.json", "40kHz config"),
        ("rvc/configs/32000.json", "rvc/configs/32000.json", "32kHz config"),
        ("rvc/configs/24000.json", "rvc/configs/24000.json", "24kHz config"),
        # Pretrains download list
        (
            "assets/pretrains.json",
            "rvc/models/pretraineds/custom/pretrains.json",
            "Pretrains list",
        ),
        # JavaScript files for tabs
        (
            "tabs/report/recorder.js",
            "tabs/report/recorder.js",
            "Report tab recorder JS",
        ),
        ("tabs/report/main.js", "tabs/report/main.js", "Report tab main JS"),
        (
            "tabs/report/record_button.js",
            "tabs/report/record_button.js",
            "Report tab button JS",
        ),
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


# setup_bundled_resources() is called from start_gui() after os.chdir(DATA_PATH).


# =================================================================
# 2.5. Progress Monitor IPC Signal
# =================================================================


def _signal_show_progress_monitor():
    """
    Signal the launcher to show the Progress Monitor dashboard.

    Writes 'show_progress_monitor': True to runtime_paths.json.
    The launcher's IPC checker detects this and shows the dashboard.

    Returns:
        bool: True if signal was sent successfully, False otherwise.
    """
    import json
    import fcntl

    config_locations = [
        os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
        os.path.expanduser("~/.applio/runtime_paths.json"),
    ]

    for config_path in config_locations:
        config_dir = os.path.dirname(config_path)

        # Ensure directory exists
        if not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir, exist_ok=True)
            except OSError as e:
                logging.warning(f"[IPC] Could not create directory {config_dir}: {e}")
                continue

        # Read existing config or start fresh
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"[IPC] Could not read config at {config_path}: {e}")
                config = {}

        try:
            # Set the signal flag
            config["show_progress_monitor"] = True

            # Write atomically with file locking
            temp_path = config_path + ".tmp"
            with open(temp_path, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock
                json.dump(config, f, indent=2)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # Unlock
            os.rename(temp_path, config_path)

            logging.info(f"[IPC] Signaled show_progress_monitor via {config_path}")
            return True
        except Exception as e:
            logging.warning(f"[IPC] Failed to write config at {config_path}: {e}")

    return False


def _show_progress_monitor_info():
    """Show info dialog when Progress Monitor is not available.

    Called in standalone mode where there's no launcher to show the dashboard.
    """
    try:
        from AppKit import NSAlert, NSAlertStyleInformational

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Progress Monitor")
        alert.setInformativeText_(
            "The Progress Monitor shows real-time training and inference progress.\n\n"
            "To use this feature, launch Applio via the main application bundle.\n\n"
            "In standalone mode, you can monitor progress via:\n"
            "• Terminal output\n"
            "• Log files in ~/Library/Logs/Applio/"
        )
        alert.setAlertStyle_(NSAlertStyleInformational)
        alert.addButtonWithTitle_("OK")
        alert.runModal()
    except ImportError:
        # Fallback for non-macOS platforms
        print("Progress Monitor requires running under the Applio launcher.")


def render_pywebview():
    """Build the standalone pywebview menu from menu_spec (static subset).

    pywebview Menu/MenuAction are immutable and cannot bind shortcuts; the menu
    rebuilds only on windowDidBecomeKey (webview/platforms/cocoa.py). So this is
    a STATIC render: no dynamic status, no shortcuts. pywebview's unconditional
    _add_app_menu already injects About/Hide/HideOthers/Quit, so the __app__
    payload carries only the Applio-specific app-menu item (Check for Updates).
    """
    from webview.menu import Menu, MenuAction, MenuSeparator
    from menu_spec import MENU, PYWEBVIEW_APP_KEY

    def open_in_finder(subpath: str):
        if ApplioApp.DATA_PATH:
            full_path = os.path.join(ApplioApp.DATA_PATH, subpath)
            FinderHelper.open_path(full_path)

    def change_data_location():
        new_path = select_data_folder(ApplioApp.DATA_PATH)
        if new_path and new_path != ApplioApp.DATA_PATH:
            PreferencesManager().set_data_path(new_path)
            logging.info(f"Data location changed to: {new_path} (restart required)")

    dispatch = _build_wrapper_dispatch(open_in_finder, change_data_location)

    import applio_i18n

    _tr = applio_i18n.native_tr  # titles translate at render; spec stays English

    def build(nodes, is_app_payload=False):
        items = []
        for mi in nodes:
            if mi.separator:
                # Collapse leading/consecutive separators (app-menu payload omits
                # about/hide/hide_others/quit, which would leave dangling separators).
                if items and not isinstance(items[-1], MenuSeparator):
                    items.append(MenuSeparator())
                continue
            if mi.submenu:
                children = build(mi.submenu)
                if not children:
                    continue  # empty nested submenu (children launcher-only, e.g.
                    # Accessibility) — mirrors the top-level empty check below
                items.append(Menu(_tr(mi.title), children))
                continue
            if not mi.key:
                continue  # display-only status line: pywebview can't mutate it; skip
            fn = dispatch.get(mi.key)
            if fn is None:
                continue  # keys pywebview injects (about/hide/hide_others/quit) -> omit
            items.append(MenuAction(_tr(mi.title), (lambda f=fn: f())))
        if items and isinstance(items[-1], MenuSeparator):
            items.pop()  # drop a trailing separator
        return items

    out = []
    for idx, top in enumerate(MENU):
        if idx == 0:
            out.append(Menu(PYWEBVIEW_APP_KEY, build(top.submenu, is_app_payload=True)))
        else:
            children = build(top.submenu)
            if not children:
                continue  # e.g. Edit: selector-only items this renderer cannot bind
            out.append(Menu(_tr(top.title), children))
    return out


def _build_wrapper_dispatch(open_in_finder, change_data_location):
    import applio_update_check
    from menu_spec import REVEAL_PATHS

    d = {}
    d["app.check_updates"] = applio_update_check.check_for_updates_interactive
    d["file.set_data_location"] = change_data_location
    for key, sub in REVEAL_PATHS.items():
        d[key] = lambda s=sub: open_in_finder(s)
    d["process.open_dashboard"] = _show_progress_monitor_info
    d["process.open_logs"] = lambda: subprocess.Popen(
        ["open", os.path.expanduser("~/Library/Logs/Applio")]
    )
    # pywebview Window exposes show()/restore()/minimize(). Wire the two window
    # actions we CAN implement; OMIT window.zoom and window.bring_all_to_front
    # (no pywebview API) rather than ship no-ops.
    d["window.minimize"] = _minimize_main_window
    d["window.show_main"] = _focus_main_window
    d["help.guide"] = lambda: _open_bundled_guide()
    d["help.docs"] = lambda: webbrowser.open("https://docs.applio.org")
    d["help.report_issue"] = lambda: webbrowser.open(
        "https://github.com/froggeric/applio-macOS-native-app/issues"
    )
    d["help.discord"] = lambda: webbrowser.open("https://discord.gg/IAHispano")
    return d


def _focus_main_window():
    """Best-effort: restore + show the first pywebview window (standalone)."""
    try:
        for w in webview.windows:
            try:
                w.restore()
            except Exception:
                pass
            w.show()
    except Exception as e:
        logging.warning(f"[Wrapper] show main window failed: {e}")


def _minimize_main_window():
    """Best-effort: minimize the first pywebview window (standalone)."""
    try:
        for w in webview.windows:
            w.minimize()
    except Exception as e:
        logging.warning(f"[Wrapper] minimize failed: {e}")


def _open_bundled_guide():
    for name in ("STUDIO_PRODUCTION_GUIDE.html", "STUDIO_PRODUCTION_GUIDE.md"):
        p = os.path.join(BASE_PATH, name)
        if os.path.exists(p):
            webbrowser.open("file://" + p)
            return
    logging.warning("[Wrapper] Studio Production Guide is not bundled")


# =================================================================
# 3. App Core Class
# =================================================================


def _supervised_backend(app):
    """Single-process Gradio supervisor: soft-restart up to 3x, then fatal.

    Wraps ``app.start_backend()`` (which blocks for Gradio's lifetime and RAISES
    on failure in single-process). On an exception it logs, backs off linearly
    (3 s, 6 s), and retries; after 3 soft failures it escalates to a native
    fatal alert + in-process terminate via ``_report_fatal_error``. Honors
    ``app._stopping`` so a user-initiated quit aborts the retry/backoff loop.
    """
    attempts = 0
    last_err = None
    while not app._stopping and attempts < 3:
        try:
            app.start_backend()  # RAISES in single-process; blocks for Gradio's lifetime
            return  # clean shutdown
        except Exception as e:
            last_err = e
            attempts += 1
            # exc_info=True preserves the full traceback in the log (stdout/stderr is no longer
            # redirected to the log in single-process, so the bare traceback would be lost).
            logging.error(
                f"[Gradio] crashed (attempt {attempts}/3): {e}", exc_info=True
            )
            # Non-transient errors (e.g. EADDRINUSE — port 6969 already bound by another instance;
            # single-process has no orphan-wrapper reaper) won't resolve on retry — fail fast instead
            # of wasting the 3 s/6 s backoff.
            if isinstance(e, OSError):
                break
            if attempts < 3:
                time.sleep(3 * attempts)  # linear backoff: 3 s, 6 s
    # Fatal. Guard: the loop ALSO exits if the user quit mid-retry (_stopping flipped during the
    # backoff) — don't show a spurious alert then; the quit path owns termination. Include the
    # underlying error so the alert/log is actionable (e.g. "Address already in use").
    if not app._stopping:
        detail = f": {last_err}" if last_err else ""
        app._report_fatal_error(
            f"The backend failed to start after {attempts} attempt(s){detail}."
        )


class ApplioApp:
    # Class-level data path for menu callbacks
    DATA_PATH = None  # Set after initialization

    def __init__(self, launcher=None):
        import applio_i18n

        _t = applio_i18n.native_tr

        self.server_host = "127.0.0.1"
        self.server_port = 6969
        self.loading_port = 5678
        self.window = None
        self.is_ready = False
        self.heading = _t("System Calibration")
        self.sub_heading = _t("Initializing environment...")
        self.technical_detail = _t("Allocating memory...")
        self.progress = 0
        self.stage = "1/4"
        self.log_file = os.path.expanduser("~/Library/Logs/Applio/applio_wrapper.log")
        # Launcher handle (None in standalone).
        self.launcher = launcher
        # Reentrancy guard for shutdown (used by later Phase 2 tasks).
        self._stopping = False
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
                        "detail": parent.technical_detail,
                    }
                    self.wfile.write(json.dumps(data).encode("utf-8"))
                    return

                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                try:
                    path = os.path.join(BASE_PATH, "assets", "loading.html")
                    with open(path, "r") as f:
                        self.wfile.write(f.read().encode("utf-8"))
                except Exception as e:
                    self.wfile.write(
                        f"<h1>Loading Applio...</h1><p>{e}</p>".encode("utf-8")
                    )

            def log_message(self, format, *args):
                pass

        try:
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(
                (self.server_host, self.loading_port), LoadingHandler
            ) as httpd:
                logging.info(f"Loading UI server active on port {self.loading_port}")
                httpd.serve_forever()
        except Exception as e:
            logging.error(f"Loading UI server failed: {e}")

    def tail_logs(self):
        """Expert Log Observer with Real-Time Technical Feed."""
        import re

        import applio_i18n

        _t = applio_i18n.native_tr

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
                with open(self.log_file, "r") as f:
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
                        if not line:
                            continue

                        # --- LOGIC MAPPING ---

                        # 1. Downloads
                        if p_dl_percent.search(line):
                            self.stage = "2/4"
                            self.heading = _t("Synchronizing Assets")
                            match = p_dl_percent.search(line)
                            val = int(match.group(1))
                            if val > self.progress:
                                self.progress = val

                        elif p_dl_file.search(line):
                            self.stage = "2/4"
                            self.heading = _t("Synchronizing Assets")
                            fname = p_dl_file.search(line).group(1)
                            self.sub_heading = _t("Fetching {basename}").format(
                                basename=os.path.basename(fname)
                            )
                            self.technical_detail = _t(
                                "Network Request: {fname}"
                            ).format(fname=fname)

                        # 2. Operations
                        elif p_extract.search(line):
                            self.stage = "2/4"
                            self.heading = _t("Decompressing Resources")
                            fname = p_extract.search(line).group(1)
                            self.sub_heading = _t("Unpacking {basename}").format(
                                basename=os.path.basename(fname)
                            )
                            self.technical_detail = _t("IO Operation: {fname}").format(
                                fname=fname
                            )

                        elif p_pip_install.search(line):
                            self.stage = "2/4"
                            self.heading = _t("Building Environment")
                            pkgs = p_pip_install.search(line).group(1)
                            if len(pkgs) > 30:
                                pkgs = pkgs[:27] + "..."
                            self.sub_heading = _t("Installing {pkgs}").format(pkgs=pkgs)
                            self.technical_detail = line

                        # 3. Initialization
                        elif p_prereq.search(line):
                            self.stage = "1/4"
                            self.heading = _t("System Validation")
                            self.sub_heading = _t("Checking Prerequisites...")
                            if self.progress < 10:
                                self.progress = 10

                        elif p_device.search(line):
                            self.heading = _t("Hardware Optimization")
                            device = p_device.search(line).group(1)
                            self.sub_heading = _t("Accelerating with {device}").format(
                                device=device
                            )
                            self.technical_detail = _t(
                                "Device allocation: {device}"
                            ).format(device=device)

                        # 4. Boot
                        elif p_init_app.search(line):
                            self.stage = "3/4"
                            self.heading = _t("Booting Inference Engine")
                            self.sub_heading = _t("Loading Neural Networks...")
                            self.technical_detail = _t(
                                "Initializing pytorch contexts..."
                            )
                            if self.progress < 80:
                                self.progress = 80

                        elif p_load_model.search(line):
                            self.heading = _t("Loading Models")
                            model = p_load_model.search(line).group(1)
                            self.sub_heading = _t("Hydrating {model}...").format(
                                model=model
                            )
                            self.technical_detail = _t("Memory mapping {model}").format(
                                model=model
                            )

                        # 5. Success
                        elif (
                            p_server.search(line)
                            or p_responsive.search(line)
                            or "Gradio backend is responsive" in line
                        ):
                            self.stage = "4/4"
                            self.heading = _t("Initialization Complete")
                            self.sub_heading = _t("Launching User Interface...")
                            self.progress = 100
                            self.is_ready = True
                            return

                        # GENERIC FALLBACK: Show raw log activity
                        else:
                            clean = line
                            if len(clean) > 8 and "it/s]" not in clean:
                                if ":root:" in clean:
                                    clean = clean.split(":root:", 1)[1].strip()
                                if len(clean) > 60:
                                    clean = clean[:57] + "..."
                                self.technical_detail = clean
                                if self.stage == "1/4" and self.sub_heading == _t(
                                    "Initializing environment..."
                                ):
                                    self.sub_heading = _t("Configuring Runtime...")

                        self._sync_title_to_heading()
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
            # Don't swallow silently (1.6): a bind failure (port already in use)
            # would otherwise leave the loading screen hung forever. Surface a
            # real error to the user, then quit.
            logging.error(f"Backend launch failed: {e}")
            msg = f"Applio failed to start its backend.\n\n{e}"
            if isinstance(e, OSError):
                msg = (
                    f"Applio could not bind port {self.server_port}. Another "
                    f"instance may already be running.\n\n{e}"
                )
            # Re-raise so _supervised_backend can soft-restart (up to 3x, linear
            # backoff) before escalating to a fatal alert via _report_fatal_error.
            raise

    def _report_fatal_error(self, message):
        """Show a fatal-error alert on the main thread, then quit.

        Single-process only: terminate THIS process in-place -- the launcher
        owns the lifecycle, so there is no separate wrapper to signal.
        """

        def _show_and_quit():
            try:
                from AppKit import NSAlert

                alert = NSAlert.alloc().init()
                alert.setMessageText_("Applio failed to start")
                alert.setInformativeText_(message)
                alert.addButtonWithTitle_("OK")
                alert.runModal()
            except Exception as ae:
                logging.warning(f"[Wrapper] Could not show fatal alert: {ae}")

            # Defer NSApp.terminate_ to the next run-loop iteration (same
            # closure/sender pattern as on_window_closing); runModal() above has
            # already returned.
            def _deferred_terminate():
                try:
                    from AppKit import NSApp

                    NSApp.terminate_(None)
                except Exception as te:
                    logging.warning(f"[Wrapper] deferred NSApp.terminate_ failed: {te}")

            AppHelper.callAfter(_deferred_terminate)

        try:
            AppHelper.callAfter(_show_and_quit)
        except Exception:
            try:
                from AppKit import NSApp

                AppHelper.callAfter(lambda: NSApp.terminate_(None))
            except Exception as fe:
                logging.warning(f"[Wrapper] fatal-alert schedule failed: {fe}")

    def monitor_transition(self):
        """Switches from loading screen to main app."""
        if self.wait_for_backend():
            # Graceful delay for UI settling
            time.sleep(1.5)
            if self.window:
                logging.info("Transitioning to main UI...")
                self.window.load_url(f"http://{self.server_host}:{self.server_port}")
                self._post_layout_changed()
                self._set_window_title("Applio")
        else:
            logging.error("Backend timeout period exceeded.")
            self._set_window_title("Applio — Startup Error")
            try:
                from PyObjCTools import AppHelper

                AppHelper.callAfter(self._alert_startup_timeout)
            except Exception:
                pass
            if self.window:
                self.window.load_html(
                    "<h1>Startup Error</h1><p>The server failed to respond in time.</p>"
                )

    def _post_layout_changed(self):
        """Marshal to main thread — monitor_transition runs on a daemon thread."""
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._do_post_layout_changed)
        except Exception:
            pass

    def _do_post_layout_changed(self):
        """Force VoiceOver AX-tree resync after the full page swap.

        WKWebView accessibility trees can fall out of sync on async loads
        (Apple forums thread 809541 / FB21257352); LayoutChanged is the
        documented workaround.
        """
        try:
            from AppKit import (
                NSAccessibilityPostNotification,
                NSAccessibilityLayoutChangedNotification,
            )

            wv = self.window.native.contentView()
            NSAccessibilityPostNotification(
                wv, NSAccessibilityLayoutChangedNotification
            )
        except Exception:
            pass

    def _set_window_title(self, title):
        """pywebview Window.set_title (verified at webview/window.py:314).

        Thread-safe from tail_logs' daemon thread: the cocoa backend marshals
        via AppHelper.callAfter (cocoa.py:761-762). set_title is wrapped in
        @_shown_call, so before the window is shown it blocks up to 20 s then
        raises — the getattr guard + except covers the early race (threads
        start at L1441-1449, self.window is created at L452).
        """
        try:
            if getattr(self, "window", None):
                self.window.set_title(title)
        except Exception:
            logging.debug("[A11y] set_title failed", exc_info=True)

    def _sync_title_to_heading(self):
        """Set the window title to the current heading, deduped.

        ONE call site (end of tail_logs' per-line dispatch) instead of one
        per branch: the LOGIC MAPPING block at L1238-1329 has ~12 assignment
        branches — hooking each would churn. Title is heading-only (never the
        download percent: percent lines arrive many times per second).
        """
        if self.heading != getattr(self, "_last_title_heading", None):
            self._last_title_heading = self.heading
            self._set_window_title(f"Applio — {self.heading}")

    def _alert_startup_timeout(self):
        """Main-thread NSAlert for the boot-timeout path (was a silent <h1>)."""
        try:
            from AppKit import NSAlert, NSApp

            import applio_i18n

            _t = applio_i18n.native_tr

            NSApp.activateIgnoringOtherApps_(True)
            alert = NSAlert.alloc().init()
            alert.setMessageText_(_t("Applio failed to start"))
            alert.setInformativeText_(
                _t(
                    "The backend did not become ready in time. The log file explains "
                    "why: once the window loads, use Process → Open Debug Logs…, or "
                    "open ~/Library/Logs/Applio/ manually."
                )
            )
            alert.addButtonWithTitle_(_t("OK"))
            alert.runModal()
        except Exception:
            pass

    def run_until_window_created(self):
        """Start helper/backend threads and create the pywebview window.

        Does NOT block and does NOT call ``webview.start`` -- the caller owns
        running the webview event loop (so the launcher / __main__ can drive it).
        Contains everything the old ``run()`` did except the final
        ``webview.start(...)`` line.
        """
        # 1. Start Helpers
        threading.Thread(target=self.start_loading_server, daemon=True).start()
        threading.Thread(target=self.tail_logs, daemon=True).start()

        # 2. Start Backend direct. Wrap start_backend in the supervisor so a
        # Gradio crash soft-restarts (up to 3x, linear backoff) before escalating
        # to a fatal alert.
        logging.info("Launching Backend directly...")
        threading.Thread(target=lambda: _supervised_backend(self), daemon=True).start()
        threading.Thread(target=self.monitor_transition, daemon=True).start()

        # 3. Main Window
        self.window = webview.create_window(
            "Applio",
            url=f"http://{self.server_host}:{self.loading_port}",
            width=1280,
            height=900,
            min_size=(1024, 720),
            resizable=True,
            text_select=True,
            vibrancy=True,
        )

        self.window.events.closing += on_window_closing
        global _main_window_ref
        _main_window_ref = self.window

        logging.info("Starting Webview GUI...")

        # Always create the pywebview menu (Progress Monitor entry, etc.).
        webview.settings["SHOW_DEFAULT_MENUS"] = False  # suppress auto View/Edit menus
        # gr.File download links (model export, F0 txt) are silently cancelled without this.
        # NOTE (intended behavior change): any non-displayable response now offers a
        # save panel instead of doing nothing — that is exactly the export journey fix.
        webview.settings["ALLOW_DOWNLOADS"] = True

    def run(self):
        # Convenience: window bootstrap + blocking webview loop. Requires start_gui() to have run
        # first (it sets up env/DATA_PATH and imports webview). Currently UNUSED — __main__ and the
        # launcher both call start_gui() + webview.start(...) directly. Candidate for removal in Task 1+.
        self.run_until_window_created()
        webview.start(menu=render_pywebview(), debug=False)


def start_gui(launcher=None):
    """Bootstrap the GUI in the calling process. Does NOT block.

    Returns the ApplioApp instance. The caller holds ``app.window`` and runs
    ``webview.start(...)`` (which blocks until the window closes).

    This consolidates every module-level side effect (multiprocessing
    freeze_support, env/cache setup, activation-policy configure+patch,
    logging, frozen early data-path setup, the subprocess-script dispatch,
    data-path resolution + ``os.chdir``, bundled-resource copy, and
    ``import webview``) so that merely importing ``macos_wrapper`` is
    side-effect-free. Ordering is load-bearing:

      * ``os.chdir(DATA_PATH)`` and activation-policy configure+patch happen
        BEFORE ``import webview`` (pywebview's cocoa.py forces
        setActivationPolicy_(0) + sharedApplication at import time, and the
        frozen CWD must be the data dir before Gradio is imported in a worker).
      * Activation-policy unpatch + Accessory re-assert happen AFTER.
    """
    # 0. Multiprocessing safety (must run before any workers are spawned; was
    #    the very first statement at module scope).
    multiprocessing.freeze_support()

    # 1. Performance tuning + cache/env redirection (moved from the module-level
    #    env/makedirs block). APP_SUPPORT_DIR was only used here -> local.
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    os.environ["PYTORCH_ENABLE_METAL_ACCELERATOR"] = "1"
    os.environ["GRADIO_ALLOWED_PATHS"] = (
        "/,/,/private/var/folders,/var/folders,/tmp,/private/tmp"
    )
    os.environ["GRADIO_TEMP_DIR"] = os.path.expanduser("~/Library/Caches/Applio/gradio")
    os.makedirs(os.environ["GRADIO_TEMP_DIR"], exist_ok=True)
    _app_support_dir = os.path.expanduser("~/Library/Application Support/Applio")
    os.makedirs(_app_support_dir, exist_ok=True)
    os.environ["HF_HOME"] = os.path.join(_app_support_dir, "huggingface")
    os.environ["HF_DATASETS_CACHE"] = os.path.join(
        _app_support_dir, "huggingface", "datasets"
    )
    os.environ["TRANSFORMERS_CACHE"] = os.path.join(
        _app_support_dir, "huggingface", "models"
    )
    os.environ["MPLCONFIGDIR"] = os.path.join(_app_support_dir, "matplotlib")
    os.environ["TORCH_HOME"] = os.path.join(_app_support_dir, "torch")

    # Frozen PyInstaller CWD hygiene: cwd to the bundle before any relative
    # reads (build_info.json, configs). Was at module scope right after the
    # BASE_PATH assignment; DATA_PATH chdir follows below.
    if getattr(sys, "frozen", False):
        os.chdir(BASE_PATH)

    # 2. Activation policy: configure + patch -- BEFORE ``import webview``.
    _configure_activation_policy()
    _patch_pywebview_activation_policy()

    # 3. Logging (must precede subprocess-script dispatch so output is captured).
    setup_logging()

    # Frozen early data-path setup (moved from the early-prefs block): makes
    # APPLIO_LOGS_PATH / APPLIO_DATA_PATH available to subprocess scripts that
    # run via the dispatch below BEFORE the GUI data-path resolution.
    if getattr(sys, "frozen", False):
        _early_prefs = PreferencesManager()
        _early_data_path = _early_prefs.get_data_path() or os.path.expanduser(
            "~/Applio"
        )
        # Debug logging only when APPLIO_DEBUG env var is set
        if os.environ.get("APPLIO_DEBUG"):
            with open("/tmp/applio_debug.txt", "a") as f:
                f.write(f"=== Early env setup ===\n")
                f.write(f"_early_data_path={_early_data_path}\n")
                f.write(f"APPLIO_LOGS_PATH={os.path.join(_early_data_path, 'logs')}\n")
                f.write(f"PID={os.getpid()}\n")
        os.environ["APPLIO_DATA_PATH"] = _early_data_path
        os.environ["APPLIO_LOGS_PATH"] = os.path.join(_early_data_path, "logs")
        # Also set these for subprocess scripts that may need them
        os.environ["APPLIO_DATASETS_PATH"] = os.path.join(
            _early_data_path, "assets", "datasets"
        )
        os.environ["APPLIO_AUDIOS_PATH"] = os.path.join(
            _early_data_path, "assets", "audios"
        )

        # Write config in frozen mode (ensures it's available for all subprocesses).
        _write_runtime_config()

    # Subprocess script execution mode (moved from module scope). If launched as
    # ``macos_wrapper.py <script.py> [args...]``, run that script and exit.
    # Preserves the path-resolution + ``os.chdir(_data_path)`` logic exactly.
    if len(sys.argv) > 1:
        potential_script = sys.argv[1]

        # Check if it's a Python script path
        if potential_script.endswith(".py"):
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
                if (
                    script_path.endswith("rvc/train/preprocess/preprocess.py")
                    and len(script_args) >= 2
                ):
                    dataset_path = script_args[1]
                    original_path = dataset_path

                    # First check: does path exist as-is?
                    if not os.path.exists(dataset_path):
                        # Second check: try resolving relative path from DATA_PATH (user's data location)
                        if not os.path.isabs(dataset_path):
                            data_path = os.environ.get(
                                "APPLIO_DATA_PATH", os.path.expanduser("~/Applio")
                            )
                            resolved_from_data = os.path.normpath(
                                os.path.join(data_path, dataset_path)
                            )
                            if os.path.exists(resolved_from_data):
                                dataset_path = resolved_from_data
                                script_args[1] = resolved_from_data
                                logging.info(
                                    f"Dataset path resolved from DATA_PATH: {original_path} -> {resolved_from_data}"
                                )
                            else:
                                # Third check: try resolving relative path from BASE_PATH (app bundle)
                                resolved_from_base = os.path.normpath(
                                    os.path.join(BASE_PATH, dataset_path)
                                )
                                if os.path.exists(resolved_from_base):
                                    dataset_path = resolved_from_base
                                    script_args[1] = resolved_from_base
                                    logging.info(
                                        f"Dataset path resolved from BASE_PATH: {original_path} -> {resolved_from_base}"
                                    )
                                else:
                                    logging.error(
                                        f"Dataset path not found: {original_path}"
                                    )
                                    logging.error(
                                        f"  Tried DATA_PATH: {resolved_from_data}"
                                    )
                                    logging.error(
                                        f"  Tried BASE_PATH: {resolved_from_base}"
                                    )
                                    print(
                                        f"Error: Dataset path does not exist: {original_path}"
                                    )
                                    print(f"  Tried: {resolved_from_data}")
                                    print(f"  Tried: {resolved_from_base}")
                                    print(
                                        f"  Please use an absolute path to your dataset folder."
                                    )
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
                _data_path = os.environ.get(
                    "APPLIO_DATA_PATH", os.path.expanduser("~/Applio")
                )
                _original_cwd = os.getcwd()
                os.chdir(_data_path)
                logging.info(f"Changed CWD for subprocess: {_data_path}")

                # Ensure config file is written before running subprocess script
                # This handles the case where subprocess starts before main GUI
                _write_runtime_config()

                try:
                    runpy.run_path(script_path_abs, run_name="__main__")
                    logging.info(f"Script completed successfully: {script_path_abs}")
                    sys.exit(0)
                except SystemExit as e:
                    # SystemExit is raised by sys.exit() in the script
                    # Non-zero exit codes indicate failure
                    if e.code != 0 and e.code is not None:
                        logging.error(
                            f"Script exited with code {e.code}: {script_path_abs}"
                        )
                    else:
                        logging.info(f"Script exited normally: {script_path_abs}")
                    sys.exit(e.code if e.code is not None else 0)
                except Exception as e:
                    logging.error(f"Script execution failed: {script_path_abs}")
                    logging.exception(e)
                    sys.exit(1)
                finally:
                    os.chdir(_original_cwd)  # Restore original CWD

    # 4. GUI data-path resolution + chdir + bundled resources (moved from the
    #    module-level GUI block). First-run picker runs here, NOT at import.
    global DATA_PATH
    _prefs = PreferencesManager()
    DATA_PATH = _prefs.get_data_path()

    if not DATA_PATH:
        import applio_i18n

        _t = applio_i18n.native_tr

        # First run - prompt for location
        default_location = os.path.expanduser("~/Applio")
        DATA_PATH = select_data_folder(default_location)

        while not DATA_PATH:
            # User cancelled - confirm the fallback instead of silently defaulting
            use_default = confirm_data_location(
                default_location,
                _t("No data location was chosen."),
                _t(
                    "Applio stores models, datasets and training results in the data "
                    "location. Use the default ({default}) or choose again?"
                ).format(default=default_location),
            )
            if use_default:
                DATA_PATH = default_location
                logging.info(f"User confirmed default data location: {DATA_PATH}")
            else:
                DATA_PATH = select_data_folder(default_location)

        # Validate path is writable
        path_error = None
        try:
            os.makedirs(DATA_PATH, exist_ok=True)
            test_file = os.path.join(DATA_PATH, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except (IOError, OSError) as e:
            path_error = str(e)

        while path_error is not None:
            use_default = confirm_data_location(
                default_location,
                _t("The selected location is not writable."),
                _t(
                    "Error: {error}\nUse the default location "
                    "({default}) or choose again?"
                ).format(error=path_error, default=default_location),
            )
            if use_default:
                path_error = None
                DATA_PATH = default_location
                try:
                    os.makedirs(DATA_PATH, exist_ok=True)
                except (IOError, OSError) as e:
                    # Default itself unwritable (~/Applio) — hard stop with the
                    # error rather than an unhandled crash at startup.
                    logging.error(f"Default data location unwritable: {e}")
                    raise
            else:
                DATA_PATH = select_data_folder(default_location)
                if not DATA_PATH:
                    # Cancelled the re-pick: keep the previous error and
                    # re-offer the alert (os.makedirs(None) would raise TypeError).
                    continue
                path_error = None
                try:
                    os.makedirs(DATA_PATH, exist_ok=True)
                    test_file = os.path.join(DATA_PATH, ".write_test")
                    with open(test_file, "w") as f:
                        f.write("test")
                    os.remove(test_file)
                except (IOError, OSError) as e:
                    path_error = str(e)

        # Save preference
        _prefs.set_data_path(DATA_PATH)
        _prefs.mark_first_run_complete()
        logging.info(f"Data location set to: {DATA_PATH}")

    # Create directory structure
    create_data_structure(DATA_PATH)

    # Change working directory to user data location
    # This causes all relative paths (now_dir = os.getcwd()) to resolve here.
    # frozen-CWD invariant: BEFORE import webview / Gradio (deferred
    # `from app import launch_gradio` fires in start_backend's thread).
    os.chdir(DATA_PATH)
    logging.info(f"Working directory changed to: {DATA_PATH}")

    # Set APPLIO_LOGS_PATH for core.py — ensures logs_path is correct regardless of import
    # timing. Byte-for-byte Step 0: this UNCONDITIONAL GUI-block write existed in the original
    # (L1120) and MUST be kept — core.py's _get_logs_path() prefers this env var, so without it
    # dev-mode never sets it and frozen-first-run can be left with the stale ~/Applio guess.
    # (APPLIO_DATA_PATH has NO unconditional GUI write in the original [frozen-early-block only],
    # so it is intentionally NOT exported here; its unconditional resolved-path export is a
    # Task 2 / §6.12 change for single-process training subs.)
    os.environ["APPLIO_LOGS_PATH"] = os.path.join(DATA_PATH, "logs")

    # Copy bundled static resources to the data location (was called at module
    # scope after import webview; CWD-independent, so safe before it).
    setup_bundled_resources()
    # Byte-for-byte Step 0: the original GUI block did NOT call _write_runtime_config() here —
    # only the frozen early-prefs block and the subprocess-script dispatch do (both preserved in
    # their own branches above). The single-process skeleton's unconditional _write_runtime_config()
    # in this GUI path is deferred to Task 1+. Omitting it matches the original; the launcher's
    # runtime_paths.json read is already covered by the frozen early-block write.

    # 5. import webview -- pywebview forces Regular + sharedApplication here;
    #    the launcher owns the (Regular) dock icon in single-process. `global
    #    webview` so the import binds the MODULE global used by run(),
    #    render_pywebview(), _focus_main_window(), etc.
    global webview
    import webview

    # 6. Activation policy: unpatch is a guarded no-op in single-process (the
    #    patch step never applied anything); kept for bootstrap-step parity.
    _unpatch_pywebview_activation_policy()

    # 7. Expose launcher to the module-level on_window_closing (used by later tasks).
    global _launcher_ref
    _launcher_ref = launcher

    # 8. The app: create window + start helper/backend threads (does NOT block,
    #    does NOT call webview.start -- the caller owns that).
    app = ApplioApp(launcher=launcher)
    app.run_until_window_created()
    return app


if __name__ == "__main__":
    app = start_gui()
    webview.start(menu=render_pywebview(), debug=False)
