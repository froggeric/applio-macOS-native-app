# Progress Window UI Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:executing-plans to implement this plan task-by-task.

**Goal:** Transform the progress window into a visually rich, scannable interface with a rich status card and syntax-highlighted logs.

**Architecture:** Increase window height from 500 to 580px. Replace simple live zone text field with multi-row Rich Status Card (icon, visual progress bar, stats grid). Change log font to monospace and add NSAttributedString-based syntax highlighting.

**Tech Stack:** PyObjC (NSTextField, NSColor, NSAttributedString, NSFont), Unicode blocks for progress bar

**Design Doc:** `docs/plans/2026-03-03-progress-window-ui-design.md`

---

## Task 1: Increase Window Height

**Files:**
- Modify: `applio_launcher.py:389` (_create_window method)
- Modify: `applio_launcher.py:411` (_create_ui method - y starting point)

**Step 1: Update window height in _create_window**

In `_create_window` method, change line 389:

From:
```python
NSMakeRect(0, 0, 500, 500),
```

To:
```python
NSMakeRect(0, 0, 500, 580),
```

**Step 2: Update y starting point in _create_ui**

In `_create_ui` method, change line 411:

From:
```python
y = 500 - padding
```

To:
```python
y = 580 - padding
```

**Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 4: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(ui): increase progress window height from 500 to 580px"
```

---

## Task 2: Add Status Badge to Header

**Files:**
- Modify: `applio_launcher.py:417-430` (type_label creation)
- Modify: `applio_launcher.py:860-870` (status updates in processQueueUpdates_)

**Step 1: Add status badge after type_label**

After `self.window.contentView().addSubview_(self.type_label)` (around line 430), add:

```python
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
```

**Step 2: Add helper method for status badge updates**

After `_log_phase_completion` method, add:

```python
def _update_status_badge(self, status):
    """Update the status badge with color and text.

    Status options: running, paused, completed, error
    """
    status_colors = {
        'running': (NSColor.systemGreenColor(), "Running"),
        'paused': (NSColor.systemOrangeColor(), "Paused"),
        'completed': (NSColor.systemBlueColor(), "Completed"),
        'error': (NSColor.systemRedColor(), "Error"),
    }

    color, text = status_colors.get(status, (NSColor.labelColor(), status.capitalize()))
    self.status_badge.setStringValue_(text)
    self.status_badge.setTextColor_(color)
    self.status_badge.setBackgroundColor_(color.colorWithAlphaComponent_(0.2))
```

**Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 4: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(ui): add status badge to progress window header"
```

---

## Task 3: Convert Live Zone to Rich Status Card

**Files:**
- Modify: `applio_launcher.py:489-522` (live zone UI creation)
- Modify: `applio_launcher.py:786-817` (_update_live_zone method)

**Step 1: Replace live zone with Rich Status Card UI**

Replace the entire live zone creation block (lines 489-522) with:

```python
# Rich Status Card (72px total)
STATUS_CARD_HEIGHT = 72
y -= 4  # Small gap before card

# Row 1: Phase icon + name + counter (24px)
row1_height = 24
self.phase_label = NSTextField.alloc().initWithFrame_(
    NSMakeRect(padding, y - row1_height, window_width - 2*padding, row1_height)
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
    NSMakeRect(padding, y - row2_height, window_width - 2*padding - 50, row2_height)
)
self.visual_progress.setStringValue_("░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░")
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
stats_width = (window_width - 2*padding - 30) / 4
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

y -= row3_height + 4

# Status card background (optional - adds visual separation)
self.status_card_box = NSBox.alloc().initWithFrame_(
    NSMakeRect(padding - 5, y, window_width - 2*padding + 10, STATUS_CARD_HEIGHT + 4)
)
self.status_card_box.setBoxType_(1)  # NSBoxCustom
self.status_card_box.setBorderType_(0)  # No border
self.status_card_box.setFillColor_(NSColor.systemBlueColor().colorWithAlphaComponent_(0.05))
self.window.contentView().addSubview_(self.status_card_box, positioned_atIndex_(0, 0))
```

**Step 2: Add NSBox and NSFontWeightSemibold imports**

At the top of file, update the NATIVE_APIS_AVAILABLE imports (around line 30):

Add `NSBox` and `NSFontWeightSemibold` to the import list.

**Step 3: Update _update_live_zone method**

Replace the existing `_update_live_zone` method with:

```python
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
        self._add_log_line(f"{phase_name} started ({tqdm_data['total']} {total_label})")

    # Build phase label with icon
    phase = self._live_phase or "Processing"
    phase_icons = {
        'preprocessing': '📁',
        'feature extraction': '🔬',
        'training': '🎯',
        'inference': '🎵',
        'tts': '🗣️',
    }
    icon = phase_icons.get(phase.lower(), '⚙️')
    current = tqdm_data['current']
    total = tqdm_data['total']
    total_label = "files" if "preprocess" in phase.lower() else "items"

    self.phase_label.setStringValue_(f"{icon}  {phase.upper()}  •  {current} of {total} {total_label}")

    # Update visual progress bar (50 chars = 100%)
    percent = tqdm_data.get('percent', 0)
    filled = int(percent / 2)  # 50 chars max
    empty = 50 - filled
    bar = "█" * filled + "░" * empty
    self.visual_progress.setStringValue_(bar)
    self.progress_percent.setStringValue_(f"{percent}%")

    # Update stats grid
    # Speed
    if tqdm_data.get('rate'):
        rate_str = f"{tqdm_data['rate']:.2f}{tqdm_data['rate_unit']}"
    else:
        rate_str = "--"
    self.stats_values[0].setStringValue_(rate_str)

    # ETA
    eta_str = tqdm_data.get('eta', '--') or '--'
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
```

**Step 4: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 5: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(ui): convert live zone to Rich Status Card with visual progress bar"
```

---

## Task 4: Change Log Font to Monospace

**Files:**
- Modify: `applio_launcher.py:540` (log_view font)

**Step 1: Update log_view font**

In `_create_ui`, change line 540:

From:
```python
self.log_view.setFont_(NSFont.systemFontOfSize_(11))
```

To:
```python
self.log_view.setFont_(NSFont.fontWithName_size_("Menlo", 11))
```

**Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 3: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(ui): use monospace font (Menlo) for log view"
```

---

## Task 5: Add Syntax Highlighting to Log

**Files:**
- Modify: `applio_launcher.py` (add _colorize_log_line method)
- Modify: `applio_launcher.py` (_add_log_line method)

**Step 1: Add NSAttributedString import**

At the top of file, in the NATIVE_APIS_AVAILABLE block, add `NSAttributedString` and `NSMutableAttributedString`:

```python
from AppKit import (
    NSApplication, NSWindow, NSButton, NSTextField, NSScrollView,
    NSTextView, NSProgressIndicator, NSMenu, NSMenuItem, NSFont,
    NSMakeRect, NSTitledWindowMask, NSClosableWindowMask,
    NSBackingStoreBuffered, NSBezelBorder, NSBox, NSColor,
    NSFontWeightMedium, NSFontWeightSemibold, NSCenterTextAlignment,
    NSApplicationActivationPolicyRegular, NSAttributedString,
    NSMutableAttributedString
)
```

**Step 2: Add _colorize_log_line method**

After `_detect_phase_name` method, add:

```python
def _colorize_log_line(self, line):
    """Create colorized attributed string for log line.

    Returns NSAttributedString with appropriate colors and icons.
    """
    # Determine icon and color based on content
    line_lower = line.lower()

    if "complete" in line_lower:
        icon = "✓ "
        color = NSColor.systemGreenColor()
    elif "started" in line_lower:
        icon = "→ "
        color = NSColor.systemBlueColor()
    elif any(w in line_lower for w in ["error", "fail", "exception"]):
        icon = "✗ "
        color = NSColor.systemRedColor()
    elif "warning" in line_lower or "caution" in line_lower:
        icon = "⚠ "
        color = NSColor.systemOrangeColor()
    elif re.search(r'epoch\s*\d+/\d+', line_lower):
        icon = "◆ "
        color = NSColor.systemPurpleColor()
    else:
        icon = ""
        color = NSColor.labelColor()

    # Build attributed string
    text = icon + line
    attr_string = NSMutableAttributedString.alloc().initWithString_(text)

    # Apply color to entire string
    attr_string.addAttribute_value_range_(
        NSForegroundColorAttributeName,
        color,
        (0, len(text))
    )

    # Gray out timestamp if present (format: [HH:MM:SS])
    timestamp_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
    if timestamp_match:
        # Adjust for icon offset
        start = len(icon) + timestamp_match.start()
        length = len(timestamp_match.group(0))
        attr_string.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            NSColor.secondaryLabelColor(),
            (start, length)
        )

    return attr_string
```

