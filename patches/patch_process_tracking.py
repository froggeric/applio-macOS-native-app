#!/usr/bin/env python3
"""
Patcher to add process tracking to core.py subprocess calls.

Upstream 3.7.2 launches every worker with `result = run_quiet(<command>)` and then
checks `result.returncode` itself (and `result.stderr` for TTS). This patcher replaces
each tracked launch line with `_applio_tracked_run(...)`, a drop-in that returns a
`subprocess.CompletedProcess`, so upstream's handling after the call is left untouched,
and records the child's PID in active_processes.json for the launcher's Progress
Monitor (pause / resume / terminate, log tailing, process history).

Tracked call sites, all required:
  - run_preprocess_script  -> "preprocess"  log: <logs>/<model>/preprocess.log
  - run_extract_script     -> "extract"     log: <logs>/<model>/extract.log
  - run_train_script       -> "training"    log: <logs>/<model>/training.log
  - run_tts_script         -> "tts"         stdout/stderr captured, as upstream does

run_index_script is left on upstream's run_quiet(): the index step was never tracked
(the launcher has no "index" process type) and upstream now checks its return code.

Tracked children that get a log file do not inherit APPLIO_TERMINAL_LOG. Upstream's
worker scripts call capture_worker_output() (rvc/lib/terminal.py), which re-points
their stdout/stderr at the UI session log when that variable is set, bypassing the
per-process log file the launcher tails. The per-process log is forwarded to that
session log instead, so upstream's Terminal tab still shows the worker's output.

Exit codes: 0 = applied or already applied; 2 = a required anchor was not found or the
patched file failed verification (nothing is written then).

Applied at build time by build_macos.py.
"""

import os
import re
import sys

EXIT_OK = 0
EXIT_FAILED = 2

TAG = "[patch_process_tracking]"

