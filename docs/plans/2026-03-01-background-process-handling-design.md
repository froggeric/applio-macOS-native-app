# Background Process Handling Design

**Date:** 2026-03-01
**Status:** Approved
**Task:** #13

## Problem Statement

When the user closes the Applio app while training or other long-running processes are active, the subprocess continues running in the background as an orphaned process. The user has no visibility or control over the process.

## Design Goals

1. Detect active processes when closing the app
2. Offer user choice: terminate or keep running with monitoring
3. Provide minimal progress window with real-time logs
4. Enable pause/resume/terminate control
5. Survive app crashes (file-based state)

## Architecture Overview

```
+-------------------------------------------------------------+
|                      macos_wrapper.py                        |
+-------------------------------------------------------------+
|  +-----------------+    +----------------------------------+ |
|  | Main Gradio UI  |    | Progress Monitor Window          | |
|  |                 |    |  - Reads active_processes.json   | |
|  |  On close ----- |--->|  - Tails existing log files      | |
|  |  with active    |    |  - Pause/Resume via SIGSTOP/CONT | |
|  |  processes      |    |  - Terminate via SIGTERM         | |
|  +-----------------+    +----------------------------------+ |
|           |                          |                        |
|           v                          v                        |
|  +-------------------------------------------------------+   |
|  |              active_processes.json                     |   |
|  |  { "training": {...}, "inference": {...}, "tts": {...}}|   |
|  +-------------------------------------------------------+   |
|           ^                          |                        |
+-----------|--------------------------|------------------------+
            |                          |
+-----------|--------------------------|------------------------+
|           |   patches/patch_process_ |                        |
|           |   tracking.py            |                        |
|           |                          |                        |
|  +--------+----------+    +----------v------------------+     |
|  | run_train_script  |    | run_inference_script       |     |
|  |  - Popen instead  |    | run_tts_script             |     |
|  |  - Write to JSON  |    |  - Write to JSON on start  |     |
|  |  - Clear on done  |    |  - Clear on completion     |     |
|  +-------------------+    +----------------------------+     |
|                    Applied at build time                     |
+-------------------------------------------------------------+
```

**Key Principle:** The file `active_processes.json` is the single source of truth.

## Process State File

**Location:** `~/.applio/active_processes.json`

```json
{
  "version": 1,
  "processes": {
    "training": {
      "pid": 12345,
      "model_name": "MyVoice-48k",
      "started_at": "2026-03-01T14:30:00Z",
      "log_path": "/Users/frederic/Applio/logs/MyVoice-48k/training.log",
      "status": "running"
    },
    "inference": null,
    "tts": null,
    "preprocess": null,
    "extract": null
  }
}
```

### Process Types

| Key | Triggered By | Log Location |
|-----|--------------|--------------|
| `training` | `run_train_script()` | `logs/{model}/training.log` |
| `preprocess` | `run_preprocess_script()` | `logs/{model}/preprocess.log` |
| `extract` | `run_extract_script()` | `logs/{model}/extract.log` |
| `inference` | `voice_conversion()` | Wrapper log only |
| `tts` | TTS functions | Wrapper log only |

### Status Values

- `running` - Normal operation
- `paused` - SIGSTOP sent, awaiting SIGCONT
- `completed` - Process finished

## Core.py Patch

**Patch File:** `patches/patch_process_tracking.py`

### Transformation Pattern

**Before:**
```python
subprocess.run(command)
return f"Model {model_name} trained successfully."
```

**After:**
```python
# Write to active_processes.json
_process_file = os.path.join(os.getcwd(), ".applio", "active_processes.json")
_process_entry = {"pid": None, "model_name": model_name, "started_at": datetime.now().isoformat(), "status": "running"}

# Use Popen instead of run
proc = subprocess.Popen(command)
_process_entry["pid"] = proc.pid

# Wait for completion
proc.wait()

# Clear from active_processes.json

# Check return code
if proc.returncode != 0:
    return f"Error: Training failed with code {proc.returncode}"

return f"Model {model_name} trained successfully."
```

### Functions to Patch

| Function | Process Type |
|----------|--------------|
| `run_preprocess_script()` | `preprocess` |
| `run_extract_script()` | `extract` |
| `run_train_script()` | `training` |
| `voice_conversion()` | `inference` |

