"""
Process Log Parser - Shared parsing utilities for training/inference logs.

Used by:
- ProgressWindowController (applio_launcher.py)
- ProcessDashboardController (future)
"""

import re
from typing import Optional, Dict, Any

# A tqdm bar update, with or without a description prefix. The second form is
# the training bar since Applio 3.7 (rvc/train/train.py); keep this identical
# to ProgressWindowController._TQDM_LINE in applio_launcher.py.
_TQDM_LINE = (
    r"^\s*(?:.*[|:]\s*)?"  # optional description ending in "|" or ":"
    r"(\d+)%\|[^|]*\|\s*"  # percentage and bar
    r"(?:batch\s*=\s*)?"  # "{n}" or "batch={n}"
    r"(\d+)/(\d+)\s*\[([^\]]+)\]"
)


def is_tqdm_line(line: str) -> bool:
    """Check if line is a tqdm progress bar update."""
    return bool(re.match(_TQDM_LINE, line))


def parse_tqdm_line(line: str) -> Optional[Dict[str, Any]]:
    """Extract progress info from tqdm line.

    Returns dict with: percent, current, total, eta, rate, rate_unit
    or None if parsing fails.

    Patterns:
      "  5%|▍         | 16/333 [00:18<04:36,  1.16it/s]"
      "epoch=3 | step=120 |  43%|████ | batch=21/49 [00:18<04:36,  1.16it/s]"
    """
    match = re.match(_TQDM_LINE, line)
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


def detect_phase_name(line: str) -> Optional[str]:
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


def parse_training_status_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse training status line with epoch/step/loss info.

    Parses lines like:
    "Frederic v6 KLM5-44k | epoch=115 | step=11385 | time=23:13:10 | training_speed=0:15:25 | lowest_value=2.876 (epoch 76 and step 7455)"

    Returns dict with: epoch, step, training_speed, best_epoch, best_loss, best_step
    or None if not a training status line.
    """
    # Match training status line pattern with lowest_value
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

    # Simpler pattern without lowest_value (early training)
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


def parse_epoch_progress(line: str) -> Optional[Dict[str, int]]:
    """Parse epoch progress from log line.

    Looks for patterns like "Epoch: 5/100" or "epoch 5 of 100"

    Returns dict with: current, total
    or None if not found.
    """
    match = re.search(r"[Ee]poch[:\s]*(\d+)\s*/\s*(\d+)", line)
    if match:
        current = int(match.group(1))
        total = int(match.group(2))
        if total > 0 and current <= total:
            return {"current": current, "total": total}
    return None
