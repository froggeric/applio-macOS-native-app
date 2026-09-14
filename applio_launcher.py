#!/usr/bin/env python3
"""
Applio Launcher - Native single-process entry point.

Main entry point for Applio.app. Runs the pywebview/Gradio GUI in-process
(via macos_wrapper.start_gui) and hosts the native menu bar, dock, and the
Process Dashboard window.

Architecture (single process):
    applio_launcher.py  (this file; the whole native app)
      -> macos_wrapper.start_gui()  (in-process: env bootstrap + Gradio + webview window)
           -> training / preprocess / extract / tts subprocesses
"""

# =================================================================
# 0. Multiprocessing Safety (MUST BE FIRST)
# =================================================================
import multiprocessing

multiprocessing.freeze_support()

# =================================================================
# 0.5. Early Imports for Process Group Setup
# =================================================================
import os
import logging


# =================================================================
# 0.6. Process Group Setup (MUST BE EARLY)
# =================================================================
def _setup_process_group():
    """Establish this process as session leader for cascade termination.

    When the launcher terminates, all child processes in the session
    will receive the signal, enabling graceful cascade shutdown.
    """
    try:
        os.setsid()  # Create new session, become session leader
        pgid = os.getpgid(0)
        logging.info(f"[Launcher] Session leader established: PGID={pgid}")
        return pgid
    except OSError as e:
        logging.warning(f"[Launcher] Could not create session: {e}")
        return None


_LAUNCHER_PGID = _setup_process_group()

# =================================================================
# 1. Imports & Environment Setup
# =================================================================
import sys
import signal
import subprocess
import threading
import queue
import json
import re
import datetime
import fcntl
import time
from pathlib import Path
from collections import deque
import weakref
import menu_spec
import applio_a11y

# Optional psutil for process verification
try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# macOS native APIs
try:
    from AppKit import (
        NSApplication,
        NSApp,
        NSMenu,
        NSMenuItem,
        NSWindow,
        NSButton,
        NSTextField,
        NSProgressIndicator,
        NSScrollView,
        NSTextView,
        NSTableView,
        NSTableColumn,
        NSMakeRect,
        NSTitledWindowMask,
        NSClosableWindowMask,
        NSMiniaturizableWindowMask,
        NSBackingStoreBuffered,
        NSCenterTextAlignment,
        NSRightTextAlignment,
        NSFont,
        NSBezelBorder,
        NSApplicationActivationPolicyRegular,
        NSAccessibilityAnnouncementRequestedNotification,
        NSCommandKeyMask,
        NSShiftKeyMask,
        NSAlternateKeyMask,
        NSBox,
        NSColor,
        NSBoxPrimary,
        NSView,
        NSProgressIndicatorBarStyle,
        NSFontWeightMedium,
        NSFontWeightSemibold,
        NSFontWeightRegular,
        NSBezierPath,
        NSWorkspace,
        NSAttributedString,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
    )
    from Foundation import (
        NSRunLoop,
        NSDate,
        NSNotificationCenter,
        NSURL,
        NSRange,
        NSObject,
    )
    from PyObjCTools import AppHelper
    import objc

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
                    element, NSAccessibilityAnnouncementRequestedNotification, userInfo
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


# Performance tuning for Apple Silicon
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["PYTORCH_ENABLE_METAL_ACCELERATOR"] = "1"

# Path setup for PyInstaller
if getattr(sys, "frozen", False):
    BASE_PATH = sys._MEIPASS
    os.chdir(BASE_PATH)
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))


def _update_check():
    import applio_update_check

    return applio_update_check


# =================================================================
# 2. Subprocess Mode Detection (MUST BE BEFORE LOGGING)
# =================================================================
# In PyInstaller frozen apps, sys.executable points to this launcher.
# When subprocesses are spawned via subprocess.Popen([sys.executable, "script.py"]),
# this launcher is re-executed with the script path as argv[1].
# We detect this and delegate to the script via runpy.
#
# This handles:
# - rvc/train/train.py (training)
# - rvc/train/preprocess/preprocess.py (preprocessing)
# - rvc/train/extract/extract.py (feature extraction)
# - Any other Python scripts spawned by core.py

if len(sys.argv) > 1:
    potential_script = sys.argv[1]
    # Accept any .py script, not just macos_wrapper.py
    if potential_script.endswith(".py") and not potential_script.startswith("-"):
        # Find the script - check both absolute path and relative to BASE_PATH
        script_path = None
        if os.path.exists(potential_script):
            script_path = potential_script
        elif os.path.exists(os.path.join(BASE_PATH, potential_script)):
            script_path = os.path.join(BASE_PATH, potential_script)

        if script_path:
            # =================================================================
            # 2.1. Subprocess Mode Activation Policy (CRITICAL)
            # =================================================================
            # When running as a subprocess (e.g., training scripts), hide from Dock.
            # This MUST happen BEFORE NSApplication is created by the script.
            # NSApplicationActivationPolicyAccessory (1) = No Dock icon
            if getattr(sys, "frozen", False) and NATIVE_APIS_AVAILABLE:
                try:
                    from AppKit import (
                        NSApplication,
                        NSApplicationActivationPolicyAccessory,
                    )

                    app = NSApplication.sharedApplication()
                    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                except Exception:
                    pass

            # Resolve RELATIVE path args (dataset folder, etc.) against DATA_PATH
            # then BASE_PATH. The frozen subprocess's CWD is the bundle
            # (BASE_PATH / sys._MEIPASS), NOT the user's data dir, so relative
            # paths the UI stores relative to the data dir would otherwise fail
            # to resolve — e.g. preprocess "The dataset path does not exist".
            # (Ported from macos_wrapper.py's dispatch; this resolution was lost
            # when the frozen entry point moved to applio_launcher.py.) Only
            # resolves args that ARE existing paths, so non-path args like the
            # sample rate or booleans are left untouched.
            script_args = list(sys.argv[2:])
            _data_path = os.environ.get(
                "APPLIO_DATA_PATH", os.path.expanduser("~/Applio")
            )
            _resolved_args = []
            for _arg in script_args:
                if (
                    isinstance(_arg, str)
                    and _arg
                    and not os.path.isabs(_arg)
                    and not os.path.exists(_arg)
                ):
                    _from_data = os.path.normpath(os.path.join(_data_path, _arg))
                    if os.path.exists(_from_data):
                        _resolved_args.append(_from_data)
                        continue
                    _from_base = os.path.normpath(os.path.join(BASE_PATH, _arg))
                    if os.path.exists(_from_base):
                        _resolved_args.append(_from_base)
                        continue
                _resolved_args.append(_arg)

            # Add script's directory to sys.path so relative imports work
            # This is needed because runpy.run_path doesn't add the script's dir to path
            script_path_abs = os.path.abspath(script_path)
            script_dir = os.path.dirname(script_path_abs)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

            # Delegate to script via runpy
            import runpy

            sys.argv = [script_path_abs] + _resolved_args
            runpy.run_path(script_path_abs, run_name="__main__")
            sys.exit(0)

# =================================================================
# 3. Constants & Configuration
# =================================================================
PROCESS_STATE_FILE = os.path.expanduser("~/.applio/active_processes.json")

# Window dimensions
WINDOW_WIDTH = 500
WINDOW_HEIGHT = 660  # Updated for training panel

# Layout constants
PADDING = 15
STATUS_CARD_HEIGHT = 72
TRAINING_PANEL_HEIGHT = 80
LOG_HEIGHT = 216

# Dashboard dimensions
DASHBOARD_WIDTH = 650
DASHBOARD_HEIGHT = 720
SIDEBAR_WIDTH = 180

# Timing constants (seconds)
FILE_POLL_INTERVAL = 0.5
TIMER_TICK_INTERVAL = 0.5
PHASE_TIMEOUT = 2.0
FILE_LOCK_TIMEOUT = 5.0

# Dashboard update intervals (seconds)
SIDEBAR_UPDATE_INTERVAL = 3.0
DETAIL_UPDATE_INTERVAL = 1.0

# Limits
MAX_LOG_LINES = 200  # Match deque maxlen for consistency
MAX_INITIAL_LINES = 50
MAX_QUEUE_ITEMS_PER_TICK = 20
QUEUE_MAX_SIZE = 1000
LOG_SCROLL_INTERVAL = 5
# Loss-vs-epoch chart: keep every evaluated epoch, but bound output for very
# long runs. The training.log is flooded with per-step tqdm progress between
# the sparse per-epoch summary lines, so we stream the whole file rather than
# a 1MB tail (which only spanned the last few evaluated epochs).
MAX_EPOCH_POINTS = 2000  # generous cap on plotted epoch points
MAX_LOG_SCAN_BYTES = (
    64 * 1024 * 1024
)  # bound I/O; only the tail of a huge log is scanned

# =================================================================
# 2.5. IPC Notification Constants
# =================================================================
# 2nd instance -> 1st instance: surface the main window (single-instance surfacing).
IPC_BRING_TO_FRONT_NAME = "com.applio.bring_to_front"

# --- Single-instance lock (1.6) -----------------------------------------------
# Fixed path (NOT the user-chosen data dir, which may not exist on first run).
LAUNCHER_LOCK_PATH = os.path.expanduser(
    "~/Library/Application Support/Applio/.launcher.lock"
)
_LAUNCHER_SINGLE_INSTANCE_LOCK_FH = (
    None  # kept open to hold the flock for the process lifetime
)


def acquire_single_instance_lock():
    """Try to acquire the single-instance flock.

    Returns True if this is the only instance (the lock handle is kept in a
    module global for the process lifetime); False if another instance holds it.
    """
    global _LAUNCHER_SINGLE_INSTANCE_LOCK_FH
    try:
        os.makedirs(os.path.dirname(LAUNCHER_LOCK_PATH), exist_ok=True)
    except OSError:
        pass
    try:
        fh = open(LAUNCHER_LOCK_PATH, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LAUNCHER_SINGLE_INSTANCE_LOCK_FH = fh
        return True
    except (OSError, IOError):
        try:
            fh.close()
        except Exception:
            pass
        return False


def release_single_instance_lock():
    """Release the single-instance lock.

    Used by relaunchApp_ BEFORE spawning the new instance, so the new instance
    can acquire the lock while this one is still tearing down. (Normal process
    exit releases the flock automatically; this is only for the relaunch race.)
    """
    global _LAUNCHER_SINGLE_INSTANCE_LOCK_FH
    fh = _LAUNCHER_SINGLE_INSTANCE_LOCK_FH
    _LAUNCHER_SINGLE_INSTANCE_LOCK_FH = None
    if fh is not None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass


# Logging setup — own the root logger explicitly. logging.basicConfig is a NO-OP
# if the root logger already has handlers (an earlier import adds one in the
# frozen build), leaving the launcher silently unlogged (applio_launcher.log
# stays stale).
log_dir = os.path.expanduser("~/Library/Logs/Applio")
os.makedirs(log_dir, exist_ok=True)
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
for _h in list(_root_logger.handlers):
    _root_logger.removeHandler(_h)
_log_fh = logging.FileHandler(os.path.join(log_dir, "applio_launcher.log"))
_log_fh.setLevel(logging.INFO)
_log_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_root_logger.addHandler(_log_fh)
logging.info("[Launcher] Starting Applio Launcher")

# =================================================================
# 4. Process State Management (with file locking)
# =================================================================

# Thread lock for in-memory state access
_state_lock = threading.Lock()


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
                        return os.path.join(
                            data_path, ".applio", "active_processes.json"
                        )
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


def load_process_state(retry_on_lock_fail=True):
    """Load process state from file with locking.

    Args:
        retry_on_lock_fail: If True, returns empty state on lock failure.
                           If False, raises IOError on lock failure.
    """
    path = get_process_state_path()
    if not os.path.exists(path):
        return {"version": 1, "processes": {}}

    lock_path = path + ".lock"
    lock_file = None
    try:
        # Use "a+" mode to create if needed, read+write, without truncating
        lock_file = open(lock_path, "a+")
        if not _acquire_file_lock(lock_file):
            if retry_on_lock_fail:
                logging.warning(
                    "[Launcher] Could not acquire lock for reading, returning empty state"
                )
                return {"version": 1, "processes": {}}
            else:
                raise IOError(f"Could not acquire lock for {path} within timeout")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        finally:
            _release_file_lock(lock_file)
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"[Launcher] Error reading process state: {e}")
        return {"version": 1, "processes": {}}
    finally:
        if lock_file:
            try:
                lock_file.close()
            except:
                pass


def save_process_state(state) -> bool:
    """Save process state to file with locking.

    Returns:
        True if save succeeded, False if lock could not be acquired.
    """
    path = get_process_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    lock_path = path + ".lock"
    lock_file = None
    try:
        # Use "a+" mode to create if needed, read+write, without truncating
        lock_file = open(lock_path, "a+")
        if not _acquire_file_lock(lock_file):
            logging.error(
                "[Launcher] Could not acquire lock for writing, state NOT saved"
            )
            return False
        try:
            temp = path + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.rename(temp, path)
            return True
        finally:
            _release_file_lock(lock_file)
    except IOError as e:
        logging.error(f"[Launcher] Error saving process state: {e}")
        return False
    finally:
        if lock_file:
            try:
                lock_file.close()
            except:
                pass


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
    if not PSUTIL_AVAILABLE:
        return True  # Assume valid if can't verify

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
            try:
                actual = datetime.datetime.fromtimestamp(proc.create_time())
            except psutil.AccessDenied:
                # Process exists but its start time is unreadable. A *dead* pid raises
                # NoSuchProcess, not AccessDenied — so reaching here means it is ALIVE.
                # For quit-safety we treat an unverifiable-live process as our own
                # rather than risk skipping a "training in progress" warning.
                logging.info(
                    f"[Launcher] PID {pid} alive but start time unreadable "
                    f"(AccessDenied); assuming active"
                )
                return True

            delta = abs((actual - expected).total_seconds())

            if delta > 2.0:
                logging.warning(f"[Launcher] PID {pid} recycled (time delta: {delta}s)")
                return False

        return True

    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        # Process exists but is inaccessible (rare for same-user processes). Dead pids
        # raise NoSuchProcess above; AccessDenied implies the process is ALIVE, so be
        # conservative and treat it as our own active process.
        logging.info(
            f"[Launcher] PID {pid} exists but inaccessible (AccessDenied); assuming active"
        )
        return True


def validate_process_state(state):
    """Remove stale entries where process has died (with PID recycling protection)."""
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


def _read_inference_progress(path=None):
    """Read ~/Applio/.applio/inference_progress.json, or None if missing/corrupt.

    Reuses the launcher's own get_process_state_path 3-tier resolver so this is
    guaranteed to read from the SAME .applio dir the launcher reads history and
    active-process state from (env > runtime_paths.json > ~/Applio).
    ``path`` overrides the resolved location — the quit-gate helpers' test
    seam; production callers leave it None.
    """
    if path is None:
        path = os.path.join(
            os.path.dirname(get_process_state_path()), "inference_progress.json"
        )
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _synthesize_inference_proc():
    """Synthesize a dashboard proc dict from the live inference_progress.json.

    Returns None when there is no active batch (missing file, or a terminal
    status like completed/cancelled/error). The synthesized proc is appended to
    _active_processes so it flows through the EXISTING sidebar / detail-panel /
    action-bar / history plumbing; every branch that touches pid/log paths keys
    off the ``_is_inference`` marker to stay off the subprocess codepath.
    """
    inf = _read_inference_progress()
    if not inf or inf.get("status") not in ("running", "cancelling"):
        return None
    return {
        "type": "inference",
        "status": inf["status"],
        # scope rides along so label builders can tell a one-file conversion
        # ("single", written by patch_inference_progress since 4b) from a batch
        # (no scope) — see inference_job_type below.
        "scope": inf.get("scope"),
        "model_name": inf.get("model_name", ""),
        "total": inf.get("total", 0),
        "processed": inf.get("processed", 0),
        "converted": inf.get("converted", 0),
        "skipped": inf.get("skipped", 0),
        "current_file": inf.get("current_file", ""),
        "started_at": inf.get("started_at"),
        "output_folder": inf.get("output_folder"),
        "_is_inference": True,
    }


def inference_job_type(scope):
    """Scope-aware announcement type for the synthesized inference job.

    The progress record's scope ("single" for a one-file conversion, absent
    for a batch) picks the spoken type — a single conversion must not be
    announced as "batch inference" (the 2026-08-23 re-test mislabel). The web
    jobLabel mirrors this mapping from the payload's scope field.
    """
    return "conversion" if scope == "single" else "batch inference"


def _inference_running(progress_path=None):
    """Quit-gate predicate: True while the in-process conversion worker is live.

    Same source and active-status set as _synthesize_inference_proc — a
    conversion is live while status is "running" OR "cancelling" ("cancelling"
    means the worker saw the cancel flag but is still winding down between
    files, i.e. its thread is still inside torch). ``progress_path`` is the
    test seam; production leaves it None so the reader's own resolver picks
    the location. Never raises.
    """
    try:
        inf = _read_inference_progress(progress_path)
        return bool(inf and inf.get("status") in ("running", "cancelling"))
    except Exception:
        return False


def _cancel_inference_and_join(timeout=2.5, data_dir=None, _sleep=None, _now=None):
    """Cooperatively cancel a live in-process conversion, then wait (bounded).

    Writes the same inference_cancel.flag the patched stop_infer and the
    dashboard's Stop write — the per-file checkpoint in the injected loop
    honors it — then polls the progress file until the status leaves
    running/cancelling (the worker landed) or ``timeout`` elapses. Called ONLY
    on a confirmed quit: without this, AppKit's exit(0) finalizes pybind while
    the gradio worker thread is still inside torch (the garbled
    set_grad_enabled TypeError, repro 2026-08-27). Bounded — the quit path
    never blocks more than ``timeout`` seconds. ``data_dir``/``_sleep``/``_now``
    are test seams; production leaves them default. Never raises.
    """
    _sleep = _sleep or time.sleep
    _now = _now or time.time
    try:
        if data_dir is None:
            data_dir = os.path.dirname(get_process_state_path())
        flag = os.path.join(data_dir, "inference_cancel.flag")
        os.makedirs(data_dir, exist_ok=True)
        Path(flag).touch()
        logging.info("[Launcher] Quit: wrote inference cancel flag")
    except Exception as e:
        logging.warning(f"[Launcher] Quit: inference cancel-flag write failed: {e}")
        return False
    progress_path = os.path.join(data_dir, "inference_progress.json")
    deadline = _now() + timeout
    while _now() < deadline:
        _sleep(0.1)
        if not _inference_running(progress_path):
            logging.info("[Launcher] Quit: conversion worker landed at its checkpoint")
            return True
    logging.info(
        f"[Launcher] Quit: conversion worker still live after {timeout:.1f}s "
        "grace; proceeding with terminate"
    )
    return False


def voice_over_enabled():
    """Live VoiceOver state; False whenever AppKit/the query is unavailable."""
    try:
        return bool(NSWorkspace.sharedWorkspace().isVoiceOverEnabled())
    except Exception:
        return False


def effective_speech(override, vo_enabled):
    """Zero-config speech policy (2026-08-23 owner ruling).

    override: the hidden a11y.speech NSUserDefaults value ("auto" default,
    "on", "off" — no UI); vo_enabled: NSWorkspace's live VoiceOver state.
    Returns the web payload's verbosity: "verbose" (speak, milestones
    included) or "off". None/unknown overrides behave as "auto".
    """
    if override == "on":
        return "verbose"
    if override == "off":
        return "off"
    return "verbose" if vo_enabled else "off"


_AFPLAY_PATH = "/usr/bin/afplay"
_SOUND_CUE_BAD = "/System/Library/Sounds/Basso.aiff"
_SOUND_CUE_GOOD = "/System/Library/Sounds/Glass.aiff"