# Helper functions injected before `def run_quiet(` in core.py.
# `datetime` is imported under an alias on purpose: core.py does
# `from datetime import datetime, timedelta`, so a bare `import datetime` here would
# rebind the name to the module and break every later `datetime.now()` in core.py.
PROCESS_TRACKER_HELPERS = '''# === Process Tracking (injected by patch) ===
import json
import datetime as _applio_datetime
import fcntl
import time as _time_module
import threading

_PROCESS_STATE_FILE = None
_PROCESS_LOCK_TIMEOUT = 5.0
_history_thread_lock = threading.Lock()  # Thread safety for history operations

def _get_process_state_path():
    global _PROCESS_STATE_FILE
    if _PROCESS_STATE_FILE is None:
        data_path = os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))
        _PROCESS_STATE_FILE = os.path.join(data_path, ".applio", "active_processes.json")
    return _PROCESS_STATE_FILE

def _acquire_file_lock(lock_file, timeout=_PROCESS_LOCK_TIMEOUT):
    """Acquire exclusive file lock with timeout."""
    start_time = _time_module.time()
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            if _time_module.time() - start_time > timeout:
                return False
            _time_module.sleep(0.05)

def _release_file_lock(lock_file):
    """Release file lock."""
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except (IOError, OSError):
        pass

def _read_process_state():
    path = _get_process_state_path()
    if not os.path.exists(path):
        return {"version": 1, "processes": {}}
    lock_path = path + ".lock"
    try:
        # Use "a" mode to avoid truncating before lock is acquired
        with open(lock_path, "a") as lock_file:
            if not _acquire_file_lock(lock_file):
                pass  # Proceed anyway
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            finally:
                _release_file_lock(lock_file)
    except (json.JSONDecodeError, IOError):
        return {"version": 1, "processes": {}}

def _write_process_state(state):
    path = _get_process_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock_path = path + ".lock"
    try:
        # Use "a" mode to avoid truncating before lock is acquired
        with open(lock_path, "a") as lock_file:
            if not _acquire_file_lock(lock_file):
                pass  # Proceed anyway
            try:
                temp = path + ".tmp"
                with open(temp, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
                os.rename(temp, path)
            finally:
                _release_file_lock(lock_file)
    except IOError as e:
        print(f"[ProcessTracking] Error saving state: {e}")

def _verify_process_identity(pid, expected_start_time=None):
    """Verify a process is still the same one we started (protects against PID recycling)."""
    if not pid:
        return False
    try:
        import psutil
        proc = psutil.Process(pid)
        if expected_start_time:
            if isinstance(expected_start_time, str):
                expected = _applio_datetime.datetime.fromisoformat(expected_start_time)
            else:
                expected = expected_start_time
            actual = _applio_datetime.datetime.fromtimestamp(proc.create_time())
            delta = abs((actual - expected).total_seconds())
            if delta > 2.0:
                return False
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

def _track_process(process_type, pid, **metadata):
    state = _read_process_state()
    state["processes"][process_type] = {
        "pid": pid,
        "started_at": _applio_datetime.datetime.now().isoformat(),
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

# === Process History Tracking ===
_HISTORY_MAX_ENTRIES = 50
# Cap on plotted epoch points in a history snapshot (matches the live path's
# MAX_EPOCH_POINTS in applio_launcher). A real run evaluates far fewer.
_SNAPSHOT_MAX_POINTS = 2000


def _get_history_file_path():
    """Get path to process_history.json."""
    state_path = _get_process_state_path()
    return os.path.join(os.path.dirname(state_path), "process_history.json")

def _read_process_history():
    """Read process history from file."""
    path = _get_history_file_path()
    if not os.path.exists(path):
        return {"version": 1, "history": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"version": 1, "history": []}

def _write_process_history(history):
    """Write process history to file."""
    path = _get_history_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock_path = path + ".lock"
    try:
        with open(lock_path, "a") as lock_file:
            if not _acquire_file_lock(lock_file):
                pass  # Proceed anyway
            try:
                temp = path + ".tmp"
                with open(temp, "w", encoding="utf-8") as f:
                    json.dump(history, f, indent=2)
                os.rename(temp, path)
            finally:
                _release_file_lock(lock_file)
    except IOError as e:
        print(f"[ProcessTracking] Error saving history: {e}")

def _add_to_history(entry):
    """Add a completed process to history (thread-safe with validation)."""
    # Validate required fields
    required = ["type", "started_at", "completed_at"]
    for field in required:
        if not entry.get(field):
            print(f"[ProcessTracking] Warning: Missing required field '{field}' in history entry")
            return

    with _history_thread_lock:
        history = _read_process_history()
        # Generate unique process ID
        process_id = f"{entry.get('type', 'unknown')}-{entry.get('started_at', _applio_datetime.datetime.now().isoformat())}"
        entry["process_id"] = process_id
        # Add to front of list
        history["history"].insert(0, entry)
        # Enforce max entries
        if len(history["history"]) > _HISTORY_MAX_ENTRIES:
            history["history"] = history["history"][:_HISTORY_MAX_ENTRIES]
        _write_process_history(history)

def _snapshot_training_metrics(log_file_path, prior_points=None):
    """Snapshot final best-epoch metrics from a training.log into history.

    Mirrors applio_launcher._parse_training_log_line semantics but uses
    string-split parsing (no regex) so it embeds cleanly into this injected
    triple-quoted template without backslash-escape issues. Runs in the
    training subprocess (core.py) which cannot import the launcher helper.
    Frozen-safe: stdlib only (os). Returns None when the log is missing or
    has no evaluated epochs. epoch_points is [[epoch, best_loss], ...] for the
    dashboard's loss-vs-epoch graph (Feature 3) and survives a retrain that
    overwrites the per-model training.log (Feature 1 durability).

    prior_points: optional [[epoch, loss], ...] captured by run_train_script
    from the PREVIOUS training.log before this run truncated it. Resumed runs
    reopen the log with mode "w", wiping every pre-resume epoch, so without
    this the curve would show only the resumed tail (the original "~5 points"
    symptom). We merge prior_points back in for a genuine resume (see below).
    """
    if not log_file_path or not os.path.exists(log_file_path):
        return None
    points = []
    last_epoch = None
    best_epoch = None
    best_loss = None
    try:
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                # Only full evaluation lines carry lowest_value (epoch > 1).
                if "epoch=" not in line or "lowest_value=" not in line:
                    continue
                try:
                    after_epoch = line.split("epoch=", 1)[1]
                    epoch = int(after_epoch.split("|", 1)[0].strip())
                    after_lv = line.split("lowest_value=", 1)[1]
                    loss = float(after_lv.split("(", 1)[0].strip())
                    after_be = after_lv.split("epoch", 1)[1]
                    best_epoch = int(after_be.split("and", 1)[0].strip())
                except (ValueError, IndexError):
                    continue
                last_epoch = epoch
                best_loss = loss
                points.append([epoch, loss])
    except (IOError, OSError):
        return None
    if last_epoch is None:
        return None
    # Resume handling. training.log is truncated (open "w") on every run start,
    # so a RESUMED run only contains its post-resume epochs here -- merge the
    # prior lineage (captured before truncation) so the curve is whole. A fresh
    # start's first evaluated epoch is 2 (epoch 1 has no lowest_value), so a
    # current min epoch > 2 means this run picked up mid-way; a fresh retrain
    # (min epoch 2) DISCARDS the prior lineage so retraining the same model
    # never drags in a stale curve. On epoch overlap the current run wins.
    if prior_points:
        try:
            cur_min = min(p[0] for p in points)
        except ValueError:
            cur_min = None
        if cur_min is not None and cur_min > 2:
            merged = {}
            for pp in prior_points:
                try:
                    merged[int(pp[0])] = float(pp[1])
                except (TypeError, ValueError, IndexError):
                    continue
            for e, l in points:
                merged[e] = l
            points = sorted([[e, l] for e, l in merged.items()])
    # Bound output for pathologically long lineages (matches the live path's
    # MAX_EPOCH_POINTS): keep the most recent evaluated epochs.
    if len(points) > _SNAPSHOT_MAX_POINTS:
        points = points[-_SNAPSHOT_MAX_POINTS:]
    return {
        "best_epoch": best_epoch,
        "best_loss": best_loss,
        "final_epoch": last_epoch,
        "epoch_points": points,
    }

# === End Process History Tracking ===

# === End Process History Tracking ===

def _applio_child_env():
    """Child environment without APPLIO_TERMINAL_LOG.

    Upstream's worker scripts call capture_worker_output(), which re-points their
    stdout/stderr at the UI session log when that variable is set. The launcher tails
    our per-process log file instead, so the variable must not reach the child.
    """
    env = os.environ.copy()
    env.pop("APPLIO_TERMINAL_LOG", None)
    return env

def _applio_tee_to_session_log(log_path):
    """Forward a per-process log into upstream's terminal session log, if there is one.

    Tracked workers do not get APPLIO_TERMINAL_LOG (see _applio_child_env()), so
    upstream's Terminal tab would not show their output. This copies it there
    while the launcher keeps tailing the per-process file. Returns a function
    that stops the forwarding after one final copy, or None when there is no
    session log.
    """
    session_log = os.environ.get("APPLIO_TERMINAL_LOG")
    if not session_log:
        return None
    stop = threading.Event()
    done = threading.Event()

    def copy_out(position):
        data = b""
        try:
            with open(log_path, "rb") as source:
                source.seek(position)
                data = source.read()
            if data:
                with open(session_log, "ab") as target:
                    target.write(data)
        except OSError:
            pass
        return position + len(data)

    def run():
        position = 0
        while True:
            position = copy_out(position)
            if stop.is_set():
                break
            stop.wait(0.25)
        copy_out(position)
        done.set()

    def stop_copying():
        stop.set()
        done.wait(2)  # returns once the last copy is written (2 s at most)

    threading.Thread(target=run, name="applio-log-tee", daemon=True).start()
    return stop_copying

def _applio_tracked_run(process_type, command, model_name=None, log_file=None,
                        capture_output=False, text=False, **metadata):
    """Run one child in place of run_quiet() and report it to the Progress Monitor.

    Returns subprocess.CompletedProcess, so callers keep using result.returncode,
    result.stdout and result.stderr exactly as with subprocess.run().
    """
    started_at = _applio_datetime.datetime.now().isoformat()
    log_path = None
    log_handle = None
    stop_tee = None
    prior_points = None
    popen_kwargs = {}
    track_metadata = dict(metadata)
    if capture_output:
        popen_kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text)
    elif log_file:
        log_dir = os.path.join(logs_path, model_name or "")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, log_file)
        if process_type == "training" and os.path.exists(log_path):
            # Capture this model's existing epoch curve BEFORE truncating the log
            # below. A resumed run reopens training.log with "w", wiping every
            # pre-resume epoch; handing those points to _snapshot_training_metrics
            # lets it merge the full lineage back together.
            try:
                _prior_snap = _snapshot_training_metrics(log_path)
                prior_points = _prior_snap["epoch_points"] if _prior_snap else None
            except Exception:
                prior_points = None
        log_handle = open(log_path, "w")
        stop_tee = _applio_tee_to_session_log(log_path)
        track_metadata["log_file"] = log_path
        popen_kwargs.update(
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=_applio_child_env(),
        )
    if model_name is not None:
        track_metadata["model_name"] = model_name

    proc = None
    stdout = stderr = None
    try:
        proc = subprocess.Popen(command, **popen_kwargs)
        _track_process(process_type, proc.pid, **track_metadata)
        if capture_output:
            stdout, stderr = proc.communicate()
        else:
            proc.wait()
    finally:
        if stop_tee is not None:
            stop_tee()  # copies what is left, then ends the forwarding thread
        if log_handle is not None:
            log_handle.close()
        # Add to history BEFORE untracking: once the key leaves
        # active_processes.json the terminal word must already be in
        # process_history.json (untrack-then-write raced heartbeat readers).
        try:
            history = {
                "type": process_type,
                "model_name": (
                    model_name if model_name is not None else process_type.upper()
                ),
                "started_at": started_at,
                "completed_at": _applio_datetime.datetime.now().isoformat(),
                "status": (
                    "completed" if proc is not None and proc.returncode == 0 else "failed"
                ),
            }
            if log_path:
                history["log_path"] = log_path
            if "total_epoch" in metadata:
                history["total_epoch"] = metadata["total_epoch"]
            if process_type == "training" and log_path:
                # Snapshot final metrics so they survive a retrain overwriting
                # training.log. The snapshot opens the log itself, so it runs
                # after the handle is closed. The pre-truncation points make a
                # resumed run's curve span its whole lineage.
                try:
                    _snapshot = _snapshot_training_metrics(log_path, prior_points)
                except Exception:
                    _snapshot = None
                if _snapshot:
                    history["best_epoch"] = _snapshot["best_epoch"]
                    history["best_loss"] = _snapshot["best_loss"]
                    history["final_epoch"] = _snapshot["final_epoch"]
                    history["epoch_points"] = _snapshot["epoch_points"]
            _add_to_history(history)
        except Exception:
            pass
        try:
            _untrack_process(process_type)
        except Exception:
            pass

    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)

# === End Process Tracking ===


'''