## Close Confirmation Dialog

**Trigger:** User closes main window while processes are active.

```
+-------------------------------------------------------------+
|  [!] Active Processes                              [Close]  |
+-------------------------------------------------------------+
|                                                              |
|   The following processes are still running:                 |
|                                                              |
|   - Training: MyVoice-48k (Epoch 3/10)                      |
|   - Inference: Converting audio...                           |
|                                                              |
|   What would you like to do?                                 |
|                                                              |
|   +---------------------+  +-----------------------------+   |
|   |  Terminate & Quit   |  |  Keep Running in Background |   |
|   +---------------------+  +-----------------------------+   |
|                                                              |
+-------------------------------------------------------------+
```

## Progress Monitoring Window

### Collapsed View (Default)

```
+-------------------------------------------------------------+
|  [gear] Applio Training Monitor                     [-][x]  |
+-------------------------------------------------------------+
|                                                              |
|   ===============================---------  42%             |
|                                                              |
|   Training: MyVoice-48k                                      |
|   Epoch 3/10 - Step 234/500                                  |
|   Elapsed: 1h 23m - ETA: 4h 15m                              |
|                                                              |
|   +------------+  +------------+  +------------------+       |
|   |  Terminate |  |    Pause   |  |  Relaunch App    |       |
|   +------------+  +------------+  +------------------+       |
|                                                              |
|   [ v Show Log Output ]                                      |
|                                                              |
+-------------------------------------------------------------+
   Size: 480x220 (collapsed)
```

### Expanded View

```
+-------------------------------------------------------------+
|  [Same header section]                                       |
|  [ ^ Hide Log Output ]                                       |
+-------------------------------------------------------------+
|  +-------------------------------------------------------+  |
|  | 2026-03-01 15:23:45 | Epoch 3 started                |  |
|  | 2026-03-01 15:24:12 | Step 234/500 - loss: 0.0342   |  |
|  | 2026-03-01 15:24:45 | Step 235/500 - loss: 0.0338   |  |
|  | ...                                                   |  |
|  | [auto-scrolling to latest]                            |  |
|  +-------------------------------------------------------+  |
+-------------------------------------------------------------+
   Size: 600x400 (expanded)
```

## Signal Handling

| Signal | Constant | Effect | Use Case |
|--------|----------|--------|----------|
| SIGSTOP | 19 | Freeze process immediately | Pause |
| SIGCONT | 18 | Resume frozen process | Resume |
| SIGTERM | 15 | Graceful termination request | Terminate (preferred) |
| SIGKILL | 9 | Immediate forced termination | Force quit (last resort) |

### ProcessController Class

```python
class ProcessController:
    @staticmethod
    def pause(pid: int) -> bool:
        os.kill(pid, signal.SIGSTOP)
        _update_process_status(pid, "paused")

    @staticmethod
    def resume(pid: int) -> bool:
        os.kill(pid, signal.SIGCONT)
        _update_process_status(pid, "running")

    @staticmethod
    def terminate(pid: int, force: bool = False) -> bool:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)
        _clear_process(pid)

    @staticmethod
    def terminate_all():
        # Kill all tracked processes
        ...
```

## Implementation Tasks

| Task | Description | Blocked By |
|------|-------------|------------|
| #14 | Process tracking helper module | - |
| #15 | patch_process_tracking.py | - |
| #16 | Close confirmation dialog | #14 |
| #17 | Progress monitoring window | #14, #16 |
| #18 | Integration and testing | #14, #15, #16, #17 |

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `macos_wrapper.py` | Modify | Add ProcessController, helpers, dialogs |
| `patches/patch_process_tracking.py` | Create | Patch core.py subprocess calls |
| `assets/progress_monitor.html` | Create | Progress window HTML |
| `build_macos.py` | Modify | Register new patch |
| `requirements_macos.txt` | Modify | Add psutil if needed |

## Safety Considerations

1. **Process validation** - Always check `psutil.pid_exists()` before signaling
2. **Stale PID cleanup** - On app start, clear entries for PIDs that no longer exist
3. **Orphan detection** - If progress window opens and process is gone, show "Process completed"
4. **Idempotent patches** - All patches must be safe to run multiple times
