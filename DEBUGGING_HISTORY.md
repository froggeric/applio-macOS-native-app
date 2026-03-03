# Debugging History

This file documents debugging sessions and solutions for the Applio macOS native app.

---

## 2026-03-01: Training Failure - Pretrained Models Not Found from UI

### Status: RESOLVED

### Root Cause
**macOS spawn-mode multiprocessing doesn't inherit environment variables** - When subprocess scripts are spawned (preprocess, extract, train), they don't inherit `APPLIO_LOGS_PATH` and `APPLIO_DATA_PATH` environment variables set in the main process. This caused path resolution failures.

### Solution
**File-based path resolution via `runtime_paths.json`** - Instead of relying on environment variables, subprocess scripts read paths from a configuration file written at app startup:

```
~/Library/Application Support/Applio/runtime_paths.json
```

This file contains:
```json
{
  "data_path": "/path/to/user/Applio",
  "logs_path": "/path/to/user/Applio/logs"
}
```

### Patches Applied at Build Time

The following patches are applied by `build_macos.py` before PyInstaller bundles files:

| Patch | Target File | Purpose |
|-------|-------------|---------|
| `patch_data_paths.py` | `core.py` | File-based `logs_path` resolution |
| `patch_train_paths.py` | `rvc/train/train.py` | File-based path resolution for training |
| `patch_mute_paths.py` | `rvc/train/extract/preparing_files.py` | Mute file paths for frozen app |
| `patch_pretrained_selector.py` | `rvc/lib/tools/pretrained_selector.py` | File-based pretrained model path resolution |
| `patch_custom_pretrained_paths.py` | `core.py` | Resolve relative custom pretrained paths to absolute |
| `patch_subprocess_validation.py` | `core.py` | Validate preprocessing/extraction before training |
| `patch_preflight_validation.py` | `core.py` | Pre-flight dataset path validation |
| `patch_preprocess_warning.py` | `rvc/train/preprocess/preprocess.py` | Empty dataset warning |

### Bugs Fixed During Investigation

1. **Indentation bug in `patch_subprocess_validation.py`** - The validation code ended with `\2` (captured indentation) which got duplicated when adding `train_script_path`, causing the line to be unreachable code with 8 spaces instead of 4.

2. **Custom pretrained paths not resolved** - Relative paths from the UI (e.g., `rvc/models/pretraineds/custom/...`) were passed directly to training subprocess without resolution to absolute paths.

### Build Process

1. **`pre_build_patch()`** - Applies all patches to source files
2. **PyInstaller** - Bundles patched files into app
3. **`post_build_restore()`** - Restores source files to pristine state

### Investigation Timeline

1. Initial hypothesis: `pretrained_selector` returning empty strings
2. Created `patch_pretrained_selector.py` with file-based path resolution
3. Added debug logging to trace execution
4. Discovered patches were being applied correctly at build time
5. Confirmed the real issue was environment variable inheritance in spawn mode

### Lessons Learned

1. **macOS spawn mode** doesn't inherit parent's environment variables
2. **File-based configuration** is process-safe across all subprocess boundaries
3. **Build-time patching** ensures patches are bundled in PyInstaller's PYZ archive
4. **Source files should not be modified directly** - all fixes go through patches

### Key Files
- `patches/patch_data_paths.py` - File-based logs_path for core.py
- `patches/patch_train_paths.py` - File-based paths for train.py
- `patches/patch_mute_paths.py` - Mute file path fixes
- `patches/patch_pretrained_selector.py` - File-based pretrained model paths
- `build_macos.py` - Applies patches before build, restores after

---

## 2026-03-03: Progress Window Unresponsive (Beachball)

### Status: RESOLVED

### Symptoms
When closing the main Gradio window with an active training process:
1. Close confirmation dialog appeared correctly
2. Choosing "Keep Running" showed progress window
3. Progress window displayed but was frozen with beachball cursor
4. Window did not respond to any mouse clicks

### Root Cause
Multiple issues combined:
1. **Timer not started** - `_start_timer()` was defined but never called, so queue updates were never processed
2. **Wrong event loop** - `runConsoleEventLoop()` was used instead of `runEventLoop()`
3. **Initial log read** - Reading entire log file queued thousands of lines at once
4. **Missing activation** - Window wasn't activated to receive input events

### Investigation Timeline
1. Confirmed close confirmation dialog worked (NSAlert appeared)
2. Confirmed progress window was created (logs showed completion)
3. Used `sample PID` to check main thread state - appeared normal (in run loop)
4. User reported progress bar now showed (timer was processing something)
5. User clarified window was frozen immediately, not after delay
6. Discovered `_start_timer()` was never called
7. Fixed timer start, rebuilt - still frozen
8. Changed `runConsoleEventLoop()` to `runEventLoop()` - FIXED
9. User's autocorrect had changed "now responsive" to "not responsive" causing confusion

### Solution
Applied to `applio_launcher.py`:
1. Added `_start_timer()` call in `ProgressWindowController.__init__` after `_start_file_thread()`
2. Changed `AppHelper.runConsoleEventLoop()` to `AppHelper.runEventLoop()`
3. Limited initial log read to last 50 lines instead of entire file
4. Added `activateIgnoringOtherApps_(True)` when showing window
5. Added log buffer limit (100 lines) with batch updates

### Key Insight: Event Loop Choice
- `AppHelper.runEventLoop()` - For GUI apps with windows that need to receive events
- `AppHelper.runConsoleEventLoop()` - For console tools with occasional GUI elements

Using `runConsoleEventLoop()` for a GUI app causes windows to appear but not respond to input.

### Key Files
- `applio_launcher.py` - ProgressWindowController class, event loop setup

---

## Template for New Debugging Sessions

```markdown
## YYYY-MM-DD: [Issue Title]

### Status: [INVESTIGATING / FIXED / BLOCKED]

### Symptoms
[What is happening that shouldn't be]

### Root Cause
[What is causing the issue - fill in when discovered]

### Investigation Timeline
1. [What was tried first]
2. [What was tried second]
...

### Solution
[What fixed it - fill in when resolved]

### Key Files
- [File paths involved]
```