HELPERS_MARKER = "# === Process Tracking (injected by patch) ==="
HELPERS_ANCHOR = "def run_quiet(command, **kwargs):\n"
TRACKED_RUN_DEF = "def _applio_tracked_run("
CHILD_ENV_MARKER = 'env.pop("APPLIO_TERMINAL_LOG", None)'
TEE_DEF = "def _applio_tee_to_session_log("
TEE_USE = "stop_tee = _applio_tee_to_session_log(log_path)"

# One entry per tracked launch: (function, anchor, replacement for its first line,
# marker once applied).
#
# `anchor` is upstream's exact text: the run_quiet call plus the start of upstream's
# own return-code handling. The tail matters: three launch lines are textually
# identical (`result = run_quiet(command)`), and run_index_script's copy must stay
# untouched. Only the first line is replaced, the tail is kept verbatim.
CALL_SITES = [
    (
        "run_preprocess_script",
        "    result = run_quiet(command)\n"
        "    if result.returncode != 0:\n"
        '        return f"Preprocessing failed for model {model_name}.',
        '    result = _applio_tracked_run("preprocess", command, model_name, "preprocess.log")\n',
        '_applio_tracked_run("preprocess",',
    ),
    (
        "run_extract_script",
        "    result = run_quiet(command_1)\n"
        "    if result.returncode != 0:\n"
        '        return f"Feature extraction failed for model {model_name}.',
        '    result = _applio_tracked_run("extract", command_1, model_name, "extract.log")\n',
        '_applio_tracked_run("extract",',
    ),
    (
        "run_train_script",
        "    result = run_quiet(command)\n"
        "    if result.returncode != 0:\n"
        '        return f"Training failed for model {model_name}.',
        "    result = _applio_tracked_run("
        '"training", command, model_name, "training.log", total_epoch=total_epoch)\n',
        '_applio_tracked_run("training",',
    ),
    (
        "run_tts_script",
        "    result = run_quiet(cmd, capture_output=True, text=True)\n"
        "    if result.returncode != 0:\n"
        "        err_msg = result.stderr.strip()\n",
        '    result = _applio_tracked_run("tts", cmd, capture_output=True, text=True)\n',
        '_applio_tracked_run("tts",',
    ),
]