def _play_sound_cue(bad, _runner=None):
    """Terminal sound cue through the REGULAR audio channel (re-test round 2).

    NSSound system sounds honor the ALERT volume slider, which can be muted
    while speech on the regular channel still works — the 2026-08-23 re-test
    heard no chime. afplay plays the same system .aiff through the standard
    output device; the Popen child is fire-and-forget (DEVNULL pipes), so the
    main thread never blocks. Falls back to NSSound when afplay or the file
    is missing. Returns the channel that fired ("afplay" / "nssound", None on
    total failure); never raises. ``_runner`` is the test seam (defaults to
    subprocess.Popen).
    """
    path = _SOUND_CUE_BAD if bad else _SOUND_CUE_GOOD
    try:
        import subprocess

        if os.path.isfile(_AFPLAY_PATH) and os.path.isfile(path):
            runner = _runner or subprocess.Popen
            runner(
                [_AFPLAY_PATH, path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "afplay"
    except Exception:
        pass
    try:
        from AppKit import NSSound

        NSSound.soundNamed_("Basso" if bad else "Glass").play()
        return "nssound"
    except Exception:
        return None


def _merged_live_procs():
    """Tracked subprocess jobs + the synthesized in-app batch, one list.

    The single merge the Process Dashboard (refresh_process_list /
    update_process_list) and the Active-Processes menu both need: subprocess
    jobs from active_processes.json (get_active_processes) plus the
    batch-inference proc synthesized from inference_progress.json
    (_synthesize_inference_proc) — disjoint sources, no dedupe.
    """
    procs = get_active_processes()
    inf = _synthesize_inference_proc()
    if inf:
        procs.append(inf)
    return procs


def _annotate_paused(procs):
    """Stamp live SIGSTOP state (``_ps_stopped``) on each proc dict.

    Module-level mirror of ProcessDashboardController._annotate_pause_state
    so the menu's status-submenu rebuild can derive " — paused" titles
    without a controller instance. Procs without a live pid — e.g. the
    synthesized inference proc — stay False (an in-process batch cannot be
    SIGSTOPped, so "running" is the truthful word).
    """
    for proc in procs:
        proc["_ps_stopped"] = False
        pid = proc.get("pid")
        started = proc.get("started_at")
        if pid and PSUTIL_AVAILABLE and verify_process_identity(pid, started):
            try:
                proc["_ps_stopped"] = (
                    psutil.Process(pid).status() == psutil.STATUS_STOPPED
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


def _menu_job_title(proc, training_epoch=None):
    """Compose an Active-Processes menu title for a live job (AppKit-free).

    Does NO I/O of its own: inference pct comes from
    applio_inference_stats.compute_inference_stats (bundled, frozen-safe) over
    the synthesized proc's fields, and the training epoch is supplied by the
    CALLER via ``training_epoch`` (from _last_training_metrics). i18n is
    resolved at CALL TIME via applio_i18n.native_tr so a locale change shows
    on the next 2 s menu tick. Formats (name capped at 30 chars + "…", the
    composed line at 64):

      inference   "Inference: batch — 43% (2/3 files)"
                  "Inference: batch — stopping… (2/3 files)"   (cancelling)
      training    "Training: voice — epoch 34/200"
                  "Training: voice — starting…"  (no status line logged yet)
      preprocess/extract   model name only
      tts         "TTS: active job"  (tracked bare: no model_name/log_file)

    A paused job (caller stamped ``_ps_stopped`` via _annotate_paused)
    appends " — paused".
    """
    import applio_i18n
    from applio_inference_stats import compute_inference_stats

    _t = applio_i18n.native_tr

    def _short(raw):
        n = (raw or "").strip()
        return n[:30] + "…" if len(n) > 30 else n

    ptype = (proc.get("type") or "process").lower()
    if ptype == "inference":
        name = _short(proc.get("model_name")) or "batch"
        processed = proc.get("processed", 0) or 0
        total = proc.get("total", 0) or 0
        if proc.get("status") == "cancelling":
            seg = _t("stopping…")
        else:
            pct = int(round(compute_inference_stats(proc, time.time())["pct"]))
            seg = f"{pct}%"
        title = f"{_t('Inference')}: {name} — {seg} ({processed}/{total} {_t('files')})"
    elif ptype == "training":
        name = _short(proc.get("model_name"))
        total_epoch = proc.get("total_epoch")
        if training_epoch is None:
            seg = _t("starting…")
        elif total_epoch:
            seg = f"{_t('epoch')} {training_epoch}/{total_epoch}"
        else:
            seg = f"{_t('epoch')} {training_epoch}"
        title = f"{_t('Training')}: {name} — {seg}"
    elif ptype in ("preprocess", "extract"):
        title = _short(proc.get("model_name")) or ptype.capitalize()
    elif ptype == "tts":
        title = _t("TTS: active job")
    else:
        title = _short(proc.get("model_name")) or ptype.capitalize()
    if proc.get("_ps_stopped"):
        title = f"{title} — {_t('paused')}"
    return title[:64]


def _row_ax_summary(proc, metrics=None, total_epoch=None, eta=None):
    """One-line VoiceOver summary of a dashboard row's live state (AppKit-free).

    Single wording source for a row's live metrics, consumed by BOTH spoken
    channels and the visible cell text: the row-view AX value (stamped by
    _apply_row_ax), the selection announcement, and — since re-test round 3 —
    the runs-list cell itself via _row_display_text (VoiceOver does not
    reliably speak the row view's accessibilityValue, so the metrics must be
    IN the text). Shapes:

      training   "epoch {cur} of {total}, best loss {best}, ETA {eta}"
                 best is "{:.4g}" or "--" before the first evaluation
                 (best_loss is None); eta defaults "--" — the CONTROLLER
                 caller passes the derived string via self._derive_eta(...)
      inference  "{processed} of {total} files converted, {pct:.0f} percent"
                 (pct via applio_inference_stats.compute_inference_stats, the
                 same math the detail panel uses)
      other      "" — unknown types / missing metrics carry nothing to add;
                 callers skip stamping a value.

    Consumes the metrics shapes _last_training_metrics returns
    (epoch/step/training_speed/best_loss/best_epoch/best_step) and the
    synthesized inference proc's fields (total/processed/converted). English
    keys are wrapped in applio_i18n.native_tr at call time; i18n and stats
    imports are local (fork-owned bundled modules — frozen-safe).
    """
    import applio_i18n
    from applio_inference_stats import compute_inference_stats

    _t = applio_i18n.native_tr

    if not proc:
        return ""
    ptype = (proc.get("type") or "").lower()
    if ptype == "training":
        if not metrics:
            return ""
        cur = metrics.get("epoch")
        total = total_epoch if total_epoch is not None else proc.get("total_epoch")
        try:
            total = int(total) if total not in (None, "") else None
        except (ValueError, TypeError):
            total = None
        if not cur:
            return ""
        # No total recorded (a history snapshot without one) -> bare "epoch N".
        head = (
            f"{_t('epoch')} {cur} {_t('of')} {total}"
            if total
            else f"{_t('epoch')} {cur}"
        )
        best = metrics.get("best_loss")
        best_str = f"{best:.4g}" if best is not None else "--"
        eta_str = eta if eta else "--"
        return f"{head}, {_t('best loss')} {best_str}, {_t('ETA')} {eta_str}"
    if ptype == "inference":
        total = proc.get("total", 0) or 0
        processed = proc.get("processed", 0) or 0
        pct = compute_inference_stats(proc, time.time())["pct"]
        return (
            f"{processed} {_t('of')} {total} {_t('files converted')}, "
            f"{pct:.0f} {_t('percent')}"
        )
    return ""


def _row_display_text(proc, word, summary=""):
    """Visible runs-list row text: "{word} — {Type}: {name}" (+ live metrics).

    Re-test round 3 (2026-08-23): the row view's accessibilityValue proved
    unreliable under VoiceOver, so ACTIVE rows now carry their metrics IN the
    cell text — the dataSource appends ``summary`` (built from
    _row_ax_summary via the controller's _ax_summary_for: epoch/best loss/ETA
    for training, files/percent for inference). History rows (and active rows
    whose type carries no metrics) pass no summary and keep the plain shape.
    Capped at 80 chars — truncation eats the summary tail; the status/type/
    name head always survives. AppKit-free, no I/O. ``word`` is the caller's
    FINAL status string (already translated, or a raw status capitalize).
    """
    import applio_i18n

    if not proc:
        return ""
    _t = applio_i18n.native_tr
    proc_type = proc.get("type", _t("Unknown")).capitalize()
    model_name = proc.get("model_name", "") or ""
    base = f"{word} — {proc_type}: {model_name}"
    text = f"{base} — {summary}" if summary else base
    if len(text) > 80:
        text = text[:79].rstrip() + "…"
    return text


def _sweep_stale_inference_progress():
    """Mark a stale live inference record (app crashed/quit mid-conversion) as
    'interrupted' so the dashboard never shows a phantom job. BOTH live
    statuses sweep: 'running', and 'cancelling' — a crash in the tiny
    cancelling->cancelled window would otherwise leave a phantom 'cancelling'
    record that reads as live (dashboard job + quit-gate prompt) until a new
    conversion overwrites it. Appends a schema-compatible history entry and
    removes any stale cancel flag. Safe to call when no record exists (no-op)
    and to call multiple times. Never raises — every I/O path is wrapped so
    the sweep cannot crash startup."""
    inf = _read_inference_progress()
    if not inf or inf.get("status") not in ("running", "cancelling"):
        return
    import time as _t, datetime as _dt

    started = inf.get("started_at") or _t.time()
    ended = _t.time()
    inf["status"] = "interrupted"
    inf["error"] = "interrupted by app restart"
    inf["ended_at"] = ended
    inf["elapsed"] = ended - started
    inf["current_file"] = ""
    # Write the progress file atomically (0o600) — reuse the launcher's resolver.
    prog_path = os.path.join(
        os.path.dirname(get_process_state_path()), "inference_progress.json"
    )
    try:
        os.makedirs(os.path.dirname(prog_path), exist_ok=True)
        tmp = prog_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(inf, f)
        os.replace(tmp, prog_path)
    except OSError as e:
        logging.warning(f"[Launcher] inference sweep write failed: {e}")
    # Append interrupted history entry (fcntl LOCK_EX, schema-compatible).
    hist_path = get_history_file_path()
    try:
        os.makedirs(os.path.dirname(hist_path), exist_ok=True)
        with open(hist_path + ".lock", "a") as _lf:
            fcntl.flock(_lf.fileno(), fcntl.LOCK_EX)
            try:
                hist = {"version": 1, "history": []}
                if os.path.exists(hist_path):
                    try:
                        with open(hist_path, "r", encoding="utf-8") as f:
                            hist = json.load(f) or hist
                    except json.JSONDecodeError:
                        pass
                hist.setdefault("history", []).insert(
                    0,
                    {
                        "type": "inference",
                        "model_name": inf.get("model_name", ""),
                        "started_at": _dt.datetime.fromtimestamp(started).isoformat(),
                        "completed_at": _dt.datetime.fromtimestamp(ended).isoformat(),
                        "status": "interrupted",
                        "total": inf.get("total", 0),
                        "converted": inf.get("converted", 0),
                        "skipped": inf.get("skipped", 0),
                        "process_id": "inference-%s" % started,
                    },
                )
                hist["history"] = hist["history"][:HISTORY_MAX_ENTRIES]
                tmp = hist_path + ".tmp"
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(hist, f, indent=2)
                os.replace(tmp, hist_path)
            finally:
                fcntl.flock(_lf.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        logging.warning(f"[Launcher] inference history append failed: {e}")
    # Clear a stale cancel flag (best-effort).
    try:
        os.remove(
            os.path.join(
                os.path.dirname(get_process_state_path()), "inference_cancel.flag"
            )
        )
    except OSError:
        pass


# =================================================================
# 4.5. Process History Management
# =================================================================

HISTORY_MAX_ENTRIES = 50
HISTORY_MAX_AGE_DAYS = 7
_history_lock = threading.Lock()  # Thread-safe history access


def _get_history_lock_path() -> str:
    """Get path to history lock file."""
    return get_history_file_path() + ".lock"


def load_process_history() -> dict:
    """Load process history from file with locking.

    Returns:
        dict with 'version' and 'history' (list of entries)

    Handles:
        - Missing file (returns empty history)
        - Corrupted JSON (returns empty history)
        - Invalid structure (validates and repairs)
        - Lock timeout (returns cached/empty)
    """
    history_path = get_history_file_path()
    if not os.path.exists(history_path):
        return {"version": 1, "history": []}

    lock_path = _get_history_lock_path()
    lock_file = None
    try:
        lock_file = open(lock_path, "a+")
        if not _acquire_file_lock(lock_file, timeout=2.0):
            logging.warning("[Launcher] Could not acquire history lock for reading")
            return {"version": 1, "history": []}
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate structure
            if not isinstance(data, dict):
                logging.warning(
                    "[Launcher] History file has invalid root structure, resetting"
                )
                return {"version": 1, "history": []}

            if "history" not in data:
                data["history"] = []
            elif not isinstance(data["history"], list):
                logging.warning(
                    "[Launcher] History 'history' key is not a list, resetting"
                )
                data["history"] = []

            # Validate and clean individual entries
            valid_history = []
            for i, entry in enumerate(data.get("history", [])):
                if not isinstance(entry, dict):
                    logging.debug(
                        f"[Launcher] Skipping invalid history entry at index {i}"
                    )
                    continue
                # Require minimal fields
                if entry.get("type") and entry.get("started_at"):
                    valid_history.append(entry)
                else:
                    logging.debug(
                        f"[Launcher] Skipping incomplete history entry at index {i}"
                    )

            data["history"] = valid_history
            return data

        except json.JSONDecodeError as e:
            logging.warning(f"[Launcher] History file corrupted (JSON error): {e}")
            # Create backup of corrupted file for debugging
            try:
                import shutil

                backup_path = history_path + ".corrupted"
                shutil.copy2(history_path, backup_path)
                logging.info(f"[Launcher] Corrupted history backed up to {backup_path}")
            except Exception:
                pass
            return {"version": 1, "history": []}
        except IOError as e:
            logging.warning(f"[Launcher] Error reading process history: {e}")
            return {"version": 1, "history": []}
        finally:
            _release_file_lock(lock_file)
    except IOError as e:
        logging.warning(f"[Launcher] Error opening history lock: {e}")
        return {"version": 1, "history": []}
    finally:
        if lock_file:
            try:
                lock_file.close()
            except:
                pass


def save_process_history(history: dict) -> bool:
    """Save process history to file with locking.

    Returns:
        True if save succeeded, False otherwise.

    Handles:
        - Directory creation errors
        - Lock acquisition failures
        - Write errors (atomic write via temp file)
    """
    history_path = get_history_file_path()

    # Ensure directory exists
    try:
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
    except OSError as e:
        logging.error(f"[Launcher] Could not create history directory: {e}")
        return False

    lock_path = _get_history_lock_path()
    lock_file = None
    try:
        lock_file = open(lock_path, "a+")
        if not _acquire_file_lock(lock_file, timeout=2.0):
            logging.error("[Launcher] Could not acquire history lock for writing")
            return False
        try:
            # Atomic write: write to temp file, then rename
            temp_path = history_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
            os.rename(temp_path, history_path)
            return True
        except IOError as e:
            logging.error(f"[Launcher] Error saving process history: {e}")
            # Clean up temp file if it exists
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except Exception:
                pass
            return False
        finally:
            _release_file_lock(lock_file)
    except IOError as e:
        logging.error(f"[Launcher] Error opening history lock: {e}")
        return False
    finally:
        if lock_file:
            try:
                lock_file.close()
            except:
                pass


def add_to_history(entry: dict) -> bool:
    """Add a completed process to history (thread-safe).

    Args:
        entry: dict with type, model_name, started_at, completed_at, status, etc.

    Returns:
        True if added successfully.

    Validates entry has required fields before adding.
    """
    # Validate required fields
    required_fields = ["type", "started_at", "completed_at"]
    for field in required_fields:
        if field not in entry:
            logging.warning(f"[Launcher] History entry missing required field: {field}")
            return False

    with _history_lock:
        try:
            history = load_process_history()

            # Generate unique process ID
            process_id = f"{entry.get('type', 'unknown')}-{entry.get('started_at', datetime.datetime.now().isoformat())}"
            entry["process_id"] = process_id

            # Add to history
            history["history"].insert(0, entry)

            # Enforce max entries
            if len(history["history"]) > HISTORY_MAX_ENTRIES:
                history["history"] = history["history"][:HISTORY_MAX_ENTRIES]

            success = save_process_history(history)
            if success:
                logging.debug(
                    f"[Launcher] Added to history: {entry.get('type')} - {entry.get('model_name', 'unknown')}"
                )
            return success

        except Exception as e:
            logging.error(f"[Launcher] Failed to add to history: {e}")
            return False


def cleanup_old_history() -> int:
    """Remove entries older than HISTORY_MAX_AGE_DAYS (thread-safe).

    Returns:
        Number of entries removed.
    """
    with _history_lock:
        history = load_process_history()
        cutoff = datetime.datetime.now() - datetime.timedelta(days=HISTORY_MAX_AGE_DAYS)

        original_count = len(history["history"])
        history["history"] = [
            h
            for h in history["history"]
            if h.get("completed_at")
            and datetime.datetime.fromisoformat(h["completed_at"]) > cutoff
        ]

        removed = original_count - len(history["history"])
        if removed > 0:
            save_process_history(history)
            logging.info(f"[Launcher] Cleaned up {removed} old history entries")

        return removed


def get_history_file_path() -> str:
    """Get path to process_history.json."""
    # Use same directory as active_processes.json
    state_path = get_process_state_path()
    return os.path.join(os.path.dirname(state_path), "process_history.json")


def get_recent_processes(limit: int = 10) -> list:
    """Get recent completed processes from history (thread-safe).

    Args:
        limit: Maximum number of entries to return.

    Returns:
        List of history entries, most recent first.
    """
    with _history_lock:
        history = load_process_history()
        return history.get("history", [])[:limit]


# =================================================================
# 5. Progress Window Controller (moved from macos_wrapper.py)
# =================================================================


def _parse_training_log_line(line):
    """Parse an RVC training status line into a metrics dict, or None.

    Shared by ProgressWindowController (live tail) and ProcessDashboardController
    (per-run training.log). Lives at module scope here - NOT imported from
    rvc.lib.tools.process_log_parser - because that module ships only as a data
    file and is not importable in the frozen app. One regex, frozen-safe, no
    third copy.

    Recognises (rvc/train/train.py:884-890):
      "<model> | epoch=N | step=N | time=H:M:S | training_speed=H:M:S
       | lowest_value=X.XXX (epoch B and step C)"
    plus the early-training variant without lowest_value (epoch == 1).

    Returns {epoch, step, training_speed, best_loss, best_epoch, best_step}
    (best_* are None before the first evaluation), or None.
    """
    # Full line carrying lowest_value (epoch > 1)
    match = re.match(
        r".*\|\s*epoch=(\d+)\s*\|\s*step=(\d+)\s*\|\s*time=[\d:]+\s*\|\s*training_speed=([\d:]+)\s*\|\s*lowest_value=([\d.]+)\s*\(epoch\s+(\d+)\s+and\s+step\s+(\d+)\)",
        line,
    )
    if match:
        return {
            "epoch": int(match.group(1)),
            "step": int(match.group(2)),
            "training_speed": match.group(3),
            "best_loss": float(match.group(4)),
            "best_epoch": int(match.group(5)),
            "best_step": int(match.group(6)),
        }
    # Simpler line without lowest_value (epoch == 1, no evaluation yet)
    match = re.match(
        r".*\|\s*epoch=(\d+)\s*\|\s*step=(\d+)\s*\|\s*time=[\d:]+\s*\|\s*training_speed=([\d:]+)",
        line,
    )
    if match:
        return {
            "epoch": int(match.group(1)),
            "step": int(match.group(2)),
            "training_speed": match.group(3),
            "best_loss": None,
            "best_epoch": None,
            "best_step": None,
        }
    return None


def _last_training_metrics(log_path, max_bytes=262144):
    """Last parseable training status line from a training.log tail.

    One tail-scan reader, two consumers: the Process Dashboard's per-proc
    metrics (ProcessDashboardController._parse_training_metrics, which keeps
    its historical-snapshot branch and delegates here) and the menu's live
    "epoch N/M" titles (which use the default 256 KB cap so the 2 s menu
    tick costs at most one bounded read + regex per training proc). Frozen-
    safe: scans with the module-level _parse_training_log_line — never
    rvc.lib.tools.process_log_parser (data file in the frozen bundle, not
    importable). Returns the metrics dict, or None for a missing/unreadable
    log or one with no status lines yet.
    """
    if not log_path:
        return None
    try:
        if not os.path.exists(log_path) or not os.access(log_path, os.R_OK):
            return None
        size = os.path.getsize(log_path)
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                content = f.read()
                nl = content.find("\n")
                if nl >= 0:
                    content = content[nl + 1 :]  # drop the partial first line
            else:
                content = f.read()
        for line in reversed(content.splitlines()):
            parsed = _parse_training_log_line(line)
            if parsed:
                return parsed
    except Exception as e:
        logging.debug(f"[Launcher] training metrics tail-scan failed: {e}")
    return None


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
        self.log_lines = deque()  # Manual trimming for text storage sync
        self._last_file_pos = 0
        self._last_file_size = 0
        # Smart log display state
        self._live_phase = None  # Current phase name
        self._live_phase_start = None  # Timestamp when phase started
        self._last_tqdm_time = None  # Timestamp of last tqdm activity
        self._last_non_tqdm_line = ""  # For phase name detection
        # Epoch tracking for progress bar
        self._total_epoch = process_info.get("total_epoch")
        self._current_epoch = 0
        # Training status tracking (for training tasks only)
        self._training_status = None  # Parsed training status dict
        self._best_epoch = None  # Epoch with lowest loss
        self._best_loss = None  # Lowest loss value
        self._best_step = None  # Step at best epoch
        self._current_step = 0  # Current training step
        self._training_speed = None  # Time per epoch
        self.window = None  # Initialize to None for safe cleanup
        # Thread safety and file tracking
        self._shutdown_event = threading.Event()  # Graceful shutdown signal
        self._state_lock = threading.Lock()  # Protect shared state
        self._file_inode = None  # Track inode for rotation detection

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
            NSMakeRect(
                0, 0, 500, 660
            ),  # Increased from 580 to 660 for training info panel
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_(f"Applio - {self.process_type.capitalize()}")
        self.window.center()
        self.window.setReleasedWhenClosed_(False)

        # Register for close notification
        notification_center = NSNotificationCenter.defaultCenter()
        self._observer = notification_center.addObserver_selector_name_object_(
            self, "windowWillClose:", "NSWindowWillCloseNotification", self.window
        )

        # Also observe app termination as safety net for timer cleanup
        self._terminate_observer = (
            notification_center.addObserver_selector_name_object_(
                self,
                "applicationWillTerminate:",
                "NSApplicationWillTerminateNotification",
                None,
            )
        )

    def _create_ui(self):
        """Create UI elements with accessibility support."""
        import applio_i18n

        _t = applio_i18n.native_tr

        window_width = 500
        padding = 15
        y = 660 - padding  # Updated from 580 to match new window height

        # Set window accessibility
        self.window.setAccessibilityLabel_(
            f"Applio {self.process_type.capitalize()} Progress"
        )
        self.window.setAccessibilityHelp_(
            f"Monitoring window for {self.process_type} process"
        )

        # Process type label (bold, larger)
        self.type_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 24, window_width - 2 * padding, 24)
        )
        model_name = self.process_info.get("model_name", _t("Unknown"))
        self.type_label.setStringValue_(
            f"{self.process_type.capitalize()}: {model_name}"
        )
        self.type_label.setBezeled_(False)
        self.type_label.setDrawsBackground_(False)
        self.type_label.setEditable_(False)
        self.type_label.setFont_(NSFont.boldSystemFontOfSize_(16))
        # Accessibility
        self.type_label.setAccessibilityLabel_(
            f"{self.process_type.capitalize()} process for model {model_name}"
        )
        self.type_label.setAccessibilityIdentifier_("process_type_label")
        self.window.contentView().addSubview_(self.type_label)

        # Status badge (pill-shaped, right side)
        badge_width = 80
        badge_height = 22
        self.status_badge = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                window_width - padding - badge_width, y - 22, badge_width, badge_height
            )
        )
        self.status_badge.setStringValue_(_t("Running"))
        self.status_badge.setBezeled_(False)
        self.status_badge.setDrawsBackground_(True)
        self.status_badge.setBackgroundColor_(
            NSColor.systemGreenColor().colorWithAlphaComponent_(0.2)
        )
        self.status_badge.setEditable_(False)
        self.status_badge.setFont_(
            NSFont.systemFontOfSize_weight_(11, NSFontWeightMedium)
        )
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
            NSMakeRect(padding, y - 20, window_width - 2 * padding, 20)
        )
        self.status_label.setStringValue_("Status: Running")
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        self.status_label.setEditable_(False)
        # Accessibility
        self.status_label.setAccessibilityLabel_("Process status")
        self.status_label.setAccessibilityHelp_(
            "Current status of the process: Running, Paused, Completed, or Terminated"
        )
        self.status_label.setAccessibilityIdentifier_("status_label")
        self.window.contentView().addSubview_(self.status_label)
        y -= 25

        # Elapsed time label
        self.time_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, y - 18, window_width - 2 * padding, 18)
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
        total_epoch = self.process_info.get("total_epoch", 0)
        self.progress_bar = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(padding, y - 20, window_width - 2 * padding, 20)
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
            self.progress_bar.setAccessibilityHelp_(
                f"Training progress: 0 of {total_epoch} epochs"
            )
        else:
            self.progress_bar.setAccessibilityHelp_(
                "Shows that the process is actively running"
            )
        self.progress_bar.setAccessibilityIdentifier_("progress_bar")
        self.window.contentView().addSubview_(self.progress_bar)
        y -= 30

        # Training Info Panel (only for training tasks) - 80px total
        # This panel shows critical training metrics: best epoch, current progress, speed
        TRAINING_PANEL_HEIGHT = 80
        is_training = self.process_type == "training"

        # Training panel container (hidden for non-training tasks)
        self.training_panel_box = NSBox.alloc().initWithFrame_(
            NSMakeRect(
                padding - 5,
                y - TRAINING_PANEL_HEIGHT,
                window_width - 2 * padding + 10,
                TRAINING_PANEL_HEIGHT,
            )
        )
        self.training_panel_box.setBoxType_(1)  # NSBoxCustom
        self.training_panel_box.setBorderType_(2)  # NSBezelBorder for subtle inset look
        self.training_panel_box.setTitlePosition_(0)  # No title
        self.training_panel_box.setHidden_(not is_training)
        self.window.contentView().addSubview_(self.training_panel_box)

        # Best Epoch Row (most prominent) - highlighted with accent color
        # Positioned at top of training panel (y - 28 from panel top)
        best_row_y = y - 28
        self.best_epoch_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, best_row_y, window_width - 2 * padding, 28)
        )
        self.best_epoch_label.setStringValue_("Best Epoch: Waiting for training...")
        self.best_epoch_label.setBezeled_(False)
        self.best_epoch_label.setDrawsBackground_(False)
        self.best_epoch_label.setEditable_(False)
        self.best_epoch_label.setFont_(NSFont.boldSystemFontOfSize_(14))
        self.best_epoch_label.setTextColor_(
            NSColor.systemGreenColor()
        )  # Green for "best"
        self.best_epoch_label.setHidden_(not is_training)
        self.best_epoch_label.setAccessibilityLabel_("Best epoch indicator")
        self.best_epoch_label.setAccessibilityHelp_(
            "Shows the epoch with lowest loss - use this for inference"
        )
        self.window.contentView().addSubview_(self.best_epoch_label)

        # Current Epoch + Speed Row (middle of panel)
        current_row_y = y - 54
        self.current_epoch_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, current_row_y, window_width - 2 * padding, 22)
        )
        self.current_epoch_label.setStringValue_(
            "Current: -- | Step: -- | Speed: --/epoch"
        )
        self.current_epoch_label.setBezeled_(False)
        self.current_epoch_label.setDrawsBackground_(False)
        self.current_epoch_label.setEditable_(False)
        self.current_epoch_label.setFont_(
            NSFont.systemFontOfSize_weight_(12, NSFontWeightMedium)
        )
        self.current_epoch_label.setTextColor_(NSColor.labelColor())
        self.current_epoch_label.setHidden_(not is_training)
        self.current_epoch_label.setAccessibilityLabel_("Current training status")
        self.window.contentView().addSubview_(self.current_epoch_label)

        # Best epoch details (step info) - bottom of panel
        details_y = y - 76
        self.best_details_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding, details_y, window_width - 2 * padding, 18)
        )
        self.best_details_label.setStringValue_("Loss: -- | Step: --")
        self.best_details_label.setBezeled_(False)
        self.best_details_label.setDrawsBackground_(False)
        self.best_details_label.setEditable_(False)
        self.best_details_label.setFont_(
            NSFont.systemFontOfSize_weight_(10, NSFontWeightRegular)
        )
        self.best_details_label.setTextColor_(NSColor.secondaryLabelColor())
        self.best_details_label.setHidden_(not is_training)
        self.window.contentView().addSubview_(self.best_details_label)

        # Adjust y position based on whether training panel is shown
        if is_training:
            y -= TRAINING_PANEL_HEIGHT + 8  # Account for the training panel
        else:
            y -= 4  # Small gap before Rich Status Card

        # Rich Status Card (72px total)
        STATUS_CARD_HEIGHT = 72
        y -= 4  # Small gap before card

        # Row 1: Phase icon + name + counter (24px)
        row1_height = 24
        self.phase_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                padding, y - row1_height, window_width - 2 * padding, row1_height
            )
        )
        self.phase_label.setStringValue_("Waiting for progress...")
        self.phase_label.setBezeled_(False)
        self.phase_label.setDrawsBackground_(False)
        self.phase_label.setEditable_(False)
        self.phase_label.setFont_(NSFont.boldSystemFontOfSize_(14))
        self.phase_label.setTextColor_(NSColor.labelColor())
        self.window.contentView().addSubview_(self.phase_label)
        y -= row1_height + 2

        # Row 2: Visual progress bar (20px)
        row2_height = 20
        self.visual_progress = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                padding, y - row2_height, window_width - 2 * padding - 50, row2_height
            )
        )
        self.visual_progress.setStringValue_(
            "░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░"
        )
        self.visual_progress.setBezeled_(False)
        self.visual_progress.setDrawsBackground_(False)
        self.visual_progress.setEditable_(False)
        self.visual_progress.setFont_(NSFont.fontWithName_size_("Menlo", 12))
        self.visual_progress.setTextColor_(NSColor.systemBlueColor())
        self.window.contentView().addSubview_(self.visual_progress)

        # Progress percentage label
        self.progress_percent = NSTextField.alloc().initWithFrame_(
            NSMakeRect(window_width - padding - 45, y - row2_height, 45, row2_height)
        )
        self.progress_percent.setStringValue_("0%")
        self.progress_percent.setBezeled_(False)
        self.progress_percent.setDrawsBackground_(False)
        self.progress_percent.setEditable_(False)
        self.progress_percent.setFont_(NSFont.boldSystemFontOfSize_(12))
        self.progress_percent.setTextColor_(NSColor.secondaryLabelColor())
        self.progress_percent.setAlignment_(NSRightTextAlignment)
        self.window.contentView().addSubview_(self.progress_percent)
        y -= row2_height + 2

        # Row 3: Stats grid (24px)
        row3_height = 24
        stats_width = (window_width - 2 * padding - 30) / 4
        stats_labels = ["Speed", "ETA", "Phase Time", "Items"]
        self.stats_values = []

        for i, label_text in enumerate(stats_labels):
            x_offset = padding + i * (stats_width + 10)
            # Label
            label = NSTextField.alloc().initWithFrame_(
                NSMakeRect(x_offset, y - 10, stats_width, 10)
            )
            label.setStringValue_(label_text)
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setEditable_(False)
            label.setFont_(NSFont.systemFontOfSize_weight_(9, NSFontWeightMedium))
            label.setTextColor_(NSColor.tertiaryLabelColor())
            label.setAlignment_(NSCenterTextAlignment)
            self.window.contentView().addSubview_(label)

            # Value
            value = NSTextField.alloc().initWithFrame_(
                NSMakeRect(x_offset, y - row3_height, stats_width, 14)
            )
            value.setStringValue_("--")
            value.setBezeled_(False)
            value.setDrawsBackground_(False)
            value.setEditable_(False)
            value.setFont_(NSFont.systemFontOfSize_weight_(12, NSFontWeightSemibold))
            value.setTextColor_(NSColor.labelColor())
            value.setAlignment_(NSCenterTextAlignment)
            self.window.contentView().addSubview_(value)
            self.stats_values.append(value)

        # Accessibility: label the live-zone fields for screen readers. The
        # Unicode block bar is pure glyph noise by ear, so hide it instead.
        self.phase_label.setAccessibilityLabel_("Current phase")
        self.progress_percent.setAccessibilityLabel_("Phase progress")
        self.visual_progress.setAccessibilityHidden_(True)  # '█░░█…' is SR noise
        for field, ax_label in zip(
            self.stats_values,
            ("Speed", "Estimated time remaining", "Phase time", "Items"),
        ):
            field.setAccessibilityLabel_(ax_label)

        y -= row3_height + 4

        # Status card background box (adds visual separation)
        # Note: NSBox doesn't support setFillColor in PyObjC, so we use a bordered style instead
        self.status_card_box = NSBox.alloc().initWithFrame_(
            NSMakeRect(
                padding - 5, y, window_width - 2 * padding + 10, STATUS_CARD_HEIGHT + 4
            )
        )
        self.status_card_box.setBoxType_(1)  # NSBoxCustom = 1
        self.status_card_box.setBorderType_(1)  # NSLineBorder = 1 for subtle border
        self.status_card_box.setTitlePosition_(0)  # No title
        # Just add normally - the box serves as visual separator
        self.window.contentView().addSubview_(self.status_card_box)

        # Log scroll view
        log_height = 216  # Reduced from 250 to make room for live zone
        self.log_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(padding, y - log_height, window_width - 2 * padding, log_height)
        )
        self.log_scroll.setHasVerticalScroller_(True)
        self.log_scroll.setBorderType_(NSBezelBorder)
        # Accessibility
        self.log_scroll.setAccessibilityLabel_("Log output")
        self.log_scroll.setAccessibilityHelp_(
            "Real-time log output from the training process"
        )
        self.log_scroll.setAccessibilityIdentifier_("log_scroll_view")

        self.log_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, window_width - 2 * padding - 20, log_height)
        )
        self.log_view.setEditable_(False)
        self.log_view.setFont_(NSFont.fontWithName_size_("Menlo", 11))
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
        self.terminate_btn.setAccessibilityHelp_(
            "Stop the process immediately. The process will not complete its current task."
        )
        self.terminate_btn.setAccessibilityIdentifier_("terminate_button")
        self.window.contentView().addSubview_(self.terminate_btn)

        # Pause/Resume button (center-left)
        self.pause_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(
                padding + button_width + 10, button_y, button_width, button_height
            )
        )
        self.pause_btn.setTitle_("Pause")
        self.pause_btn.setTarget_(self)
        self.pause_btn.setAction_("togglePause:")
        # Accessibility
        self.pause_btn.setAccessibilityLabel_("Pause or resume process")
        self.pause_btn.setAccessibilityHelp_(
            "Temporarily pause the process or resume a paused process"
        )
        self.pause_btn.setAccessibilityIdentifier_("pause_button")
        self.window.contentView().addSubview_(self.pause_btn)

        # Open Logs button (center-right)
        self.logs_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(
                padding + 2 * (button_width + 10), button_y, button_width, button_height
            )
        )
        self.logs_btn.setTitle_("Open Logs")
        self.logs_btn.setTarget_(self)
        self.logs_btn.setAction_("openLogsFolder:")
        # Accessibility
        self.logs_btn.setAccessibilityLabel_("Open logs folder")
        self.logs_btn.setAccessibilityHelp_(
            "Open the folder containing log files in Finder"
        )
        self.logs_btn.setAccessibilityIdentifier_("open_logs_button")
        self.window.contentView().addSubview_(self.logs_btn)

        # Relaunch button (right)
        self.relaunch_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(
                padding + 3 * (button_width + 10), button_y, button_width, button_height
            )
        )
        self.relaunch_btn.setTitle_("Relaunch App")
        self.relaunch_btn.setTarget_(self)
        self.relaunch_btn.setAction_("relaunchApp:")
        # Accessibility
        self.relaunch_btn.setAccessibilityLabel_("Relaunch application")
        self.relaunch_btn.setAccessibilityHelp_(
            "Open a new instance of Applio while this process continues in the background"
        )
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

        self._file_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
        self._dropped_lines = 0  # Counter for dropped lines when queue is full
        self._file_thread = threading.Thread(target=self._file_poll_worker, daemon=True)
        self._file_thread.start()

    def _file_poll_worker(self):
        """Background worker thread for file polling."""

        while not self._shutdown_event.is_set():
            time.sleep(FILE_POLL_INTERVAL)

            if self._shutdown_event.is_set():
                break

            if not self.log_file_path or not os.path.exists(self.log_file_path):
                continue

            try:
                # Check for file rotation via inode
                file_stat = os.stat(self.log_file_path)
                current_inode = file_stat.st_ino
                current_size = file_stat.st_size

                with self._state_lock:
                    # Detect rotation (inode changed) or truncation (size < pos)
                    if self._file_inode is not None and (
                        current_inode != self._file_inode
                        or current_size < self._last_file_pos
                    ):
                        # File was rotated or truncated - reset position
                        self._last_file_pos = 0
                        self._last_file_size = 0
                    self._file_inode = current_inode

                if current_size > self._last_file_size:
                    # Read file position under lock, then release for I/O
                    with self._state_lock:
                        seek_position = self._last_file_pos
                        inode_to_verify = self._file_inode

                    with open(
                        self.log_file_path, "r", encoding="utf-8", errors="replace"
                    ) as f:
                        if seek_position == 0 and current_size > 0:
                            # Read from end of file, limiting to ~50 lines
                            # Estimate ~200 bytes per line on average
                            estimated_start = max(
                                0, current_size - (MAX_INITIAL_LINES * 200)
                            )
                            f.seek(estimated_start)
                            content = f.read()
                            # Skip partial first line (we started mid-file)
                            if estimated_start > 0 and content:
                                first_newline = content.find("\n")
                                if first_newline >= 0:
                                    content = content[first_newline + 1 :]
                            lines = content.splitlines()
                        else:
                            # Normal incremental read
                            f.seek(seek_position)
                            content = f.read()
                            lines = content.splitlines()

                        new_pos = f.tell()

                    # Verify inode hasn't changed during read (file rotation detection)
                    try:
                        verify_inode = os.stat(self.log_file_path).st_ino
                    except FileNotFoundError:
                        # File deleted during read - skip this update
                        continue

                    if verify_inode != inode_to_verify:
                        # File was rotated during read - skip this update
                        continue

                    with self._state_lock:
                        # Only update if inode still matches
                        if self._file_inode == inode_to_verify:
                            self._last_file_pos = new_pos
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
                                with self._state_lock:
                                    last_line = self._last_non_tqdm_line
                                phase_name = self._detect_phase_name(last_line)
                                try:
                                    self._file_queue.put(
                                        (
                                            "tqdm",
                                            {"data": tqdm_data, "phase": phase_name},
                                        ),
                                        block=False,
                                    )
                                except queue.Full:
                                    pass  # Skip tqdm update if queue is full
                        else:
                            # Non-tqdm line - store for phase detection and queue for logging
                            with self._state_lock:
                                self._last_non_tqdm_line = line
                            # Parse epoch progress (for progress bar)
                            self._parse_epoch_progress_bg(line)
                            # Check for training status line (for training tasks)
                            if self.process_type == "training":
                                training_data = self._parse_training_status_line(line)
                                if training_data:
                                    try:
                                        self._file_queue.put(
                                            ("training_status", training_data),
                                            block=False,
                                        )
                                    except queue.Full:
                                        pass  # Skip training status if queue is full
                            # Queue log line for main thread
                            try:
                                self._file_queue.put(("log_line", line), block=False)
                            except queue.Full:
                                self._dropped_lines += 1
                                if self._dropped_lines == 1:
                                    logging.warning(
                                        "[ProgressWindow] Queue full, dropping log lines (consumer lagging)"
                                    )
            except OSError as e:
                logging.warning(
                    f"[ProgressWindow] File access error in poll worker: {e}"
                )
            except Exception as e:
                logging.warning(f"[ProgressWindow] Error in file poll worker: {e}")

    def _parse_epoch_progress_bg(self, line):
        """Parse epoch progress in background thread (no UI updates)."""
        if not self._total_epoch:
            return

        match = re.search(r"[Ee]poch[:\s]*(\d+)\s*/\s*(\d+)", line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            if total > 0 and current <= total:
                self._current_epoch = current
                if not self._total_epoch:
                    self._total_epoch = total
                # Queue progress update for main thread
                try:
                    self._file_queue.put(
                        ("progress", {"current": current, "total": total}), block=False
                    )
                except queue.Full:
                    pass  # Skip progress update if queue is full

    def _is_tqdm_line(self, line):
        """Check if line is a tqdm progress bar update."""
        # Match patterns like: "  5%|▍         | 16/333 [00:18<04:36,  1.16it/s]"
        return bool(re.match(r"^\s*\d+%\|.*\|\s*\d+/\d+\s*\[", line))

    def _parse_tqdm_line(self, line):
        """Extract progress info from tqdm line.

        Returns dict with: percent, current, total, eta, rate, rate_unit
        or None if parsing fails.
        """
        # Pattern: "  5%|▍         | 16/333 [00:18<04:36,  1.16it/s]"
        match = re.match(r"^\s*(\d+)%\|.*\|\s*(\d+)/(\d+)\s*\[([^\]]+)\]", line)
        if not match:
            return None

        percent = int(match.group(1))
        current = int(match.group(2))
        total = int(match.group(3))
        bracket_content = match.group(4)

        # Validate parsed values
        if not (0 <= percent <= 100) or current < 0 or total <= 0 or current > total:
            return None

        # Parse bracket content: "00:18<04:36,  1.16it/s" or "00:18<04:36,  5.38s/it"
        eta = None
        rate = None
        rate_unit = None

        # Extract ETA (after <)
        eta_match = re.search(r"<\s*([\d:]+)", bracket_content)
        if eta_match:
            eta = eta_match.group(1)

        # Extract rate (after comma or at end)
        rate_match = re.search(r"([\d.]+)\s*(it/s|s/it)", bracket_content)
        if rate_match:
            rate = float(rate_match.group(1))
            rate_unit = rate_match.group(2)

        return {
            "percent": percent,
            "current": current,
            "total": total,
            "eta": eta,
            "rate": rate,
            "rate_unit": rate_unit,
        }

    def _detect_phase_name(self, line):
        """Extract phase name from a log line.

        Looks for patterns like:
        - "Starting preprocessing..."
        - "[11:02:15] Starting preprocessing..."
        - "Preprocessing audio files..."
        - "Extracting features..."
        """

        # Strip timestamp prefix if present (e.g., "[11:02:15] ")
        stripped = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", line)

        # Common phase patterns
        phase_patterns = [
            r"[Ss]tarting\s+(\w+)",
            r"^(\w+ing)\s+",  # "Preprocessing", "Extracting", "Training"
            r"^(\w+)\s+started",
        ]

        for pattern in phase_patterns:
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                phase = match.group(1).capitalize()
                # Normalize common variations
                phase_map = {
                    "Preprocess": "Preprocessing",
                    "Extract": "Extracting",
                    "Train": "Training",
                    "Feature": "Feature extraction",
                }
                return phase_map.get(phase, phase)

        return None

    def _parse_training_status_line(self, line):
        """Parse a training status line.

        Delegates to the module-level _parse_training_log_line helper, shared
        with ProcessDashboardController (single regex, frozen-safe).
        """
        return _parse_training_log_line(line)

    def _update_training_panel(self, training_data):
        """Update the training info panel with current training status.

        Args:
            training_data: dict with epoch, step, training_speed, best_loss, best_epoch, best_step
        """
        # Only update if this is a training process
        if self.process_type != "training":
            return

        # Update current epoch and step
        self._current_epoch = training_data.get("epoch", 0)
        self._current_step = training_data.get("step", 0)
        self._training_speed = training_data.get("training_speed")

        # Update best epoch info if available
        if training_data.get("best_epoch") is not None:
            self._best_epoch = training_data["best_epoch"]
            self._best_loss = training_data["best_loss"]
            self._best_step = training_data["best_step"]

        # Update UI - Best Epoch (most prominent)
        if self._best_epoch is not None:
            self.best_epoch_label.setStringValue_(
                f"Best: Epoch {self._best_epoch}  |  Loss {self._best_loss:.4f}"
            )
            self.best_details_label.setStringValue_(f"Step {self._best_step:,}")
        else:
            self.best_epoch_label.setStringValue_("Best Epoch: Training in progress...")
            self.best_details_label.setStringValue_("Loss: -- | Step: --")

        # Update Current Status
        speed_str = (
            f"{self._training_speed}/epoch" if self._training_speed else "--/epoch"
        )
        self.current_epoch_label.setStringValue_(
            f"Current: Epoch {self._current_epoch}  |  Step {self._current_step:,}  |  Speed: {speed_str}"
        )

        # Update progress bar if we have total_epoch
        if self._total_epoch and self._current_epoch:
            self.progress_bar.setDoubleValue_(self._current_epoch)

    def _update_live_zone(self, tqdm_data, phase_name=None):
        """Update the Rich Status Card with current tqdm progress."""
        if phase_name and phase_name != self._live_phase:
            # Phase changed - log completion of previous phase
            if self._live_phase and self._live_phase_start:
                self._log_phase_completion()
            # Start new phase
            self._live_phase = phase_name
            self._live_phase_start = datetime.datetime.now()
            # Log phase start
            total_label = "files" if "preprocess" in phase_name.lower() else "items"
            self._add_log_line(
                f"{phase_name} started ({tqdm_data['total']} {total_label})"
            )

        # Build phase label with icon
        phase = self._live_phase or "Processing"
        phase_icons = {
            "preprocessing": "📁",
            "feature extraction": "🔬",
            "training": "🎯",
            "inference": "🎵",
            "tts": "🗣️",
        }
        icon = phase_icons.get(phase.lower(), "⚙️")
        current = tqdm_data["current"]
        total = tqdm_data["total"]
        total_label = "files" if "preprocess" in phase.lower() else "items"

        self.phase_label.setStringValue_(
            f"{icon}  {phase.upper()}  •  {current} of {total} {total_label}"
        )
        # AX value mirrors the visual line minus the emoji; casing stays
        # natural (screen readers read "Feature extraction" naturally —
        # the visual .upper() is styling only).
        self.phase_label.setAccessibilityValue_(
            f"{phase} — {current} of {total} {total_label}"
        )

        # Update visual progress bar (50 chars = 100%)
        percent = tqdm_data.get("percent", 0)
        filled = int(percent / 2)  # 50 chars max
        empty = 50 - filled
        bar = "█" * filled + "░" * empty
        self.visual_progress.setStringValue_(bar)
        self.progress_percent.setStringValue_(f"{percent}%")

        # Update stats grid
        # Speed
        if tqdm_data.get("rate"):
            rate_str = f"{tqdm_data['rate']:.2f}{tqdm_data['rate_unit']}"
        else:
            rate_str = "--"
        self.stats_values[0].setStringValue_(rate_str)

        # ETA
        eta_str = tqdm_data.get("eta", "--") or "--"
        self.stats_values[1].setStringValue_(eta_str)

        # Phase Time
        if self._live_phase_start:
            elapsed = datetime.datetime.now() - self._live_phase_start
            total_seconds = int(elapsed.total_seconds())
            minutes, seconds = divmod(total_seconds, 60)
            hours, minutes = divmod(minutes, 60)
            if hours > 0:
                time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                time_str = f"{minutes}:{seconds:02d}"
        else:
            time_str = "--"
        self.stats_values[2].setStringValue_(time_str)

        # Items
        self.stats_values[3].setStringValue_(f"{current}/{total}")

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
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._add_log_line(
            f"[{timestamp}] {self._live_phase} complete ({duration_str})"
        )

        # Clear phase tracking
        self._live_phase = None
        self._live_phase_start = None
        return True

    def _start_timer(self):
        """Start a lightweight timer for UI updates from queue."""
        from AppKit import NSTimer

        self.timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                TIMER_TICK_INTERVAL, self, "processQueueUpdates:", None, True
            )
        )

    def processQueueUpdates_(self, timer):
        """Process pending updates from background thread (runs on main thread)."""
        import applio_i18n

        _t = applio_i18n.native_tr

        # Update elapsed time
        elapsed = datetime.datetime.now() - self.start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.time_label.setStringValue_(
            f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}"
        )

        # Process all pending updates from queue
        updates_processed = 0
        while updates_processed < MAX_QUEUE_ITEMS_PER_TICK:
            try:
                update_type, data = self._file_queue.get(block=False)
                updates_processed += 1

                if update_type == "log_line":
                    self._add_log_line(data)
                elif update_type == "tqdm":
                    # Update live zone with tqdm progress
                    self._update_live_zone(data["data"], data.get("phase"))
                elif update_type == "training_status":
                    # Update training info panel (training tasks only)
                    self._update_training_panel(data)
                elif update_type == "progress":
                    # Update progress bar
                    self.progress_bar.setDoubleValue_(data["current"])
                    self.progress_bar.setAccessibilityHelp_(
                        f"Training progress: Epoch {data['current']} of {data['total']}"
                    )
            except queue.Empty:
                break  # Queue empty - expected, not an error
            except (KeyError, TypeError) as e:
                # Data format errors - log and continue with next item
                logging.warning(f"[ProgressWindow] Malformed queue data: {e}")
                continue
            except AttributeError as e:
                # Code bugs (typos in attribute names) - re-raise to surface during development
                logging.critical(
                    f"[ProgressWindow] AttributeError (possible typo): {e}"
                )
                raise
            except Exception as e:
                # Unexpected errors - log and continue (don't break the entire UI)
                logging.error(
                    f"[ProgressWindow] Unexpected error processing queue: {e}"
                )
                continue

        # Check if process still running (with PID recycling protection)
        pid = self.process_info.get("pid")
        started_at = self.process_info.get("started_at")
        if pid and not verify_process_identity(pid, started_at):
            current_status = self.status_label.stringValue()
            if _t("Running") in current_status or _t("Paused") in current_status:
                self.status_label.setStringValue_(_t("Status: Completed"))
                self.status_badge.setStringValue_(_t("Completed"))
                if self._total_epoch:
                    self.progress_bar.setDoubleValue_(self._total_epoch)
                else:
                    self.progress_bar.stopAnimation_(None)
                _announce_for_accessibility(
                    self.status_label,
                    f"{self.process_type.capitalize()} process completed",
                )

        # Check for live zone timeout (no tqdm for 2+ seconds)
        if self._last_tqdm_time and self._live_phase:
            elapsed = (datetime.datetime.now() - self._last_tqdm_time).total_seconds()
            if elapsed > PHASE_TIMEOUT:
                # Phase likely complete - log completion and clear live zone
                # _log_phase_completion returns True only if a phase was active
                if self._log_phase_completion():
                    # Reset Rich Status Card to waiting state
                    self.phase_label.setStringValue_("Waiting for progress...")
                    # The explicit AX value set in _update_live_zone stops
                    # tracking setStringValue_, so reset it here too or the
                    # last progress value outlives the visual reset.
                    self.phase_label.setAccessibilityValue_("Waiting for progress...")
                    self.visual_progress.setStringValue_(
                        "░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░"
                    )
                    self.progress_percent.setStringValue_("0%")
                    for val in self.stats_values:
                        val.setStringValue_("--")
                self._last_tqdm_time = None

    def _add_log_line(self, line):
        """Add a line to the log view with buffer limit to prevent slowdowns."""
        self.log_lines.append(line)

        # Efficient O(1) trimming using popleft - also sync text storage
        while len(self.log_lines) > MAX_LOG_LINES:
            self.log_lines.popleft()
            # Note: Text storage trimming is done via periodic reset below

        text_storage = self.log_view.textStorage()
        current_length = text_storage.length()

        # Add newline if not first line
        if current_length > 0 and not text_storage.string().endswith("\n"):
            text_storage.replaceCharactersInRange_withString_((current_length, 0), "\n")
            current_length += 1

        # Append new line
        text_storage.replaceCharactersInRange_withString_((current_length, 0), line)

        # Periodically reset text storage to match deque content
        # This prevents unbounded growth and syncs with deque
        if (
            len(self.log_lines) >= MAX_LOG_LINES
            and len(self.log_lines) % MAX_LOG_LINES == 0
        ):
            text_storage.beginEditing()
            text_storage.deleteCharactersInRange_((0, text_storage.length()))
            text_storage.appendString_("\n".join(self.log_lines))
            text_storage.endEditing()

        # Scroll to bottom only every N lines to reduce overhead
        if len(self.log_lines) % LOG_SCROLL_INTERVAL == 0:
            self.log_view.scrollRangeToVisible_((text_storage.length(), 0))

    def show(self):
        """Show the window and start log tailing."""
        # Activate the application to ensure it receives events
        from AppKit import NSApplication, NSApplicationActivationPolicyRegular

        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)

        self.window.makeKeyAndOrderFront_(None)
        logging.info(f"[ProgressWindow] Showing window for {self.process_type}")

        # Initial keyboard focus: Pause is the primary RECOVERABLE action. Never
        # Terminate — a reflexive Return there would kill the run. After a user
        # terminate both pause+terminate are disabled; fall back to the always-
        # enabled, fully non-destructive Open Logs.
        try:
            target = (
                self.pause_btn
                if hasattr(self, "pause_btn")
                and self.pause_btn
                and self.pause_btn.isEnabled()
                else self.logs_btn
            )
            self.window.setInitialFirstResponder_(target)
            # setInitialFirstResponder_ is consulted when the window BECOMES
            # key; ordering front above already made it key, so move focus
            # directly for this first open (later re-keys use the initial one).
            self.window.makeFirstResponder_(target)
        except Exception:
            logging.debug(
                "[ProgressWindow] first-responder setup failed", exc_info=True
            )

        # Initial log read - queue to background thread instead of blocking main thread
        # The background thread will pick up existing content on first poll
        if self.log_file_path and os.path.exists(self.log_file_path):
            try:
                # Just set the file position to 0 so background thread reads from start
                self._last_file_pos = 0
                self._last_file_size = 0
            except Exception as e:
                logging.warning(
                    f"[ProgressWindow] Error setting initial file position: {e}"
                )

    def terminateProcess_(self, sender):
        """Terminate the process."""
        if not PSUTIL_AVAILABLE:
            logging.warning("[ProgressWindow] Cannot terminate - psutil not available")
            return

        pid = self.process_info.get("pid")
        started_at = self.process_info.get("started_at")
        if pid and verify_process_identity(pid, started_at):
            try:
                psutil.Process(pid).terminate()
                self.status_label.setStringValue_("Status: Terminated")
                self.status_badge.setStringValue_("Terminated")
                self._add_log_line(
                    f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process terminated by user"
                )
                # Accessibility announcement
                _announce_for_accessibility(
                    self.status_label,
                    f"{self.process_type.capitalize()} process terminated",
                )
                # Update button accessibility
                self.terminate_btn.setEnabled_(False)
                self.terminate_btn.setAccessibilityHelp_("Process has been terminated")
                self.pause_btn.setEnabled_(False)
                self.pause_btn.setAccessibilityHelp_("Process has been terminated")
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError) as e:
                logging.warning(f"[ProgressWindow] Could not terminate process: {e}")
                self.status_label.setStringValue_("Status: Already terminated")
                self.status_badge.setStringValue_("Already terminated")

    def togglePause_(self, sender):
        """Toggle pause/resume."""
        import applio_i18n

        _t = applio_i18n.native_tr

        pid = self.process_info.get("pid")
        started_at = self.process_info.get("started_at")
        if not pid or not verify_process_identity(pid, started_at):
            return

        try:
            if self.paused:
                os.kill(pid, signal.SIGCONT)
                self.pause_btn.setTitle_(_t("Pause"))
                self.pause_btn.setAccessibilityLabel_("Pause process")
                self.status_label.setStringValue_(_t("Status: Running"))
                self.status_badge.setStringValue_(_t("Running"))
                self._add_log_line(
                    f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process resumed"
                )
                # Accessibility announcement
                _announce_for_accessibility(
                    self.status_label,
                    f"{self.process_type.capitalize()} process resumed",
                )
            else:
                os.kill(pid, signal.SIGSTOP)
                self.pause_btn.setTitle_(_t("Resume"))
                self.pause_btn.setAccessibilityLabel_("Resume process")
                self.status_label.setStringValue_(_t("Status: Paused"))
                self.status_badge.setStringValue_(_t("Paused"))
                self._add_log_line(
                    f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Process paused"
                )
                # Accessibility announcement
                _announce_for_accessibility(
                    self.status_label,
                    f"{self.process_type.capitalize()} process paused",
                )
            self.paused = not self.paused
        except (ProcessLookupError, PermissionError, OSError) as e:
            logging.warning(f"[ProgressWindow] Could not toggle pause: {e}")
            self.status_label.setStringValue_(_t("Status: Error controlling process"))
            self.status_badge.setStringValue_(_t("Error"))

    def openLogsFolder_(self, sender):
        """Open logs folder in Finder."""
        model_name = self.process_info.get("model_name", "")
        if model_name:
            data_path = os.environ.get(
                "APPLIO_DATA_PATH", os.path.expanduser("~/Applio")
            )
            logs_folder = os.path.join(data_path, "logs", model_name)
            if os.path.exists(logs_folder):
                subprocess.run(["open", logs_folder])
            else:
                subprocess.run(["open", os.path.join(data_path, "logs")])

    def relaunchApp_(self, sender):
        """Relaunch the main app.

        Order matters (1.6): release the single-instance lock, spawn the new
        instance in a NEW session (LaunchServices `open`, or start_new_session),
        THEN terminate this instance via the delegate cascade (which killpg's
        the OLD group — the new instance is in a different session so it is
        safe). Do NOT call _terminate_children() directly here: that killpg's
        THIS process's own group and would kill us before the spawn lands.
        """
        release_single_instance_lock()
        if getattr(sys, "frozen", False):
            app_path = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
            subprocess.Popen(["open", app_path])  # LaunchServices -> new session
        else:
            subprocess.Popen(
                [sys.executable, os.path.join(BASE_PATH, "applio_launcher.py")],
                start_new_session=True,
            )
        # Gracefully terminate this instance (runs the ApplioAppDelegate cascade).
        try:
            from AppKit import NSApplication

            NSApplication.sharedApplication().terminate_(None)
        except Exception:
            sys.exit(0)

    def windowWillClose_(self, notification):
        """Handle window close."""
        self._cleanup()

    def applicationWillTerminate_(self, notification):
        """Handle application termination - ensure cleanup."""
        self._cleanup()

    def _cleanup(self):
        """Clean up resources."""
        # Signal background thread to stop
        if hasattr(self, "_shutdown_event"):
            self._shutdown_event.set()

        if self.timer:
            self.timer.invalidate()
            self.timer = None
        if self._observer:
            NSNotificationCenter.defaultCenter().removeObserver_(self._observer)
            self._observer = None
        if hasattr(self, "_terminate_observer") and self._terminate_observer:
            NSNotificationCenter.defaultCenter().removeObserver_(
                self._terminate_observer
            )
            self._terminate_observer = None
        # Reset smart log display state
        self._live_phase = None
        self._live_phase_start = None
        self._last_tqdm_time = None
        self._last_non_tqdm_line = ""

        # Wait for background thread to finish (with timeout)
        if (
            hasattr(self, "_file_thread")
            and self._file_thread
            and self._file_thread.is_alive()
        ):
            self._file_thread.join(timeout=1.0)


