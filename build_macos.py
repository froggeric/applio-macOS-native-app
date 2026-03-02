#!/usr/bin/env python3
"""
Applio macOS Build Script

Usage:
    python build_macos.py              # Build app (models download on first launch)
    python build_macos.py --dmg        # Also create DMG installer
    python build_macos.py --sign --dmg # Signed DMG for distribution
    python build_macos.py --sign --dmg --notarize  # Full release build
    python build_macos.py --models-installer  # Build models installer app
    python build_macos.py --models-installer --sign  # Signed models installer

Build mode:
    Lite build (default): User data stored externally, models download on first launch
    Models PKG: Standalone installer that downloads all pretrained models

Signing & Notarization:
    --sign:           Sign with Developer ID certificate
    --notarize:       Notarize with Apple (password retrieved from keychain "applio-notarize")

Version format: {APPLIO_VERSION}.{BUILD_NUMBER}
Example: 3.6.0.1 (Applio 3.6.0, build 1)
"""

import os
import shutil
import json
import requests
import argparse
import subprocess
import sys
import time
import atexit
from pathlib import Path

# =================================================================
# SELF-PROTECTION: Backup this script to prevent accidental deletion
# =================================================================
# This script has been observed to be deleted during builds.
# We backup and restore it to prevent data loss.
_SCRIPT_PATH = os.path.abspath(__file__)
_BACKUP_PATH = f"/tmp/{os.path.basename(_SCRIPT_PATH)}.backup"

def _backup_script():
    """Backup this script to /tmp."""
    try:
        shutil.copy2(_SCRIPT_PATH, _BACKUP_PATH)
        with open(_BACKUP_PATH, "a") as f:
            f.write(f"\n# Backup created at: {time.ctime()}\n")
    except Exception as e:
        print(f"WARNING: Failed to backup script: {e}")

def _restore_script():
    """Restore this script from /tmp backup if it was deleted."""
    if not os.path.exists(_SCRIPT_PATH) and os.path.exists(_BACKUP_PATH):
        print(f"\n{'='*60}")
        print("WARNING: build_macos.py was deleted during build!")
        print("Restoring from backup...")
        print(f"{'='*60}\n")
        try:
            # Remove the timestamp comment
            with open(_BACKUP_PATH, "r") as f:
                content = f.read()
            # Remove backup timestamp line
            if "# Backup created at:" in content:
                content = content[:content.rfind("\n# Backup created at:")]
            with open(_SCRIPT_PATH, "w") as f:
                f.write(content)
            print(f"Restored: {_SCRIPT_PATH}")
        except Exception as e:
            print(f"ERROR: Failed to restore script: {e}")

# Register restore handler for exit
atexit.register(_restore_script)

# Backup at startup
_backup_script()

import PyInstaller.__main__

# =================================================================
# Configuration
# =================================================================
APP_NAME = "Applio"
BUILD_NUMBER = 3  # Increment for each build

# Read version from assets/config.json
def get_applio_version():
    import json
    try:
        with open("assets/config.json", "r") as f:
            config = json.load(f)
            return config.get("version", "3.6.0")
    except:
        return "3.6.0"

APPLIO_VERSION = get_applio_version()
ENTRY_POINT = "applio_launcher.py"
ICON_FILE = "assets/ICON.ico"

# Signing configuration
DEVELOPER_IDENTITY = "Developer ID Application: Frédéric Guigand (46BZ85ALNS)"
TEAM_ID = "46BZ85ALNS"
ENTITLEMENTS_PATH = "assets/entitlements.plist"

# Full version string
VERSION = f"{APPLIO_VERSION}.{BUILD_NUMBER}"


# =================================================================
# Parse arguments
# =================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Build Applio macOS app",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    # Lite mode is now the default - all user data stored externally
    parser.add_argument(
        "--lite",
        action="store_true",
        default=True,
        help="Lite build - models download on first launch (default)",
    )
    parser.add_argument(
        "--build-number",
        type=int,
        default=BUILD_NUMBER,
        help=f"Build number (default: {BUILD_NUMBER})"
    )
    parser.add_argument(
        "--dmg",
        action="store_true",
        help="Create DMG installer after build"
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="Sign app with Developer ID certificate"
    )
    parser.add_argument(
        "--notarize",
        action="store_true",
        help="Notarize app with Apple (requires --sign)"
    )
    parser.add_argument(
        "--models-installer",
        action="store_true",
        help="Build standalone models installer app (bundles all models)"
    )
    parser.add_argument(
        "--apple-id",
        type=str,
        default="frederic@guigand.com",
        help="Apple ID for notarization"
    )
    return parser.parse_args()