# Upstream code that must survive the patch untouched (exact text, counted before and
# after): the return-code checks, TTS stderr handling, the untracked index launch and
# the shutdown branch that follows the training run.
PRESERVED_UPSTREAM = [
    "if result.returncode != 0:",
    "        err_msg = result.stderr.strip()",
    "    result = run_quiet(command)\n"
    "    if result.returncode != 0:\n"
    '        return f"Index generation failed for model {model_name}.',
    "    run_index_script(model_name, index_algorithm)\n\n    if shutdown_check:",
]

BARE_DATETIME_IMPORT = re.compile(r"^import datetime\s*$", re.MULTILINE)


def apply_call_site(content, name, anchor, new_first_line, marker):
    """Replace one launch line.

    Returns (content, status, reason) with status "applied", "already" or "missing".
    """
    if marker in content:
        return content, "already", None
    old_first_line = anchor.split("\n", 1)[0] + "\n"
    count = content.count(anchor)
    if count != 1:
        return (
            content,
            "missing",
            (
                f"expected exactly 1 match of the `{old_first_line.strip()}` launch line "
                f"followed by upstream's return-code check, found {count}"
            ),
        )
    replacement = new_first_line + anchor[len(old_first_line) :]
    return content.replace(anchor, replacement, 1), "applied", None