# =================================================================
# 5.5. Process Dashboard Controller (Persistent Window)
# =================================================================


def _chart_text_attr(size, weight=None, color=None):
    """Build an NSAttributedString attributes dict for the loss chart.

    Module-scope (not a LossChartView method) because PyObjC validates every
    method on an NSView subclass as an ObjC selector and rejects plain helper
    signatures. Returns {NSFontAttributeName, NSForegroundColorAttributeName}.
    """
    font = (
        NSFont.systemFontOfSize_weight_(size, weight)
        if weight is not None
        else NSFont.systemFontOfSize_(size)
    )
    return {
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: color or NSColor.secondaryLabelColor(),
    }


# A new-best epoch is flagged as a "significant improvement" when its drop from
# the previous running-best loss is at least this fraction of that previous best
# (3%). See _significant_improvements for the rationale.
LOSS_SIG_IMPROVEMENT_REL = 0.03


def _significant_improvements(points):
    """Indices (0-based, sorted) of the "significant improvement" epochs.

    ``points`` is the loss chart's [(epoch, best_loss), ...] in epoch order, where
    best_loss is the running minimum (monotone non-increasing) -- so it only
    changes at genuine new bests. A point is an *improvement* when its best_loss
    is strictly below the previous point's (a new best set that epoch); it is
    *significant* when that drop is meaningful rather than rounding noise.

    Threshold: a relative drop of >= ``LOSS_SIG_IMPROVEMENT_REL`` of the previous
    best (drop / prev_best >= 0.03). Relative is scale-invariant, so it works
    whether loss is ~8 early or ~0.5 late, and because the series is a monotone
    running minimum (no in-sequence jitter) even a modest 3% reliably denotes a
    real step while excluding the trivial 8.822->8.821 new-bests the user wants
    skipped. This also means only the FIRST epoch reaching each notable new-best
    level is flagged -- exactly the "only the first instance" requirement.

    The first point is never an improvement (no baseline to drop from). Returns
    [] for a flat curve or a tail of only tiny new-bests -- correct: nothing to
    celebrate. Pure (no AppKit) so it is unit-testable headlessly.
    """
    sig = []
    for i in range(1, len(points)):
        prev = points[i - 1][1]
        cur = points[i][1]
        if (
            cur < prev
            and prev > 0.0
            and (prev - cur) / prev >= LOSS_SIG_IMPROVEMENT_REL
        ):
            sig.append(i)
    return sig


def _chart_ax_summary(points):
    """VoiceOver summary of the loss chart's plotted curve (AppKit-free).

    Module-level (NOT a LossChartView method — PyObjC validates every method
    on an NSView subclass as an ObjC selector; see the _chart_text_attr note).
    LossChartView.set_points publishes this as the view's AX value: a
    custom-drawn chart is invisible to VoiceOver, so the value string is the
    only readable channel. The improvement count comes from the SAME
    _significant_improvements the green drawRect_ highlights use, so the
    spoken count matches the drawn markers. Fewer than 2 evaluated points is
    the chart's placeholder case (no line is drawn either) -> "no data yet".
    Malformed points are skipped by the same coercion set_points applies.
    """
    import applio_i18n

    _t = applio_i18n.native_tr

    pts = []
    for p in points or []:
        try:
            pts.append((int(p[0]), float(p[1])))
        except (TypeError, ValueError, IndexError):
            continue
    if len(pts) < 2:
        return f"{_t('Loss chart')}: {_t('no data yet')}."
    first_ep, first_loss = pts[0]
    last_ep, last_loss = pts[-1]
    best = min(pts, key=lambda t: t[1])
    n_impr = len(_significant_improvements(pts))
    return (
        f"{_t('Loss chart')}: {len(pts)} {_t('epochs plotted')}, "
        f"{first_ep}–{last_ep}. {_t('Loss fell from')} {first_loss:.4g} "
        f"{_t('to')} {last_loss:.4g}. {_t('Best')} {best[1]:.4g} @ {best[0]}. "
        f"{n_impr} {_t('significant improvements')}."
    )


