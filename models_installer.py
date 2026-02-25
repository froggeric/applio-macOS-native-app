#!/usr/bin/env python3
"""
Applio Models Installer

A standalone installer that copies pretrained models from the project directory
to the user's external data directory. Reuses preferences from the main Applio app.

Usage:
    python models_installer.py              # GUI mode (default)
    python models_installer.py --cli      # CLI mode (no GUI)
    python models_installer.py --help     # Show help
"""

import os
import sys
import argparse
import logging
import shutil
from pathlib import Path

# macOS native APIs (conditional)
try:
    from Foundation import NSUserDefaults, NSURL
    from AppKit import NSOpenPanel, NSModalResponseOK
    NATIVE_APIS_AVAILABLE = True
except ImportError:
    NATIVE_APIS_AVAILABLE = False


# =================================================================
# Configuration
# =================================================================

PREFERENCES_DOMAIN = "com.iahispano.applio"
KEY_DATA_PATH = "userDataPath"
KEY_FIRST_RUN_DONE = "firstRunCompleted"

# HuggingFace base URL (fallback for downloading if models not bundled)
HUGGINGFACE_BASE = "https://huggingface.co/IAHispano/Applio/resolve/main/Resources"

# Models to copy/bundle - we now copy the entire models directory recursively
# This ensures all models (pretrained, custom, embedders, predictors) are included
# without needing to specify each file individually.


# =================================================================
# Logging Setup
# =================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# =================================================================
# Preferences Manager
# =================================================================

class PreferencesManager:
    """Manages user preferences using macOS NSUserDefaults."""

    def __init__(self):
        if NATIVE_APIS_AVAILABLE:
            self.defaults = NSUserDefaults.standardUserDefaults()
        else:
            self.defaults = None

    def get_data_path(self) -> str | None:
        """Get the user's selected data storage path."""
        if self.defaults:
            path = self.defaults.stringForKey_(KEY_DATA_PATH)
            return path
        return None

    def set_data_path(self, path: str):
        """Save the data storage path preference."""
        if self.defaults:
            self.defaults.setObject_forKey_(path, KEY_DATA_PATH)
            self.defaults.synchronize()

    def is_first_run(self) -> bool:
        """Check if this is the first run (no preferences set)."""
        if self.defaults:
            return not self.defaults.boolForKey_(KEY_FIRST_RUN_DONE)
        return True

    def mark_first_run_complete(self):
        """Mark that first run setup has been completed."""
        if self.defaults:
            self.defaults.setBool_forKey_(True, KEY_FIRST_RUN_DONE)
            self.defaults.synchronize()


# =================================================================
# Directory Selection Dialog
# =================================================================

def select_data_folder(default_path: str = None) -> str | None:
    """
    Show native macOS folder selection dialog.

    Args:
        default_path: Initial directory to show in dialog

    Returns:
        Selected path or None if cancelled
    """
    if not NATIVE_APIS_AVAILABLE:
        print(f"Native dialogs not available, using default: {default_path}")
        return default_path

    panel = NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    panel.setTitle_("Select Applio Data Location")
    panel.setPrompt_("Select")
    panel.setMessage_("Choose where Applio stores models, datasets, and training data.")

    if default_path:
        expanded = os.path.expanduser(default_path)
        if os.path.exists(expanded):
            panel.setDirectoryURL_(NSURL.fileURLWithPath_(expanded))

    result = panel.runModal()
    if result == NSModalResponseOK:
        return str(panel.URLs()[0].path())
    return None


# =================================================================
# Directory Structure
# =================================================================

def create_directory_structure(base_path: str):
    """
    Create required directory structure in user's data location.

    Args:
        base_path: Root path for user data
    """
    dirs = [
        "rvc/models/pretraineds/hifi-gan",
        "rvc/models/pretraineds/refinegan",
        "rvc/models/pretraineds/custom",
        "rvc/models/embedders/contentvec",
        "rvc/models/embedders/embedders_custom",
        "rvc/models/predictors",
        "rvc/models/formant",
    ]

    for d in dirs:
        full_path = os.path.join(base_path, d)
        os.makedirs(full_path, exist_ok=True)
        logger.info(f"Created directory: {full_path}")


# =================================================================
# Model Copy Functions
# =================================================================

