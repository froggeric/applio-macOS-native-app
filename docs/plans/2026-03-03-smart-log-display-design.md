# Smart Log Display Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:executing-plans to implement this plan task-by-task.

**Goal:** Transform the progress window log from a flooded stream of tqdm lines into a clean two-zone display with live progress and readable history.

**Problem:** tqdm progress bars output hundreds of nearly-identical lines using carriage return (`\r`), making the log view unusable for finding errors, phase transitions, or understanding overall progress.

**Solution:** Two-zone design separating "what's happening now" from "what happened."

---

## Design Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Training: Frederic v6 Titan-48k                             │
│ Status: Running                                              │
│ Elapsed: 00:15:23                                           │
│ [████████████░░░░░░░░░░░░░░░░░░░░]  Epoch 50/200           │
├─────────────────────────────────────────────────────────────┤
│ ▶ Preprocessing:  88/333 files  │  ETA: 1:45  │  1.16it/s  │  ← LIVE ZONE
├─────────────────────────────────────────────────────────────┤
│ 11:02:15 Starting training...                               │  ← LOG ZONE
│ 11:02:18 Model loaded: Frederic v6 Titan-48k               │
│ 11:05:44 Preprocessing started (333 files)                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Component 1: Live Zone

### Purpose
Display the single active progress line that updates in-place.

### Detection Logic
- A line is a "tqdm line" if it matches pattern: `^\s*\d+%.*\|\s*\d+/\d+`
- When a tqdm line arrives, it updates the live zone (not the log)
- If no tqdm activity for 2+ seconds, live zone clears

### Display Format
```
▶ Preprocessing:  88/333 files  │  ETA: 1:45  │  1.16it/s
```

Extracted from tqdm line:
- **Phase name:** From preceding log line (e.g., "Preprocessing", "Extracting", "Training")
- **Progress:** `88/333` → "88/333 files" or "88/333 items"
- **ETA:** `01:45` from `[...]` bracket
- **Rate:** `1.16it/s` or `5.38s/it`

### Visual Specs
- Height: 24px single-line NSTextField
- Background: Light gray/azure tint (`#F0F8FF` or system `controlBackgroundColor`)
- Font: Monospace 12pt, bold
- Border: Thin separator lines above/below
- Accessibility: Live region announcement when phase changes

---

## Component 2: Log Zone Behavior

### Purpose
Clean history of phase transitions, errors, and completions.

### What Gets Logged
1. **Phase starts** - "11:02:18 Preprocessing started (333 files)"
2. **Phase completions** - "11:04:32 Preprocessing complete (333 files, 2m 14s)"
3. **Non-tqdm lines** - Errors, warnings, status messages (as-is)
4. **Epoch milestones** - "11:15:00 Epoch 50/200 complete (loss: 0.023)"

### What Does NOT Get Logged
- tqdm progress lines (captured by live zone only)
- Repetitive status lines

### Phase Tracking
- When live zone starts showing tqdm for "Preprocessing", log one "started" line
- When tqdm completes (100% or different phase starts), log one "complete" line with duration
- Duration calculated from start/stop timestamps

### Example Log Output
```
11:02:15 Starting training pipeline...
11:02:18 Model loaded: Frederic v6 Titan-48k
11:02:44 Preprocessing started (333 files)
11:04:58 Preprocessing complete (333 files, 2m 14s)
11:05:01 Feature extraction started (333 files)
11:08:22 Feature extraction complete (333 files, 3m 21s)
11:08:25 Training started (200 epochs)
11:15:00 Epoch 50/200 (loss: 0.023)
```

---

## Component 3: UI Layout Changes

### Current Layout (top to bottom)
```
Process type label
Status label
Elapsed time label
Progress bar (epoch)
[Log scroll view - full height]
Buttons row
```

### New Layout
```
Process type label
Status label
Elapsed time label
Progress bar (epoch)
────────────────────────────
Live Zone (NSTextField, 1 line, highlighted background)
────────────────────────────
[Log scroll view - reduced height]
Buttons row
```

### Window Size
Remains 500x500, just reallocated space:
- Live zone: 24px
- Log view: reduced by ~30px

---

## Component 4: State Machine & Data Flow

### State Tracking
```python
self._live_phase = None          # Current phase name: "Preprocessing", "Extracting", etc.
self._live_phase_start = None    # Timestamp when phase started
self._live_progress = None       # Current tqdm line data
self._last_tqdm_time = None      # Timestamp of last tqdm activity
```

### Line Processing Flow
```
Line from file
    │
    ├─→ Is tqdm line? (regex match)
    │       │
    │       ├─→ Yes → Update live zone
    │       │         Track phase start if new
    │       │         Update self._last_tqdm_time
    │       │
    │       └─→ No → Is phase-end marker? (100% or different phase)
    │               │
    │               ├─→ Yes → Log phase completion
    │               │         Clear live zone
    │               │
    │               └─→ No → Log normally (non-tqdm line)
```

### Phase Detection Logic
- Look backwards from tqdm line to find preceding non-tqdm line
- Extract phase name from patterns like "Starting preprocessing..." or "Preprocessing..."
- Default to "Processing" if no phase name found

### 2-Second Timeout
- Timer check in `processQueueUpdates_` clears live zone if `_last_tqdm_time` > 2s ago
- Triggers phase completion logging if a phase was active

---

## File to Modify

| File | Changes |
|------|---------|
| `applio_launcher.py` | Add live zone UI, modify `_file_poll_worker`, update `_add_log_line`, add state tracking |

---

## Acceptance Criteria

- [ ] Live zone displays active tqdm progress in single line
- [ ] Log zone shows only phase starts, completions, errors, and non-tqdm lines
- [ ] Phase transitions are detected and logged correctly
- [ ] Live zone clears after 2 seconds of no tqdm activity
- [ ] Window remains responsive during active tqdm output
- [ ] Accessibility: Live zone announces phase changes