class LossChartView(NSView):
    """Compact loss-vs-epoch line chart for the dashboard detail panel (Feature 3).

    Set points via set_points([(epoch, loss), ...]); the view redraws. With
    fewer than 2 evaluated points it draws a "Training..." placeholder instead
    of a line (graceful: a run that just started has no curve yet). The y-axis
    is the running best-loss (lowest_value) per epoch — the same field the
    snapshot stores, so historical and active processes plot identically.

    Significant quality improvements (epochs where the running best drops
    notably) are always highlighted with a green marker + a bold epoch label —
    see _significant_improvements. This is pure data drawn in drawRect_, with no
    mouse/tracking/overlay machinery.

    Note: text-attribute helpers live at module scope (_chart_text_attr), not as
    methods here, because PyObjC validates every method on an NSView subclass as
    an ObjC selector and rejects plain helper signatures.
    """

    CHART_HEIGHT = 140  # reserved height in the detail panel layout

    def initWithFrame_(self, frame):
        self = objc.super(LossChartView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._points = []  # [(epoch, best_loss)]
        # Screen-space positions of each plotted point, recomputed in drawRect_.
        # Retained as a stable point-geometry cache the draw reuses (and that a
        # headless render check can inspect); empty until the first real draw /
        # when the chart shows its placeholder.
        self._screen_points = []  # [(sx, sy, epoch, loss), ...]
        return self

    def set_points(self, points):
        """Accept a list of (epoch, loss) tuples and trigger a redraw."""
        cleaned = []
        for p in points or []:
            try:
                cleaned.append((int(p[0]), float(p[1])))
            except (TypeError, ValueError, IndexError):
                continue
        self._points = cleaned
        self.setNeedsDisplay_(True)
        # VoiceOver cannot read a custom-drawn chart; publish a text summary
        # of the plotted curve as the view's AX value. The builder is
        # module-level (_chart_ax_summary) — see the class docstring note
        # about PyObjC selector validation on NSView subclasses.
        try:
            self.setAccessibilityValue_(_chart_ax_summary(self._points))
        except Exception:
            pass

    def drawRect_(self, rect):
        """Draw background, gridlines + loss axis labels, the loss polyline,
        dots at each evaluated epoch, and a current-value label."""
        # Reset the point-geometry cache for this pass; repopulated below once
        # real points are plotted (every early return leaves it empty so the
        # highlight loop + headless render checks never see stale geometry).
        self._screen_points = []
        bounds = self.bounds()
        width = bounds.size.width
        height = bounds.size.height

        # Background + title
        NSColor.controlBackgroundColor().setFill()
        NSBezierPath.fillRect_(bounds)
        title = NSAttributedString.alloc().initWithString_attributes_(
            "Training loss (best so far)",
            _chart_text_attr(10, NSFontWeightMedium, NSColor.labelColor()),
        )
        title.drawAtPoint_((8.0, height - 14.0))

        pad_left, pad_right, pad_top, pad_bottom = 38.0, 10.0, 20.0, 14.0
        plot_x = pad_left
        plot_y = pad_bottom
        plot_w = width - pad_left - pad_right
        plot_h = height - pad_top - pad_bottom
        if plot_w <= 8 or plot_h <= 8:
            return

        points = self._points
        if len(points) < 2:
            ph = NSAttributedString.alloc().initWithString_attributes_(
                "Training… waiting for evaluation data",
                _chart_text_attr(11, color=NSColor.secondaryLabelColor()),
            )
            ph.drawAtPoint_(
                ((width - ph.size().width) / 2.0, (height - ph.size().height) / 2.0)
            )
            return

        epochs = [p[0] for p in points]
        losses = [p[1] for p in points]
        min_e, max_e = min(epochs), max(epochs)
        min_l, max_l = min(losses), max(losses)
        epoch_span = (max_e - min_e) or 1
        # The chart plots the RUNNING best loss (lowest_value), which is
        # monotonic non-increasing. When the best loss was set early and never
        # beaten (common for short runs -- e.g. the test run held 8.822 for
        # every evaluated epoch), every point shares the same value and the
        # curve is genuinely flat. The old max==min fallback glued that flat
        # line to the plot floor (y == plot_y), reading as a broken chart;
        # render the no-variation case as a centered line + note instead.
        all_equal = (max_l - min_l) < 1e-9

        def x_for(e):
            return plot_x + (e - min_e) / epoch_span * plot_w

        if all_equal:
            y_line = plot_y + plot_h / 2.0

            def y_for(l):
                return y_line

        else:

            def y_for(l):
                return plot_y + (l - min_l) / (max_l - min_l) * plot_h

        # Gridlines (3 interior); numeric loss-axis labels only when there is a
        # real range (the all-equal note carries the single value instead).
        grid = NSColor.secondaryLabelColor().colorWithAlphaComponent_(0.18)
        grid.setStroke()
        label_attr = _chart_text_attr(9)
        for i in range(4):
            gy = plot_y + (i / 3.0) * plot_h
            gp = NSBezierPath.bezierPath()
            gp.moveToPoint_((plot_x, gy))
            gp.lineToPoint_((plot_x + plot_w, gy))
            gp.setLineWidth_(0.5)
            gp.stroke()
            if not all_equal:
                # Track y_for exactly: min loss at the BOTTOM (i=0 -> plot_y),
                # max at the top. The old max_l-(...) form drew the axis labels
                # upside-down relative to the plotted points.
                val = min_l + (i / 3.0) * (max_l - min_l)
                t = NSAttributedString.alloc().initWithString_attributes_(
                    f"{val:.3f}", label_attr
                )
                t.drawAtPoint_((2.0, gy - 5.0))

        # X-axis epoch legend (first + last epoch); compact for the small chart.
        x_axis_attr = _chart_text_attr(8)
        first_lbl = NSAttributedString.alloc().initWithString_attributes_(
            "ep {}".format(min_e),
            x_axis_attr,
        )
        first_lbl.drawAtPoint_((plot_x, 1.0))
        if max_e > min_e:
            last_lbl = NSAttributedString.alloc().initWithString_attributes_(
                "ep {}".format(max_e),
                x_axis_attr,
            )
            last_lbl.drawAtPoint_((plot_x + plot_w - last_lbl.size().width, 1.0))

        # Compute each point's screen position once and reuse for the line, the
        # dots, and the improvement-highlight markers (cached on _screen_points).
        screen_points = [(x_for(e), y_for(l), e, l) for e, l in zip(epochs, losses)]
        self._screen_points = screen_points

        # Polyline (loss curve).
        NSColor.systemBlueColor().setStroke()
        path = NSBezierPath.bezierPath()
        path.moveToPoint_((screen_points[0][0], screen_points[0][1]))
        for sx, sy, e, l in screen_points[1:]:
            path.lineToPoint_((sx, sy))
        path.setLineWidth_(1.5)
        path.stroke()

        # Dots at each evaluated epoch.
        NSColor.systemBlueColor().setFill()
        for sx, sy, e, l in screen_points:
            NSBezierPath.bezierPathWithOvalInRect_(
                ((sx - 2.0, sy - 2.0), (4.0, 4.0))
            ).fill()

        if all_equal:
            # Annotate so the flat line reads as intentional, not broken.
            note = NSAttributedString.alloc().initWithString_attributes_(
                "Best loss unchanged at {:.3f}".format(min_l),
                _chart_text_attr(10, NSFontWeightMedium, NSColor.secondaryLabelColor()),
            )
            note.drawAtPoint_(((width - note.size().width) / 2.0, y_line + 6.0))

        # Current value (latest epoch) top-right.
        last_e, last_l = epochs[-1], losses[-1]
        cur = NSAttributedString.alloc().initWithString_attributes_(
            f"loss {last_l:.3f}  @  ep {last_e}",
            _chart_text_attr(10, NSFontWeightMedium, NSColor.labelColor()),
        )
        cur.drawAtPoint_((width - cur.size().width - 8.0, height - 14.0))

        # Significant-improvement highlights -- the chart's "story". The plotted
        # series is the running best loss (monotone non-increasing), so it only
        # steps DOWN at genuine new bests; _significant_improvements() picks the
        # steps that drop notably and we mark those epochs with a confident green
        # marker + a bold epoch label so the eye lands on the quality gains first.
        # Always-on by design: pure data, drawn every frame -- no tracking area,
        # no mouse events, no overlay view -- so it cannot hit the frozen-
        # compositing problem the crosshair overlay did.
        sig = _significant_improvements(points)
        if not sig:
            return
        green = NSColor.systemGreenColor()
        # Light halo behind each marker so it clears the blue curve line/dots
        # (figure-ground separation without floating the marker off its point).
        halo = NSColor.controlBackgroundColor()
        label_attr = _chart_text_attr(10, NSFontWeightSemibold, green)
        last_label_x = None
        for i in sig:
            sx, sy, epoch, _loss = self._screen_points[i]
            halo.setFill()
            NSBezierPath.bezierPathWithOvalInRect_(
                ((sx - 5.0, sy - 5.0), (10.0, 10.0))
            ).fill()
            green.setFill()
            NSBezierPath.bezierPathWithOvalInRect_(
                ((sx - 4.0, sy - 4.0), (8.0, 8.0))
            ).fill()
            # Bold epoch label above the marker; thin by horizontal proximity so
            # a cluster of improvements reads cleanly (the marker always draws).
            if last_label_x is None or (sx - last_label_x) >= 26.0:
                lbl = NSAttributedString.alloc().initWithString_attributes_(
                    str(epoch),
                    label_attr,
                )
                lw = float(lbl.size().width)
                lh = float(lbl.size().height)
                lx = sx - lw / 2.0
                if lx < plot_x:
                    lx = plot_x
                elif lx + lw > plot_x + plot_w:
                    lx = plot_x + plot_w - lw
                ly = sy + 7.0
                if ly + lh > plot_y + plot_h:
                    ly = plot_y + plot_h - lh
                lbl.drawAtPoint_((lx, ly))
                last_label_x = sx


class ProcessDashboardController(NSObject):
    """Persistent dashboard window with idle/active/completed states.

    This window is always accessible from the Window menu and shows:
    - Idle state: "No Active Processes" placeholder
    - Active state: Process list + detail panel with logs
    - Completed state: Process summary

    Key design decisions:
    - Window never releases on close (setReleasedWhenClosed_(False))
    - Close button hides window instead of destroying
    - Uses weakref to prevent retain cycles in selectors
    - Single instance managed by ApplioLauncher
    """

    def initWithLauncher_(self, launcher):
        """Initialize the dashboard controller (NSObject init pattern).

        Create via ``.alloc().initWithLauncher_(launcher)`` — required so the
        controller can be an NSWindow delegate + NSTableView dataSource/delegate
        + NSNotificationCenter observer (plain Python classes can't answer AppKit's
        conformsToProtocol: / respondsToSelector:).
        """
        self = objc.super(ProcessDashboardController, self).init()
        if self is None:
            return None
        if not NATIVE_APIS_AVAILABLE:
            raise RuntimeError("Native APIs not available")

        self._launcher = launcher
        self._current_state = "idle"  # idle, active, completed
        self._selected_process = None
        self._shutdown_event = threading.Event()
        self._update_counter = 0  # For timer-based throttling
        # Feature 2: auto-show gating. True once the user has opened the dashboard
        # this session — only then do we surface it on a new job (single-process).
        # Stays False if the user never opens it (respect their choice).
        self._opened_this_session = False

        # Window and UI elements (initialized in _create_window)
        self.window = None
        self._observer = None
        self._terminate_observer = None
        self._timer = None

        # Process list data
        self._active_processes = []
        self._recent_processes = []

        # UI element references
        self.placeholder_view = None
        self.idle_label = None
        self.idle_subtitle = None

        # Sidebar UI elements (for active state)
        self.sidebar_scroll = None
        self.process_table = None
        self.active_header = None

        # Detail panel UI elements (for selected process)
        self.detail_panel = None
        self.detail_name = None
        self.detail_status = None
        self.detail_progress = None
        self.detail_progress_text = None
        self.detail_log_scroll = None
        self.detail_log_view = None
        self.detail_eta = None
        self.detail_chart = None  # Feature 3: loss-vs-epoch line chart
        # Feature 4: action bar buttons + the resolved proc they act on
        self.stop_btn = None
        self.pause_btn = None
        self.reveal_btn = None
        self.open_btn = None
        self._current_proc = None  # resolved proc shown in the detail panel

        # Create window
        try:
            self._create_window()
            self._create_sidebar()  # Create sidebar (initially hidden)
            self._create_detail_panel()  # Create detail panel (initially hidden)
            self._create_idle_ui()  # Start in idle state
        except Exception:
            self._cleanup()
            raise
        return self

    def _create_window(self):
        """Create the persistent dashboard window."""
        style = NSTitledWindowMask | NSClosableWindowMask | NSMiniaturizableWindowMask
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, DASHBOARD_WIDTH, DASHBOARD_HEIGHT),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Applio Dashboard")
        self.window.center()
        self.window.setReleasedWhenClosed_(False)  # CRITICAL: Never release
        self.window.setDelegate_(self)  # Enable windowShouldClose_ delegate

        # Register for close notification to hide instead
        notification_center = NSNotificationCenter.defaultCenter()
        self._observer = notification_center.addObserver_selector_name_object_(
            self,
            "dashboardWindowWillClose:",
            "NSWindowWillCloseNotification",
            self.window,
        )

        # App termination observer
        self._terminate_observer = (
            notification_center.addObserver_selector_name_object_(
                self,
                "applicationWillTerminate:",
                "NSApplicationWillTerminateNotification",
                None,
            )
        )

        # Set accessibility
        self.window.setAccessibilityLabel_("Applio Dashboard")
        self.window.setAccessibilityHelp_(
            "Monitor active training and inference processes"
        )

    def _create_sidebar(self):
        """Create the process list sidebar (initially hidden).

        Shows active and recent processes in an NSTableView.
        """
        # Header height at top of sidebar
        header_height = 24

        # Sidebar container (left side) - positioned below title bar with room for header
        # Account for title bar height (~28px) and header (24px) in the frame
        sidebar_frame = NSMakeRect(
            0, 0, SIDEBAR_WIDTH, DASHBOARD_HEIGHT - 28 - header_height
        )
        self.sidebar_scroll = NSScrollView.alloc().initWithFrame_(sidebar_frame)
        self.sidebar_scroll.setAutohidesScrollers_(True)
        self.sidebar_scroll.setBorderType_(0)  # No border
        self.sidebar_scroll.setHasVerticalScroller_(True)
        self.sidebar_scroll.setAccessibilityLabel_("Process list sidebar")
        self.sidebar_scroll.setAccessibilityHelp_("List of active and recent processes")

        # Create table view
        self.process_table = NSTableView.alloc().init()
        self.process_table.setDataSource_(self)
        self.process_table.setDelegate_(self)
        self.process_table.setHeaderView_(None)  # No header
        self.process_table.setRowHeight_(36)
        self.process_table.setSelectionHighlightStyle_(
            1
        )  # NSTableViewSelectionHighlightStyleSourceList
        self.process_table.setAccessibilityLabel_("Process list")
        self.process_table.setAllowsEmptySelection_(True)
        self.process_table.setAllowsMultipleSelection_(False)

        # Create single column
        column = NSTableColumn.alloc().initWithIdentifier_("process")
        column.setWidth_(SIDEBAR_WIDTH - 20)
        column.setEditable_(False)
        self.process_table.addTableColumn_(column)

        # Set as document view
        self.sidebar_scroll.setDocumentView_(self.process_table)
        self.window.contentView().addSubview_(self.sidebar_scroll)

        # Initially hidden (shown when active)
        self.sidebar_scroll.setHidden_(True)

        # Section header: "ACTIVE" - positioned at top, above sidebar
        self.active_header = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                8,
                DASHBOARD_HEIGHT - 28 - header_height,
                SIDEBAR_WIDTH - 16,
                header_height,
            )
        )
        self.active_header.setStringValue_("ACTIVE")
        self.active_header.setFont_(
            NSFont.systemFontOfSize_weight_(11, NSFontWeightSemibold)
        )
        self.active_header.setTextColor_(NSColor.secondaryLabelColor())
        self.active_header.setBezeled_(False)
        self.active_header.setDrawsBackground_(False)
        self.active_header.setEditable_(False)
        self.active_header.setAlignment_(NSCenterTextAlignment)
        self.window.contentView().addSubview_(self.active_header)
        self.active_header.setHidden_(True)

    def _create_detail_panel(self):
        """Create the detail panel for selected process.

        Shows process name, status, progress bar, log output, and ETA.
        Positioned on the right side, occupying remaining width after sidebar.
        """
        panel_x = SIDEBAR_WIDTH
        panel_width = DASHBOARD_WIDTH - SIDEBAR_WIDTH

        # Detail panel container
        detail_frame = NSMakeRect(panel_x, 0, panel_width, DASHBOARD_HEIGHT - 28)
        self.detail_panel = NSBox.alloc().initWithFrame_(detail_frame)
        self.detail_panel.setBoxType_(NSBoxPrimary)
        self.detail_panel.setBorderType_(0)  # No border
        # NSBox defaults its title to "Title" — suppress it (NSNoTitle) so the
        # panel doesn't render a stray "Title" caption.
        self.detail_panel.setTitlePosition_(0)
        self.detail_panel.setContentView_(NSView.alloc().init())
        self.detail_panel.setAccessibilityLabel_("Process detail panel")
        self.window.contentView().addSubview_(self.detail_panel)

        # Process name label
        name_y = DASHBOARD_HEIGHT - 28 - 40
        self.detail_name = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, name_y, panel_width - 32, 24)
        )
        self.detail_name.setFont_(
            NSFont.systemFontOfSize_weight_(18, NSFontWeightSemibold)
        )
        self.detail_name.setBezeled_(False)
        self.detail_name.setDrawsBackground_(False)
        self.detail_name.setEditable_(False)
        self.detail_name.setStringValue_("Select a process")
        self.detail_name.setAccessibilityLabel_("Process name")
        self.detail_panel.contentView().addSubview_(self.detail_name)

        # Status/phase label
        status_y = name_y - 30
        self.detail_status = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, status_y, panel_width - 32, 20)
        )
        self.detail_status.setFont_(NSFont.systemFontOfSize_(13))
        self.detail_status.setTextColor_(NSColor.secondaryLabelColor())
        self.detail_status.setBezeled_(False)
        self.detail_status.setDrawsBackground_(False)
        self.detail_status.setEditable_(False)
        self._set_detail_status("No process selected")
        self.detail_status.setAccessibilityLabel_("Process status")
        self.detail_panel.contentView().addSubview_(self.detail_status)

        # Progress bar
        progress_y = status_y - 30
        self.detail_progress = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(16, progress_y, panel_width - 32, 20)
        )
        self.detail_progress.setStyle_(NSProgressIndicatorBarStyle)
        self.detail_progress.setMinValue_(0)
        self.detail_progress.setMaxValue_(100)
        self.detail_progress.setIndeterminate_(False)
        self.detail_progress.setDoubleValue_(0)
        self.detail_progress.setAccessibilityLabel_("Progress indicator")
        self.detail_panel.contentView().addSubview_(self.detail_progress)

        # Progress text (percentage)
        progress_text_y = progress_y - 20
        self.detail_progress_text = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, progress_text_y, panel_width - 32, 16)
        )
        self.detail_progress_text.setFont_(NSFont.systemFontOfSize_(12))
        self.detail_progress_text.setAlignment_(NSCenterTextAlignment)
        self.detail_progress_text.setBezeled_(False)
        self.detail_progress_text.setDrawsBackground_(False)
        self.detail_progress_text.setEditable_(False)
        self.detail_progress_text.setStringValue_("0%")
        self.detail_progress_text.setAccessibilityLabel_("Progress percentage")
        self.detail_panel.contentView().addSubview_(self.detail_progress_text)

        # --- Training metrics (parsed live from the run's training.log) ---
        # Best epoch + its loss (green headline - the number that matters for inference)
        best_y = (
            progress_text_y - 8 - 20
        )  # 8px gap below progress text; label is 20px tall
        self.detail_best_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, best_y, panel_width - 32, 20)
        )
        self.detail_best_label.setFont_(NSFont.boldSystemFontOfSize_(13))
        self.detail_best_label.setTextColor_(NSColor.systemGreenColor())
        self.detail_best_label.setBezeled_(False)
        self.detail_best_label.setDrawsBackground_(False)
        self.detail_best_label.setEditable_(False)
        self.detail_best_label.setStringValue_("Best: --")
        self.detail_best_label.setAccessibilityLabel_("Best epoch and its loss")
        self.detail_best_label.setAccessibilityHelp_(
            "Epoch with the lowest generator loss so far - use this checkpoint for inference"
        )
        self.detail_panel.contentView().addSubview_(self.detail_best_label)

        # Current metrics: epoch/total, step, speed (per epoch)
        current_y = best_y - 6 - 16  # 6px gap below the best label; label is 16px tall
        self.detail_current_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, current_y, panel_width - 32, 16)
        )
        self.detail_current_label.setFont_(
            NSFont.systemFontOfSize_weight_(11, NSFontWeightMedium)
        )
        self.detail_current_label.setTextColor_(NSColor.labelColor())
        self.detail_current_label.setBezeled_(False)
        self.detail_current_label.setDrawsBackground_(False)
        self.detail_current_label.setEditable_(False)
        self.detail_current_label.setStringValue_("--")
        self.detail_current_label.setAccessibilityLabel_(
            "Current epoch, step and training speed"
        )
        self.detail_panel.contentView().addSubview_(self.detail_current_label)

        # --- Loss-vs-epoch chart (Feature 3) ---
        # Sits between the current-metrics label and the log: a compact line
        # chart of the running best-loss per evaluated epoch. Hidden by default
        # (shown in _update_detail_panel when there's a selected process).
        chart_top = current_y - 8  # 8px gap below the current-metrics label
        chart_height = LossChartView.CHART_HEIGHT
        chart_y = chart_top - chart_height
        self.detail_chart = LossChartView.alloc().initWithFrame_(
            NSMakeRect(16, chart_y, panel_width - 32, chart_height)
        )
        self.detail_chart.setAccessibilityLabel_("Training loss chart")
        self.detail_chart.setAccessibilityHelp_(
            "Line chart of the running best generator loss per epoch"
        )
        self.detail_panel.contentView().addSubview_(self.detail_chart)

        # Log output (NSTextView in NSScrollView) - sized below the chart.
        # Bottom margin leaves room for the ETA line + action bar (Feature 4).
        log_y = 68
        log_top = chart_y - 8  # 8px gap below the chart
        log_height = max(120, log_top - log_y)
        log_frame = NSMakeRect(16, log_y, panel_width - 32, log_height)
        self.detail_log_scroll = NSScrollView.alloc().initWithFrame_(log_frame)
        self.detail_log_scroll.setBorderType_(NSBezelBorder)
        self.detail_log_scroll.setHasVerticalScroller_(True)
        self.detail_log_scroll.setAccessibilityLabel_("Log output")

        self.detail_log_view = NSTextView.alloc().init()
        self.detail_log_view.setFont_(NSFont.fontWithName_size_("Menlo", 11))
        self.detail_log_view.setEditable_(False)
        self.detail_log_view.setString_("Select a process to view logs")
        self.detail_log_view.setAccessibilityLabel_("Log output")

        self.detail_log_scroll.setDocumentView_(self.detail_log_view)
        self.detail_panel.contentView().addSubview_(self.detail_log_scroll)

        # Estimated time remaining (sits between the log and the action bar)
        eta_y = 46
        self.detail_eta = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, eta_y, panel_width - 32, 14)
        )
        self.detail_eta.setFont_(NSFont.systemFontOfSize_(12))
        self.detail_eta.setTextColor_(NSColor.secondaryLabelColor())
        self.detail_eta.setBezeled_(False)
        self.detail_eta.setDrawsBackground_(False)
        self.detail_eta.setEditable_(False)
        self.detail_eta.setStringValue_("Estimated time: --")
        self.detail_eta.setAccessibilityLabel_("Time remaining")
        self.detail_panel.contentView().addSubview_(self.detail_eta)

        # --- Action bar (Feature 4): Stop / Pause-Resume / Reveal Log / Open Log ---
        # Reuses ProgressWindowController's POSIX primitives (verify_process_identity,
        # psutil.terminate, os.kill SIGSTOP/SIGCONT) and NSWorkspace for reveal/open.
        # Stop/Pause are gated on a live pid in _update_detail_panel; Reveal/Open
        # work for historical processes too (they just open the log path).
        action_y = 14
        action_h = 28
        action_gap = 8
        action_left = 16
        action_total_w = panel_width - 32
        actions = [
            ("stop_btn", "Stop", "stopProcess:", "Stop the process (SIGTERM)"),
            (
                "pause_btn",
                "Pause",
                "togglePauseProcess:",
                "Pause or resume the process",
            ),
            ("reveal_btn", "Reveal Log", "revealLog:", "Reveal the log file in Finder"),
            ("open_btn", "Open Log", "openLog:", "Open the log file"),
        ]
        n = len(actions)
        btn_w = (action_total_w - action_gap * (n - 1)) // n
        for i, (attr, title, action, help_text) in enumerate(actions):
            bx = action_left + i * (btn_w + action_gap)
            btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(bx, action_y, btn_w, action_h)
            )
            btn.setTitle_(title)
            btn.setBezelStyle_(1)  # NSRoundedBezelStyle
            btn.setTarget_(self)
            btn.setAction_(action)
            btn.setAccessibilityLabel_(title)
            btn.setAccessibilityHelp_(help_text)
            setattr(self, attr, btn)
            self.detail_panel.contentView().addSubview_(btn)

        # Key-view loop (Phase 4 a11y), set ONCE here — _create_sidebar (and
        # with it process_table) runs before _create_detail_panel, so all five
        # views exist by this point. Tab out of the runs list walks the action
        # bar and returns to the list: a keyboard user can always LEAVE the
        # table (a list-only focus loop is the classic table a11y trap).
        self.process_table.setNextKeyView_(self.stop_btn)
        self.stop_btn.setNextKeyView_(self.pause_btn)
        self.pause_btn.setNextKeyView_(self.reveal_btn)
        self.reveal_btn.setNextKeyView_(self.open_btn)
        self.open_btn.setNextKeyView_(self.process_table)

        # Initially hidden
        self.detail_panel.setHidden_(True)

    def _set_detail_status(self, display):
        """Single choke point for every detail-status write.

        Writes the dashboard's status line. (The dashboard has no status
        badge — that is a ProgressWindowController element; the badge branch
        that used to live here never fired and was removed.)
        """
        if hasattr(self, "detail_status") and self.detail_status:
            self.detail_status.setStringValue_(display)

    def _update_detail_panel(self):
        """Update detail panel with selected process info.

        Handles edge cases:
        - Process ends mid-viewing (selected process no longer in active list)
        - Log file deleted while viewing
        - Null/missing UI elements
        """
        import applio_i18n

        _t = applio_i18n.native_tr

        # Safety check: ensure window still exists
        if not self.window:
            return

        # Hide detail panel if no process selected
        if not self._selected_process:
            if hasattr(self, "detail_panel") and self.detail_panel:
                self.detail_panel.setHidden_(True)
            # In idle, bring the placeholder back so the area isn't blank after
            # the user deselects a history row.
            if (
                self._current_state == "idle"
                and hasattr(self, "placeholder_view")
                and self.placeholder_view
            ):
                self.placeholder_view.setHidden_(False)
            return

        proc = self._selected_process

        # Ensure detail panel exists
        if not hasattr(self, "detail_panel") or not self.detail_panel:
            return

        # Check if selected process is still valid (may have ended)
        # Look up fresh process info from state
        proc_type = proc.get("type", "Unknown")
        fresh_procs = get_active_processes()
        fresh_info = None
        for p in fresh_procs:
            if p.get("type") == proc_type:
                fresh_info = p
                break

        # If process ended mid-viewing, check if we have history info
        if not fresh_info:
            # Process no longer active - check if we should show "completed" status
            recent = get_recent_processes(limit=5)
            for r in recent:
                if r.get("type") == proc_type and r.get("model_name") == proc.get(
                    "model_name"
                ):
                    # Found in history - show completion info
                    fresh_info = r
                    logging.info(
                        f"[Dashboard] Process {proc_type} ended mid-viewing, showing from history"
                    )
                    break

        # Use fresh info if available, otherwise fall back to original
        if fresh_info:
            proc = fresh_info

        # Remember the resolved proc so the action-bar handlers (Feature 4) act
        # on the process actually being displayed, not a stale selection.
        self._current_proc = proc

        # Batch inference has no subprocess - it runs in the GUI process, so it
        # has no PID/log/training.log. Branch off the subprocess codepath and
        # render onto the SAME outlets the training path uses. Re-read the LIVE
        # record each tick so the bar climbs every ~1s (the table rebuild only
        # refreshes the row every ~3s).
        if proc.get("_is_inference") or proc.get("type") == "inference":
            # A completed/historical inference row comes from process_history
            # (type=inference) without the _is_inference marker the live synth
            # sets; tag it so the renderer + action bar treat it as inference.
            if not proc.get("_is_inference"):
                proc = dict(proc)
                proc["_is_inference"] = True
                self._current_proc = proc
            live = _read_inference_progress()
            if live and live.get("status") in ("running", "cancelling"):
                proc = dict(proc)
                proc.update(live)
                proc["_is_inference"] = True
                self._current_proc = proc
            self._render_inference_detail(proc)
            return

        try:
            self.detail_panel.setHidden_(False)

            # A process is selected for the detail view -> hide the idle
            # placeholder so the two never overlap.
            if hasattr(self, "placeholder_view") and self.placeholder_view:
                self.placeholder_view.setHidden_(True)

            # Update name (with null check)
            model_name = proc.get("model_name", "")
            if hasattr(self, "detail_name") and self.detail_name:
                if model_name:
                    self.detail_name.setStringValue_(
                        f"{proc_type.capitalize()}: {model_name}"
                    )
                else:
                    self.detail_name.setStringValue_(proc_type.capitalize())

            # Update status (with null check)
            status = proc.get("status", "running")
            phase = proc.get("phase", "")
            if hasattr(self, "detail_status") and self.detail_status:
                if phase:
                    status_text = f"{status.title()} - {phase}"
                else:
                    status_text = status.title()
                self._set_detail_status(status_text)

            # --- Real training metrics, parsed live from the run's training.log ---
            # training.log holds epoch/step/loss/speed per epoch. The legacy
            # proc "progress"/"eta" fields were never written mid-run, so we
            # derive progress (epoch-fraction) and ETA here instead. For
            # non-training processes (or a missing/unparseable log) this
            # degrades gracefully to "--" - never crashes the dashboard.
            metrics = self._parse_training_metrics(proc)
            total_epoch = proc.get("total_epoch")
            try:
                total_epoch = (
                    int(total_epoch) if total_epoch not in (None, "") else None
                )
            except (ValueError, TypeError):
                total_epoch = None

            # Progress bar -> epoch-fraction (current_epoch / total_epoch)
            if hasattr(self, "detail_progress") and self.detail_progress:
                cur_ep = metrics.get("epoch") if metrics else None
                if cur_ep and total_epoch and total_epoch > 0:
                    frac = min(
                        1.0, cur_ep / total_epoch
                    )  # clamp at 100% if epoch overshoots
                    self.detail_progress.stopAnimation_(None)
                    self.detail_progress.setIndeterminate_(False)
                    self.detail_progress.setDoubleValue_(frac * 100.0)
                    # Template text, not a bare percentage: VoiceOver reads
                    # this verbatim, so it must say WHAT is at that percentage.
                    self.detail_progress.setAccessibilityValue_(
                        f"{_t('Epoch')} {cur_ep} of {total_epoch}, "
                        f"{int(frac * 100)} {_t('percent')}"
                    )
                    pct_txt = f"Epoch {cur_ep}/{total_epoch}  ({int(frac * 100)}%)"
                elif status == "running":
                    # No metrics yet (just started) or non-training: spin to
                    # show activity. startAnimation_ is required for an
                    # indeterminate bar to actually move. The AX value is
                    # RESET here — without this it kept the last known
                    # percentage while the bar spun (stale-value bug).
                    self.detail_progress.setDoubleValue_(0.0)
                    self.detail_progress.setIndeterminate_(True)
                    self.detail_progress.startAnimation_(None)
                    self.detail_progress.setAccessibilityValue_(
                        _t("Working, no metrics yet")
                    )
                    pct_txt = "--"
                else:
                    # Not running and no metrics -> empty bar
                    self.detail_progress.stopAnimation_(None)
                    self.detail_progress.setIndeterminate_(False)
                    self.detail_progress.setDoubleValue_(0.0)
                    pct_txt = "--"
                if hasattr(self, "detail_progress_text") and self.detail_progress_text:
                    self.detail_progress_text.setStringValue_(pct_txt)

            # Re-assert the training labels: an inference row may have
            # repurposed these outlets, so every training write restores them.
            if hasattr(self, "detail_best_label") and self.detail_best_label:
                self.detail_best_label.setAccessibilityLabel_("Best epoch and its loss")
            if hasattr(self, "detail_current_label") and self.detail_current_label:
                self.detail_current_label.setAccessibilityLabel_(
                    "Current epoch, step and training speed"
                )
            # Best epoch + loss headline (green) - the inference-relevant number
            if hasattr(self, "detail_best_label") and self.detail_best_label:
                if metrics and metrics.get("best_epoch") is not None:
                    self.detail_best_label.setStringValue_(
                        f"Best: Epoch {metrics['best_epoch']}  |  Loss {metrics['best_loss']:.3f}"
                    )
                    self.detail_best_label.setHidden_(False)
                elif metrics:
                    # Training underway but no evaluation yet (first epoch)
                    self.detail_best_label.setStringValue_(
                        "Best epoch: waiting for first evaluation…"
                    )
                    self.detail_best_label.setHidden_(False)
                else:
                    # Non-training process, or no parseable log -> hide the metric
                    self.detail_best_label.setHidden_(True)

            # Current epoch/total, step, speed (per epoch)
            if hasattr(self, "detail_current_label") and self.detail_current_label:
                if metrics:
                    cur_ep = metrics.get("epoch")
                    ep_part = (
                        f"Epoch {cur_ep}/{total_epoch}"
                        if (cur_ep and total_epoch)
                        else (f"Epoch {cur_ep}" if cur_ep else None)
                    )
                    step = metrics.get("step")
                    spd = metrics.get("training_speed")
                    parts = [
                        p
                        for p in (
                            ep_part,
                            f"Step {step:,}" if step is not None else None,
                            f"Speed {spd}/ep" if spd else None,
                        )
                        if p
                    ]
                    self.detail_current_label.setStringValue_(
                        "  |  ".join(parts) if parts else "--"
                    )
                    self.detail_current_label.setHidden_(False)
                else:
                    self.detail_current_label.setHidden_(True)

            # ETA -> derived: (total_epoch - current_epoch) * seconds_per_epoch
            if hasattr(self, "detail_eta") and self.detail_eta:
                eta_str = self._derive_eta(metrics, total_epoch)
                self.detail_eta.setStringValue_(f"Estimated time: {eta_str}")

            # Loss-vs-epoch chart (Feature 3). Historical processes plot from
            # the snapshot; active ones from the live log. set_points handles
            # the <2-points placeholder, so this never throws.
            if hasattr(self, "detail_chart") and self.detail_chart:
                try:
                    self.detail_chart.set_points(self._collect_epoch_points(proc))
                except Exception as e:
                    logging.debug(f"[Dashboard] chart update failed: {e}")

            # Action-bar enablement (Feature 4). Stop/Pause require a live,
            # identity-verified pid; the Pause label reflects the live status
            # (queried, not tracked, so it stays correct across process switches).
            # Reveal/Open are enabled whenever a log path resolves (historical too).
            self._update_action_bar(proc)

            # Update log (last 20 lines) - handle file deletion
            self._update_log_display(proc)

        except Exception as e:
            logging.warning(f"[Dashboard] Error updating detail panel: {e}")

    def _update_log_display(self, proc: dict):
        """Update log display with error handling for missing/deleted files.

        Args:
            proc: Process info dict with log_path or log_file key
        """
        if not hasattr(self, "detail_log_view") or not self.detail_log_view:
            return

        log_path = proc.get("log_path") or proc.get("log_file")

        # Handle missing log path
        if not log_path:
            self.detail_log_view.setString_("No log file path available")
            return

        # Handle deleted log file
        if not os.path.exists(log_path):
            self.detail_log_view.setString_(f"Log file no longer exists:\n{log_path}")
            logging.debug(f"[Dashboard] Log file deleted: {log_path}")
            return

        # Handle unreadable log file
        if not os.access(log_path, os.R_OK):
            self.detail_log_view.setString_(f"Log file not readable:\n{log_path}")
            logging.warning(f"[Dashboard] Log file not readable: {log_path}")
            return

        try:
            # Read with size limit to prevent memory issues
            max_size = 1024 * 1024  # 1MB max
            file_size = os.path.getsize(log_path)

            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                if file_size > max_size:
                    # Read only last portion of large files
                    f.seek(file_size - max_size)
                    content = f.read()
                    # Skip partial first line
                    first_newline = content.find("\n")
                    if first_newline >= 0:
                        content = content[first_newline + 1 :]
                else:
                    content = f.read()

                lines = content.splitlines()
                last_lines = lines[-20:] if len(lines) > 20 else lines
                log_text = "\n".join(last_lines)
                self.detail_log_view.setString_(log_text)

                # Scroll to show latest content (with null check)
                if hasattr(self, "detail_log_view") and self.detail_log_view:
                    text_length = len(log_text)
                    self.detail_log_view.scrollRangeToVisible_(NSRange(text_length, 0))
        except PermissionError as e:
            logging.warning(f"[Dashboard] Permission denied reading log: {e}")
            self.detail_log_view.setString_("Permission denied reading log file")
        except OSError as e:
            logging.warning(f"[Dashboard] OS error reading log: {e}")
            self.detail_log_view.setString_("Error reading log file")
        except Exception as e:
            logging.warning(f"[Dashboard] Unexpected error reading log: {e}")
            self.detail_log_view.setString_("Unexpected error reading log file")

    def _render_inference_detail(self, proc):
        """Render a synthesized batch-inference proc onto the detail panel.

        Maps inference progress onto the SAME outlets the training path uses
        (outlet names confirmed in _create_detail_panel): the progress bar climbs
        with processed/total, the "best" label carries speed, the "current" label
        carries converted/skipped/current file, and the log view carries a
        one-shot status summary (the batch has no training.log). For a
        terminal/historical inference row — history entries are wired in B4 —
        the caller lets ``proc`` keep the stored terminal stats so
        compute_inference_stats uses ended_at.
        """
        from applio_inference_stats import compute_inference_stats

        import applio_i18n

        _t = applio_i18n.native_tr

        try:
            self.detail_panel.setHidden_(False)
            if hasattr(self, "placeholder_view") and self.placeholder_view:
                self.placeholder_view.setHidden_(True)
            model_name = proc.get("model_name", "")
            if hasattr(self, "detail_name") and self.detail_name:
                self.detail_name.setStringValue_(
                    f"Inference: {model_name}" if model_name else "Inference"
                )
            status = proc.get("status", "running")
            label = {"running": _t("Running"), "cancelling": _t("Stopping…")}.get(
                status, status.title()
            )
            if hasattr(self, "detail_status") and self.detail_status:
                self._set_detail_status(label)
            # Normalize a history entry for compute_inference_stats: history
            # rows store started_at/completed_at as ISO strings and omit
            # processed/ended_at. Work on a copy so the stored entry is untouched.
            proc = dict(proc)
            if not proc.get("processed"):
                proc["processed"] = (proc.get("converted", 0) or 0) + (
                    proc.get("skipped", 0) or 0
                )
            import datetime as _inf_dt

            _sa = proc.get("started_at")
            if isinstance(_sa, str):
                try:
                    proc["started_at"] = _inf_dt.datetime.fromisoformat(_sa).timestamp()
                except ValueError:
                    proc["started_at"] = time.time()
            if "ended_at" not in proc:
                _ca = proc.get("completed_at")
                if isinstance(_ca, str):
                    try:
                        proc["ended_at"] = _inf_dt.datetime.fromisoformat(
                            _ca
                        ).timestamp()
                    except ValueError:
                        pass
            stats = compute_inference_stats(proc, now=time.time())
            total = proc.get("total", 0) or 0
            processed = proc.get("processed", 0) or 0
            converted = proc.get("converted", 0) or 0
            skipped = proc.get("skipped", 0) or 0
            if hasattr(self, "detail_progress") and self.detail_progress:
                self.detail_progress.stopAnimation_(None)
                self.detail_progress.setIndeterminate_(False)
                self.detail_progress.setDoubleValue_(stats["pct"])
                # Template text, not a bare percentage (matches the training
                # branch): VoiceOver reads this verbatim.
                self.detail_progress.setAccessibilityValue_(
                    f"{processed} of {total} {_t('files')}, "
                    f"{int(stats['pct'])} {_t('percent')}"
                )
            if hasattr(self, "detail_progress_text") and self.detail_progress_text:
                self.detail_progress_text.setStringValue_(
                    f"{processed}/{total} files ({stats['pct']}%)"
                )
            # Inference repurposes the training outlets: re-label them for
            # VoiceOver before writing values (the training render path
            # re-asserts its own labels, so switching row types self-corrects).
            if hasattr(self, "detail_best_label") and self.detail_best_label:
                self.detail_best_label.setAccessibilityLabel_("Conversion speed")
            if hasattr(self, "detail_current_label") and self.detail_current_label:
                self.detail_current_label.setAccessibilityLabel_(
                    "Converted, skipped and current file"
                )
            if hasattr(self, "detail_current_label") and self.detail_current_label:
                cur = proc.get("current_file", "")
                self.detail_current_label.setStringValue_(
                    f"Converted {converted}  |  Skipped {skipped}"
                    + (f"  |  File: {cur}" if cur else "")
                )
                self.detail_current_label.setHidden_(False)
            if hasattr(self, "detail_best_label") and self.detail_best_label:
                self.detail_best_label.setStringValue_(
                    f"Speed {stats['speed']} files/min"
                )
                self.detail_best_label.setHidden_(False)
            if hasattr(self, "detail_eta") and self.detail_eta:
                self.detail_eta.setStringValue_(f"Estimated time: {stats['eta']}s")
            if hasattr(self, "detail_chart") and self.detail_chart:
                self.detail_chart.setHidden_(True)  # no loss curve for inference
            if hasattr(self, "detail_log_view") and self.detail_log_view:
                self.detail_log_view.setString_(
                    f"Status: {label}\n{converted} converted, {skipped} skipped of {total}.\n"
                    f"Speed {stats['speed']} files/min, elapsed {stats['elapsed']}s."
                )
            self._update_action_bar(proc)
        except Exception as e:
            logging.warning(f"[Dashboard] inference detail render failed: {e}")

    # =================================================================
    # Action bar (Feature 4)
    # =================================================================

    def _resolve_log_path(self, proc):
        """Resolve the log file path for a proc (log_file or log_path), or None.

        For an inference proc, Reveal/Open should target the batch's output
        folder (a directory, not a file); realpath + isdir guard so we never
        hand a stale/missing path to NSWorkspace.
        """
        if not proc:
            return None
        if proc.get("_is_inference"):
            out = proc.get("output_folder")
            if out:
                real = os.path.realpath(out)
                if os.path.isdir(real):
                    return real
            return None
        return proc.get("log_file") or proc.get("log_path")

    def _current_pid(self, proc):
        """Return the proc's pid if identity-verified as still alive, else None.

        Reuses verify_process_identity (shared with ProgressWindowController) so a
        recycled PID is never mistaken for our process.
        """
        pid = proc.get("pid") if proc else None
        started_at = proc.get("started_at") if proc else None
        if pid and verify_process_identity(pid, started_at):
            return pid
        return None

    def _annotate_pause_state(self, procs):
        """Stamp live SIGSTOP state on each proc (JSON status stays 'running').

        Called once per list rebuild (refresh_process_list/update_process_list)
        so the row builder can spell out Paused vs Running without probing
        psutil per visible cell on every repaint. Procs without a live pid —
        e.g. the synthesized inference proc — stay False (an in-process batch
        cannot be SIGSTOPped, so "Running" is the truthful word).
        """
        for proc in procs:
            proc["_ps_stopped"] = False
            pid = self._current_pid(proc)
            if pid and PSUTIL_AVAILABLE:
                try:
                    proc["_ps_stopped"] = (
                        psutil.Process(pid).status() == psutil.STATUS_STOPPED
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

    def _update_action_bar(self, proc):
        """Enable/disable action buttons + set the Pause label for the shown proc.

        Stop/Pause need a live pid; the Pause label reflects the live process
        status (STATUS_STOPPED) queried from psutil — robust across process
        switches, no stale flag. Reveal/Open are enabled whenever a log path
        resolves (works for historical processes too).

        REGRESSION GUARD: inference procs have no pid, so the pid-based logic
        below would DISABLE Stop and break the cooperative cancel. Branch first.
        """
        import applio_i18n

        _t = applio_i18n.native_tr

        if proc is not None and proc.get("_is_inference"):
            is_running = proc.get("status") in ("running", "cancelling")
            has_output = bool(proc.get("output_folder"))
            if hasattr(self, "stop_btn") and self.stop_btn:
                self.stop_btn.setEnabled_(is_running)
            if hasattr(self, "pause_btn") and self.pause_btn:
                # Pause is meaningless for an in-process batch (no PID to SIGSTOP)
                self.pause_btn.setEnabled_(False)
                self.pause_btn.setTitle_(_t("Pause"))
                self.pause_btn.setAccessibilityLabel_(_t("Pause"))
            if hasattr(self, "reveal_btn") and self.reveal_btn:
                self.reveal_btn.setEnabled_(has_output)
            if hasattr(self, "open_btn") and self.open_btn:
                self.open_btn.setEnabled_(has_output)
            return

        pid = self._current_pid(proc)
        pid_alive = bool(pid)
        is_stopped = False
        if pid_alive and PSUTIL_AVAILABLE:
            try:
                is_stopped = psutil.Process(pid).status() == psutil.STATUS_STOPPED
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                is_stopped = False

        if hasattr(self, "stop_btn") and self.stop_btn:
            self.stop_btn.setEnabled_(pid_alive)
        if hasattr(self, "pause_btn") and self.pause_btn:
            self.pause_btn.setEnabled_(pid_alive)
            new_title = _t("Resume") if is_stopped else _t("Pause")
            self.pause_btn.setTitle_(new_title)
            self.pause_btn.setAccessibilityLabel_(new_title)

        has_log = bool(self._resolve_log_path(proc))
        if hasattr(self, "reveal_btn") and self.reveal_btn:
            self.reveal_btn.setEnabled_(has_log)
        if hasattr(self, "open_btn") and self.open_btn:
            self.open_btn.setEnabled_(has_log)

    def stopProcess_(self, sender):
        """Stop (SIGTERM/terminate) the selected active process. Gated on a live pid.

        For an inference proc there is no PID to kill - the batch runs in the
        GUI process. Cooperatively cancel it by writing the cancel flag the
        patcher's loop checks between files. MUST branch BEFORE the pid
        early-return (inference procs have no pid).
        """
        import applio_i18n

        _t = applio_i18n.native_tr

        proc = getattr(self, "_current_proc", None) or self._selected_process
        if proc is not None and proc.get("_is_inference"):
            if proc.get("status") not in ("running", "cancelling"):
                return
            try:
                data_dir = os.path.dirname(get_process_state_path())
                flag = os.path.join(data_dir, "inference_cancel.flag")
                os.makedirs(os.path.dirname(flag), exist_ok=True)
                Path(flag).touch()
                if hasattr(self, "detail_status") and self.detail_status:
                    self._set_detail_status(_t("Stopping…"))
                if hasattr(self, "stop_btn") and self.stop_btn:
                    self.stop_btn.setEnabled_(False)
                logging.info("[Dashboard] Wrote inference cancel flag")
            except OSError as e:
                logging.warning(
                    f"[Dashboard] Could not write inference cancel flag: {e}"
                )
            return
        pid = self._current_pid(proc)
        if not pid:
            logging.info("[Dashboard] Stop requested but no live process")
            return
        if not PSUTIL_AVAILABLE:
            logging.warning("[Dashboard] Cannot stop - psutil not available")
            return
        try:
            psutil.Process(pid).terminate()
            logging.info(
                f"[Dashboard] Sent terminate to pid {pid} ({proc.get('type', '?')})"
            )
            if hasattr(self, "stop_btn") and self.stop_btn:
                self.stop_btn.setEnabled_(False)
            if hasattr(self, "pause_btn") and self.pause_btn:
                self.pause_btn.setEnabled_(False)
            if hasattr(self, "detail_status") and self.detail_status:
                self._set_detail_status(_t("Stopping…"))
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError) as e:
            logging.warning(f"[Dashboard] Could not stop process: {e}")

    def togglePauseProcess_(self, sender):
        """Pause/Resume (SIGSTOP/SIGCONT) the selected active process.

        Direction is derived from the live status (STATUS_STOPPED -> resume),
        so the action is correct even if the label/view is momentarily stale.
        """
        import applio_i18n

        _t = applio_i18n.native_tr

        proc = getattr(self, "_current_proc", None) or self._selected_process
        pid = self._current_pid(proc)
        if not pid or not PSUTIL_AVAILABLE:
            return
        try:
            is_stopped = psutil.Process(pid).status() == psutil.STATUS_STOPPED
            os.kill(pid, signal.SIGCONT if is_stopped else signal.SIGSTOP)
            now_stopped = not is_stopped
            if sender is not None and hasattr(sender, "setTitle_"):
                new_title = _t("Resume") if now_stopped else _t("Pause")
                sender.setTitle_(new_title)
                sender.setAccessibilityLabel_(new_title)
            logging.info(
                f"[Dashboard] Process pid {pid} {'paused' if now_stopped else 'resumed'}"
            )
            if hasattr(self, "detail_status") and self.detail_status:
                self._set_detail_status(_t("Paused") if now_stopped else _t("Running"))
        except (ProcessLookupError, PermissionError, OSError) as e:
            logging.warning(f"[Dashboard] Could not toggle pause: {e}")

    def revealLog_(self, sender):
        """Reveal the log file in Finder (NSWorkspace). Works for historical too."""
        proc = getattr(self, "_current_proc", None) or self._selected_process
        path = self._resolve_log_path(proc)
        if not path or not os.path.exists(path):
            logging.info("[Dashboard] Reveal requested but log path missing")
            return
        try:
            NSWorkspace.sharedWorkspace().activateFileViewerSelecting_([path])
        except Exception as e:
            logging.warning(f"[Dashboard] Reveal log failed: {e}")

    def openLog_(self, sender):
        """Open the log file with its default app (NSWorkspace). Works for historical."""
        proc = getattr(self, "_current_proc", None) or self._selected_process
        path = self._resolve_log_path(proc)
        if not path or not os.path.exists(path):
            return
        try:
            NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(path))
        except Exception as e:
            logging.warning(f"[Dashboard] Open log failed: {e}")

    def _parse_training_metrics(self, proc: dict):
        """Parse the latest training status line from a process's training.log.

        Returns the metrics dict {epoch, step, training_speed, best_epoch,
        best_loss, best_step} for the most recent status line, or None when
        there is no log / the process is not training / nothing has been logged
        yet. Delegates the live-log tail-scan to the module-level
        _last_training_metrics helper (shared with the menu's live titles;
        regex via _parse_training_log_line) - frozen-safe, no rvc import.

        For a HISTORICAL (completed) process, prefers the durability snapshot
        stored in its history entry (best_epoch/best_loss/final_epoch written by
        patches/patch_process_tracking.py on completion). This survives a retrain
        that overwrites the per-model training.log — re-parsing the log would
        otherwise show the *new* run's metrics against an old history entry.
        Active processes never carry snapshot fields, so the snapshot branch is
        only taken for genuine history entries.
        """
        # Historical snapshot first (survives retrain / log overwrite).
        if proc.get("best_epoch") is not None and proc.get("best_loss") is not None:
            try:
                return {
                    "epoch": (
                        int(proc.get("final_epoch"))
                        if proc.get("final_epoch") is not None
                        else None
                    ),
                    "step": None,
                    "training_speed": None,
                    "best_epoch": int(proc.get("best_epoch")),
                    "best_loss": float(proc.get("best_loss")),
                    "best_step": None,
                    "from_snapshot": True,
                }
            except (TypeError, ValueError):
                pass  # Malformed snapshot -> fall back to live log parse

        # Live-log tail-scan lives in the module-level _last_training_metrics
        # (shared with the menu's live titles). Keep the dashboard's 1 MB cap
        # — the detail panel refreshes on its ~1 s timer and wants the fuller
        # tail; the menu's default 256 KB is plenty for "epoch N/M".
        return _last_training_metrics(
            proc.get("log_file") or proc.get("log_path"), max_bytes=1024 * 1024
        )

    def _collect_epoch_points(self, proc: dict):
        """Return [(epoch, best_loss), ...] for the loss-vs-epoch chart.

        Historical processes: prefer the snapshot's epoch_points (written by
        patches/patch_process_tracking.py on completion — survives a retrain
        overwriting training.log). Active processes (or an entry with no
        snapshot): re-parse the live training.log for every evaluated epoch
        line via the shared _parse_training_log_line helper. Returns [] when
        there's no parseable data; the chart then shows its placeholder.
        """
        # Historical snapshot first.
        snap_points = proc.get("epoch_points")
        if snap_points:
            out = []
            for p in snap_points:
                try:
                    out.append((int(p[0]), float(p[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            if out:
                return out
        # Active (or no snapshot): scan the live log for EVERY evaluated epoch.
        #
        # The training subprocess redirects stdout+stderr into training.log, so
        # the file is flooded with per-step tqdm progress lines between the
        # sparse per-epoch summary lines (_parse_training_log_line matches). A
        # byte-tail read (the old 1MB cap) therefore only spanned the last few
        # evaluated epochs -- which is why the chart showed ~5 points. Instead we
        # STREAM the whole file line-by-line (low memory: non-matching lines are
        # discarded immediately) and keep every epoch line, capped at the last
        # MAX_EPOCH_POINTS to bound output for pathologically long runs. An I/O
        # guard (MAX_LOG_SCAN_BYTES) bounds disk reads: only the tail of a truly
        # huge log is scanned, which still holds far more than MAX_EPOCH_POINTS
        # evaluated epochs at any realistic step rate.
        log_path = proc.get("log_file") or proc.get("log_path")
        if not log_path:
            return []
        try:
            if not os.path.exists(log_path) or not os.access(log_path, os.R_OK):
                return []
            size = os.path.getsize(log_path)
            points = deque(maxlen=MAX_EPOCH_POINTS)
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                if size > MAX_LOG_SCAN_BYTES:
                    f.seek(size - MAX_LOG_SCAN_BYTES)
                    next(f, None)  # discard the partial first line
                for line in f:
                    parsed = _parse_training_log_line(line)
                    if parsed and parsed.get("best_loss") is not None:
                        points.append((parsed["epoch"], parsed["best_loss"]))
            return list(points)
        except Exception as e:
            logging.debug(f"[Dashboard] epoch-points parse failed: {e}")
            return []

    def _derive_eta(self, metrics, total_epoch):
        """Estimate remaining wall-clock time for a training run.

        ETA = (total_epoch - current_epoch) * seconds_per_epoch, formatted as
        "Xh Ym". Returns "--" when speed or epoch totals are unknown, and "0m"
        once the current epoch reaches/exceeds the target.
        """
        if not metrics:
            return "--"
        cur_ep = metrics.get("epoch")
        speed = metrics.get("training_speed")
        if not cur_ep or not total_epoch or total_epoch <= 0 or not speed:
            return "--"
        secs_per_epoch = self._hms_to_seconds(speed)
        if not secs_per_epoch or secs_per_epoch <= 0:
            return "--"
        remaining = total_epoch - cur_ep
        if remaining <= 0:
            return "0m"
        total_minutes = int((remaining * secs_per_epoch) // 60)
        hours = total_minutes // 60
        mins = total_minutes % 60
        if hours > 0:
            return f"{hours}h {mins}m"
        if mins > 0:
            return f"{mins}m"
        return f"{int(remaining * secs_per_epoch)}s"

    @staticmethod
    def _hms_to_seconds(value):
        """Convert an "H:MM:SS" / "MM:SS" / "SS" training_speed string to seconds.

        Returns None when the value can't be parsed (so ETA can fall back to "--").
        """
        try:
            parts = [int(p) for p in str(value).split(":")]
        except (ValueError, AttributeError):
            return None
        if not parts or any(p < 0 for p in parts):
            return None
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return secs

    # =================================================================
    # NSTableViewDataSource Protocol
    # =================================================================

    def numberOfRowsInTableView_(self, tableView):
        """Return number of rows (active + recent)."""
        return len(self._active_processes) + len(self._recent_processes)

    def tableView_objectValueForTableColumn_row_(self, tableView, column, row):
        """Return cell content for given row.

        Rows spell the state out in words (VoiceOver reads them verbatim —
        symbol prefixes like ●/⏸/✓ are silence or noise). Active rows derive
        Paused from the psutil SIGSTOP probe stamped by _annotate_pause_state
        at list-refresh time (active_processes.json keeps paused jobs
        "running"); history rows use the status stored when the run ended.
        A cancelling batch shows "Stopping" — checked BEFORE the probe,
        which synthesized inference procs force to False (never paused).
        Active rows also embed their live metrics in the cell text (re-test
        round 3: VoiceOver does not reliably speak the row view's
        accessibilityValue) via _row_display_text + _ax_summary_for; history
        rows keep the plain shape (no live metrics).
        """
        import applio_i18n

        _t = applio_i18n.native_tr

        if row < len(self._active_processes):
            proc = self._active_processes[row]
            if proc.get("status") == "cancelling":
                word = _t("Stopping")
            elif proc.get("_ps_stopped"):
                word = _t("Paused")
            else:
                word = _t("Running")
            return _row_display_text(proc, word, summary=self._ax_summary_for(proc))
        else:
            recent_idx = row - len(self._active_processes)
            if recent_idx < len(self._recent_processes):
                proc = self._recent_processes[recent_idx]
                status = (proc.get("status") or "completed").lower()
                # 'failed' and 'error' share ONE translated word so a single
                # override covers both.
                _failed = _t("Failed")
                word = {
                    "completed": _t("Completed"),
                    "failed": _failed,
                    "error": _failed,
                    "cancelled": _t("Cancelled"),
                    "canceled": _t("Cancelled"),
                    "interrupted": _t("Interrupted"),
                }.get(status, status.capitalize() or _t("Completed"))
                return _row_display_text(proc, word)
        return ""

    # =================================================================
    # NSTableViewDelegate Protocol
    # =================================================================

    def tableViewSelectionDidChange_(self, notification):
        """Handle row selection."""
        import applio_i18n

        _t = applio_i18n.native_tr

        row = self.process_table.selectedRow()
        if row < 0:
            self._selected_process = None
            self._update_detail_panel()
            return

        if row < len(self._active_processes):
            proc = self._active_processes[row]
            self._selected_process = proc
            logging.info(f"[Dashboard] Selected active process: {proc.get('type')}")
        else:
            idx = row - len(self._active_processes)
            if idx < len(self._recent_processes):
                proc = self._recent_processes[idx]
                self._selected_process = proc
                logging.info(f"[Dashboard] Selected recent process: {proc.get('type')}")

        # Update detail panel with selected process info
        self._update_detail_panel()

        # Announce the selected row's summary (Phase 4): VoiceOver focus stays
        # on the table after a selection change, so without this the user has
        # no signal that the detail pane refreshed — with THESE numbers. Fires
        # while the DASHBOARD window is focused with native VO focus on the
        # table (the configuration where AX posts demonstrably work); selection
        # changes arrive on the main thread, as AX posts require. Gated on VO
        # running ONLY (auto-a11y, 2026-08-23: the user pressed a key, speech
        # is warranted — no verbosity coupling), and must never break
        # selection: any failure is swallowed.
        try:
            if self._selected_process and voice_over_enabled():
                summary = self._ax_summary_for(self._selected_process)
                note = _t("Detail pane updated.")
                message = f"{summary}. {note}" if summary else note
                applio_a11y.post_announcement(self.process_table, message)
        except Exception as e:
            logging.debug(f"[Dashboard] selection announcement failed: {e}")

    # =================================================================
    # Row accessibility (Phase 4): full per-row values for VoiceOver
    # =================================================================

    def _ax_summary_for(self, proc):
        """Controller-side _row_ax_summary caller (derives the context).

        The module-level builder is pure and I/O-free; only the controller can
        supply what the training shape needs: the run's parsed metrics
        (_parse_training_metrics — live log or history snapshot), the
        int-coerced total_epoch, and the ETA via _derive_eta. Inference and
        unknown types need no context.
        """
        if not proc or (proc.get("type") or "").lower() != "training":
            return _row_ax_summary(proc)
        metrics = self._parse_training_metrics(proc)
        total_epoch = proc.get("total_epoch")
        try:
            total_epoch = int(total_epoch) if total_epoch not in (None, "") else None
        except (ValueError, TypeError):
            total_epoch = None
        return _row_ax_summary(
            proc,
            metrics=metrics,
            total_epoch=total_epoch,
            eta=self._derive_eta(metrics, total_epoch),
        )

    def _apply_row_ax(self, table, row, view=None):
        """Stamp AX label + value on one runs-list row (Phase 4 a11y).

        Belt-and-braces alongside the cell text: since re-test round 3 the
        visible cell text itself carries the live metrics (_row_display_text)
        because VoiceOver does not reliably speak the row view's
        accessibilityValue; this stamp remains the second channel (label +
        value). ``view`` is the freshly added row view from
        the didAddRowView hook; when None (the willDisplayCell path) it is
        resolved via rowViewAtRow_. Skips silently when the row/proc/view
        cannot be resolved or the row view is already stamped (the two hooks
        can both fire for the same row). Re-fires on each 3 s reloadData.
        Non-training/inference rows are left to their cell text (verbatim
        already) — only rows with metrics get a value.
        """
        import applio_i18n

        _t = applio_i18n.native_tr

        try:
            if row < 0:
                return
            n_active = len(self._active_processes)
            if row < n_active:
                proc = self._active_processes[row]
            else:
                idx = row - n_active
                if idx >= len(self._recent_processes):
                    return
                proc = self._recent_processes[idx]
            rv = view if view is not None else table.rowViewAtRow_(row)
            if rv is None:
                return  # row not realized yet; the next display pass retries
            if rv.accessibilityLabel():
                return  # already stamped by the first hook (dedupe)
            ptype = (proc.get("type") or "").lower()
            if ptype == "training":
                prefix = _t("Training run")
            elif ptype == "inference":
                prefix = _t("Inference batch")
            else:
                return
            name = (proc.get("model_name") or "").strip()
            rv.setAccessibilityLabel_(f"{prefix} {name}" if name else prefix)
            rv.setAccessibilityValue_(self._ax_summary_for(proc))
        except Exception as e:
            logging.debug(f"[Dashboard] row AX stamp failed: {e}")

    def tableView_didAddRowView_forRow_(self, table, view, row):
        """Delegate hook (view-based tables): stamp the freshly added row view.

        The runs list is CELL-based, so this is NOT guaranteed to fire here —
        kept because it is the documented channel when the table ever moves to
        view-based rows and it costs nothing; willDisplayCell below is the
        guaranteed cell-based channel.
        """
        self._apply_row_ax(table, row, view=view)

    def tableView_willDisplayCell_forTableColumn_row_(self, table, cell, column, row):
        """Delegate hook (GUARANTEED for cell-based tables): stamp before draw.

        Passes view=None so _apply_row_ax resolves the row view itself; the
        helper's dedupe skips rows the didAddRowView hook already stamped.
        """
        self._apply_row_ax(table, row)

    def refresh_process_list(self):
        """Refresh the process list from current state.

        Handles errors gracefully - on error, keeps existing data.
        """
        try:
            # Subprocess jobs + the synthesized in-app batch, one merge
            # (_merged_live_procs — shared with the Active-Processes menu).
            self._active_processes = _merged_live_procs()
        except Exception as e:
            logging.warning(f"[Dashboard] Could not refresh active processes: {e}")
            # Keep existing data on error

        # Probe SIGSTOP state once per refresh so row cells render truthfully
        # without a psutil call per visible cell (see _annotate_pause_state).
        self._annotate_pause_state(self._active_processes)

        try:
            self._recent_processes = get_recent_processes(limit=5)
        except Exception as e:
            logging.warning(f"[Dashboard] Could not refresh recent processes: {e}")
            # Keep existing data on error

        if hasattr(self, "process_table") and self.process_table:
            try:
                self.process_table.reloadData()
            except Exception as e:
                logging.warning(f"[Dashboard] Could not reload table: {e}")

    def _create_idle_ui(self):
        """Create the idle state UI (placeholder).

        This shows when no processes are active.
        """
        # Placeholder lives in the DETAIL-panel area (right of the sidebar) so
        # the history sidebar can stay visible + selectable in idle. Sizing is
        # relative to content_width, so the centered labels rescale cleanly.
        detail_area_w = DASHBOARD_WIDTH - SIDEBAR_WIDTH
        content_width = detail_area_w - 2 * PADDING
        content_height = 200
        center_y = ((DASHBOARD_HEIGHT - 28) - content_height) // 2

        # Create container box with subtle styling
        self.placeholder_view = NSBox.alloc().initWithFrame_(
            NSMakeRect(SIDEBAR_WIDTH + PADDING, center_y, content_width, content_height)
        )
        self.placeholder_view.setBoxType_(1)  # NSBoxCustom
        self.placeholder_view.setBorderType_(2)  # NSBezelBorder
        # NSBox defaults its title to "Title" — suppress it (NSNoTitle) so idle
        # doesn't render a stray "Title" caption above the message.
        self.placeholder_view.setTitlePosition_(0)
        self.placeholder_view.setTransparent_(False)
        self.placeholder_view.setWantsLayer_(True)
        self.placeholder_view.layer().setCornerRadius_(12)
        self.placeholder_view.layer().setBackgroundColor_(
            NSColor.controlBackgroundColor().CGColor()
        )
        self.placeholder_view.setAccessibilityLabel_("Idle state container")
        self.window.contentView().addSubview_(self.placeholder_view)

        # Idle message label
        label_y = content_height - 50
        self.idle_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(0, label_y, content_width, 36)
        )
        self.idle_label.setStringValue_("No Active Processes")
        self.idle_label.setBezeled_(False)
        self.idle_label.setDrawsBackground_(False)
        self.idle_label.setEditable_(False)
        self.idle_label.setFont_(NSFont.boldSystemFontOfSize_(24))
        self.idle_label.setTextColor_(NSColor.labelColor())
        self.idle_label.setAlignment_(NSCenterTextAlignment)
        self.idle_label.setAccessibilityLabel_("No active processes message")
        self.placeholder_view.addSubview_(self.idle_label)

        # Subtitle label
        subtitle_y = label_y - 50
        self.idle_subtitle = NSTextField.alloc().initWithFrame_(
            NSMakeRect(20, subtitle_y, content_width - 40, 40)
        )
        self.idle_subtitle.setStringValue_(
            "Start training or inference from the main window\nto monitor progress here."
        )
        self.idle_subtitle.setBezeled_(False)
        self.idle_subtitle.setDrawsBackground_(False)
        self.idle_subtitle.setEditable_(False)
        self.idle_subtitle.setFont_(NSFont.systemFontOfSize_(13))
        self.idle_subtitle.setTextColor_(NSColor.secondaryLabelColor())
        self.idle_subtitle.setAlignment_(NSCenterTextAlignment)
        self.idle_subtitle.setAccessibilityLabel_("Instructions for starting processes")
        self.placeholder_view.addSubview_(self.idle_subtitle)

        # Open Main Window button
        button_width = 160
        button_height = 28
        button_x = (content_width - button_width) // 2
        button_y = 20
        self.open_main_window_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(button_x, button_y, button_width, button_height)
        )
        self.open_main_window_btn.setTitle_("Open Main Window")
        self.open_main_window_btn.setBezelStyle_(1)  # NSRoundedBezelStyle
        self.open_main_window_btn.setTarget_(self)
        self.open_main_window_btn.setAction_("openMainWindow:")
        self.open_main_window_btn.setAccessibilityLabel_("Open main window button")
        self.open_main_window_btn.setAccessibilityHelp_(
            "Open the main Applio window to start training or inference"
        )
        self.placeholder_view.addSubview_(self.open_main_window_btn)

        # Placeholder is initially visible
        self.placeholder_view.setHidden_(False)

    # =================================================================
    # Update Coordinator (Single Timer Pattern)
    # =================================================================

    def _start_update_timer(self):
        """Start the single coordinated update timer.

        Uses the faster DETAIL_UPDATE_INTERVAL for detail panel updates,
        and throttles sidebar refreshes to SIDEBAR_UPDATE_INTERVAL.

        Logs timer start for debugging.
        """
        # Stop any existing timer first (prevents duplicates from rapid show/hide)
        if self._timer:
            self._stop_update_timer()

        # Guard against starting during shutdown
        if self._shutdown_event.is_set():
            logging.debug("[Dashboard] Not starting timer - shutdown in progress")
            return

        # Create timer with coordinator callback
        # Use DETAIL_UPDATE_INTERVAL (faster) as base, throttle sidebar in callback
        from AppKit import NSTimer

        self._timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                DETAIL_UPDATE_INTERVAL, self, "coordinatedUpdate:", None, True
            )
        )
        logging.debug(
            f"[Dashboard] Update timer started (interval: {DETAIL_UPDATE_INTERVAL}s)"
        )

    def coordinatedUpdate_(self, timer):
        """Single coordinated update method called by timer.

        This method dispatches all periodic updates from a single timer,
        preventing timer collisions and ensuring consistent state.
        Sidebar updates are throttled to SIDEBAR_UPDATE_INTERVAL.

        Safety: All UI updates check for existence before operating.
        """
        # Guard against updates after shutdown
        if self._shutdown_event.is_set():
            return

        # Guard against missing window (shouldn't happen, but defensive)
        if not self.window:
            return

        # Throttle sidebar updates using counter
        if not hasattr(self, "_update_counter"):
            self._update_counter = 0
        self._update_counter += 1

        try:
            # Always update detail panel if visible and process selected
            # Multiple safety checks before UI operations
            should_update_detail = (
                self._selected_process is not None
                and hasattr(self, "detail_panel")
                and self.detail_panel is not None
                and not self.detail_panel.isHidden()
                and hasattr(self, "window")
                and self.window is not None
            )

            if should_update_detail:
                self._update_detail_panel()

            # Throttled sidebar refresh (every Nth call)
            # With DETAIL_UPDATE_INTERVAL=1.0 and SIDEBAR_UPDATE_INTERVAL=3.0,
            # refresh every 3rd call (every 3 seconds)
            throttle_factor = int(SIDEBAR_UPDATE_INTERVAL / DETAIL_UPDATE_INTERVAL)
            if self._update_counter % throttle_factor == 0:
                if self._current_state == "active":
                    self.refresh_process_list()
                    # A new job may have appeared while nothing was selected —
                    # auto-select it so its detail panel populates (issue 3).
                    # No-op when the user already has a selection.
                    self._auto_select_first_active()

        except Exception as e:
            # Log but don't crash - timer will continue
            logging.warning(f"[Dashboard] Update error (non-fatal): {e}")

    def _stop_update_timer(self):
        """Stop the update timer."""
        if self._timer:
            self._timer.invalidate()
            self._timer = None
            logging.debug("[Dashboard] Update timer stopped")

    def openMainWindow_(self, sender):
        """Handle 'Open Main Window' button click — surface the in-process window."""
        launcher = self._launcher
        if launcher is not None and getattr(launcher, "_main_window", None):
            # The window lives in THIS process — show it directly.
            logging.info("[Dashboard] Open Main Window")
            try:
                AppHelper.callAfter(launcher._main_window.show)
                from AppKit import NSApp

                NSApp.activateIgnoringOtherApps_(True)
            except Exception as e:
                logging.warning(f"[Dashboard] Open Main Window failed: {e}")

    def show(self):
        """Show or bring the dashboard window to front.

        Restarts the update timer if in active state.
        Handles multiple rapid show/hide cycles gracefully.
        """
        if not self.window:
            logging.warning("[Dashboard] show() called but window is None")
            return

        # Check for rapid show/hide - if window is already visible, just bring to front
        if self.window.isVisible():
            self.window.makeKeyAndOrderFront_(None)
            return

        logging.info(f"[Dashboard] Showing window (state: {self._current_state})")
        self.window.makeKeyAndOrderFront_(None)

        # Give the process list keyboard focus on open (arrows/Enter act on it),
        # with row 0 preselected so Enter has a target even before any click.
        try:
            self.window.setInitialFirstResponder_(self.process_table)
            # setInitialFirstResponder_ is consulted when the window BECOMES
            # key; makeKeyAndOrderFront_ above already did that, so move focus
            # directly for this first open (later re-keys use the initial one).
            self.window.makeFirstResponder_(self.process_table)
            if self.process_table.numberOfRows() > 0:
                from Foundation import NSIndexSet

                self.process_table.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(0), False
                )
        except Exception:
            logging.debug("[Dashboard] first-responder setup failed", exc_info=True)

        # User has shown interest in the dashboard this session — enable auto-show.
        self._opened_this_session = True

        # Restart timer if in active state
        if self._current_state == "active":
            self._start_update_timer()
        else:
            # Idle: render the idle layout so the history sidebar is visible +
            # selectable from the very first open (the initial state never goes
            # through transition_to_idle).
            self._apply_idle_display()

    def _surface_window(self):
        """Aggressively bring the dashboard to front (single-process auto-show).

        orderFrontRegardless brings the window forward even when the app is not
        frontmost; activateIgnoringOtherApps_ steals focus so the user notices a
        job just started. Used ONLY on the idle->active transition in
        single-process mode, and only when the user opened the dashboard this
        session. See update_process_list / menuUpdateTimerFired_.
        """
        if not self.window:
            return
        try:
            self.window.orderFrontRegardless()
            from AppKit import NSApp

            NSApp.activateIgnoringOtherApps_(True)
        except Exception as e:
            logging.warning(f"[Dashboard] auto-show surface failed: {e}")

    def hide(self):
        """Hide the dashboard window without destroying.

        Stops the update timer to save resources.
        """
        if not self.window:
            logging.warning("[Dashboard] hide() called but window is None")
            return

        logging.info("[Dashboard] Hiding window")
        self.window.orderOut_(None)

        # Stop timer when hidden (no need to update)
        self._stop_update_timer()

    def dashboardWindowWillClose_(self, notification):
        """Handle window close - hide instead of destroy."""
        # This is called when user clicks the close button
        # We intercept and hide instead
        self._stop_update_timer()
        self.hide()

    def windowShouldClose_(self, sender):
        """Delegate method - intercept close to hide instead."""
        self._stop_update_timer()
        self.hide()
        return False  # Prevent actual close

    def applicationWillTerminate_(self, notification):
        """Clean up on app termination."""
        logging.info("[Dashboard] Application terminating, cleaning up")
        self._cleanup()

    def _cleanup(self):
        """Clean up resources.

        Safe to call multiple times. All operations are idempotent.
        """
        # Set shutdown flag first to stop any pending operations
        self._shutdown_event.set()

        logging.debug("[Dashboard] Starting cleanup")

        # Stop timer (uses consistent method)
        try:
            self._stop_update_timer()
        except Exception as e:
            logging.warning(f"[Dashboard] Error stopping timer during cleanup: {e}")

        # Remove observers with error handling
        try:
            if self._observer:
                NSNotificationCenter.defaultCenter().removeObserver_(self._observer)
                self._observer = None
        except Exception as e:
            logging.warning(f"[Dashboard] Error removing window observer: {e}")

        try:
            if self._terminate_observer:
                NSNotificationCenter.defaultCenter().removeObserver_(
                    self._terminate_observer
                )
                self._terminate_observer = None
        except Exception as e:
            logging.warning(f"[Dashboard] Error removing terminate observer: {e}")

        # Clear references to help GC
        self._selected_process = None
        self._active_processes = []
        self._recent_processes = []

        logging.debug("[Dashboard] Cleanup complete")

    def _apply_idle_display(self):
        """Render the idle layout: history sidebar (left) + 'no active' placeholder
        (right).

        History stays reachable even with nothing running — the user can select a
        past run and its metrics/chart populate the detail panel. Selecting a row
        hides the placeholder; deselecting (or entering idle) restores it.
        """
        # Recent runs feed the sidebar (the active list is empty in idle).
        try:
            self._recent_processes = get_recent_processes(limit=5)
        except Exception as e:
            logging.warning(
                f"[Dashboard] Could not load recent processes for idle: {e}"
            )
            self._recent_processes = []
        if hasattr(self, "process_table") and self.process_table:
            try:
                self.process_table.reloadData()
            except Exception as e:
                logging.warning(f"[Dashboard] Could not reload table for idle: {e}")
        # Sidebar visible + relabelled so history is always selectable.
        if hasattr(self, "sidebar_scroll") and self.sidebar_scroll:
            self.sidebar_scroll.setHidden_(False)
        if hasattr(self, "active_header") and self.active_header:
            self.active_header.setStringValue_("HISTORY")
            self.active_header.setHidden_(False)
        # Placeholder (now in the detail-panel area) stays; detail hidden until a
        # history row is selected.
        if hasattr(self, "placeholder_view") and self.placeholder_view:
            self.placeholder_view.setHidden_(False)
        if hasattr(self, "detail_panel") and self.detail_panel:
            self.detail_panel.setHidden_(True)

    def transition_to_idle(self):
        """Transition dashboard to idle state.

        Called when no active processes remain.
        Logs the transition for debugging.
        """
        old_state = self._current_state
        self._current_state = "idle"
        self._selected_process = None

        logging.info(f"[Dashboard] State transition: {old_state} -> idle")

        # Update window title (with null check)
        if self.window:
            self.window.setTitle_("Applio Dashboard")

        # Stop timer in idle state (no updates needed)
        self._stop_update_timer()

        # Render idle layout (history sidebar + placeholder). History MUST stay
        # reachable in idle so past runs are selectable.
        self._apply_idle_display()

    def _auto_select_first_active(self):
        """Auto-select the first active process when nothing is selected.

        On a fresh detection (idle->active, or a new job appearing while nothing
        is selected) this populates the detail panel immediately instead of
        waiting for a manual click. If the user has already selected anything
        (active OR a history row), we leave it alone -- never yank a manual
        selection.
        """
        if self._selected_process is not None:
            return
        if not self._active_processes:
            return
        self._selected_process = self._active_processes[0]
        # Mirror the selection in the table (best-effort). We do NOT rely on the
        # selection delegate here -- programmatic selection timing can vary, so
        # we also drive the detail panel directly below.
        if hasattr(self, "process_table") and self.process_table:
            try:
                from AppKit import NSIndexSet

                self.process_table.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(0),
                    False,
                )
            except Exception as e:
                logging.debug(f"[Dashboard] auto-select highlight failed: {e}")
        logging.info(
            "[Dashboard] Auto-selected active process: %s",
            self._selected_process.get("type"),
        )
        self._update_detail_panel()

    def transition_to_active(self, processes: list):
        """Transition dashboard to active state.

        Args:
            processes: List of active process dicts

        Logs the transition and validates input.
        """
        old_state = self._current_state
        self._current_state = "active"

        # Validate input
        if not processes:
            logging.warning(
                "[Dashboard] transition_to_active called with empty list, going idle"
            )
            self.transition_to_idle()
            return

        self._active_processes = processes

        # Load recent processes with error handling
        try:
            self._recent_processes = get_recent_processes(limit=5)
        except Exception as e:
            logging.warning(f"[Dashboard] Could not load recent processes: {e}")
            self._recent_processes = []

        self._selected_process = None  # Clear selection on transition

        logging.info(
            f"[Dashboard] State transition: {old_state} -> active ({len(processes)} processes)"
        )

        # Update window title (with null check)
        if self.window:
            self.window.setTitle_(f"Applio Dashboard ({len(processes)} active)")

        # Hide placeholder, show sidebar (all with null checks)
        if hasattr(self, "placeholder_view") and self.placeholder_view:
            self.placeholder_view.setHidden_(True)

        if hasattr(self, "sidebar_scroll") and self.sidebar_scroll:
            self.sidebar_scroll.setHidden_(False)
            if hasattr(self, "process_table") and self.process_table:
                self.process_table.reloadData()

        if hasattr(self, "active_header") and self.active_header:
            self.active_header.setStringValue_("ACTIVE")
            self.active_header.setHidden_(False)

        # Detail panel hidden initially — auto-select fills it immediately so
        # the user sees metrics/graph without a manual click (issue 3).
        if hasattr(self, "detail_panel") and self.detail_panel:
            self.detail_panel.setHidden_(True)

        # Start update timer for active monitoring
        self._start_update_timer()

        self._auto_select_first_active()

    def update_process_list(self):
        """Refresh the process list and update dashboard state.

        Handles:
        - Process list refresh errors
        - State transitions (idle <-> active)
        - Null checks for UI elements
        - Single-process auto-show on idle->active (Feature 2)
        """
        # Capture pre-transition state for idle->active detection (Feature 2).
        was_active = self._current_state == "active"
        # Subprocess jobs + the synthesized in-app batch, one merge
        # (_merged_live_procs — shared with the Active-Processes menu) so the
        # sidebar / idle->active auto-show / detail panel all light up for an
        # in-app batch with no PID of its own.
        try:
            self._active_processes = _merged_live_procs()
        except Exception as e:
            logging.warning(f"[Dashboard] Could not get active processes: {e}")
            self._active_processes = []

        # Probe SIGSTOP state once per refresh so row cells render truthfully
        # without a psutil call per visible cell (see _annotate_pause_state).
        self._annotate_pause_state(self._active_processes)

        try:
            self._recent_processes = get_recent_processes(limit=5)
        except Exception as e:
            logging.warning(f"[Dashboard] Could not get recent processes: {e}")
            self._recent_processes = []

        # Update state based on process count
        if self._active_processes:
            if self._current_state != "active":
                self.transition_to_active(self._active_processes)
        else:
            if self._current_state == "active":
                self.transition_to_idle()

        # Surface the dashboard when a job appears (idle->active), but only if
        # the user opened it this session (never force-open for a user who
        # doesn't use the dashboard).
        if (
            not was_active
            and self._current_state == "active"
            and self._opened_this_session
        ):
            logging.info("[Dashboard] idle->active transition: auto-showing")
            self._surface_window()

    def get_state(self) -> str:
        """Get current dashboard state."""
        return self._current_state


