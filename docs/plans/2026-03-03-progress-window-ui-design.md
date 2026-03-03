# Progress Window UI Redesign

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:executing-plans to implement this plan task-by-task.

**Goal:** Transform the progress window into a visually rich, scannable interface that supports quick status checks, active monitoring, and log review.

**Problem:** Current live zone shows text-only progress, log uses proportional font making it hard to read, and no visual hierarchy for quick scanning.

**Solution:** Rich status card with visual progress bar + syntax-highlighted monospace logs + taller window for breathing room.

---

## Window Overview

**Dimensions:** 500px × 580px (increased from 500×500)

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  🔊  Training: Frederic v6 Titan-48k              [Running] │  ← Header (48px)
│  Elapsed: 00:15:23                           Epoch 50/200   │
│  [████████████████░░░░░░░░░░░░░░░░░░░░]          25%        │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  📁 PREPROCESSING                              88 of 333    │  ← Rich Status Card (72px)
│  [████████████████████░░░░░░░░░░░░░░░░░░░░░]      26%       │
│                                                             │
│  ┌───────────┬───────────┬───────────┬───────────────────┐ │
│  │  Speed    │   ETA     │  Phase    │  Time in phase    │ │
│  │  1.16it/s │  01:45    │  1.16it/s │     00:12         │ │
│  └───────────┴───────────┴───────────┴───────────────────┘ │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  Log History                                    [⬇ Scroll] │  ← Log Zone (220px)
│  ─────────────────────────────────────────────────────────  │
│  11:02:15  Starting training pipeline...                    │
│  11:02:18  ✓ Model loaded: Frederic v6 Titan-48k           │
│  11:05:44  → Preprocessing started (333 files)             │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [Terminate]  [Pause]  [Open Logs]  [Relaunch App]         │  ← Buttons (40px)
└─────────────────────────────────────────────────────────────┘
```

---

## Component 1: Header (48px)

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  🔊  Training: Frederic v6 Titan-48k                 [Running] │
│  Elapsed: 00:15:23                           Epoch 50/200      │
│  [████████████████░░░░░░░░░░░░░░░░░░░░]           25%         │
└─────────────────────────────────────────────────────────────────┘
```

### Elements

1. **Process Icon + Title** (left side)
   - Icon based on process type (see Phase Icons table)
   - Bold title: "Training: Frederic v6 Titan-48k"
   - Font: System bold, 16pt

2. **Status Badge** (right side)
   - Pill-shaped background
   - Color-coded by status:
     - Running → Green (`NSColor.systemGreenColor()`)
     - Paused → Orange (`NSColor.systemOrangeColor()`)
     - Completed → Blue (`NSColor.systemBlueColor()`)
     - Error → Red (`NSColor.systemRedColor()`)
   - Font: Medium weight, 11pt

3. **Elapsed Time + Epoch Counter** (second row)
   - "Elapsed: 00:15:23" on left
   - "Epoch 50/200" on right (training only)
   - Font: Regular, 12pt

4. **Epoch Progress Bar** (third row)
   - Native `NSProgressIndicator`
   - Full width minus padding
   - Percentage label at right
   - Hidden when no epoch info available

---

## Component 2: Rich Status Card (72px)

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  📁 PREPROCESSING                              88 of 333 files  │
│  ══════════════════════════════════════════════════            │
│                                                                 │
│  ┌─────────────┬─────────────┬─────────────┬─────────────────┐ │
│  │   SPEED     │     ETA     │    PHASE    │  TIME IN PHASE  │ │
│  │   1.16it/s  │    01:45    │   1.16it/s  │      00:12      │ │
│  └─────────────┴─────────────┴─────────────┴─────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Phase Icons

| Process Type | Icon | Unicode Fallback |
|--------------|------|------------------|
| Preprocessing | 📁 | 📁 |
| Feature extraction | 🔬 | 🔬 |
| Training | 🎯 | 🎯 |
| Inference | 🎵 | 🎵 |
| TTS | 🗣️ | 🗣️ |
| Generic/Unknown | ⚙️ | ⚙️ |

### Visual Progress Bar

- **Characters:** Unicode blocks `█` (filled) and `░` (empty)
- **Length:** 50 characters = 100%
- **Percentage:** Displayed at right end
- **Background:** Slightly tinted (`NSColor.systemBlueColor()` at 5% opacity)

### Stats Grid (4 cells)

| Cell | Source | Format |
|------|--------|--------|
| Speed | tqdm rate | `1.16it/s` or `5.38s/it` |
| ETA | tqdm eta | `01:45` or `--:--` |
| Phase | Phase name | From detection |
| Time in Phase | Timer | `00:12`, `02:34`, `1:15:00` |

