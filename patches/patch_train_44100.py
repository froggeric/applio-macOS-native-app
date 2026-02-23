#!/usr/bin/env python3
"""
Patcher for tabs/train/train.py to add 44100 Hz sample rate support.

This patcher is designed to be:
- Robust: Uses regex to handle whitespace variations
- Idempotent: Safe to run multiple times
- Verifiable: Reports exactly what was changed
- Future-proof: Fails gracefully with clear error messages

Patches applied:
1. Add "44100" to sampling_rate Radio choices
2. Add "44100" to toggle_vocoder HiFi-GAN choices
3. Add "44100" to toggle_vocoder RefineGAN choices

Usage:
    python patches/patch_train_44100.py [path/to/train.py] [--dry-run]
"""

import re
import sys
import argparse
from pathlib import Path


class PatchResult:
    """Result of a single patch operation."""
    def __init__(self, name: str, success: bool, message: str, changed: bool = False):
        self.name = name
        self.success = success
        self.message = message
        self.changed = changed

    def __str__(self):
        status = "✓" if self.success else "✗"
        change = " (modified)" if self.changed else " (already patched)" if self.success else ""
        return f"  {status} {self.name}: {self.message}{change}"


def patch_sampling_rate_choices(content: str) -> tuple[str, PatchResult]:
    """
    Patch the sampling_rate Radio choices to include 44100.

    Finds the choices=["32000", "40000", "48000"] pattern in the sampling_rate
    Radio component and adds 44100.
    """
    name = "sampling_rate choices"

    # Find the sampling_rate Radio section
    sr_start = content.find('sampling_rate = gr.Radio(')
    if sr_start == -1:
        return content, PatchResult(name, False, "Could not find sampling_rate Radio definition")

    # Find the end of this Radio call (matching closing paren)
    sr_end = content.find('\n                )', sr_start)
    if sr_end == -1:
        sr_end = content.find('\n)', sr_start)

    sr_section = content[sr_start:sr_end] if sr_end != -1 else content[sr_start:sr_start+500]

    # Check if already patched
    if '"44100"' in sr_section:
        return content, PatchResult(name, True, "Already contains 44100 in sampling_rate choices", changed=False)

    # Find and replace the choices list within this section
    old_pattern = 'choices=["32000", "40000", "48000"]'
    new_pattern = 'choices=["32000", "40000", "44100", "48000"]'

    if old_pattern not in sr_section:
        return content, PatchResult(name, False, f"Could not find expected choices pattern: {old_pattern}")

    # Apply patch
    new_content = content[:sr_start] + sr_section.replace(old_pattern, new_pattern) + content[sr_end:] if sr_end != -1 else content[:sr_start] + sr_section.replace(old_pattern, new_pattern) + content[sr_start + len(sr_section):]

    return new_content, PatchResult(name, True, "Added 44100 to choices", changed=True)


def patch_toggle_vocoder_hifigan(content: str) -> tuple[str, PatchResult]:
    """
    Patch the toggle_vocoder HiFi-GAN choices to include 44100.

    Pattern: "choices": ["32000", "40000", "48000"]
    Result:  "choices": ["32000", "40000", "44100", "48000"]
    """
    name = "toggle_vocoder HiFi-GAN choices"

    # Find the HiFi-GAN block in toggle_vocoder
    # Pattern: if vocoder == "HiFi-GAN": ... "choices": [...]
    pattern = r'(if\s+vocoder\s*==\s*"HiFi-GAN":\s*return\s*\{[^}]*"choices":\s*\[)("32000",\s*"40000",\s*"48000")(\])'

    match = re.search(pattern, content, re.DOTALL)
    if not match:
        # Check if already patched
        check_pattern = r'if\s+vocoder\s*==\s*"HiFi-GAN":\s*return\s*\{[^}]*"choices":\s*\[[^\]]*"44100"[^\]]*\]'
        if re.search(check_pattern, content, re.DOTALL):
            return content, PatchResult(name, True, "Already contains 44100", changed=False)
        return content, PatchResult(name, False, "Could not find HiFi-GAN choices pattern")

    old_choices = match.group(2)
    new_choices = '"32000", "40000", "44100", "48000"'

    new_content = content[:match.start(2)] + new_choices + content[match.end(2):]

    return new_content, PatchResult(name, True, f"Added 44100 to HiFi-GAN choices", changed=True)


def patch_toggle_vocoder_refinegan(content: str) -> tuple[str, PatchResult]:
    """
    Patch the toggle_vocoder RefineGAN choices to include 44100.

    Pattern: "choices": ["24000", "32000"]
    Result:  "choices": ["24000", "32000", "44100"]
    """
    name = "toggle_vocoder RefineGAN choices"

    # Find the else block in toggle_vocoder (RefineGAN)
    # We need to be careful to match the else block, not the HiFi-GAN block
    pattern = r'(def\s+toggle_vocoder\(vocoder\):[^}]+if\s+vocoder\s*==\s*"HiFi-GAN":[^}]+\}[^}]*else:\s*return\s*\{[^}]*"choices":\s*\[)("24000",\s*"32000")(\])'

    match = re.search(pattern, content, re.DOTALL)
    if not match:
        # Check if already patched
        check_pattern = r'def\s+toggle_vocoder\(vocoder\):.+?else:\s*return\s*\{[^}]*"choices":\s*\[[^\]]*"44100"[^\]]*\]'
        if re.search(check_pattern, content, re.DOTALL):
            return content, PatchResult(name, True, "Already contains 44100", changed=False)
        return content, PatchResult(name, False, "Could not find RefineGAN choices pattern")

    old_choices = match.group(2)
    new_choices = '"24000", "32000", "44100"'

    new_content = content[:match.start(2)] + new_choices + content[match.end(2):]

    return new_content, PatchResult(name, True, f"Added 44100 to RefineGAN choices", changed=True)


def patch_file(file_path: Path, dry_run: bool = False) -> bool:
    """
    Apply all patches to the specified file.

    Args:
        file_path: Path to train.py
        dry_run: If True, don't write changes

    Returns:
        True if all patches succeeded
    """
    print(f"Patching: {file_path}")
    print(f"Mode: {'dry-run' if dry_run else 'apply'}")
    print()

    # Read file
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"✗ Error reading file: {e}")
        return False

    original_content = content
    results = []

    # Apply patches in sequence
    content, result = patch_sampling_rate_choices(content)
    results.append(result)

    content, result = patch_toggle_vocoder_hifigan(content)
    results.append(result)

    content, result = patch_toggle_vocoder_refinegan(content)
    results.append(result)

    # Print results
    print("Results:")
    all_success = True
    any_changed = False
    for r in results:
        print(r)
        if not r.success:
            all_success = False
        if r.changed:
            any_changed = True

    print()

    if not all_success:
        print("✗ Patching failed - some patches could not be applied")
        return False

    if not any_changed:
        print("✓ File already patched - no changes needed")
        return True

    # Write changes
    if dry_run:
        print("✓ Dry-run complete - no changes written")
        return True

    try:
        file_path.write_text(content, encoding='utf-8')
        print("✓ File patched successfully")
        return True
    except Exception as e:
        print(f"✗ Error writing file: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Patch train.py to add 44100 Hz sample rate support"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="tabs/train/train.py",
        help="Path to train.py (default: tabs/train/train.py)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying the file"
    )

    args = parser.parse_args()
    file_path = Path(args.file)

    if not file_path.exists():
        print(f"✗ File not found: {file_path}")
        sys.exit(1)

    success = patch_file(file_path, args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