# =================================================================
# 5.6. Menu Action Handler (NSObject Proxy)
# =================================================================


def _mods_to_mask(mods):
    """Translate menu_spec mod tokens to a PyObjC key-equivalent modifier mask."""
    from AppKit import NSCommandKeyMask, NSShiftKeyMask, NSAlternateKeyMask

    mask = 0
    if "cmd" in mods:
        mask |= NSCommandKeyMask
    if "shift" in mods:
        mask |= NSShiftKeyMask
    if "option" in mods:
        mask |= NSAlternateKeyMask
    return mask


def _fill_ns_menu(
    spec_menu,
    ns_menu,
    target,
    dispatch,
    tag_counter,
    dynamic_out,
    key_to_tag=None,
    is_top_level=False,
):
    """Fill the passed-in `ns_menu` with items from a list of menu_spec.MenuItem.

    Recursion: submenus are built by calling _fill_ns_menu on a fresh NSMenu
    (no item-by-item moving). The FIRST top-level submenu is the app menu; leave
    it UNTITLED so macOS renders the bold app name from the bundle (matches the
    original _setup_menu + spec section 5.1 - do NOT setTitle_ it).

    Per leaf:
    - dispatch[key] == str  -> standard AppKit selector, target None (responder chain)
    - dispatch[key] callable -> tagged item, action runDispatch:, target = target;
      also records key_to_tag[key] = tag (so the timer can find items by action key)
    - dispatch[key] missing  -> display-only item (e.g. process.status): disabled, no action
    - dynamic items are recorded in dynamic_out[key] = (ns_item, hint)
    """
    from AppKit import NSMenuItem

    # Titles translate at RENDER time (menu_spec stays English literals).
    # Lazy, call-time: a module-level import would couple menu building to
    # config/i18n presence at import time.
    import applio_i18n

    _tr = applio_i18n.native_tr

    for mi in spec_menu:
        if mi.separator:
            ns_menu.addItem_(NSMenuItem.separatorItem())
            continue
        if mi.submenu:
            from AppKit import NSMenu

            sub = NSMenu.alloc().init()
            _fill_ns_menu(
                mi.submenu,
                sub,
                target,
                dispatch,
                tag_counter,
                dynamic_out,
                key_to_tag,
                is_top_level=False,
            )
            if is_top_level:
                # Top-level main-menu item: the menu BAR shows the submenu's title;
                # the item itself is left untitled (and MENU[0] must stay untitled so
                # macOS renders the bold app name from the bundle).
                if mi.title:
                    sub.setTitle_(_tr(mi.title))
                parent_item = NSMenuItem.alloc().init()
            else:
                # Nested submenu (e.g. "Reveal in Finder" inside File): Cocoa shows
                # the ITEM's title, not the submenu's, so set it explicitly.
                parent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    _tr(mi.title), "", ""
                )
            parent_item.setSubmenu_(sub)
            ns_menu.addItem_(parent_item)
            continue
        # leaf
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _tr(mi.title), "", mi.shortcut or ""
        )
        if mi.shortcut and mi.mods:
            item.setKeyEquivalentModifierMask_(_mods_to_mask(mi.mods))
        handler = dispatch.get(mi.key)
        if isinstance(handler, str):
            item.setAction_(handler)
            item.setTarget_(None)
        elif callable(handler):
            tag = next(tag_counter)
            item.setTag_(tag)
            item.setAction_("runDispatch:")
            item.setTarget_(target)
            target._dispatch_table[tag] = handler
            if key_to_tag is not None and mi.key:
                key_to_tag[mi.key] = tag
        else:
            # display-only (status) item: disabled, no action
            item.setEnabled_(False)
        if mi.dynamic and mi.key:
            dynamic_out[mi.key] = (item, mi.dynamic)
        ns_menu.addItem_(item)


