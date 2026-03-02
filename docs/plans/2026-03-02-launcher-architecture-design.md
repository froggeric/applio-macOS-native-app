# Design: Launcher Process Architecture

**Date:** 2026-03-02
**Status:** Approved
**Author:** Claude Code

## Overview

Refactor Applio.app to use a launcher process architecture where a parent process (`applio_launcher.py`) spawns and monitors the existing wrapper (`macos_wrapper.py`) as a child process. This enables proper log visibility and process control.

## Problem Statement

The current architecture has a fundamental issue: the progress monitoring window runs inside the same process as the pywebview wrapper, making it impossible to capture training subprocess stdout/stderr. Training logs (epoch progress, tqdm bars, save messages) are lost because they go to stdout which isn't connected to the progress window.

## Solution: Launcher Process Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  applio_launcher.py (Process Group Leader)                         │
│                                                                     │
│  - Spawns macos_wrapper.py as child process                         │
│  - Hosts ProgressWindowController (PyObjC native window)            │
│  - Manages native macOS menu                                        │
│  - Tails log files for progress display                             │
│  - Signal handling (SIGCHLD, SIGINT, SIGTERM)                       │
│  - Process lifecycle management                                      │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ subprocess.Popen()
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│  macos_wrapper.py (Child Process)                                   │
│                                                                     │
│  - PyWebView window for Gradio UI                                   │
│  - Spawns training/inference subprocesses                           │
│  - Writes logs to files (via patched core.py)                       │
│  - Updates active_processes.json                                    │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ subprocess.Popen(stdout=log_file)
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│  Training/Inference Subprocesses                                    │
│                                                                     │
│  - stdout/stderr → logs/{model_name}/training.log                   │
│  - PID tracked in active_processes.json                             │
└────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Log storage | Per-model file | Fits existing `logs/{model_name}/` structure |
| Log format | Plain text | Compatible with tqdm, human-readable |
| Tailing method | Polling (0.5s) | Simpler than watchdog, sufficient for training speed |
| Process tracking | JSON file | Reuse `active_processes.json`, add log_file field |
| Event loop | Per-process | Each process has its own NSApplication event loop |

## Component Specifications

### applio_launcher.py (New - Entry Point)

**Responsibilities:**
- Process group leader
- Spawns macos_wrapper.py as subprocess
- Hosts ProgressWindowController
- Native macOS menu management
- Signal handling (SIGCHLD, SIGINT, SIGTERM)
- Log file tailing
- Auto-detection of running processes on launch
- Runs own NSApplication event loop

**Key Classes:**
- `ApplioLauncher` - Main orchestrator
- `ProgressWindowController` - Native monitoring window (moved from wrapper)
- `MenuController` - Native menu management

### macos_wrapper.py (Modified - Child Process)

**Removed:**
- `ProgressWindowController` class (~350 lines)
- `show_progress_window()` function
- `show_close_confirmation_dialog()` function
- Close confirmation logic in `on_window_closing()`

**Added:**
- Simple hide-on-close behavior
- Notification to launcher via signal file

### patches/patch_process_tracking.py (Modified)

**Changes:**
- Redirect subprocess stdout/stderr to log file
- Track log_file path in active_processes.json

```python
# New pattern
log_file_path = os.path.join(logs_path, model_name, "training.log")
log_file = open(log_file_path, "a")
_proc = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)
_track_process("training", _proc.pid, model_name=model_name, log_file=log_file_path)
```

## Data Flow