args = parse_args()
LITE_MODE = args.lite
CREATE_DMG = args.dmg
SIGN_APP = args.sign
NOTARIZE = args.notarize
MODELS_INSTALLER = args.models_installer
VERSION = f"{APPLIO_VERSION}.{args.build_number}"

# Validate arguments
if NOTARIZE and not SIGN_APP:
    print("ERROR: --notarize requires --sign")
    sys.exit(1)


# =================================================================
# Clean up previous builds
# =================================================================
def clean_dir(path):
    """Clean directory with retry logic for Spotlight locks."""
    if os.path.exists(path):
        print(f"Cleaning {path}...")
        for i in range(3):
            try:
                shutil.rmtree(path)
                return
            except Exception:
                time.sleep(1)
        os.system(f"rm -rf {path}")


# =================================================================
# Build Models Installer PKG
# =================================================================
def build_models_installer_app():
    """Build the models installer app.

    Creates a standalone .app that copies bundled models to the user's
    Applio data location. No PKG/DMG - just the .app.
    """
    installer_app_name = "ApplioModelsInstaller"
    installer_entry = "models_installer.py"

    print("Building Applio Models Installer app...")
    print("(Standalone .app - run it to install models)")

    # Verify models exist
    models_dir = "rvc/models"
    if not os.path.exists(models_dir):
        print(f"ERROR: Models directory not found at {models_dir}")
        return None

    # Count model files
    model_files = []
    for root, dirs, files in os.walk(models_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if not f.startswith('.'):
                model_files.append(os.path.join(root, f))

    if not model_files:
        print(f"ERROR: No model files found in {models_dir}")
        return None

    total_size = sum(os.path.getsize(f) for f in model_files) / 1024 / 1024
    print(f"Bundling {len(model_files)} model files ({total_size:.1f} MB)")

    # PyInstaller arguments for the installer app
    installer_args = [
        installer_entry,
        f"--name={installer_app_name}",
        "--windowed",
        "--noconfirm",
        f"--icon={ICON_FILE}",
        "--target-arch=arm64",
        "--osx-bundle-identifier=com.iahispano.applio.models-installer",
        "--hidden-import=Foundation",
        "--hidden-import=AppKit",
        "--hidden-import=requests",
        "--hidden-import=tqdm",
        # Bundle the entire rvc/models directory (pretraineds, embedders, predictors)
        "--add-data=rvc/models:rvc/models",
    ]

    PyInstaller.__main__.run(installer_args)

    installer_app_path = os.path.join("dist", f"{installer_app_name}.app")

    if not os.path.exists(installer_app_path):
        print(f"ERROR: Installer app not created at {installer_app_path}")
        return None

    print(f"Installer app created: {installer_app_path}")

    # Patch Info.plist
    info_plist_path = os.path.join(installer_app_path, "Contents", "Info.plist")
    if os.path.exists(info_plist_path):
        print("Patching installer Info.plist...")
        try:
            import plistlib
            with open(info_plist_path, 'rb') as f:
                plist = plistlib.load(f)

            plist['CFBundleShortVersionString'] = VERSION
            plist['CFBundleVersion'] = VERSION
            plist['CFBundleDisplayName'] = "Applio Models Installer"
            plist['CFBundleName'] = "Applio Models Installer"
            plist['NSHumanReadableCopyright'] = f"Copyright © 2026 IAHispano. All rights reserved."

            with open(info_plist_path, 'wb') as f:
                plistlib.dump(plist, f)
            print(f"  Info.plist patched (version: {VERSION})")
        except Exception as e:
            print(f"  WARNING: Failed to patch Info.plist: {e}")

    # Sign the installer app
    if SIGN_APP:
        print("\nSigning installer app with Developer ID certificate...")
        result = subprocess.run(
            ["codesign", "--force", "--deep", "--sign", DEVELOPER_IDENTITY,
             "--options", "runtime", "--timestamp", installer_app_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("  Installer app signed successfully.")
        else:
            print(f"  WARNING: Signing failed: {result.stderr}")
    else:
        # Ad-hoc signing
        print("\nSigning installer app (ad-hoc)...")
        result = subprocess.run(
            ["codesign", "--force", "--deep", "--sign", "-", installer_app_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("  Installer app signed (ad-hoc).")
        else:
            print(f"  WARNING: Ad-hoc signing failed: {result.stderr}")

    # Get app size
    app_size = sum(
        os.path.getsize(os.path.join(root, f))
        for root, dirs, files in os.walk(installer_app_path)
        for f in files
    ) / 1024 / 1024
    print(f"\nInstaller app size: {app_size:.1f} MB")

    return installer_app_path


# If building models installer only, skip main app build
if MODELS_INSTALLER:
    print("=" * 60)
    print(f"Applio Models Installer Build - {VERSION}")
    print("=" * 60)
    print()

    # Only clean build directory - preserve dist/ to keep main app
    clean_dir("build")

    # Build the models installer app
    build_models_installer_app()

    print("\n" + "=" * 60)
    print("MODELS INSTALLER BUILD COMPLETE")
    print("=" * 60)
    sys.exit(0)




# =================================================================
# Merge upstream pretrains.json with macOS additions
# =================================================================
def merge_pretrains():
    """Fetch upstream pretrains.json and merge with macOS-specific additions."""
    upstream_url = "https://huggingface.co/IAHispano/Applio/raw/main/pretrains.json"
    additions_path = "assets/pretrains_macos_additions.json"
    output_path = "assets/pretrains.json"

    print("Fetching upstream pretrains.json...")
    try:
        response = requests.get(upstream_url, timeout=30)
        response.raise_for_status()
        upstream_data = response.json()
        print(f"  Found {len(upstream_data)} upstream models")
    except Exception as e:
        print(f"  WARNING: Failed to fetch upstream pretrains: {e}")
        upstream_data = {}

    print("Loading macOS additions...")
    if os.path.exists(additions_path):
        with open(additions_path, 'r', encoding='utf-8') as f:
            additions_data = json.load(f)
        print(f"  Found {len(additions_data)} macOS-specific models")
    else:
        print(f"  WARNING: Additions file not found at {additions_path}")
        additions_data = {}

    # Merge: additions override/extend upstream
    merged_data = {**upstream_data, **additions_data}

    # Write merged file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(merged_data, f, indent=2, ensure_ascii=False)

    print(f"Merged pretrains.json written with {len(merged_data)} models")
    return output_path


merged_pretrains_path = merge_pretrains()


# =================================================================
# Download pretrained models (full mode only)
# =================================================================
def download_pretraineds():
    """Download additional pretrained models to bundle in the app (full mode only)."""
    download_script = "patches/download_pretraineds.py"
    if not os.path.exists(download_script):
        print(f"WARNING: Pretrained download script not found at {download_script}")
        return False

    print("Downloading pretrained models for full build...")
    result = subprocess.run(
        [sys.executable, download_script],
        capture_output=True,
        text=True
    )

    # Print output
    for line in result.stdout.strip().split('\n'):
        if line:
            print(f"  {line}")

    if result.returncode != 0:
        print(f"WARNING: Pretrained download failed with exit code {result.returncode}")
        if result.stderr:
            print(result.stderr)
        return False

    return True


# Lite mode: models download on first launch
print("Skipping pretrained model downloads (will download on first launch)")


# =================================================================
# Prepare data files for build
# =================================================================
# Hidden imports common in scientific/ML stacks
HIDDEN_IMPORTS = [
    "pkg_resources",
    "packaging",
    "packaging.version",
    "packaging.specifiers",
    "packaging.requirements",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "gradio.networking",
    "gradio.themes",
    "torch",
    "numpy",
    "tensorboard",
    "tensorboardX",
    "passlib.handlers.bcrypt",
    "scipy.signal",
    "scipy.special.cython_special",
    "scipy.linalg.cy_linalg",
    "sklearn.utils._typedefs",
    "fairseq.models.wav2vec.wav2vec2",
    "fairseq.tasks.audio_pretraining",
    "fairseq.modules.checkpoint_activations",
    "fairseq.dataclass.configs",
    "soundfile",
    "_soundfile",
    "webview.platforms.cocoa",
]

# Collect data files - always include these
datas = [
    ("assets", "assets"),
    ("logs", "logs"),
    ("tabs", "tabs"),
    ("core.py", "."),
    ("app.py", "."),
    ("macos_wrapper.py", "."),  # Spawned by applio_launcher.py
]

# In lite mode, we need to handle rvc/ differently to exclude models
if LITE_MODE:
    # Include rvc/ but we'll clean models after build
    datas.append(("rvc", "rvc"))
else:
    # Full mode: include everything
    datas.append(("rvc", "rvc"))

# Construct --add-data arguments
add_data_args = []
for source, dest in datas:
    if os.path.exists(source):
        add_data_args.append(f"--add-data={source}:{dest}")
    else:
        print(f"WARNING: Source {source} not found, skipping.")

# Construct --hidden-import arguments
hidden_import_args = []
for lib in HIDDEN_IMPORTS:
    hidden_import_args.append(f"--hidden-import={lib}")

# PyInstaller arguments
pyinstaller_args = [
    ENTRY_POINT,
    "--name=Applio",
    "--windowed",  # No console
    "--noconfirm",
    "--clean",
    f"--icon={ICON_FILE}",
    "--collect-all=torch",
    "--collect-all=torchaudio",
    "--collect-all=gradio",
    "--collect-all=gradio_client",
    "--collect-all=safehttpx",
    "--collect-all=groovy",
    "--collect-all=sounddevice",
    "--target-arch=arm64",
    "--osx-bundle-identifier=com.iahispano.applio",
    "--additional-hooks-dir=hooks",  # Custom hooks to override broken contrib hooks
] + add_data_args + hidden_import_args


# =================================================================
# Pre-build: Patch source files before PyInstaller bundles them
# =================================================================
def pre_build_patch():
    """
    Patch source files BEFORE PyInstaller bundles them.

    CRITICAL: PyInstaller bundles modules into a PYZ archive. The frozen app
    imports from this archive, NOT from filesystem files. Therefore, patching
    files after build has NO effect.

    We must patch source files before PyInstaller runs, then restore them
    afterward to keep the repo clean.
    """
    print("\n" + "=" * 60)
    print("PRE-BUILD: Patching source files")
    print("=" * 60)

    # Patches to apply: (patcher_path, source_file, description, patcher_type)
    # patcher_type: "dir" = pass directory to patcher, "file" = pass full file path
    patches_to_apply = [
        # Directory-based patchers (pass dirname)
        ("patches/patch_data_paths.py", "core.py", "core.py - file-based path resolution", "dir"),
        ("patches/patch_preflight_validation.py", "core.py", "core.py - pre-flight dataset validation", "dir"),
        ("patches/patch_process_tracking.py", "core.py", "core.py - process tracking for subprocesses", "dir"),
        ("patches/patch_subprocess_validation.py", "core.py", "core.py - subprocess validation", "dir"),
        ("patches/patch_preprocess_warning.py", "core.py", "core.py - preprocess warning", "dir"),
        ("patches/patch_custom_pretrained_paths.py", "core.py", "core.py - custom pretrained path resolution", "dir"),
        ("patches/patch_train_paths.py", "rvc/train/train.py", "rvc/train/train.py - file-based path resolution", "dir"),
        ("patches/patch_mute_paths.py", "rvc/train/extract/preparing_files.py", "preparing_files.py - mute file paths for frozen app", "dir"),
        ("patches/patch_pretrained_selector.py", "rvc/lib/tools/pretrained_selector.py", "pretrained_selector.py - BASE_PATH resolution", "dir"),
        # File-based patchers (pass full file path)
        ("patches/patch_loading_html.py", "assets/loading.html", "assets/loading.html - dynamic version in footer", "file"),
        ("patches/patch_train_44100.py", "tabs/train/train.py", "tabs/train/train.py - 44100 Hz support", "file"),
        ("patches/patch_multiprocessing.py", "rvc/train/extract/extract.py", "extract.py - multiprocessing safety", "file"),
    ]

    patched_files = {}  # Maps source_file -> original content

    for patcher_path, source_file, description, patcher_type in patches_to_apply:
        if not os.path.exists(patcher_path):
            print(f"  SKIPPED: {description} (patcher not found)")
            continue

        if not os.path.exists(source_file):
            print(f"  SKIPPED: {description} (source file not found)")
            continue

        # Read and store original content ONLY if not already stored
        # (handles multiple patchers modifying the same file)
        if source_file not in patched_files:
            with open(source_file, "r", encoding="utf-8") as f:
                patched_files[source_file] = f.read()

        # Determine the argument based on patcher type
        if patcher_type == "dir":
            patcher_arg = os.path.dirname(source_file) or "."
        else:  # "file"
            patcher_arg = source_file

        # Run the patcher
        print(f"  Patching: {description}")
        result = subprocess.run(
            [sys.executable, patcher_path, patcher_arg],
            capture_output=True,
            text=True
        )

        for line in result.stdout.strip().split('\n'):
            if line:
                print(f"    {line}")

        if result.returncode not in [0, 1]:  # 0 = patched, 1 = already patched
            print(f"    WARNING: Patcher returned {result.returncode}")

    return patched_files


def post_build_restore(patched_files):
    """
    Restore source files to original state after build.
    """
    if not patched_files:
        return

    print("\n" + "=" * 60)
    print("POST-BUILD: Restoring source files")
    print("=" * 60)

    for source_file, original_content in patched_files.items():
        try:
            with open(source_file, "w", encoding="utf-8") as f:
                f.write(original_content)
            print(f"  Restored: {source_file}")
        except Exception as e:
            print(f"  WARNING: Failed to restore {source_file}: {e}")


# =================================================================
# Run PyInstaller
# =================================================================
print("=" * 60)
print(f"Applio macOS Build - {VERSION}")
print(f"Mode: LITE (user data stored externally)")
print("=" * 60)
print()

# PATCH SOURCE FILES BEFORE BUILD
patched_files = pre_build_patch()

print("\nStarting PyInstaller build...")
PyInstaller.__main__.run(pyinstaller_args)

# RESTORE SOURCE FILES AFTER BUILD
post_build_restore(patched_files)


# =================================================================
# Post-build: Remove models in lite mode
# =================================================================
def clean_bundled_models():
    """Remove bundled models from build - user data stored externally."""
    print("\nRemoving bundled models (user data stored externally)...")

    frameworks_path = Path("dist") / f"{APP_NAME}.app" / "Contents" / "Frameworks"
    models_path = frameworks_path / "rvc" / "models"

    if not models_path.exists():
        print("  Models directory not found, nothing to clean")
        return

    # Directories to clean (keep .gitkeep files)
    dirs_to_clean = [
        models_path / "pretraineds" / "hifi-gan",
        models_path / "pretraineds" / "refinegan",
        models_path / "pretraineds" / "custom",
        models_path / "predictors",
        models_path / "embedders" / "contentvec",
    ]

    total_freed = 0
    for dir_path in dirs_to_clean:
        if dir_path.exists():
            # Calculate size before deletion
            dir_size = sum(f.stat().st_size for f in dir_path.rglob("*") if f.is_file())
            total_freed += dir_size

            # Remove all files except .gitkeep
            for item in dir_path.iterdir():
                if item.is_file() and item.name != ".gitkeep":
                    item.unlink()
                    print(f"  Removed: {item.relative_to(frameworks_path)}")
                elif item.is_dir():
                    shutil.rmtree(item)
                    print(f"  Removed: {item.relative_to(frameworks_path)}/")

            print(f"  Cleaned: {dir_path.relative_to(frameworks_path)} ({dir_size / 1024 / 1024:.1f} MB)")

    print(f"\n  Total freed: {total_freed / 1024 / 1024:.1f} MB")


clean_bundled_models()


# =================================================================
# Post-build cleanup
# =================================================================
def post_build_cleanup():
    """Clean up after build.

    NOTE: All patches are now applied PRE-BUILD (see pre_build_patch function).
    PyInstaller bundles modules into a PYZ archive, so patching .py files
    after build has NO effect - the frozen app imports from the archive.
    """
    print("\nPost-build cleanup...")

    # Clean up __pycache__ directories
    print("  Cleaning up __pycache__ directories...")
    frameworks_path = os.path.join("dist", f"{APP_NAME}.app", "Contents", "Frameworks")
    resources_path = os.path.join("dist", f"{APP_NAME}.app", "Contents", "Resources")

    for base_path in [frameworks_path, resources_path]:
        if os.path.exists(base_path):
            pycache_count = 0
            for root, dirs, files in os.walk(base_path):
                if "__pycache__" in dirs:
                    pycache_dir = os.path.join(root, "__pycache__")
                    try:
                        shutil.rmtree(pycache_dir)
                        pycache_count += 1
                    except Exception as e:
                        print(f"    WARNING: Failed to remove {pycache_dir}: {e}")
            if pycache_count > 0:
                print(f"    Removed {pycache_count} __pycache__ directories from {os.path.basename(base_path)}")

    return True


post_build_cleanup()


# =================================================================
# Post-processing Info.plist
# =================================================================
info_plist_path = os.path.join("dist", f"{APP_NAME}.app", "Contents", "Info.plist")
app_path = os.path.join("dist", f"{APP_NAME}.app")

if os.path.exists(info_plist_path):
    print("\nPatching Info.plist for Microphone access & Metadata...")
    try:
        import plistlib
        with open(info_plist_path, 'rb') as f:
            plist = plistlib.load(f)

        # Permissions & Usage Descriptions
        plist['NSMicrophoneUsageDescription'] = "Applio needs microphone access to record audio for voice conversion."
        plist['NSCameraUsageDescription'] = "Applio needs camera access for visual processing."
        plist['NSDesktopFolderUsageDescription'] = "Applio needs desktop access to save and load models."
        plist['NSDocumentsFolderUsageDescription'] = "Applio needs documents access to save audio exports."
        plist['NSDownloadsFolderUsageDescription'] = "Applio needs downloads access to retrieve models."
        plist['NSAppleEventsUsageDescription'] = "Applio needs apple events access for automation."

        # Branding with version
        plist['CFBundleShortVersionString'] = VERSION
        plist['CFBundleVersion'] = VERSION
        plist['NSHumanReadableCopyright'] = f"Copyright © 2026 IAHispano. All rights reserved. Build {VERSION}"

        # High-DPI support
        plist['NSHighResolutionCapable'] = True

        # Prevent multiple app instances (defense in depth for subprocess handling)
        plist['LSMultipleInstancesProhibited'] = True

        # Team ID for notarization
        if SIGN_APP:
            plist['com.apple.developer.team-identifier'] = TEAM_ID

        with open(info_plist_path, 'wb') as f:
            plistlib.dump(plist, f)
        print(f"Info.plist patched successfully (version: {VERSION}).")

    except Exception as e:
        print(f"Failed to patch Info.plist: {e}")
else:
    print(f"WARNING: Info.plist not found at {info_plist_path}")


# =================================================================
# Code Signing
# =================================================================
def sign_app():
    """Sign the application with Developer ID certificate."""
    if not SIGN_APP:
        # Ad-hoc signing for local use
        print("\nSigning application (ad-hoc for local use)...")
        if os.path.exists(ENTITLEMENTS_PATH):
            result = subprocess.run(
                ["codesign", "--force", "--deep", "--sign", "-", "--entitlements", ENTITLEMENTS_PATH, app_path],
                capture_output=True, text=True
            )
        else:
            result = subprocess.run(
                ["codesign", "--force", "--deep", "--sign", "-", app_path],
                capture_output=True, text=True
            )

        if result.returncode == 0:
            print("Application signed (ad-hoc).")
        else:
            print(f"WARNING: Ad-hoc signing failed: {result.stderr}")
        return result.returncode == 0

    # Developer ID signing for distribution
    print("\nSigning application with Developer ID certificate...")

    # Check if certificate is available
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True
    )

    if TEAM_ID not in result.stdout:
        print(f"ERROR: Developer ID certificate not found for team {TEAM_ID}")
        print("Available signing identities:")
        print(result.stdout)
        print("\nPlease install your Developer ID certificate and try again.")
        return False

    # Sign the app
    print(f"  Identity: {DEVELOPER_IDENTITY}")

    # Step 1: Remove existing signatures from all binaries
    # PyInstaller binaries have ad-hoc signatures that conflict with hardened runtime
    print("  Removing existing signatures...")
    frameworks_path = Path(app_path) / "Contents" / "Frameworks"
    resources_path = Path(app_path) / "Contents" / "Resources"

    for base_path in [frameworks_path, resources_path]:
        if base_path.exists():
            for ext in ["*.so", "*.dylib"]:
                for binary in base_path.rglob(ext):
                    subprocess.run(
                        ["codesign", "--remove-signature", str(binary)],
                        capture_output=True, text=True
                    )

    # Remove signature from Python framework binaries
    for base in ["Contents/Frameworks", "Contents/Resources"]:
        framework_path = Path(app_path) / base / "Python.framework"
        if framework_path.exists():
            versions_path = framework_path / "Versions"
            if versions_path.exists():
                for version in versions_path.iterdir():
                    if version.is_dir():
                        python_bin = version / "Python"
                        if python_bin.exists():
                            subprocess.run(
                                ["codesign", "--remove-signature", str(python_bin)],
                                capture_output=True, text=True
                            )

    # Remove signature from main executable
    main_exe = Path(app_path) / "Contents" / "MacOS" / APP_NAME
    if main_exe.exists():
        subprocess.run(
            ["codesign", "--remove-signature", str(main_exe)],
            capture_output=True, text=True
        )

    # Step 2: Sign all binaries with hardened runtime
    print("  Signing binaries with hardened runtime...")
    signed_count = 0

    # Sign .so and .dylib files
    for base_path in [frameworks_path, resources_path]:
        if base_path.exists():
            for ext in ["*.so", "*.dylib"]:
                try:
                    for binary in base_path.rglob(ext):
                        if binary.exists():  # Skip broken symlinks
                            result = subprocess.run(
                                ["codesign", "--force", "--sign", DEVELOPER_IDENTITY,
                                 "--options", "runtime", "--timestamp", str(binary)],
                                capture_output=True, text=True
                            )
                            if result.returncode == 0:
                                signed_count += 1
                except (FileNotFoundError, OSError):
                    pass  # Skip directories with broken symlinks

    # Sign Python frameworks
    for base in ["Contents/Frameworks", "Contents/Resources"]:
        framework_path = Path(app_path) / base / "Python.framework"
        if framework_path.exists():
            versions_path = framework_path / "Versions"
            if versions_path.exists():
                for version in versions_path.iterdir():
                    if version.is_dir():
                        python_bin = version / "Python"
                        if python_bin.exists():
                            result = subprocess.run(
                                ["codesign", "--force", "--sign", DEVELOPER_IDENTITY,
                                 "--options", "runtime", "--timestamp", str(python_bin)],
                                capture_output=True, text=True
                            )
                            if result.returncode == 0:
                                signed_count += 1

    # Sign main executable
    if main_exe.exists():
        result = subprocess.run(
            ["codesign", "--force", "--sign", DEVELOPER_IDENTITY,
             "--options", "runtime", "--timestamp", str(main_exe)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            signed_count += 1

    print(f"  Signed {signed_count} binaries")

    # Step 3: Sign the app bundle with --deep
    print("  Signing app bundle...")
    result = subprocess.run(
        ["codesign", "--force", "--deep", "--sign", DEVELOPER_IDENTITY,
         "--entitlements", ENTITLEMENTS_PATH,
         "--options", "runtime",
         "--timestamp",
         app_path],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        print("Application signed successfully.")

        # Verify signature
        print("  Verifying signature...")
        verify_result = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", "--verbose=2", app_path],
            capture_output=True, text=True
        )
        if verify_result.returncode == 0:
            print("  Signature verified.")
        else:
            print(f"  WARNING: Signature verification failed: {verify_result.stderr}")
        return True
    else:
        print(f"ERROR: Signing failed: {result.stderr}")
        return False


sign_success = sign_app()


# =================================================================
# DMG Creation
# =================================================================
def create_dmg():
    """Create a signed DMG installer."""
    if not CREATE_DMG:
        return None

    print("\nCreating DMG installer...")

    dmg_name = f"{APP_NAME}-{VERSION}.dmg"
    dmg_path = os.path.join("dist", dmg_name)
    temp_dmg = os.path.join("dist", "temp.dmg")

    # Remove existing DMG if present
    if os.path.exists(dmg_path):
        os.remove(dmg_path)
    if os.path.exists(temp_dmg):
        os.remove(temp_dmg)

    # Create temporary DMG folder
    dmg_folder = os.path.join("dist", "dmg_temp")
    if os.path.exists(dmg_folder):
        shutil.rmtree(dmg_folder)
    os.makedirs(dmg_folder)

    # Copy app to DMG folder
    print("  Preparing DMG contents...")
    shutil.copytree(app_path, os.path.join(dmg_folder, f"{APP_NAME}.app"))

    # Create symbolic link to Applications folder
    applications_link = os.path.join(dmg_folder, "Applications")
    os.symlink("/Applications", applications_link)

    # Create DMG using hdiutil
    print("  Creating DMG image...")
    result = subprocess.run(
        ["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", dmg_folder,
         "-ov", "-format", "UDZO", temp_dmg],
        capture_output=True, text=True
    )

    # Clean up temp folder
    shutil.rmtree(dmg_folder)

    if result.returncode != 0:
        print(f"ERROR: DMG creation failed: {result.stderr}")
        return None

    # Sign DMG if signing is enabled
    if SIGN_APP and sign_success:
        print("  Signing DMG...")
        sign_result = subprocess.run(
            ["codesign", "--sign", DEVELOPER_IDENTITY, temp_dmg],
            capture_output=True, text=True
        )
        if sign_result.returncode != 0:
            print(f"  WARNING: DMG signing failed: {sign_result.stderr}")

    # Rename to final name
    os.rename(temp_dmg, dmg_path)

    # Get DMG size
    dmg_size = os.path.getsize(dmg_path) / 1024 / 1024
    print(f"  DMG created: {dmg_path}")
    print(f"  Size: {dmg_size:.1f} MB")

    return dmg_path


dmg_path = create_dmg()


# =================================================================
# Notarization
# =================================================================
def get_notarization_password():
    """Retrieve notarization password from keychain."""
    result = subprocess.run(
        ["security", "find-generic-password", "-a", args.apple_id, "-s", "applio-notarize", "-w"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def notarize_app():
    """Notarize the app or DMG with Apple."""
    if not NOTARIZE:
        return True

    if not SIGN_APP or not sign_success:
        print("ERROR: Cannot notarize - app must be signed first")
        return False

    print("\nNotarizing with Apple...")

    # Get app-specific password from keychain
    app_password = get_notarization_password()
    if not app_password:
        print("ERROR: Could not retrieve notarization password from keychain")
        print("Please store it with:")
        print('  security add-generic-password -a "frederic@guigand.com" -s "applio-notarize" -w "your-password"')
        return False

    print("  Retrieved password from keychain")

    # Submit for notarization
    submit_path = dmg_path if dmg_path else app_path
    print(f"  Submitting: {submit_path}")

    result = subprocess.run(
        ["xcrun", "notarytool", "submit", submit_path,
         "--apple-id", args.apple_id,
         "--team-id", TEAM_ID,
         "--password", app_password,
         "--wait"],
        capture_output=True, text=True,
        timeout=1800  # 30 minute timeout
    )

    if result.returncode == 0:
        print("  Notarization successful!")

        # Staple the ticket
        print("  Stapling notarization ticket...")
        staple_result = subprocess.run(
            ["xcrun", "stapler", "staple", app_path],
            capture_output=True, text=True
        )

        if staple_result.returncode == 0:
            print("  Ticket stapled successfully.")
        else:
            print(f"  WARNING: Stapling failed: {staple_result.stderr}")

        return True
    else:
        print(f"ERROR: Notarization failed: {result.stderr}")
        print(result.stdout)
        return False


if NOTARIZE:
    notarize_success = notarize_app()
else:
    notarize_success = None


# =================================================================
# Final summary
# =================================================================
if os.path.exists(app_path):
    # Calculate app size
    app_size = sum(f.stat().st_size for f in Path(app_path).rglob("*") if f.is_file())

    print("\n" + "=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(f"  Version:    {VERSION}")
    print(f"  Mode:       LITE (user data stored externally)")
    print(f"  Signed:     {'Yes (Developer ID)' if SIGN_APP and sign_success else 'Ad-hoc' if sign_success else 'No'}")
    print(f"  Location:   {app_path}")
    print(f"  Size:       {app_size / 1024 / 1024:.1f} MB ({app_size / 1024 / 1024 / 1024:.2f} GB)")

    if dmg_path:
        dmg_size = os.path.getsize(dmg_path) / 1024 / 1024
        print(f"  DMG:        {dmg_path}")
        print(f"  DMG Size:   {dmg_size:.1f} MB")

    if NOTARIZE:
        print(f"  Notarized:  {'Yes' if notarize_success else 'Failed'}")

    print(f"\n  Note: Models (~2GB) will download on first launch")

    print("=" * 60)
else:
    print(f"\nERROR: Build failed - {app_path} not found")
    sys.exit(1)