def _find_item_by_tag(ns_menu, tag):
    for i in range(ns_menu.numberOfItems()):
        item = ns_menu.itemAtIndex_(i)
        if item.tag() == tag and item.action() is not None:
            return item
        sub = item.submenu()
        if sub:
            found = _find_item_by_tag(sub, tag)
            if found is not None:
                return found
    return None


class MenuActionHandler(NSObject):
    """NSObject proxy to handle menu item actions.

    Required because ApplioLauncher is a plain Python class and cannot
    correctly respond to respondsToSelector: when used as an NSMenuItem target.

    Uses weakref to prevent retain cycles with ApplioLauncher.
    """

    def initWithLauncher_(self, launcher):
        """Initialize with weak reference to launcher.

        Args:
            launcher: ApplioLauncher instance (stored as weak reference)

        Returns:
            self (standard Objective-C init pattern)
        """
        self = objc.super(MenuActionHandler, self).init()
        if self is not None:
            self._launcher_ref = weakref.ref(launcher)
            self._dispatch_table = {}
        return self

    def _get_launcher(self):
        """Safely get launcher reference.

        Returns:
            ApplioLauncher instance or None if deallocated
        """
        if hasattr(self, "_launcher_ref"):
            return self._launcher_ref()
        return None

    def runDispatch_(self, sender):
        """Generic menu dispatch keyed by the NSMenuItem's tag."""
        fn = getattr(self, "_dispatch_table", {}).get(sender.tag() if sender else None)
        if callable(fn):
            try:
                fn()
            except Exception as e:
                logging.error(f"[Launcher] menu dispatch failed: {e}")