**Step 3: Add NSForegroundColorAttributeName constant**

At the top of the ProgressWindowController class (after `import re` if needed in method), ensure we have access to `NSForegroundColorAttributeName`. Add to imports:

```python
from Foundation import NSForegroundColorAttributeName
```

Or use the string directly: `"NSColor"` (actually the constant is `NSForegroundColorAttributeName`).

For PyObjC, use:
```python
from AppKit import NSForegroundColorAttributeName
```

**Step 4: Modify _add_log_line to use colorization**

Replace the existing `_add_log_line` method:

From:
```python
def _add_log_line(self, line):
    """Add a line to the log view with buffer limit."""
    ...
```

To (preserve existing logic but add colorization):
```python
def _add_log_line(self, line):
    """Add a line to the log view with buffer limit and syntax highlighting."""
    # Strip carriage returns (from tqdm)
    clean_line = line.replace('\r', '').strip()
    if not clean_line:
        return

    # Get current text storage
    text_storage = self.log_view.textStorage()

    # Create colorized line
    attr_line = self._colorize_log_line(clean_line)

    # Add newline
    newline = NSAttributedString.alloc().initWithString_("\n")

    # Append to log
    text_storage.appendAttributedString_(attr_line)
    text_storage.appendAttributedString_(newline)

    # Limit buffer size (keep last 100 lines)
    text_string = text_storage.string()
    lines = text_string.split('\n')
    if len(lines) > 100:
        # Remove oldest lines
        keep_text = '\n'.join(lines[-100:])
        # Create new attributed string with default attributes
        font = NSFont.fontWithName_size_("Menlo", 11)
        attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: NSColor.labelColor()}
        new_storage = NSMutableAttributedString.alloc().initWithString_attributes_(keep_text, attrs)
        text_storage.setAttributedString_(new_storage)

    # Scroll to bottom
    self.log_view.scrollRangeToVisible_((text_storage.length(), 0))
```

**Step 5: Add NSFontAttributeName to imports**

Add to the AppKit imports:
```python
NSFontAttributeName, NSForegroundColorAttributeName
```

**Step 6: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('applio_launcher.py').read())"`
Expected: No output (valid syntax)

**Step 7: Commit**

```bash
git add applio_launcher.py
git commit -m "feat(ui): add syntax highlighting to log view with colored icons"
```

---

## Task 6: Test the Implementation

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
- Close main window to see progress window

**Step 4: Verify Rich Status Card**

Expected behavior:
- Phase icon appears (📁 for preprocessing, 🎯 for training)
- Visual progress bar shows filled blocks (████░░░░)
- Percentage updates
- Stats grid shows Speed, ETA, Phase Time, Items

**Step 5: Verify Log Syntax Highlighting**

Expected behavior:
- Timestamps appear in gray
- "started" lines have → icon in blue
- "complete" lines have ✓ icon in green
- Errors have ✗ icon in red
- Epoch milestones have ◆ icon in purple

**Step 6: Verify Status Badge**

Expected behavior:
- Shows "Running" in green
- Changes to "Paused" (orange) when paused

---

## Task 7: Update Documentation

**Step 1: Update CLAUDE.md**

Add to the "Progress window" section:

```markdown
**Rich Status Card:**
- Phase icon + name (📁 Preprocessing, 🔬 Feature extraction, 🎯 Training, 🎵 Inference, 🗣️ TTS)
- Visual progress bar with Unicode blocks (████░░░░) + percentage
- Stats grid: Speed, ETA, Phase Time, Items

**Log syntax highlighting:**
- Timestamps in gray
- Phase starts (→) in blue
- Completions (✓) in green
- Errors (✗) in red
- Warnings (⚠) in orange
- Epoch milestones (◆) in purple
- Monospace font (Menlo 11pt)

**Status badge:**
- Pill-shaped, color-coded: Running (green), Paused (orange), Completed (blue), Error (red)
```

**Step 2: Commit documentation**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with progress window UI redesign details"
```

---

## Summary

| Task | Description | Commits |
|------|-------------|---------|
| 1 | Increase window height (500→580) | 1 |
| 2 | Add status badge | 1 |
| 3 | Convert live zone to Rich Status Card | 1 |
| 4 | Change log font to monospace | 1 |
| 5 | Add log syntax highlighting | 1 |
| 6 | Test implementation | - |
| 7 | Update documentation | 1 |

**Total: 6 code commits, 1 doc commit**
