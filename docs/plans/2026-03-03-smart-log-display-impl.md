# Smart Log Display Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:executing-plans to implement this plan task-by-task.

**Goal:** Transform the progress window log from a flooded stream of tqdm lines into a clean two-zone display with live progress and readable history.

**Architecture:** Add a "live zone" NSTextField above the log view to display active tqdm progress in-place. Modify line processing to detect tqdm lines, update the live zone instead of logging them, and track phase transitions for clean logging.

**Tech Stack:** PyObjC (NSTextField, NSColor), regex for tqdm detection, state machine for phase tracking

**Design Doc:** `docs/plans/2026-03-03-smart-log-display-design.md`

---

## Task 1: Add State Tracking Variables

**Files:**
- Modify: `applio_launcher.py:358` (ProgressWindowController.__init__)

**Step 1: Add state tracking variables**

In `ProgressWindowController.__init__`, after `self._last_file_size = 0`:

```python
# Smart log display state
self._live_phase = None          # Current phase name
self._live_phase_start = None    # Timestamp when phase started
self._last_tqdm_time = None      # Timestamp of last tqdm activity
self._last_non_tqdm_line = ""    # For phase name detection
```

**Step 2: Verify changes**

Run: `grep -n "_live_phase\|_last_tqdm_time" applio_launcher.py`
Expected: Shows 4 new variable assignments

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(smart-log): add state tracking variables for phase detection"
```

---

## Task 2: Add tqdm Line Detection Function

**Files:**
- Modify: `applio_launcher.py` (add new method after `_parse_epoch_progress_bg`)

**Step 1: Add tqdm detection method**

After `_parse_epoch_progress_bg` method (around line 643):

```python
def _is_tqdm_line(self, line):
    """Check if line is a tqdm progress bar update."""
    import re
    # Match patterns like: "  5%|▍         | 16/333 [00:18<04:36,  1.16it/s]"
    return bool(re.match(r'^\s*\d+%\|.*\|\s*\d+/\d+\s*\[', line))