# =================================================================
# 5.7. NSApplication Delegate (app lifecycle: reopen / quit / activation)
# =================================================================


class ApplioAppDelegate(NSObject):
    """NSApplicationDelegate implementing the macOS app-lifecycle contracts a
    plain Python class cannot fulfil: dock-click reopen, quit validation +
    process cascade, and graceful termination.

    Why this exists: the launcher is the .app's frontmost process (Regular
    activation policy) and owns the dock tile + menu bar, so the reopen/quit
    Apple-Events are delivered to THIS process's NSApplication. Without a
    delegate, dock-click reopen does nothing and Cmd+Q never cascades to the
    wrapper/Gradio/training subprocesses. (See native-integration audit.)

    Uses weakref to ApplioLauncher (same pattern as MenuActionHandler).
    """

    def initWithLauncher_(self, launcher):
        self = objc.super(ApplioAppDelegate, self).init()
        if self is not None:
            self._launcher_ref = weakref.ref(launcher)
        return self

    def _get_launcher(self):
        if hasattr(self, "_launcher_ref"):
            return self._launcher_ref()
        return None

    def applicationSupportsSecureRestorableState_(self, sender):
        # macOS requirement (pywebview's own delegate implements this). PyObjC
        # accepts a Python bool for the BOOL return.
        return True

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag):
        """Dock-click / LaunchServices reopen when already running.

        The main window lives in THIS process, so we show it directly via
        makeKeyAndOrderFront: and bring the app to the front. callAfter keeps
        the show off the AppKit reopen callback's stack.
        """
        logging.info("[AppDelegate] reopen fired")
        launcher = self._get_launcher()
        if launcher:
            if getattr(launcher, "_main_window", None):
                # The main window lives in THIS process — show it directly.
                try:
                    AppHelper.callAfter(launcher._main_window.show)
                except Exception as e:
                    logging.warning(f"[AppDelegate] reopen show failed: {e}")
            try:
                from AppKit import NSApp

                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass
        return True  # YES — we handled the reopen

    def applicationShouldTerminate_(self, sender):
        """Quit validation: confirm if training is active, then cascade.

        Uses a SYNCHRONOUS modal alert (dismissed before return), so we can
        return NSTerminateNow(1)/NSTerminateCancel(0) directly. This is
        equivalent to the NSTerminateLater+reply pattern but cannot hang the
        quit if a reply were ever missed.
        """
        logging.info("[AppDelegate] terminate fired")
        launcher = self._get_launcher()
        if not launcher:
            return 1  # NSTerminateNow

        # If the user already confirmed a quit (the window-close Terminate path
        # sets _user_confirmed_quit right before deferring NSApp.terminate_),
        # skip re-prompting. (_quit_confirmed is a legacy flag kept for safety.)
        confirmed = getattr(launcher, "_user_confirmed_quit", False) or getattr(
            launcher, "_quit_confirmed", False
        )
        try:
            active = [] if confirmed else get_active_processes()
        except Exception:
            active = []

        # In-process conversions (single or batch) run on a gradio worker
        # thread, NOT a subprocess, so get_active_processes() never sees them
        # — they live only in inference_progress.json. Synthesize the same
        # proc the dashboard builds so a mid-conversion quit gets this prompt
        # too; without it AppKit exit(0) tears Python down under the worker
        # (pybind finalize race, repro 2026-08-27). Confirmed window-close
        # quits skip this (their own dialog just ran — see on_window_closing).
        if not confirmed:
            try:
                inference_proc = _synthesize_inference_proc()
            except Exception:
                inference_proc = None
            if inference_proc:
                active.append(inference_proc)

        if active and not confirmed:
            from AppKit import (
                NSAlert,
                NSAlertStyleWarning,
                NSAlertSecondButtonReturn,
            )

            try:
                import applio_i18n

                _t = applio_i18n.native_tr
                info = ", ".join(
                    (
                        f"{inference_job_type(p.get('scope'))}:{p.get('model_name', '?')}"
                        if p.get("_is_inference")
                        else f"{p.get('type', '?')}:{p.get('model_name', '?')}"
                    )
                    for p in active[:3]
                )
                if len(active) > 3:
                    info += f", +{len(active) - 3} more"
                alert = NSAlert.alloc().init()
                alert.setMessageText_(_t("Quit Applio?"))
                alert.setInformativeText_(
                    _t(
                        "{n} process(es) still running ({info}). "
                        "Terminating now may interrupt a checkpoint write. Quit anyway?"
                    ).format(n=len(active), info=info)
                )
                alert.setAlertStyle_(NSAlertStyleWarning)
                alert.addButtonWithTitle_(
                    _t("Cancel")
                )  # First: auto Escape; NO Return default
                alert.addButtonWithTitle_(
                    _t("Terminate & Quit")
                )  # Second: no key equivalent — explicit click only
                if alert.runModal() != NSAlertSecondButtonReturn:
                    return 0  # NSTerminateCancel
            except Exception as e:
                logging.warning(f"[AppDelegate] quit-confirm alert failed: {e}")
                # Fall through to terminate — never block quit on a UI failure.

        # Confirmed or nothing active: signal the Gradio supervisor to abort any
        # retry/backoff loop, run the cascade, then allow termination.
        _applio = getattr(launcher, "_applio_app", None)
        if _applio is not None:
            _applio._stopping = True
        # A confirmed quit with a live in-process conversion must land the
        # worker at its per-file checkpoint BEFORE termination: exit(0) would
        # otherwise finalize pybind while the gradio worker thread is still
        # inside torch (repro 2026-08-27). Runs even when ``confirmed`` skipped
        # the prompt (the window-close path sets _user_confirmed_quit after its
        # own dialog). Bounded at ~2.5s — never blocks the quit path longer.
        try:
            if _inference_running():
                _cancel_inference_and_join()
        except Exception as e:
            logging.warning(f"[AppDelegate] inference cancel-on-quit failed: {e}")
        try:
            launcher._terminate_children()
        except Exception as e:
            logging.warning(f"[AppDelegate] terminate cascade failed: {e}")
        return 1  # NSTerminateNow

    def applicationWillTerminate_(self, notification):
        """Belt-and-suspenders: ensure the cascade runs even if termination came
        via a path that bypassed applicationShouldTerminate_ (e.g. system logout)."""
        launcher = self._get_launcher()
        if launcher:
            try:
                launcher._terminate_children()
            except Exception as e:
                logging.warning(f"[AppDelegate] will-terminate cascade failed: {e}")


# =================================================================
# 6. Main Launcher Class
# =================================================================