---

## Component 3: Log Zone (220px)

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Log History                                                    │
│  ─────────────────────────────────────────────────────────────  │
│  11:02:15  Starting training pipeline...                        │
│  11:02:18  ✓ Model loaded: Frederic v6 Titan-48k               │
│  11:05:44  → Preprocessing started (333 files)                 │
│  11:08:22  ✓ Preprocessing complete (2m 38s)                   │
│  11:12:01  ⚠ High memory usage detected                        │
│  11:18:22  ✗ CUDA out of memory error                          │
└─────────────────────────────────────────────────────────────────┘
```

### Font

- **Family:** Menlo or SF Mono (monospace)
- **Size:** 11pt
- **Implementation:** `NSFont.fontWithName_size_("Menlo", 11)` or `NSFont.userFixedPitchFontOfSize_(11)`

### Syntax Highlighting

Use `NSAttributedString` with colors:

| Pattern | Icon | Color | Example |
|---------|------|-------|---------|
| Timestamp `[\d{2}:\d{2}:\d{2}]` | None | `secondaryLabelColor` (gray) | `11:02:15` |
| Contains "started" | `→` | `systemBlueColor` | `→ Preprocessing started` |
| Contains "complete" | `✓` | `systemGreenColor` | `✓ Preprocessing complete` |
| Contains "error"/"fail"/"exception" | `✗` | `systemRedColor` | `✗ CUDA out of memory` |
| Contains "warning"/"caution" | `⚠` | `systemOrangeColor` | `⚠ High memory usage` |
| Contains "Epoch X/Y" | `◆` | `systemPurpleColor` | `◆ Epoch 50/200` |
| Default | None | `labelColor` (black/white) | `Starting training...` |

### Detection Logic

```python
def _colorize_log_line(self, line):
    """Apply syntax highlighting to log line."""
    if "complete" in line.lower():
        icon = "✓ "
        color = NSColor.systemGreenColor()
    elif "started" in line.lower():
        icon = "→ "
        color = NSColor.systemBlueColor()
    elif any(w in line.lower() for w in ["error", "fail", "exception"]):
        icon = "✗ "
        color = NSColor.systemRedColor()
    elif "warning" in line.lower():
        icon = "⚠ "
        color = NSColor.systemOrangeColor()
    elif re.search(r'epoch\s*\d+/\d+', line, re.I):
        icon = "◆ "
        color = NSColor.systemPurpleColor()
    else:
        icon = ""
        color = NSColor.labelColor()
    return icon, color
```

---

## Component 4: Buttons Row (40px)

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  [🛑 Terminate]  [⏸ Pause]  [📂 Open Logs]  [🔄 Relaunch App]  │
└─────────────────────────────────────────────────────────────────┘
```

### Button Specifications

| Button | Icon | Width | Behavior |
|--------|------|-------|----------|
| Terminate | 🛑 | 110px | Red hover, immediate termination |
| Pause/Resume | ⏸/▶ | 110px | Toggles icon and action |
| Open Logs | 📂 | 110px | Opens logs folder in Finder |
| Relaunch App | 🔄 | 110px | Launches new app instance |

### Button Styling

- Height: 28px
- Spacing: 10px between buttons
- Font: System, 12pt
- CornerRadius: 6px (bezeled button default)

---

## Implementation Notes

### Window Changes

- Height: 500 → 580px
- Width: 500px (unchanged)
- Update `NSMakeRect(0, 0, 500, 580)` in window creation

### Live Zone → Rich Status Card

- Replace `NSTextField` with custom layout:
  - Row 1: Icon + Label + Counter
  - Row 2: Visual progress bar (Unicode)
  - Row 3: Stats grid (4 cells)
- Increase height from 24px to 72px

### Log View Font

- Change from `NSFont.systemFontOfSize_(11)` to `NSFont.fontWithName_size_("Menlo", 11)`
- Implement `NSAttributedString` for syntax highlighting

### New Imports Required

```python
from AppKit import NSAttributedString, NSMutableAttributedString
```

---

## Acceptance Criteria

- [ ] Window height increased to 580px
- [ ] Rich Status Card shows phase icon, visual progress bar, stats grid
- [ ] Visual progress bar uses Unicode blocks (█░) with percentage
- [ ] Log zone uses monospace font (Menlo/SF Mono)
- [ ] Log lines are color-coded based on content type
- [ ] Icons prefix log lines (✓ → ✗ ⚠ ◆)
- [ ] All colors support dark mode via system colors
- [ ] Status badge shows colored pill (Running=green, Paused=orange, etc.)