```
┌──────────────────┐                              ┌──────────────────┐
│  applio_launcher │                              │  macos_wrapper   │
│                  │      POSIX SIGNALS           │                  │
│  ┌────────────┐◄─┼──────── SIGTERM ────────────┼──┐               │
│  │  Process   │──┼───────► SIGCONT ─────────────┼──┤               │
│  │  Control   │  │      (via PID from file)     │  │               │
│  └────────────┘  │                              │  ▼               │
│                  │                              │  ┌────────────┐  │
│  ┌────────────┐  │      FILE-BASED IPC          │  │ training.  │  │
│  │  Progress  │◄─┼──── reads ◄──────────────────┼──│ log        │  │
│  │  Window    │  │                              │  └────────────┘  │
│  └────────────┘  │                              │                  │
└──────────────────┘                              └──────────────────┘
         │                                                 │
         ▼                                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              active_processes.json (Shared State)                        │
│                                                                         │
│  {                                                                      │
│    "version": 1,                                                        │
│    "wrapper_pid": 12345,                                                │
│    "processes": {                                                       │
│      "training": {                                                      │
│        "pid": 12346,                                                    │
│        "model_name": "MyVoice-48k",                                     │
│        "log_file": "/Users/.../logs/MyVoice-48k/training.log",          │
│        "started_at": "2026-03-02T10:30:00",                              │
│        "status": "running"                                              │
│      }                                                                  │
│    }                                                                    │
│  }                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

## Process State File Schema

```json
{
  "version": 1,
  "wrapper_pid": 12345,
  "processes": {
    "training": {
      "pid": 12346,
      "model_name": "MyVoice-48k",
      "log_file": "/Users/fred/Applio/logs/MyVoice-48k/training.log",
      "started_at": "2026-03-02T10:30:00",
      "status": "running",
      "total_epoch": 500
    },
    "preprocess": {
      "pid": 12347,
      "model_name": "MyVoice-48k",
      "log_file": "/Users/fred/Applio/logs/MyVoice-48k/preprocess.log",
      "started_at": "2026-03-02T10:25:00",
      "status": "running"
    }
  }
}
```

## Launch Flows

### Cold Start (No Running Processes)

1. User double-clicks Applio.app
2. applio_launcher.py starts
3. Check active_processes.json - no processes
4. Spawn macos_wrapper.py
5. Wrapper creates PyWebView window with Gradio
6. User starts training
7. Wrapper spawns training, updates active_processes.json
8. User closes window
9. Wrapper hides, writes wrapper_closing signal
10. Launcher shows progress window
11. Progress window tails training.log

### Warm Start (Training Running)

1. Training running, progress window visible
2. User re-opens Applio.app
3. Launcher finds valid training PID
4. Launcher shows progress window immediately
5. Launcher spawns wrapper for Gradio access

### Recovery Start (After Crash)

1. Previous session crashed, training still running
2. User opens Applio.app
3. Launcher finds stale wrapper_pid, valid training PID
4. Launcher shows recovery dialog
5. User clicks "Monitor" → Progress window appears

## Menu Structure

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  File       │  │  Window     │  │  Help       │
└─────────────┘  └─────────────┘  └─────────────┘
       │                 │                 │
       ▼                 ▼                 ▼
 Set Data         Progress Monitor    About Applio
 Location...      (gray if none)      Check for Updates...
 Open in          ───────────────
 Finder   ▻       Show Main Window
   ├─ Logs        Minimize
   ├─ Models      Zoom
   └─ Datasets
 Quit
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| Training log file deleted | Show "Log file not found", continue monitoring |
| Training process orphaned | Detect via stale PID, offer to terminate or adopt |
| Launcher crashes | Training continues; on relaunch, detect running process |
| Multiple training processes | Progress window shows list, user selects |
| Wrapper crashes | SIGCHLD handler detects, shows error dialog |
| Stale entries | Validate PIDs on read, clean up dead processes |

## File Changes

### New Files

| File | Purpose | Lines |
|------|---------|-------|
| `applio_launcher.py` | Main entry point, process group leader | ~400 |

### Modified Files

| File | Changes |
|------|---------|
| `build_macos.py` | Change entry point to applio_launcher.py |
| `macos_wrapper.py` | Remove progress window code (~400 lines), add close notification |
| `patches/patch_process_tracking.py` | Add log_file redirection and tracking |

### Code Size Impact

| Component | Before | After | Net Change |
|-----------|--------|-------|------------|
| `applio_launcher.py` | 0 | +400 | +400 |
| `macos_wrapper.py` | ~1600 | ~1200 | -400 |
| `patch_process_tracking.py` | ~310 | ~350 | +40 |
| **Total** | ~1910 | ~1950 | **+40 lines** |

## Success Criteria

1. Progress window shows real-time training logs (epoch progress, tqdm)
2. User can pause/resume/terminate training from progress window
3. Training continues when main window is closed
4. Progress window can be closed and re-opened while training runs
5. Re-launching Applio while training shows progress window automatically
6. "Window → Progress Monitor" menu item available when processes running
7. App survives and recovers from crashes gracefully

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Two Python processes increase memory | Launcher is lightweight (~50MB), acceptable overhead |
| Signal handling complexity | Use process groups, test thoroughly |
| Log file contention | Append mode, single writer (training) |
| PyInstaller spec changes | Tested build process, update build_macos.py |

## Task Breakdown

| Task ID | Subject | Description |
|---------|---------|-------------|
| 6 | Implement applio_launcher.py | Main entry point with process spawning, signal handling, menu |
| 2 | Implement log file redirection | Patch core.py to redirect stdout to training.log |
| 3 | Implement log tailing | ProgressWindowController tails log files |
| 4 | Implement auto-detection | Check for running processes on launch |
| 5 | Implement menu integration | Native Window menu with Progress Monitor item |

## References

- Previous design: `docs/plans/2026-03-01-background-process-handling-design.md`
- Implementation: `docs/plans/2026-03-01-background-process-handling-impl.md`
- Fork differences: `FORK_DIFFERENCES.md`