def verify(original, content):
    """Return a list of problems; empty means the patched content is complete."""
    problems = []

    required_markers = [
        HELPERS_MARKER,
        TRACKED_RUN_DEF,
        CHILD_ENV_MARKER,
        TEE_DEF,
        TEE_USE,
    ] + [marker for _, _, _, marker in CALL_SITES]
    for marker in required_markers:
        count = content.count(marker)
        if count != 1:
            problems.append(
                f'verification: expected exactly 1 "{marker}", found {count}'
            )

    for text in PRESERVED_UPSTREAM:
        if content.count(text) != original.count(text):
            problems.append(
                f'verification: upstream code was altered: "{text.splitlines()[0].strip()}"'
            )

    if BARE_DATETIME_IMPORT.search(content):
        problems.append(
            "verification: a bare `import datetime` would shadow core.py's "
            "`from datetime import datetime`"
        )

    try:
        compile(content, "core.py", "exec")
    except SyntaxError as error:
        problems.append(f"verification: patched core.py does not compile: {error}")

    return problems


def patch_core_py(base_path: str) -> int:
    """Apply process tracking to core.py; returns the process exit code."""
    core_py_path = os.path.join(base_path, "core.py")
    try:
        with open(core_py_path, "r", encoding="utf-8") as f:
            original = f.read()
    except OSError as error:
        print(f"{TAG} Cannot read {core_py_path}: {error}")
        return EXIT_FAILED

    content = original
    failures = []
    statuses = []

    if HELPERS_MARKER in content and TRACKED_RUN_DEF not in content:
        failures.append(
            "helper functions: core.py already carries a helper block without "
            f"`{TRACKED_RUN_DEF[:-1]}` (older patcher version); start from a pristine core.py"
        )
    elif HELPERS_MARKER in content:
        statuses.append(("helper functions", "already applied"))
    elif content.count(HELPERS_ANCHOR) != 1:
        failures.append(
            f"helper functions: expected exactly 1 `def run_quiet(command, **kwargs):` "
            f"definition, found {content.count(HELPERS_ANCHOR)}"
        )
    else:
        content = content.replace(
            HELPERS_ANCHOR, PROCESS_TRACKER_HELPERS + HELPERS_ANCHOR, 1
        )
        statuses.append(("helper functions", "applied"))

    for name, anchor, new_first_line, marker in CALL_SITES:
        content, status, reason = apply_call_site(
            content, name, anchor, new_first_line, marker
        )
        if status == "missing":
            failures.append(f"{name}: {reason}")
        statuses.append((name, status))

    if not failures:
        failures = verify(original, content)
    if failures:
        for failure in failures:
            print(f"{TAG} FAILED - {failure}")
        print(f"{TAG} core.py left unchanged")
        return EXIT_FAILED

    for name, status in statuses:
        print(f"{TAG} {name}: {status}")

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

    print(f"{TAG} Patched core.py: {', '.join(name for name, _, _, _ in CALL_SITES)}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(patch_core_py(sys.argv[1] if len(sys.argv) > 1 else "."))