class ApplioLauncher:
    """Main launcher: runs the in-process pywebview/Gradio GUI and native menu."""

    def __init__(self):
        self.progress_window = None
        self._menu_update_timer = None
        self._dashboard_controller = None  # Persistent dashboard window
        import applio_i18n

        self._a11y_policy = applio_a11y.AnnouncementPolicy(
            translator=applio_i18n.native_tr
        )  # Job lifecycle announcements (translated, English fallback)
        self._a11y_primed = False  # First heartbeat primes, doesn't announce
        try:
            import applio_native_picker

            applio_native_picker.mark_native_loop_available()
        except Exception:
            pass
        # Accessibility (auto, 2026-08-23 owner ruling): speech is ZERO-CONFIG —
        # the web live region speaks exactly when VoiceOver runs. The hidden
        # a11y.speech NSUserDefaults key ("auto" default / "on" / "off") is the
        # only override and has NO UI (the Accessibility submenu is gone).
        # Sound cues default ON for everyone (hidden a11y.sound_cues bool).
        # Legacy keys (a11y.verbosity, a11y.announce_mode) are no longer read.
        # Guarded reads — __init__ must not gain an unguarded PyObjC import
        # (the module keeps a NATIVE_APIS_AVAILABLE fallback path).
        self._a11y_sound_cues = True
        self._a11y_effective_verbosity = None  # computed by _update_a11y_speech
        try:
            from Foundation import NSUserDefaults

            defaults = NSUserDefaults.standardUserDefaults()
            # boolForKey_ conflates "unset" with False; the default is ON, so
            # distinguish via objectForKey_ (None = unset).
            sound = defaults.objectForKey_("a11y.sound_cues")
            if sound is not None:
                self._a11y_sound_cues = bool(sound)
        except Exception:
            logging.debug("[A11y] settings read failed", exc_info=True)
        self._update_a11y_speech()  # computes the effective verbosity + pushes
        # Web-side layout changes are marshaled to the main thread and posted
        # as an AX layout-changed notification (VO re-scans the WKWebView).
        try:
            import applio_progress_api

            applio_progress_api.set_layout_changed_callback(
                lambda: AppHelper.callAfter(self._post_webview_layout_changed)
            )
        except Exception:
            pass
        self._terminating = False  # Reentry protection for signal handlers
        self._dist_center = None  # NSDistributedNotificationCenter reference
        self._menu_handler = (
            None  # NSObject proxy for menu actions (initialized in _setup_menu)
        )
        self._app_delegate = (
            None  # NSApplicationDelegate (reopen/terminate), attached in _setup_menu
        )
        self._applio_app = None  # In-process GUI (ApplioApp) from start_gui
        self._main_window = None  # pywebview window handle
        self._quit_confirmed = False  # Legacy flag (unused; kept for safety)
        self._user_confirmed_quit = False  # Window-close Terminate -> skip re-prompt
        self._setup_signal_handlers()
        # Single-instance surfacing: observe a 2nd instance's bring_to_front
        # request (posted when a second launch fails the single-instance flock).
        # The main window is in-process, so we surface it on the main thread.
        try:
            from Foundation import NSDistributedNotificationCenter

            self._dist_center = NSDistributedNotificationCenter.defaultCenter()
            self._dist_center.addObserver_selector_name_object_suspensionBehavior_(
                self,
                "bringToFront:",
                IPC_BRING_TO_FRONT_NAME,
                None,
                4,  # NSNotificationSuspensionBehaviorDeliverImmediately
            )
            logging.info(
                "[Launcher] single-instance bring_to_front observer registered"
            )
        except ImportError:
            logging.warning("[Launcher] NSDistributedNotificationCenter not available")
            self._dist_center = None

    def start(self):
        """Main entry point."""
        logging.info("[Launcher] Starting...")

        # 0. Single-instance guard (1.6). Defense-in-depth alongside
        # LSMultipleInstancesProhibited (which only blocks Finder/dock relaunch,
        # not `open -n` or direct binary invocation). If another instance holds
        # the lock, signal it to surface its window and exit.
        if not acquire_single_instance_lock():
            logging.warning(
                "[Launcher] Another instance is already running; signaling it and exiting."
            )
            # The 1st instance's window is in-process. Post a distributed
            # notification; it surfaces its own main window via bringToFront_.
            try:
                from Foundation import NSDistributedNotificationCenter

                NSDistributedNotificationCenter.defaultCenter().postNotificationName_object_(
                    IPC_BRING_TO_FRONT_NAME, None
                )
            except Exception as e:
                logging.warning(f"[Launcher] bring_to_front post failed: {e}")
            sys.exit(0)

        # 1. Validate existing processes
        state = load_process_state()
        state, cleaned = validate_process_state(state)
        if cleaned:
            save_process_state(state)

        # 1.5. Clean up old history entries (run once on startup)
        try:
            removed = cleanup_old_history()
            if removed > 0:
                logging.info(f"[Launcher] Cleaned up {removed} old history entries")
        except Exception as e:
            logging.warning(f"[Launcher] History cleanup failed: {e}")

        # 1.6. Recover a stale inference_progress.json left by a crash/quit
        # mid-batch: rewrite it to "interrupted" + append a history entry, so the
        # dashboard never shows a phantom running job on next launch.
        try:
            _sweep_stale_inference_progress()
        except Exception as e:
            logging.warning(f"[Launcher] inference progress sweep failed: {e}")

        active = get_active_processes()

        # 2. Setup native menu
        self._setup_menu()

        # 3. If processes running, show progress window
        if active:
            logging.info(f"[Launcher] Found {len(active)} active processes")
            self._show_progress_window_for_processes(active)

        # The launcher process IS the GUI process — it runs pywebview + Gradio
        # directly. webview.start drives the run loop below (NO menu= — we keep
        # our native NSMenu; _reassert_menu_and_delegate re-seats the delegate +
        # menu after webview clobbers them on window creation).
        import macos_wrapper, webview

        self._applio_app = macos_wrapper.start_gui(launcher=self)
        self._main_window = getattr(self._applio_app, "window", None)
        logging.info("[Launcher] Starting webview event loop")
        # Silent launch-time update check (daemon thread; alert only if newer).
        AppHelper.callAfter(self._launch_time_update_check)
        webview.start(func=self._reassert_menu_and_delegate, debug=False)

        # Run loop returned (webview.start returned, e.g. NSApp.stop on quit).
        # Run the termination cascade before exit — signal handlers may not fire
        # reliably while blocked in the CFRunLoop, so this post-loop call is the
        # reliable path (1.7).
        logging.info("[Launcher] Event loop ended; running termination cascade")
        try:
            self._terminate_children()
        except Exception as e:
            logging.warning(f"[Launcher] post-loop cascade failed: {e}")

    def _setup_signal_handlers(self):
        """Setup signal handlers."""
        signal.signal(signal.SIGCHLD, self._handle_child_exit)
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_terminate)

    def bringToFront_(self, notification):
        """A 2nd instance failed the single-instance lock and asked us to surface.

        The main window is in-process (self._main_window), so we surface it on
        the main thread via AppHelper.callAfter, matching the reopen pattern.
        """
        try:
            if getattr(self, "_main_window", None):
                from PyObjCTools import AppHelper
                from AppKit import NSApp

                AppHelper.callAfter(self._main_window.show)
                NSApp.activateIgnoringOtherApps_(True)
                logging.info("[Launcher] bring_to_front: surfacing main window")
        except Exception as e:
            logging.warning(f"[Launcher] bring_to_front failed: {e}")

    def _handle_child_exit(self, signum, frame):
        """Handle child process exit (SIGCHLD).

        Async-signal-safe: reaps exited children so they don't become zombies.
        (No wrapper subprocess exists — this only reaps Gradio/training child
        processes spawned within this process.)
        """
        try:
            while True:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
                logging.info(f"[Launcher] Child process {pid} exited")
        except ChildProcessError:
            pass

    def _handle_interrupt(self, signum, frame):
        """Handle SIGINT (Ctrl+C) with cascade termination."""
        if self._terminating:
            return
        self._terminating = True
        logging.info("[Launcher] Interrupt received, initiating cascade shutdown")
        self._terminate_children()
        self._cleanup()
        sys.exit(0)

    def _handle_terminate(self, signum, frame):
        """Handle SIGTERM by suppressing it (a training-cleanup artifact).

        The launcher IS the GUI process, so a normal quit never arrives as
        SIGTERM — it goes through applicationShouldTerminate_ (Cmd+Q / window
        close / NSApp.terminate), which quits via a deferred
        AppHelper.callAfter(NSApp.terminate_(None)) with _user_confirmed_quit.
        A SIGTERM here is, in practice, the leaked-resource teardown fired by
        training's os._exit(2333333): RVC ends training by os._exit-ing the
        worker WITHOUT draining its persistent DataLoader workers
        (num_workers=4, persistent_workers=True), so they are orphaned but
        remain in THIS process group, and their teardown signals the whole
        group — which would kill the entire app. Suppress the cascade quit and
        stay running — the orphaned workers self-terminate on their broken
        parent pipe within seconds (and already received this very signal if it
        was a group-wide killpg). Dedupe the log line so a burst of strays
        doesn't spam.
        """
        if self._terminating:
            return
        now = time.time()
        if now - getattr(self, "_last_spurious_sigterm", 0.0) > 5.0:
            self._last_spurious_sigterm = now
            logging.info(
                "[Launcher] SIGTERM; suppressing app quit (training-cleanup "
                "artifact). The app stays running; use Cmd+Q to quit."
            )
        return

    def inference_proc(self):
        """Quit-gate hook for macos_wrapper: the live in-process conversion.

        Delegates to _synthesize_inference_proc (the dashboard's own reader)
        so the wrapper's window-close dialog and this module's Cmd+Q gate see
        the SAME job. The wrapper cannot import applio_launcher (circular +
        it runs as __main__ frozen), so it reaches the reader through this
        instance. Returns None when no conversion is live; never raises.
        """
        try:
            return _synthesize_inference_proc()
        except Exception:
            return None

    def _terminate_children(self, timeout: float = 5.0):
        """Terminate all child processes gracefully with escalation.

        Args:
            timeout: Seconds to wait for graceful shutdown before SIGKILL
        """
        # Mark teardown so signal handlers don't re-enter mid-cascade.
        self._terminating = True
        if _LAUNCHER_PGID is None:
            # Normal for every LaunchServices launch (double-click / `open`):
            # those processes are already session leaders, so the boot-time
            # setsid failed and there is no group WE created to signal. DEBUG,
            # not warning — this is the standard path for a Finder-launched
            # app, and the module-level _setup_process_group already logged
            # the original setsid failure.
            logging.debug(
                "[Launcher] No launcher process group (setsid failed at "
                "boot); skipping group cascade"
            )
            return

        try:
            # Step 1: SIGTERM to entire process group
            logging.info(f"[Launcher] Sending SIGTERM to PGID {_LAUNCHER_PGID}")
            os.killpg(_LAUNCHER_PGID, signal.SIGTERM)

            # Step 2: Wait for graceful shutdown
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if pid == 0:
                        # Check if any children remain
                        try:
                            os.killpg(_LAUNCHER_PGID, 0)  # Check if group exists
                            time.sleep(0.1)
                        except ProcessLookupError:
                            logging.info(
                                "[Launcher] All children terminated gracefully"
                            )
                            return
                except ChildProcessError:
                    logging.info("[Launcher] All children terminated gracefully")
                    return

            # Step 3: Escalate to SIGKILL
            logging.warning("[Launcher] Graceful shutdown timeout, sending SIGKILL")
            try:
                os.killpg(_LAUNCHER_PGID, signal.SIGKILL)
            except ProcessLookupError:
                pass  # Already terminated

        except ProcessLookupError:
            logging.info("[Launcher] No child processes to terminate")

    def _setup_menu(self):
        """Setup native macOS menu bar."""
        if not NATIVE_APIS_AVAILABLE:
            logging.warning("[Launcher] Native APIs not available, skipping menu setup")
            return

        from AppKit import NSApplicationActivationPolicyRegular, NSApplication

        # Ensure NSApplication is initialized
        app = NSApplication.sharedApplication()

        # Create NSObject proxy for menu actions (plain Python classes can't be NSMenuItem targets)
        if not self._menu_handler:
            self._menu_handler = MenuActionHandler.alloc().initWithLauncher_(self)

        # Set app activation policy to show in Dock and menu bar
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

        # Attach the NSApplicationDelegate (reopen / quit-cascade / termination).
        # Must happen after sharedApplication() and before runEventLoop().
        if not self._app_delegate:
            self._app_delegate = ApplioAppDelegate.alloc().initWithLauncher_(self)
            app.setDelegate_(self._app_delegate)
            logging.info("[Launcher] NSApplicationDelegate attached (reopen/terminate)")

        main_menu = self._build_native_menu()
        # The FIRST top-level submenu (MENU[0]) is untitled on purpose: macOS renders
        # it as the bold app-name menu (from CFBundleName). Do NOT setTitle_ it.

        NSApp.setMainMenu_(main_menu)
        self._update_menu_state()
        self._start_menu_update_timer()
        logging.info("[Launcher] Menu bar setup complete (spec-driven)")

    def _build_native_menu(self):
        """Build and return the spec-driven native NSMenu.

        Pure build (no NSApp side effects): used by _setup_menu for the initial
        install AND by _reassert_menu_and_delegate to rebuild it after
        webview.start clobbers the main menu. Resets _dynamic_items / _key_to_tag
        on each build so the 2 s timer repopulates state on a fresh menu.
        """
        import itertools
        from AppKit import NSMenu

        self._dynamic_items = (
            {}
        )  # action_key -> (NSMenuItem, hint); mutated by the 2 s timer
        self._key_to_tag = {}  # action_key -> NSMenuItem tag; lets the timer find items
        tag_counter = itertools.count(1)
        dispatch = self._build_launcher_dispatch()

        main_menu = NSMenu.alloc().init()
        _fill_ns_menu(
            menu_spec.MENU,
            main_menu,
            self._menu_handler,
            dispatch,
            tag_counter,
            self._dynamic_items,
            self._key_to_tag,
            is_top_level=True,
        )
        return main_menu

    def _reassert_menu_and_delegate(self):
        """Re-seat our NSApplicationDelegate + native menu AFTER webview.start
        clobbers them.

        Passed to webview.start(func=...), so it runs on a webview WORKER thread;
        we marshal the NSApp-touching work onto the main run-loop thread via
        AppHelper.callAfter. pywebview clobbers NSApp.delegate() once on window
        creation and wipes the main menu once in first_show, so re-seating both
        here restores our reopen/terminate handling and our native menu (with
        shortcuts) for the lifetime of the window.

        REUSES the stored self._app_delegate: NSApplication.delegate is a WEAK
        (assign) ref, so the delegate object must be kept alive by Python — never
        inline a fresh ApplioAppDelegate.alloc()... here (its only ref would be
        GC'd, leaving a dangling delegate that crashes on the next reopen/quit).
        """
        from PyObjCTools import AppHelper

        def _do():
            try:
                from AppKit import NSApp

                if self._app_delegate is not None:
                    NSApp.setDelegate_(self._app_delegate)
                NSApp.setMainMenu_(self._build_native_menu())
                self._update_menu_state()  # apply dynamic state now (else ~2 s till next timer tick)
                self._enable_webview_keyboard_access()
                logging.info(
                    "[Launcher] Re-asserted delegate + native menu after webview.start"
                )
            except Exception:
                # callAfter prints uncaught exceptions to stderr, NOT the app log — capture so the
                # spike gate ("did the re-assert stick?") is diagnosable from applio_launcher.log.
                logging.exception("[Launcher] _reassert_menu_and_delegate failed")

        AppHelper.callAfter(_do)

    def _enable_webview_keyboard_access(self):
        """Tab must reach buttons/checkboxes in the WKWebView.

        WKPreferences.tabFocusesLinks defaults to False and pywebview never
        sets it (verified against venv_macos webview/platforms/cocoa.py);
        without this, Tab moves only between text inputs. Idempotent: the
        flag is set only on success, so the heartbeat retries until the
        webview exists (found via the shared _find_webview helper).
        """
        if getattr(self, "_webview_kb_done", False):
            return
        cv = self._find_webview()
        if cv is None:
            return
        try:
            cv.configuration().preferences().setTabFocusesLinks_(True)
            self._webview_kb_done = True
            logging.info("[A11y] WKWebView tab traversal enabled")
        except Exception:
            logging.debug("[A11y] setTabFocusesLinks_ failed", exc_info=True)

    def _start_menu_update_timer(self):
        """Start timer to periodically update menu state."""
        if not NATIVE_APIS_AVAILABLE:
            return
        from AppKit import NSTimer

        self._menu_update_timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                2.0, self, "menuUpdateTimerFired:", None, True  # Update every 2 seconds
            )
        )

    def menuUpdateTimerFired_(self, timer):
        """Periodic menu state update + dashboard heartbeat."""
        self._update_menu_state()
        # Dashboard heartbeat: keep its state fresh (idle<->active transitions)
        # so it can auto-show on a new job. Only drives an EXISTING controller —
        # never force-creates the dashboard for a user who hasn't opened it.
        if self._dashboard_controller:
            try:
                self._dashboard_controller.update_process_list()
            except Exception as e:
                logging.warning(f"[Launcher] dashboard heartbeat failed: {e}")
        self._a11y_heartbeat()
        self._enable_webview_keyboard_access()

    def _check_show_progress_monitor_signal(self):
        """Check if wrapper requested to show Progress Monitor via IPC.

        Returns True if signal was detected and handled, False otherwise.
        Resets the signal flag after detection to prevent repeated triggers.
        """
        import json
        import fcntl

        config_locations = [
            os.path.expanduser(
                "~/Library/Application Support/Applio/runtime_paths.json"
            ),
            os.path.expanduser("~/.applio/runtime_paths.json"),
        ]

        for config_path in config_locations:
            if not os.path.exists(config_path):
                continue

            try:
                with open(config_path, "r") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared lock for reading
                    config = json.load(f)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

                # Check if show_progress_monitor signal is set
                if config.get("show_progress_monitor") is True:
                    logging.info("[Launcher] Detected show_progress_monitor IPC signal")

                    # Reset the signal flag
                    config["show_progress_monitor"] = False
                    temp_path = config_path + ".tmp"
                    with open(temp_path, "w") as f:
                        fcntl.flock(
                            f.fileno(), fcntl.LOCK_EX
                        )  # Exclusive lock for writing
                        json.dump(config, f, indent=2)
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    os.rename(temp_path, config_path)

                    return True

            except Exception as e:
                logging.warning(
                    f"[Launcher] Failed to check show_progress_monitor signal: {e}"
                )

        return False

    def _update_menu_state(self):
        """Update dynamic menu items from the 2 s timer."""
        # Keep existing IPC handling (was already here).
        if self._check_show_progress_monitor_signal():
            try:
                if not self._dashboard_controller:
                    self._create_dashboard()
                if self._dashboard_controller:
                    self._dashboard_controller.update_process_list()
                    self._dashboard_controller.show()
            except Exception as e:
                logging.error(f"[Launcher] dashboard via IPC failed: {e}")

        dyn = getattr(self, "_dynamic_items", {})
        if not dyn:
            return

        # process.status — live jobs submenu (subprocess jobs + the in-app
        # batch, with live progress titles), rebuilt each cycle; each job item
        # opens the dashboard. Internally skips the NSMenu rebuild when the
        # title tuple is unchanged AND the parent item is still enabled.
        if dyn.get("process.status"):
            self._refresh_status_submenu()

        first_run = self._first_run_done()
        data_dir = self._resolve_data_dir() if first_run else None
        # Drive exists:<subpath> reveal items + first-run gating. SKIP status items
        # here — the status submenu parent's enabled state is owned by
        # _refresh_status_submenu and must not be gated by first-run.
        for key, (item, hint) in dyn.items():
            if hint == "status":
                continue
            if not first_run:
                item.setEnabled_(False)
                continue
            if hint and hint.startswith("exists:"):
                sub = hint.split("exists:", 1)[1]
                item.setEnabled_(os.path.exists(os.path.join(data_dir, sub)))
            else:
                item.setEnabled_(True)
        # set_data_location is a callable-dispatch item but not dynamic-flagged; gate it directly.
        sdl = self._find_item_by_key("file.set_data_location")
        if sdl is not None:
            sdl.setEnabled_(first_run)

    def _refresh_status_submenu(self):
        """Rebuild the Process→Active Processes submenu from ALL live jobs.

        Merged list (_merged_live_procs: subprocess jobs + the in-app batch) so
        the menu finally shows an in-process inference too, with live progress
        titles (_menu_job_title; training epoch via a bounded tail-scan of the
        run's training.log through _last_training_metrics — at most one 256 KB
        read + regex per training proc on this 2 s tick). Each job item
        dispatches through the SAME entry as the Open Progress Dashboard item
        (runDispatch: + _menu_handler + its recorded tag), so the dispatch
        table never grows. setSubmenu_ REPLACES the previous submenu (no
        accumulation); a fresh NSMenu per rebuild is autoreleased, not a leak.
        The NSMenu rebuild is SKIPPED only when the title tuple is unchanged
        AND the parent item is enabled — after a full _build_native_menu pass
        (the pywebview menu re-wipe path) the status parent is rebuilt
        DISABLED from the static spec, and a titles-only skip would leave it
        disabled with a dead submenu. Exception-guarded: the 2 s menu timer
        must never die.
        """
        entry = getattr(self, "_dynamic_items", {}).get("process.status")
        if not entry:
            return
        item, _hint = entry
        try:
            from AppKit import NSMenu, NSMenuItem

            procs = _merged_live_procs()
            _annotate_paused(procs)
            titles = []
            for proc in procs:
                epoch = None
                if (proc.get("type") or "").lower() == "training":
                    metrics = _last_training_metrics(
                        proc.get("log_file") or proc.get("log_path")
                    )
                    epoch = metrics.get("epoch") if metrics else None
                titles.append(_menu_job_title(proc, training_epoch=epoch))
            if (
                titles == getattr(self, "_last_status_titles", None)
                and item.isEnabled()
            ):
                return  # nothing changed and the parent is still enabled
            self._last_status_titles = titles

            sub = NSMenu.alloc().init()
            tag = getattr(self, "_key_to_tag", {}).get("process.open_dashboard")
            handler = self._menu_handler  # MenuActionHandler (NSObject proxy)
            if not titles:
                ni = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "No active processes", None, ""
                )
                ni.setEnabled_(False)
                sub.addItem_(ni)
            else:
                for title in titles:
                    ni = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        title,
                        "runDispatch:" if handler and tag is not None else None,
                        "",
                    )
                    if handler and tag is not None:
                        ni.setTarget_(handler)
                        ni.setTag_(tag)  # same tag as Open Progress Dashboard
                    sub.addItem_(ni)
            item.setSubmenu_(sub)
            item.setEnabled_(True)  # display-only items are built disabled; a
            # disabled item's submenu cannot open, so force-enable the parent
        except Exception:
            logging.debug("[Menu] status submenu rebuild failed", exc_info=True)

    # ---- Accessibility heartbeat (Phase 1: lifecycle announcements + dock badge) ----

    def _a11y_snapshot(self):
        """Current tracked-job snapshot for the announcement policy.

        Sources are the module-level functions (verified scopes): subprocess
        jobs from get_active_processes(), the in-app inference job (batch or
        single conversion — label via inference_job_type) from
        _synthesize_inference_proc() — disjoint, no dedupe. Keys are
        type:name:pid so same-type jobs sharing a model name (e.g. a
        relaunched preprocess) are tracked independently; word_key drops
        the pid to match history's type:name keys. Paused is derived per-proc via
        psutil because active_processes.json keeps SIGSTOPped jobs "running".
        The in-app job's "cancelling" maps onto the policy's terminal
        "cancelled" (see the inference block below for why a bare passthrough
        would stay silent).
        """
        snap = {}
        for proc in get_active_processes():
            name = (proc.get("model_name") or "").strip() or str(proc.get("pid"))
            status = "running"
            pid = proc.get("pid")
            if pid and PSUTIL_AVAILABLE:
                try:
                    if psutil.Process(pid).status() == psutil.STATUS_STOPPED:
                        status = "paused"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            key = f"{proc.get('type', 'process')}:{name}:{pid or 'x'}"
            snap[key] = {
                "type": proc.get("type", "process"),
                "name": name,
                "status": status,
                "word_key": f"{proc.get('type', 'process')}:{name}",
            }
        inf = _synthesize_inference_proc()
        if inf:
            name = (inf.get("model_name") or "").strip() or "batch"
            # Real status passthrough. Synthesize yields "running"/"cancelling"
            # only; "cancelling" maps onto the policy's terminal "cancelled"
            # (an existing TERMINAL_STATUSES member — no vocabulary widening)
            # so a user-stopped batch announces a CANCELLATION with a critical
            # dock bounce. A bare "cancelling" passthrough matches no policy
            # branch, and the key then vanishes via the policy's running-gated
            # disappear branch → total silence; normalizing to "running" would
            # announce "finished" (the bug this fixes). Unknown → "running".
            status = inf.get("status")
            if status == "cancelling":
                status = "cancelled"
            elif status != "running":
                status = "running"
            snap[f"inference:{name}:app"] = {
                "type": inference_job_type(inf.get("scope")),
                "name": name,
                "status": status,
                "word_key": f"inference:{name}",
            }
        return snap

    def _a11y_terminal_words(self):
        """Map snapshot keys -> stored history status for jobs that vanished.

        get_active_processes() nulls dead entries, so a subprocess that died
        non-zero reaches the policy only as a disappearance. History (written
        in the same finally-block that untracks) carries the real outcome;
        feeding it to events() makes the announcement say "failed" instead of
        the default "finished". The mapping itself now lives in
        applio_progress_api.terminal_words_from_history (history is
        newest-first, so the most recent entry for a key wins).
        """
        try:
            from applio_progress_api import terminal_words_from_history

            return terminal_words_from_history(get_recent_processes(limit=20))
        except Exception:
            logging.debug("[A11y] terminal words lookup failed", exc_info=True)
            return {}

    def _a11y_heartbeat(self):
        """Diff job states every 2 s; announce changes; refresh the dock badge.

        Zero-config speech (2026-08-23): the WEB live region owns speech
        (gated by the payload's verbosity, recomputed each tick below), so the
        native side only emits the non-speech effects: INFO logs (always —
        diagnostics, not speech) and, for terminal events, the dock attention
        request + sound cue (everyone, never VO-gated).
        """
        try:
            self._update_a11y_speech()
            snap = self._a11y_snapshot()
            if not self._a11y_primed:
                # First heartbeat: record already-running jobs silently so a
                # relaunch doesn't announce "Started X" for hour-old jobs.
                self._a11y_policy.prime(snap)
                self._a11y_primed = True
                events = []
            else:
                # Terminal words are a locked whole-file history read; only
                # pay it when a snapshot key actually disappeared.
                missing = self._a11y_policy.missing_keys(snap)
                words = self._a11y_terminal_words() if missing else {}
                events = self._a11y_policy.events(snap, terminal_words=words)
        except Exception:
            logging.debug("[A11y] snapshot failed", exc_info=True)
            return
        for kind, msg in events:
            logging.info(f"[A11y] {kind}: {msg}")
            if kind == "terminal":
                AppHelper.callAfter(self._a11y_post, msg)
        live = applio_a11y.count_live(snap)
        AppHelper.callAfter(self._a11y_update_badge, live)

    def _update_a11y_speech(self):
        """Recompute the effective announcement verbosity for this tick.

        "auto" (default) speaks exactly when VoiceOver runs, "on" always,
        "off" never — the hidden a11y.speech NSUserDefaults key is the only
        escape hatch. The result is pushed to the web payload on change so
        the live region flips within one poll cycle when VO starts/stops
        mid-session. Must never raise (the 2 s timer must never die).
        """
        try:
            override = self._read_a11y_speech_override()
            effective = effective_speech(override, voice_over_enabled())
            if effective != self._a11y_effective_verbosity:
                self._a11y_effective_verbosity = effective
                logging.info(
                    f"[A11y] speech: override={override} effective={effective}"
                )
                self._push_a11y_settings()
        except Exception:
            logging.debug("[A11y] speech update failed", exc_info=True)

    def _read_a11y_speech_override(self):
        """Hidden a11y.speech NSUserDefaults override; "auto" when unset/invalid."""
        try:
            from Foundation import NSUserDefaults

            value = NSUserDefaults.standardUserDefaults().stringForKey_("a11y.speech")
            if value in ("auto", "on", "off"):
                return value
        except Exception:
            logging.debug("[A11y] speech override read failed", exc_info=True)
        return "auto"

    def _a11y_post(self, msg):
        """Runs on the main thread. TERMINAL-event side effects only.

        The window-level AX announcement post was REMOVED (2026-08-23 owner
        ruling: unheard in 3 builds when VO focus sits in the WKWebView; the
        web live region owns speech). What remains: the dock attention
        request and the sound cue — the a11y.sound_cues defaults key gates
        sounds alone (default on, for everyone; no verbosity/VO coupling).
        The cue plays via afplay (regular output channel): NSSound system
        sounds follow the ALERT volume slider, which was muted in the
        2026-08-23 re-test while speech still worked.
        """
        try:
            from AppKit import NSApp, NSCriticalRequest, NSInformationalRequest

            bad = any(w in msg for w in ("fail", "error", "cancel", "interrupt"))
            NSApp.requestUserAttention_(
                NSCriticalRequest if bad else NSInformationalRequest
            )
            # fired BEFORE the diagnostic so the log line reports the channel
            # that actually played (_play_sound_cue never raises)
            channel = _play_sound_cue(bad) if self._a11y_sound_cues else None
            try:  # _APPLIO_AX_DIAGNOSTIC — kept for routing forensics
                element = (
                    NSApp.keyWindow() or NSApp.mainWindow() or self._main_window.native
                )
                logging.info(
                    "[A11y] terminal post: speech=%s vo=%s element=%r "
                    "sound=%s channel=%s",
                    self._read_a11y_speech_override(),
                    voice_over_enabled(),
                    element,
                    self._a11y_sound_cues,
                    channel,
                )
            except Exception:
                pass
        except Exception:
            pass

    def _a11y_update_badge(self, running):
        """Runs on the main thread. Dock badge = number of live jobs."""
        try:
            from AppKit import NSApp

            NSApp.dockTile().setBadgeLabel_(str(running) if running else None)
        except Exception:
            pass

    # ---- Accessibility settings echo (auto speech; no UI since 2026-08-23) ----

    def _push_a11y_settings(self):
        """Echo the current a11y settings to the web payload (exception-safe:
        the progress API is optional and never worth crashing the menu)."""
        try:
            import applio_progress_api

            applio_progress_api.set_settings(
                {
                    "verbosity": self._a11y_effective_verbosity or "off",
                    "sound": self._a11y_sound_cues,
                }
            )
        except Exception:
            pass

    def _find_webview(self):
        """The WKWebView contentView among NSApp.windows(), else None.

        pywebview's cocoa backend sets the WebKitHost (a WKWebView subclass)
        as the window's contentView at didFinishNavigation, so contentView()
        IS the webview. Shared by keyboard-access enablement and the AX
        layout-changed post (Task 9).
        """
        try:
            from AppKit import NSApp
            from WebKit import WKWebView
        except Exception:
            return None
        try:
            for win in NSApp.windows():
                cv = win.contentView()
                if isinstance(cv, WKWebView):
                    return cv
        except Exception:
            logging.debug("[A11y] webview enumeration failed", exc_info=True)
        return None

    def _post_webview_layout_changed(self):
        """Main thread: post an AX layout-changed notification on the webview.

        Fired via applio_progress_api's layout callback when the web payload
        reports a navigation-token change (route/view swap), so VoiceOver
        re-scans the changed region instead of staying on a stale focus.
        """
        try:
            from AppKit import (
                NSAccessibilityLayoutChangedNotification,
                NSAccessibilityPostNotification,
            )

            cv = self._find_webview()
            if cv is not None:
                NSAccessibilityPostNotification(
                    cv, NSAccessibilityLayoutChangedNotification
                )
        except Exception:
            pass

    def _find_item_by_key(self, key, menu=None):
        """Find the live NSMenuItem for an action key via self._key_to_tag, else None.

        `menu` defaults to NSApp.mainMenu(); pass an explicit menu to search a
        freshly built one that has not been installed yet."""
        target_tag = getattr(self, "_key_to_tag", {}).get(key)
        if target_tag is None:
            return None
        from AppKit import NSApp

        main = menu if menu is not None else NSApp.mainMenu()
        return _find_item_by_tag(main, target_tag)

    def _launch_time_update_check(self):
        """Silent at-launch update check. Alert only if a newer version exists.

        Skipped when running from source (not frozen): there is no build_info.json,
        so the version resolves to the upstream '3.6.3' and would false-positive
        against the fork's tagged release (e.g. '3.6.3.5'). The shipped (frozen)
        bundle reads its real version from build_info.json.

        When frozen, the check is DEFERRED ~10 s (see launchUpdateCheckFire_) so any
        alert appears AFTER the app/window is up. An alert shown at the very start of
        the run loop (before any window) renders non-modal, and dismissing it can
        terminate the app.
        """
        if not getattr(sys, "frozen", False):
            return
        try:
            from AppKit import NSTimer

            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                10.0, self, "launchUpdateCheckFire:", None, False
            )
        except Exception as e:
            logging.warning(
                f"[Launcher] launch-time update check scheduling failed: {e}"
            )

    def launchUpdateCheckFire_(self, timer):
        """One-shot NSTimer callback: run the deferred launch-time update check."""
        try:
            _update_check().check_for_updates_at_launch()
        except Exception as e:
            logging.warning(f"[Launcher] launch-time update check failed: {e}")

    # =====================================================================
    # Menu Action Methods
    # =====================================================================

    def _build_launcher_dispatch(self):
        """Map action keys -> handler (callable) or standard selector (str).

        IMPORTANT: every callable is invoked by runDispatch_ as `fn()` with NO
        arguments. The AppKit-style methods (showAbout_/checkUpdates_/etc.) are
        defined as `def X_(self, sender)`, so they MUST be wrapped to drop sender.
        """
        d = {}
        # Standard AppKit actions (responder chain / NSApp) - selector strings,
        # never go through runDispatch_.
        for key, sel in menu_spec.STANDARD_SELECTOR_KEYS.items():
            d[key] = sel
        # Custom actions - ALL zero-arg callables.
        d["app.about"] = lambda: self.showAbout_(None)
        d["app.check_updates"] = lambda: self.checkUpdates_(None)
        d["file.set_data_location"] = lambda: self.setDataLocation_(None)
        d["process.open_dashboard"] = lambda: self.showProgressMonitor_(None)
        d["process.open_logs"] = self._open_training_logs  # already zero-arg
        d["window.show_main"] = lambda: self.showMainWindow_(None)
        d["help.guide"] = self._open_guide  # already zero-arg
        d["help.docs"] = lambda: self._open_url("https://docs.applio.org")
        d["help.report_issue"] = lambda: self._open_url(
            "https://github.com/froggeric/applio-macOS-native-app/issues"
        )
        d["help.discord"] = lambda: self._open_url("https://discord.gg/IAHispano")
        for key in (
            "file.reveal_logs",
            "file.reveal_datasets",
            "file.reveal_pretraineds",
            "file.reveal_inference",
            "file.reveal_root",
        ):
            d[key] = lambda k=key: self._reveal(k)
        return d

    def _resolve_data_dir(self):
        """Fresh data-dir resolution (env -> runtime_paths.json -> ~/Applio).
        NOT a captured startup value (the env var is stale until restart)."""
        env = os.environ.get("APPLIO_DATA_PATH")
        if env:
            return env
        for cfg in (
            os.path.expanduser(
                "~/Library/Application Support/Applio/runtime_paths.json"
            ),
            os.path.expanduser("~/.applio/runtime_paths.json"),
        ):
            if os.path.exists(cfg):
                try:
                    with open(cfg, "r") as f:
                        dp = json.load(f).get("data_path")
                        if dp:
                            return dp
                except (json.JSONDecodeError, IOError):
                    pass
        return os.path.expanduser("~/Applio")

    def _first_run_done(self):
        """True once the wrapper has written runtime_paths.json (first-run complete)."""
        for cfg in (
            os.path.expanduser(
                "~/Library/Application Support/Applio/runtime_paths.json"
            ),
            os.path.expanduser("~/.applio/runtime_paths.json"),
        ):
            if os.path.exists(cfg):
                return True
        return False

    def _reveal(self, action_key):
        sub = menu_spec.REVEAL_PATHS.get(action_key, "")
        path = (
            os.path.join(self._resolve_data_dir(), sub)
            if sub
            else self._resolve_data_dir()
        )
        try:
            os.makedirs(path, exist_ok=True)
            subprocess.Popen(["open", path])
        except Exception as e:
            logging.error(f"[Launcher] reveal {action_key} failed: {e}")

    def _open_training_logs(self):
        logs = os.path.expanduser("~/Library/Logs/Applio")
        try:
            subprocess.Popen(["open", logs])
        except Exception as e:
            logging.error(f"[Launcher] open logs failed: {e}")

    def _open_guide(self):
        path = os.path.join(BASE_PATH, "STUDIO_PRODUCTION_GUIDE.html")
        if not os.path.exists(path):
            path = os.path.join(BASE_PATH, "STUDIO_PRODUCTION_GUIDE.md")
        if not os.path.exists(path):
            logging.warning("[Launcher] Studio Production Guide is not bundled")
            return
        try:
            subprocess.Popen(["open", path])
        except Exception as e:
            logging.error(f"[Launcher] open guide failed: {e}")

    def _open_url(self, url):
        try:
            subprocess.Popen(["open", url])
        except Exception as e:
            logging.error(f"[Launcher] open url failed: {e}")

    def showAbout_(self, sender):
        """Show About dialog.

        Deferred via callAfter so the modal is presented AFTER menu tracking
        finishes — calling runModal() synchronously from within a menu-item action
        (while the menu is still tracking) fails to display the alert.
        Check-for-Updates works for the same reason: it defers via callAfter.
        """
        logging.info("[Launcher] showAbout_ invoked")
        if not NATIVE_APIS_AVAILABLE:
            logging.warning("[Launcher] showAbout_: NATIVE_APIS_AVAILABLE is False")
            return
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._show_about_alert)
        except Exception as e:
            logging.error(f"[Launcher] showAbout defer failed: {e}")

    def _show_about_alert(self):
        """Build + run the About alert (on the main loop via callAfter)."""
        logging.info("[Launcher] _show_about_alert running")
        try:
            from AppKit import NSAlert, NSAlertStyleInformational, NSApp

            import applio_i18n

            _t = applio_i18n.native_tr

            # Single source of truth: applio_update_check.VERSION reads
            # Contents/Resources/build_info.json -> "3.6.3.5" (multi-root search).
            version = _update_check().VERSION
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Applio")
            alert.setInformativeText_(
                f"Version {version}\n\n"
                + "\n".join(
                    [
                        _t("Voice Conversion Application"),
                        _t("Based on RVC (Retrieval-Based Voice Conversion)"),
                        "",
                        _t("Native macOS port by Frédéric Guigand"),
                        _t("© 2024-2026 IA Hispano"),
                    ]
                )
            )
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.addButtonWithTitle_("OK")
            # The Gradio window can hold focus; bring the
            # launcher forward so the modal is actually visible.
            try:
                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass
            alert.runModal()
        except Exception as e:
            logging.error(f"[Launcher] About alert failed: {e}")

    def checkUpdates_(self, sender):
        """Check for updates - real GitHub check (shared module)."""
        _update_check().check_for_updates_interactive()

    def setDataLocation_(self, sender):
        """Open dialog to set data location."""
        if not NATIVE_APIS_AVAILABLE:
            return

        import applio_i18n

        _t = applio_i18n.native_tr

        if not self._first_run_done():
            from AppKit import NSAlert, NSAlertStyleInformational

            alert = NSAlert.alloc().init()
            alert.setMessageText_(_t("Choose a Data Location First"))
            alert.setInformativeText_(
                _t(
                    "Applio is asking you to choose where to store its data. "
                    "Please complete that prompt first, then you can change it here."
                )
            )
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.addButtonWithTitle_(_t("OK"))
            alert.runModal()
            return

        from AppKit import NSOpenPanel, NSFileHandlingPanelOKButton

        # Create open panel configured to select folders
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setMessage_(
            _t("Select a folder to store Applio data (models, training, logs):")
        )
        panel.setPrompt_(_t("Choose"))

        # Get current data path as starting point
        current_path = os.environ.get(
            "APPLIO_DATA_PATH", os.path.expanduser("~/Applio")
        )
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
                alert.setMessageText_(_t("Restart Required"))
                alert.setInformativeText_(
                    _t(
                        "Data location set to:\n{path}\n\n"
                        "Please restart Applio for this change to take effect."
                    ).format(path=new_path)
                )
                alert.setAlertStyle_(NSAlertStyleWarning)
                alert.addButtonWithTitle_(_t("OK"))
                alert.runModal()

    def showProgressMonitor_(self, sender):
        """Show the progress monitor dashboard.

        Always shows the dashboard, even in idle state.
        The dashboard transitions between idle/active states automatically.
        """
        logging.info("[Launcher] Progress Monitor menu item selected")

        # Create dashboard on first use
        if not self._dashboard_controller:
            self._create_dashboard()

        # Show the dashboard
        if self._dashboard_controller:
            # Update process list before showing
            self._dashboard_controller.update_process_list()
            self._dashboard_controller.show()
            logging.info("[Launcher] Dashboard shown")

    def showMainWindow_(self, sender):
        """Show the main Gradio window (lives in THIS process)."""
        logging.info("[Launcher] Show Main Window requested")
        if self._main_window:
            # The window lives in THIS process — show it directly.
            try:
                AppHelper.callAfter(self._main_window.show)
                from AppKit import NSApp

                NSApp.activateIgnoringOtherApps_(True)
            except Exception as e:
                logging.warning(f"[Launcher] Show Main Window failed: {e}")

    def _create_dashboard(self):
        """Create the ProcessDashboardController instance.

        Called lazily when Progress Monitor is first accessed.
        """
        if not NATIVE_APIS_AVAILABLE:
            logging.warning(
                "[Launcher] Cannot create dashboard - native APIs unavailable"
            )
            return

        try:
            logging.info("[Launcher] Creating ProcessDashboardController")
            self._dashboard_controller = (
                ProcessDashboardController.alloc().initWithLauncher_(self)
            )
            logging.info("[Launcher] ProcessDashboardController created successfully")
        except Exception as e:
            logging.error(f"[Launcher] Failed to create dashboard: {e}")
            self._dashboard_controller = None

    def _show_progress_window_for_processes(self, processes):
        """Show progress window for the first active process."""
        logging.info(
            f"[Launcher] _show_progress_window_for_processes called with {len(processes)} processes"
        )

        # Warn if multiple processes active (only showing first)
        if len(processes) > 1:
            process_types = [p["type"] for p in processes]
            logging.warning(
                f"[Launcher] {len(processes)} processes active ({process_types}), only showing first ({processes[0]['type']})"
            )

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
        logging.info(
            f"[Launcher] Creating ProgressWindowController for {proc['type']}: {proc.get('model_name', 'Unknown')}"
        )
        self.progress_window = ProgressWindowController(
            proc["type"], {k: v for k, v in proc.items() if k != "type"}
        )
        logging.info("[Launcher] Calling progress_window.show()")
        self.progress_window.show()
        logging.info("[Launcher] progress_window.show() completed")

    def _cleanup(self):
        """Clean up on exit."""
        # Remove IPC observer
        if self._dist_center:
            try:
                self._dist_center.removeObserver_(self)
            except Exception:
                pass

        # Stop menu update timer
        if self._menu_update_timer:
            self._menu_update_timer.invalidate()
            self._menu_update_timer = None

        # Clean up progress window (invalidates its timer and observer)
        if self.progress_window:
            self.progress_window._cleanup()
            self.progress_window = None


# =================================================================
# 7. Entry Point
# =================================================================

if __name__ == "__main__":
    launcher = ApplioLauncher()
    launcher.start()