def _parse_tqdm_line(self, line):
    """Extract progress info from tqdm line.

    Returns dict with: current, total, eta, rate, rate_unit
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
```

**Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(smart-log): add tqdm line detection and parsing functions"
```

---

## Task 3: Add Phase Name Detection

**Files:**
- Modify: `applio_launcher.py` (add new method after `_parse_tqdm_line`)

**Step 1: Add phase detection method**

After `_parse_tqdm_line` method:

```python
def _detect_phase_name(self, line):
    """Extract phase name from a log line.

    Looks for patterns like:
    - "Starting preprocessing..."
    - "Preprocessing audio files..."
    - "Extracting features..."
    """
    import re

    # Common phase patterns
    phase_patterns = [
        r'[Ss]tarting\s+(\w+)',
        r'^(\w+ing)\s+',  # "Preprocessing", "Extracting", "Training"
        r'^(\w+)\s+started',
    ]

    for pattern in phase_patterns:
        match = re.search(pattern, line, re.IGNORECASE)
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
```

**Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(smart-log): add phase name detection from log lines"
```

---

## Task 4: Create Live Zone UI Element

**Files:**
- Modify: `applio_launcher.py:400-480` (_create_ui method)

**Step 1: Add live zone UI creation**

In `_create_ui`, after progress bar creation (around line 480, after `y -= 30`):

```python
# Live zone separator (top)
self.live_separator_top = NSBox.alloc().initWithFrame_(
    NSMakeRect(padding, y - 2, window_width - 2*padding, 2)
)
self.live_separator_top.setBoxType_(NSBoxSeparator)
self.window.contentView().addSubview_(self.live_separator_top)
y -= 4

# Live zone - single line for active tqdm progress
LIVE_ZONE_HEIGHT = 24
self.live_zone = NSTextField.alloc().initWithFrame_(
    NSMakeRect(padding, y - LIVE_ZONE_HEIGHT, window_width - 2*padding, LIVE_ZONE_HEIGHT)
)
self.live_zone.setStringValue_("")  # Empty until tqdm detected
self.live_zone.setBezeled_(False)
self.live_zone.setDrawsBackground_(True)
self.live_zone.setBackgroundColor_(NSColor.controlBackgroundColor())
self.live_zone.setEditable_(False)
self.live_zone.setFont_(NSFont.systemFontOfSize_ofWeight_(12, NSFontWeightMedium))
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
self.live_separator_bottom.setBoxType_(NSBoxSeparator)
self.window.contentView().addSubview_(self.live_separator_bottom)
y -= 6
```

**Step 2: Add NSBox and NSColor imports**

At top of file, in the NATIVE_APIS_AVAILABLE block (around line 30), add `NSBox` and `NSColor` to imports:

```python
from AppKit import (
    NSApplication, NSWindow, NSButton, NSTextField, NSScrollView,
    NSTextView, NSProgressIndicator, NSMenu, NSMenuItem, NSFont,
    NSMakeRect, NSTitledWindowMask, NSClosableWindowMask,
    NSBackingStoreBuffered, NSBezelBorder, NSBox, NSColor,
    NSFontWeightMedium, NSCenterTextAlignment, NSApplicationActivationPolicyRegular
)
```

**Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 4: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(smart-log): add live zone UI element with separators"
```

---

## Task 5: Add Live Zone Update Method

**Files:**
- Modify: `applio_launcher.py` (add new method after `_detect_phase_name`)

**Step 1: Add live zone update method**

After `_detect_phase_name` method:

```python
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
```

**Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(smart-log): add live zone update method with phase tracking"
```

---

## Task 6: Add Phase Completion Logging

**Files:**
- Modify: `applio_launcher.py` (add new method after `_update_live_zone`)

**Step 1: Add phase completion method**

After `_update_live_zone` method:

```python
def _log_phase_completion(self):
    """Log the completion of the current phase."""
    if not self._live_phase or not self._live_phase_start:
        return

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
```

**Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(smart-log): add phase completion logging with duration"
```

---

## Task 7: Modify File Poll Worker for Smart Logging

**Files:**
- Modify: `applio_launcher.py:581-625` (_file_poll_worker method)

**Step 1: Replace line processing logic**

In `_file_poll_worker`, replace the line processing loop (around lines 617-623):

Replace:
```python
# Parse lines and queue updates
for line in lines:
    if line.strip():
        # Parse epoch progress
        self._parse_epoch_progress_bg(line)
        # Queue log line for main thread
        self._file_queue.put(("log_line", line))
```

With:
```python
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
```

**Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(smart-log): modify file poll worker to detect and route tqdm lines"
```

---

## Task 8: Update Queue Processing for tqdm Messages

**Files:**
- Modify: `applio_launcher.py:651-680` (processQueueUpdates_ method)

**Step 1: Add tqdm message handling**

In `processQueueUpdates_`, add handling for "tqdm" message type after the "log_line" handling:

```python
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
```

**Step 2: Add live zone timeout check**

At the end of `processQueueUpdates_`, add timeout check:

```python
# Check for live zone timeout (no tqdm for 2+ seconds)
if self._last_tqdm_time and self._live_phase:
    elapsed = (datetime.datetime.now() - self._last_tqdm_time).total_seconds()
    if elapsed > 2.0:
        # Phase likely complete - log completion and clear live zone
        self._log_phase_completion()
        self.live_zone.setStringValue_("")
        self._last_tqdm_time = None
```

**Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 4: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(smart-log): add tqdm queue handling and live zone timeout"
```

---

## Task 9: Test the Implementation

**Step 1: Build the app**

```bash
venv_macos/bin/python build_macos.py
```

Expected: Build succeeds without errors

**Step 2: Run the app**

```bash
open dist/Applio.app
```

**Step 3: Start a training session**

- Load a dataset
- Start training

**Step 4: Close main window and observe progress window**

Expected behavior:
- Live zone shows tqdm progress in single line
- Log zone shows phase starts/completions only
- No tqdm spam in log

**Step 5: Verify phase transitions**

- Wait for preprocessing to complete
- Verify "Preprocessing complete (Xm Ys)" appears in log
- Verify live zone updates to next phase

---

## Task 10: Final Commit and Documentation Update

**Step 1: Update CLAUDE.md with smart log feature**

Add to `CLAUDE.md` in the "Progress window" section:

```markdown
**Smart log display:**
- Live zone shows active tqdm progress in single line (not spam)
- Log zone shows only phase transitions, errors, and completions
- Phase completion includes duration (e.g., "Preprocessing complete (2m 14s)")
```

**Step 2: Commit documentation**

```bash
git add CLAUDE.md
git commit -m "docs: add smart log display documentation to CLAUDE.md"
```

---

## Summary

| Task | Description | Commits |
|------|-------------|---------|
| 1 | State tracking variables | 1 |
| 2 | tqdm detection functions | 1 |
| 3 | Phase name detection | 1 |
| 4 | Live zone UI element | 1 |
| 5 | Live zone update method | 1 |
| 6 | Phase completion logging | 1 |
| 7 | File poll worker modification | 1 |
| 8 | Queue processing updates | 1 |
| 9 | Testing | - |
| 10 | Documentation | 1 |

**Total: 9 code commits, 1 doc commit**
