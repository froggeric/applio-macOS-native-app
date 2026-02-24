#!/usr/bin/env python3
"""
Patcher for rvc/train/extract/extract.py to handle multiprocessing safely.

Issue: mp.set_start_method("spawn", force=True) at module level can cause
RuntimeError when called multiple times or when context is already set.
In frozen PyInstaller apps, this can cause issues when the script is
executed via subprocess from the main app.

Fix: Wrap in try/except to handle already-set context gracefully.

This patcher is designed to be:
- Robust: Uses exact string matching for reliable patching
- Idempotent: Safe to run multiple times
- Verifiable: Reports exactly what was changed
- Future-proof: Fails gracefully with clear error messages

Usage:
    python patches/patch_multiprocessing.py [path/to/extract.py] [--dry-run]

Integrates with build_macos.py apply_patches() function.
"""

import sys
import argparse
from pathlib import Path


class PatchResult:
    """Result of a patch operation."""
    def __init__(self, name: str, success: bool, message: str, changed: bool = False):
        self.name = name
        self.success = success
        self.message = message
        self.changed = changed

    def __str__(self):
        status = "✓" if self.success else "✗"
        change = " (modified)" if self.changed else " (already patched)" if self.success else ""
        return f"  {status} {self.name}: {self.message}{change}"


def patch_set_start_method(content: str) -> tuple[str, PatchResult]:
    """
    Wrap the set_start_method call in try/except.

    Finds: mp.set_start_method("spawn", force=True)
    Replaces with:
        try:
            mp.set_start_method("spawn", force=True)
        except RuntimeError:
            pass  # Context already set
    """
    name = "multiprocessing set_start_method"

    old_pattern = 'mp.set_start_method("spawn", force=True)'
    new_pattern = '''try:
    mp.set_start_method("spawn", force=True)
except RuntimeError:
    pass  # Context already set'''

    # Check if already patched
    if 'except RuntimeError:' in content and 'Context already set' in content:
        # Verify it's in the right context (near set_start_method)
        if 'mp.set_start_method' in content:
            return content, PatchResult(name, True, "Already patched", changed=False)

    # Check if the pattern exists
    if old_pattern not in content:
        return content, PatchResult(name, False, f"Pattern not found: {old_pattern}")

    # Apply patch
    new_content = content.replace(old_pattern, new_pattern)
    return new_content, PatchResult(name, True, "Wrapped set_start_method in try/except", changed=True)


def patch_file(file_path: Path, dry_run: bool = False) -> bool:
    """
    Apply all patches to the specified file.

    Args:
        file_path: Path to extract.py
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
    content, result = patch_set_start_method(content)
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
        description="Patch extract.py to handle multiprocessing safely in frozen apps"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="rvc/train/extract/extract.py",
        help="Path to extract.py (default: rvc/train/extract/extract.py)"
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