def get_bundled_models_dir() -> str | None:
    """Get the path to bundled models in the installer app."""
    # When running as a PyInstaller bundle, models are in Contents/Resources/rvc/models
    # When running from source, check relative to current file
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle - models are in Contents/Resources/
        # sys._MEIPASS points to the Resources directory
        if hasattr(sys, '_MEIPASS'):
            models_dir = os.path.join(sys._MEIPASS, "rvc", "models")
            if os.path.exists(models_dir):
                return models_dir
        # Fallback: check relative to executable
        exe_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(exe_dir, "..", "Resources", "rvc", "models")
        if os.path.exists(models_dir):
            return os.path.normpath(models_dir)
    else:
        # Running from source - check relative to this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(script_dir, "rvc", "models")
        if os.path.exists(models_dir):
            return models_dir
    return None


def copy_models_to_destination(data_path: str) -> bool:
    """
    Copy bundled models to user's data location.

    Uses recursive directory copy to ensure all models are transferred,
    including pretraineds, embedders, predictors, and custom models.

    Args:
        data_path: User's data path

    Returns:
        True if successful, False otherwise
    """
    # Get bundled models directory
    bundled_models = get_bundled_models_dir()
    if not bundled_models:
        logger.error("Could not find bundled models directory")
        return False

    dest_models = os.path.join(data_path, "rvc", "models")

    print("Copying bundled models to user data location...")
    logger.info(f"Source: {bundled_models}")
    logger.info(f"Destination: {dest_models}")

    total_copied = 0
    total_skipped = 0
    total_size = 0

    # Walk the entire models directory and copy files
    for root, dirs, files in os.walk(bundled_models):
        # Skip hidden directories (like .DS_Store parent)
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for filename in files:
            # Skip hidden files
            if filename.startswith('.'):
                continue

            # Calculate relative path from bundled_models
            rel_dir = os.path.relpath(root, bundled_models)
            src_path = os.path.join(root, filename)
            dest_path = os.path.join(dest_models, rel_dir, filename) if rel_dir != '.' else os.path.join(dest_models, filename)

            # Skip if destination already exists
            if os.path.exists(dest_path):
                total_skipped += 1
                continue

            # Create destination directory and copy file
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(src_path, dest_path)
            file_size = os.path.getsize(dest_path)
            total_size += file_size
            total_copied += 1

            # Log every 10 files or for large files
            if total_copied % 10 == 0 or file_size > 100 * 1024 * 1024:
                logger.info(f"  Copied {total_copied} files so far ({total_size / 1024 / 1024:.1f} MB)...")

    logger.info(f"Total copied: {total_copied} files ({total_size / 1024 / 1024:.1f} MB)")
    if total_skipped > 0:
        logger.info(f"Total skipped (already exist): {total_skipped} files")
    return True


# =================================================================
# Main Install Function
# =================================================================

def install_models(data_path: str, cli_mode: bool = False) -> bool:
    """
    Install models by copying from bundled location or user's data location.

    Args:
        data_path: User's data path
        cli_mode: If True, run in CLI mode

    Returns:
        True if successful, False otherwise
    """
    print("=" * 60)
    print("Applio Models Installer")
    print("=" * 60)
    print()
    print(f"Data location: {data_path}")
    print()

    # Create directory structure
    create_directory_structure(data_path)

    # Copy bundled models
    success = copy_models_to_destination(data_path)

    if success:
        print()
        print("=" * 60)
        print("Models installed successfully!")
        print("=" * 60)
        print()
        print(f"Models location: {data_path}/rvc/models/")
        print()
        print("You can now launch Applio and start using voice conversion.")
    else:
        print()
        print("=" * 60)
        print("Model installation failed.")
        print("=" * 60)
        return False

    return True


# =================================================================
# Main Entry Point
# =================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Install Applio pretrained models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode without GUI",
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default=None,
        help="Override data path (for testing)",
    )
    args = parser.parse_args()

    cli_mode = args.cli

    print("Starting Applio Models Installer...")
    print()

    # Get or prompt for data path
    prefs = PreferencesManager()
    if args.data_path:
        data_path = os.path.expanduser(args.data_path)
    else:
        data_path = prefs.get_data_path()

    if not data_path:
        print("No existing preferences found.")
        print("Please select where to store Applio models...")
        data_path = select_data_folder(os.path.expanduser("~/Applio"))
        if not data_path:
            print("Installation cancelled.")
            sys.exit(1)
        prefs.set_data_path(data_path)
        prefs.mark_first_run_complete()
        print(f"Data location set to: {data_path}")

    else:
        print(f"Using existing data location: {data_path}")

    success = install_models(data_path, cli_mode)

    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
