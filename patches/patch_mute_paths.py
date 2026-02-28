#!/usr/bin/env python3
"""
Patcher to fix mute audio file paths for frozen app.

The mute audio files (mute24000.wav, mute48000.wav, etc.) are static assets
bundled with the app. In frozen mode, they live in the app bundle's
Resources/logs/mute/ directory, not in the user's data folder.

This patcher modifies preparing_files.py to look for mute files in the
correct location.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_preparing_files(base_path: str) -> bool:
    """
    Patch rvc/train/extract/preparing_files.py to use app bundle paths for mute files.

    Args:
        base_path: Path to the directory containing preparing_files.py
    """
    preparing_files_path = os.path.join(base_path, "preparing_files.py")

    if not os.path.exists(preparing_files_path):
        print(f"[patch_mute_paths] preparing_files.py not found at {preparing_files_path}")
        return False

    with open(preparing_files_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if already patched
    if "_get_mute_base_path" in content:
        print(f"[patch_mute_paths] Already patched")
        return True

    # Pattern: current_directory = os.getcwd()
    original_pattern = "current_directory = os.getcwd()"

    if original_pattern not in content:
        print(f"[patch_mute_paths] Pattern 'current_directory = os.getcwd()' not found")
        return False

    # Replacement: function that returns correct path for mute files
    mute_path_code = '''def _get_mute_base_path():
    """Get the base path for mute audio files.

    In frozen app mode, mute files are in the app bundle's Resources folder.
    In development mode, they're relative to the current directory.
    """
    import sys
    import os

    if getattr(sys, 'frozen', False):
        # Frozen app: use app bundle's Resources directory
        # PyInstaller puts data files in Resources (sibling of Frameworks)
        # sys._MEIPASS = Contents/Frameworks, so Resources = Contents/Resources
        frameworks_path = getattr(sys, '_MEIPASS', '')
        if frameworks_path:
            contents_path = os.path.dirname(frameworks_path)  # Contents
            resources_path = os.path.join(contents_path, 'Resources')
            return resources_path
        else:
            # Fallback
            return os.getcwd()
    else:
        # Development mode: use current directory
        return os.getcwd()

current_directory = _get_mute_base_path()'''

    new_content = content.replace(original_pattern, mute_path_code)

    with open(preparing_files_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[patch_mute_paths] Applied mute path patch to preparing_files.py")
    return True


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_preparing_files(base_path)
    sys.exit(0 if success else 1)
