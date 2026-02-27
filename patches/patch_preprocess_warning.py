#!/usr/bin/env python3
"""
Patcher to add empty dataset warning in preprocess.py.

Prints a prominent warning when no audio files are found during preprocessing.
Helps diagnose path resolution issues.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_preprocess_py(content: str) -> tuple[str, bool]:
    """
    Add warning when files list is empty after os.walk.

    Args:
        content: The content of preprocess.py

    Returns:
        Tuple of (patched_content, success)
    """
    # Idempotency marker
    if "# Empty dataset warning" in content:
        return content, True  # Already patched

    # Pattern: find where files list is built and ProcessPoolExecutor starts
    # Look for the audio_length = [] followed by with tqdm
    pattern = r'(\s+)(audio_length = \[\]\n)(\s+)(with tqdm\(total=len\(files\)\) as pbar:)'

    if not re.search(pattern, content):
        print("[patch_preprocess_warning] Pattern not found - code may have been modified")
        return content, False

    warning_code = r'''\1\2\1# Empty dataset warning
\1if not files:
\1    print("=" * 60)
\1    print("WARNING: No audio files found in dataset path:")
\1    print(f"  {input_root}")
\1    print("Supported formats: .wav, .mp3, .flac, .ogg")
\1    print("Please check:")
\1    print("  1. The path is correct")
\1    print("  2. Audio files exist in the directory")
\1    print("  3. Files have supported extensions")
\1    print("=" * 60)

\3\4'''

    new_content = re.sub(pattern, warning_code, content)
    return new_content, True


def patch_preprocess(base_path: str) -> bool:
    """
    Apply empty dataset warning patch to preprocess.py.

    Args:
        base_path: Path to the source directory

    Returns:
        True if patching succeeded (or already patched)
    """
    preprocess_path = os.path.join(base_path, "rvc", "train", "preprocess", "preprocess.py")

    if not os.path.exists(preprocess_path):
        print(f"[patch_preprocess_warning] preprocess.py not found at {preprocess_path}")
        return False

    try:
        with open(preprocess_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[patch_preprocess_warning] Error reading preprocess.py: {e}")
        return False

    original_content = content
    content, success = patch_preprocess_py(content)

    if not success:
        return False

    if content == original_content:
        print("[patch_preprocess_warning] No changes needed - already patched")
        return True

    try:
        with open(preprocess_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[patch_preprocess_warning] Error writing preprocess.py: {e}")
        return False

    print("[patch_preprocess_warning] Added empty dataset warning to preprocess.py")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_preprocess(base_path)
    sys.exit(0 if success else 1)
