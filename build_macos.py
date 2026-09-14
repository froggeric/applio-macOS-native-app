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
    --notarize:       Notarize with Apple via --keychain-profile (App Store Connect API key;
                      see `xcrun notarytool store-credentials`)
    --keychain-profile NAME  notarytool keychain profile (default: applio-notarize)
    --identity ID     codesign identity override (default: Developer ID Application: ...)
    --team-id ID      team id override

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
                content = content[: content.rfind("\n# Backup created at:")]
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
BUILD_NUMBER = 2  # 3.6.4.2: PR #1280 merged (8/8 a11y program), sync 2026-09-11


# Read version from the tracked assets/config_template.json first (the source of
# truth at build time), falling back to a locally-generated assets/config.json.
# config.json is gitignored and created at runtime by app.py, so reading it first
# could embed a stale version from a developer's local file.
def get_applio_version():
    import json

    for config_file in ("assets/config_template.json", "assets/config.json"):
        try:
            with open(config_file, "r") as f:
                config = json.load(f)
                return config.get("version", "3.6.0")
        except Exception:
            continue
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
        epilog=__doc__,
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
        help=f"Build number (default: {BUILD_NUMBER})",
    )
    parser.add_argument(
        "--dmg", action="store_true", help="Create DMG installer after build"
    )
    parser.add_argument(
        "--sign", action="store_true", help="Sign app with Developer ID certificate"
    )
    parser.add_argument(
        "--notarize",
        action="store_true",
        help="Notarize app with Apple (requires --sign)",
    )
    parser.add_argument(
        "--models-installer",
        action="store_true",
        help="Build standalone models installer app (bundles all models)",
    )
    parser.add_argument(
        "--keychain-profile",
        type=str,
        default="applio-notarize",
        help="notarytool keychain profile name (API-key auth; see xcrun notarytool store-credentials)",
    )
    parser.add_argument(
        "--identity",
        type=str,
        default=DEVELOPER_IDENTITY,
        help="codesign identity (default: hardcoded Developer ID)",
    )
    parser.add_argument(
        "--team-id",
        type=str,
        default=TEAM_ID,
        help="team id (default: 46BZ85ALNS)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="path to App Store Connect API key (.p8) for notarytool (inline auth; CI-friendly). "
        "If set, used instead of --keychain-profile.",
    )
    parser.add_argument(
        "--api-key-id",
        type=str,
        default=None,
        help="App Store Connect API Key ID (required with --api-key)",
    )
    parser.add_argument(
        "--api-issuer",
        type=str,
        default=None,
        help="App Store Connect Issuer ID (required with --api-key)",
    )
    return parser.parse_args()


args = parse_args()
LITE_MODE = args.lite
CREATE_DMG = args.dmg
SIGN_APP = args.sign
NOTARIZE = args.notarize
MODELS_INSTALLER = args.models_installer
VERSION = f"{APPLIO_VERSION}.{args.build_number}"

# Honor --identity / --team-id / --keychain-profile overrides
DEVELOPER_IDENTITY = args.identity
TEAM_ID = args.team_id
KEYCHAIN_PROFILE = args.keychain_profile

# Notarytool auth: inline App Store Connect API key (CI, no keychain needed) if
# provided, else the keychain profile (local interactive). Selected once, used by
# _notarytool_submit.
if args.api_key:
    if not (args.api_key_id and args.api_issuer):
        print("ERROR: --api-key requires --api-key-id and --api-issuer")
        sys.exit(1)
    _NOTARY_AUTH = [
        "--key",
        args.api_key,
        "--key-id",
        args.api_key_id,
        "--issuer",
        args.api_issuer,
    ]
else:
    _NOTARY_AUTH = ["--keychain-profile", KEYCHAIN_PROFILE]

# --- Apple-valid plist versions (notarization requires ≤3 numeric segments,
# no leading zeros — Apple strips them → mismatch). The legacy VERSION
# "3.6.3.5" has 4 segments and FAILS notarization. Encode version+build as a
# single monotonic integer (base-100 per segment) so build order is preserved
# even when patch ≥ 10 (naive APPLIO_VERSION.replace(".","") gives "3635" which
# is valid but non-monotonic at patch≥10). Segments must stay < 100.
CFBUNDLE_SHORT_VERSION = APPLIO_VERSION  # "3.6.4" (display version, ≤3 segments)
_v = (APPLIO_VERSION.split(".") + ["0", "0", "0"])[:3]
_major, _minor, _patch = (int(x) for x in _v)
CFBUNDLE_VERSION = str(
    _major * 1_000_000 + _minor * 10_000 + _patch * 100 + args.build_number
)
# 3.6.3 build 5 → "3060305" | 3.6.4 build 1 → "3060401" | 4.0.0 build 1 → "4000001"

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
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.startswith("."):
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

            with open(info_plist_path, "rb") as f:
                plist = plistlib.load(f)

            plist["CFBundleShortVersionString"] = CFBUNDLE_SHORT_VERSION
            plist["CFBundleVersion"] = CFBUNDLE_VERSION
            plist["CFBundleDisplayName"] = "Applio Models Installer"
            plist["CFBundleName"] = "Applio Models Installer"
            plist["NSHumanReadableCopyright"] = (
                f"Copyright © 2026 IAHispano. All rights reserved."
            )

            with open(info_plist_path, "wb") as f:
                plistlib.dump(plist, f)
            print(f"  Info.plist patched (version: {VERSION})")
        except Exception as e:
            print(f"  WARNING: Failed to patch Info.plist: {e}")

    # Sign the installer app
    if SIGN_APP:
        print("\nSigning installer app with Developer ID certificate...")
        result = subprocess.run(
            [
                "codesign",
                "--force",
                "--deep",
                "--sign",
                DEVELOPER_IDENTITY,
                "--options",
                "runtime",
                "--timestamp",
                installer_app_path,
            ],
            capture_output=True,
            text=True,
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
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("  Installer app signed (ad-hoc).")
        else:
            print(f"  WARNING: Ad-hoc signing failed: {result.stderr}")

    # Get app size
    app_size = (
        sum(
            os.path.getsize(os.path.join(root, f))
            for root, dirs, files in os.walk(installer_app_path)
            for f in files
        )
        / 1024
        / 1024
    )
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
        with open(additions_path, "r", encoding="utf-8") as f:
            additions_data = json.load(f)
        print(f"  Found {len(additions_data)} macOS-specific models")
    else:
        print(f"  WARNING: Additions file not found at {additions_path}")
        additions_data = {}

    # Merge: additions override/extend upstream
    merged_data = {**upstream_data, **additions_data}

    # Write merged file
    with open(output_path, "w", encoding="utf-8") as f:
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
        [sys.executable, download_script], capture_output=True, text=True
    )

    # Print output
    for line in result.stdout.strip().split("\n"):
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
    "menu_spec",  # Spec-driven native menu (imported by launcher + wrapper)
    "applio_update_check",  # Shared update check (lazy-imported -> PyInstaller can't trace it)
    "applio_a11y",  # Accessibility announcement engine (lazy AppKit import -> listed for safety)
    "applio_i18n",  # Native-string i18n translator (lazy import at every call site)
    "applio_native_picker",  # Native NSOpenPanel Browse-button picker (lazy AppKit import)
    "applio_browse_ui",  # Browse-button factory injected into tab files at build time
    "applio_progress_api",  # /applio-a11y/progress payload (lazy-imported by patched app.py)
    "rvc.lib.tools.process_log_parser",  # Training-log metrics for the progress payload (unimported -> DATA-only frozen otherwise)
    "wget",  # Used by rvc/lib/utils.py for downloads
    "resampy",  # Audio resampling library
    "librosa",  # Audio analysis library
    "soundfile",  # Audio file I/O
    "_soundfile",  # soundfile C extension
    "torchcrepe",  # CREPE F0 estimation with PyTorch
    "torchfcpe",  # FCPE F0 estimation
    "pysndfile",  # Sound file library
    "nnAudio",  # Neural network audio processing
    "pyworld",  # WORLD vocoder
    "faiss",  # Similarity search for RVC
    "faiss-cpu",  # CPU version of faiss
    "soxr",  # High-quality audio resampling
    "noisereduce",  # Noise reduction
    "pedalboard",  # Audio effects
    "transformers",  # Hugging Face transformers
    "transformers.models.hubert",  # HuBERT model
    "diffusers",  # Diffusion models
    "diffusers.utils",  # Diffusers utilities
    "onnxruntime",  # ONNX runtime
    "onnx",  # ONNX format
    "pypresence",  # Discord Rich Presence
    "requests",  # HTTP library
    "pillow",  # Image processing
    "PIL",  # Pillow legacy import
    "webrtcvad",  # Voice Activity Detection
    "webrtcvad_wheels",  # webrtcvad wheels package
    "edge_tts",  # Edge TTS
    "edge_tts.communicate",  # Edge TTS communicate module
    "demucs",  # Source separation
    "demucs.api",  # Demucs API
]

# Collect data files - always include these
datas = [
    ("assets", "assets"),
    ("logs", "logs"),
    ("tabs", "tabs"),
    ("core.py", "."),
    ("app.py", "."),
    ("macos_wrapper.py", "."),  # Spawned by applio_launcher.py
    ("STUDIO_PRODUCTION_GUIDE.html", "."),  # Help → Studio Production Guide
    ("STUDIO_PRODUCTION_GUIDE.md", "."),  # Fallback if .html render unavailable
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
pyinstaller_args = (
    [
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
    ]
    + add_data_args
    + hidden_import_args
)


# =================================================================
# Pre-build: Render STUDIO_PRODUCTION_GUIDE.md -> .html
# =================================================================
def render_guide_html(repo_root=None):
    """Convert STUDIO_PRODUCTION_GUIDE.md -> .html (idempotent; fallback to copy).

    `repo_root` defaults to the directory containing this script — build_macos.py
    lives at the repo root, so this is correct regardless of CWD. (There is no
    `now_dir` variable in build_macos.py; the build runs at module scope with
    CWD = repo root and uses relative paths like 'dist'.)
    """
    if repo_root is None:
        repo_root = os.path.dirname(os.path.abspath(__file__))
    md = os.path.join(repo_root, "STUDIO_PRODUCTION_GUIDE.md")
    html = os.path.join(repo_root, "STUDIO_PRODUCTION_GUIDE.html")
    if not os.path.exists(md):
        print("[build] STUDIO_PRODUCTION_GUIDE.md not found; skipping guide render")
        return
    # Idempotent: skip if html is newer than md (so a build with unchanged md
    # leaves the committed html untouched -> `git status` stays clean).
    if os.path.exists(html) and os.path.getmtime(html) >= os.path.getmtime(md):
        print("[build] guide html up to date")
        return
    try:
        import markdown as _md  # noqa

        with open(md, "r", encoding="utf-8") as f:
            body = _md.markdown(f.read(), extensions=["fenced_code", "tables"])
        doc = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>body{font:15px -apple-system,Helvetica,Arial,sans-serif;"
            "max-width:780px;margin:32px auto;padding:0 16px;color:#222;"
            "line-height:1.5}pre{background:#f4f4f4;padding:10px;overflow:auto;"
            "border-radius:6px}code{font:13px Menlo,monospace}table{border-collapse:collapse}"
            "th,td{border:1px solid #ccc;padding:6px 10px}h1,h2,h3{color:#111}</style>"
            f"</head><body>{body}</body></html>"
        )
        with open(html, "w", encoding="utf-8") as f:
            f.write(doc)
        print("[build] rendered STUDIO_PRODUCTION_GUIDE.html")
    except Exception as e:
        print(f"[build] markdown render failed ({e}); copying .md as fallback")
        import shutil

        shutil.copyfile(md, html)


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

    CRITICAL: Patch order matters! Some patches must run before others.
    - patch_process_tracking.py MUST run before patch_subprocess_validation.py
      (tracking transforms subprocess.run to Popen, validation expects run pattern)
    """
    print("\n" + "=" * 60)
    print("PRE-BUILD: Patching source files")
    print("=" * 60)

    # Patch dependencies: patch_name -> list of patches that must run BEFORE it
    PATCH_DEPENDENCIES = {
        "patches/patch_subprocess_validation.py": ["patches/patch_process_tracking.py"],
        "patches/patch_refinegan_legacy_train.py": [
            "patches/patch_refinegan_legacy_discriminator.py"
        ],
    }

    # Patches to apply: (patcher_path, source_file, description, patcher_type)
    # patcher_type: "dir" = pass directory to patcher, "file" = pass full file path
    # IMPORTANT: Order matters! Process tracking MUST come before subprocess validation.
    patches_to_apply = [
        # Directory-based patchers (pass dirname)
        (
            "patches/patch_data_paths.py",
            "core.py",
            "core.py - file-based path resolution",
            "dir",
        ),
        (
            "patches/patch_preflight_validation.py",
            "core.py",
            "core.py - pre-flight dataset validation",
            "dir",
        ),
        (
            "patches/patch_dataset_paths.py",
            "core.py",
            "core.py + tabs/train/train.py - dataset path absolute resolution",
            "dir",
        ),
        (
            "patches/patch_download_paths.py",
            "tabs/download/download.py",
            "tabs/download/download.py - custom-pretrained download data-path resolution",
            "dir",
        ),
        (
            "patches/patch_process_tracking.py",
            "core.py",
            "core.py - process tracking for subprocesses",
            "dir",
        ),  # MUST be before subprocess_validation
        (
            "patches/patch_subprocess_validation.py",
            "core.py",
            "core.py - subprocess validation",
            "dir",
        ),
        (
            "patches/patch_custom_pretrained_paths.py",
            "core.py",
            "core.py - custom pretrained path resolution",
            "dir",
        ),
        (
            "patches/patch_train_paths.py",
            "rvc/train/train.py",
            "rvc/train/train.py - file-based path resolution",
            "dir",
        ),
        (
            "patches/patch_mute_paths.py",
            "rvc/train/extract/preparing_files.py",
            "preparing_files.py - mute file paths for frozen app",
            "dir",
        ),
        (
            "patches/patch_pretrained_selector.py",
            "rvc/lib/tools/pretrained_selector.py",
            "pretrained_selector.py - BASE_PATH resolution",
            "dir",
        ),
        (
            "patches/patch_f0_model_paths.py",
            "rvc/lib/predictors/f0.py",
            "f0.py - absolute model paths for frozen app",
            "dir",
        ),
        # File-based patchers (pass full file path)
        (
            "patches/patch_loading_html.py",
            "assets/loading.html",
            "assets/loading.html - dynamic version in footer",
            "dir",
        ),  # "dir" so patcher gets "assets" dir (patch_all expects dir/root, not the file path)
        (
            "patches/patch_version_checker.py",
            "assets/version_checker.py",
            "assets/version_checker.py - read current version from bundle, not stale data-dir config",
            "dir",
        ),
        (
            "patches/patch_train_44100.py",
            "tabs/train/train.py",
            "tabs/train/train.py - 44100 Hz support",
            "file",
        ),
        (
            "patches/patch_multiprocessing.py",
            "rvc/train/extract/extract.py",
            "extract.py - multiprocessing safety",
            "file",
        ),
        (
            "patches/patch_extract_error_logging.py",
            "rvc/train/extract/extract.py",
            "extract.py - file-based error logging",
            "dir",
        ),
        (
            "patches/patch_preprocess_error_logging.py",
            "rvc/train/preprocess/preprocess.py",
            "preprocess.py - file-based error logging",
            "dir",
        ),
        # Discriminator patch - must come FIRST before train patch
        (
            "patches/patch_refinegan_legacy_discriminator.py",
            "rvc/lib/algorithm/discriminators.py",
            "discriminators.py - DiscriminatorRLegacy support",
            "dir",
        ),
        (
            "patches/patch_refinegan_legacy_train.py",
            "rvc/train/train.py",
            "train.py - RefineGAN-Legacy architecture detection (UPDATED)",
            "dir",
        ),
        (
            "patches/patch_refinegan_legacy.py",
            "rvc/lib/algorithm/synthesizers.py",
            "synthesizers.py - RefineGAN-Legacy vocoder support",
            "dir",
        ),
        (
            "patches/patch_refinegan_legacy_infer.py",
            "rvc/infer/infer.py",
            "infer.py - RefineGAN-Legacy architecture detection",
            "dir",
        ),
        (
            "patches/patch_inference_progress.py",
            "rvc/infer/infer.py",
            "infer.py - batch inference progress tracking",
            "dir",
        ),
        (
            "patches/patch_stop_infer.py",
            "tabs/settings/sections/restart.py",
            "restart.py - cooperative inference cancel",
            "dir",
        ),
        (
            "patches/patch_stop_feedback.py",
            "tabs/settings/sections/restart.py",
            "restart.py - announced Stop Training feedback",
            "dir",
        ),
        (
            "patches/patch_stop_feedback.py",
            "tabs/inference/inference.py",
            "inference.py - announced audio-upload feedback",
            "dir",
        ),
        (
            "patches/patch_progress_routes.py",
            "app.py",
            "app.py - a11y progress route",
            "file",
        ),
        (
            "patches/patch_browse_buttons.py",
            "tabs/train/train.py",
            "train.py - a11y Browse buttons",
            "file",
        ),
        (
            "patches/patch_browse_buttons.py",
            "tabs/inference/inference.py",
            "inference.py - a11y Browse buttons",
            "file",
        ),
        (
            "patches/patch_browse_buttons.py",
            "tabs/tts/tts.py",
            "tts.py - a11y Browse buttons",
            "file",
        ),
        (
            "patches/patch_browse_buttons.py",
            "tabs/realtime/realtime.py",
            "realtime.py - a11y Browse buttons",
            "file",
        ),
        (
            "patches/patch_browse_buttons.py",
            "tabs/voice_blender/voice_blender.py",
            "voice_blender.py - a11y Browse buttons",
            "file",
        ),
        (
            "patches/patch_browse_buttons.py",
            "tabs/extra/sections/processing.py",
            "processing.py - a11y Browse buttons",
            "file",
        ),
        (
            "patches/patch_web_a11y_payload.py",
            "app.py",
            "app.py - inject a11y web payload",
            "file",
        ),
    ]

    # Validate patch order matches dependencies
    patch_names = [p[0] for p in patches_to_apply]
    for patch_name, required_before in PATCH_DEPENDENCIES.items():
        if patch_name in patch_names:
            patch_idx = patch_names.index(patch_name)
            for required in required_before:
                if required in patch_names:
                    required_idx = patch_names.index(required)
                    if required_idx > patch_idx:
                        print(f"  ERROR: Patch order violation!")
                        print(f"    {required} must come before {patch_name}")
                        print(
                            f"    Current order: {required} at {required_idx}, {patch_name} at {patch_idx}"
                        )
                        raise ValueError(
                            "Patch order violates dependencies. Fix the patches_to_apply order."
                        )

    patched_files = {}  # Maps source_file -> original content
    patch_failures = []  # (description, exit code) — any nonzero fails the build

    for patcher_path, source_file, description, patcher_type in patches_to_apply:
        if not os.path.exists(patcher_path):
            patch_failures.append((description, "patcher not found"))
            continue

        if not os.path.exists(source_file):
            patch_failures.append((description, "source file not found"))
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
            [sys.executable, patcher_path, patcher_arg], capture_output=True, text=True
        )

        for line in result.stdout.strip().split("\n"):
            if line:
                print(f"    {line}")

        if result.returncode != 0:
            # 0 = patched or already applied. 2 = anchor miss (upstream moved
            # the anchor); anything else is a crash or invocation failure.
            # Both ship a broken app if skipped.
            patch_failures.append((description, str(result.returncode)))

    if patch_failures:
        for description, why in patch_failures:
            print(f"  PATCH FAILURE: {description} ({why})")
        raise SystemExit(
            "Patchers failed (anchor miss = exit 2, see CLAUDE.md "
            "'Re-pointing patches after an upstream sync')."
        )

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
render_guide_html()

print("\nStarting PyInstaller build...")
PyInstaller.__main__.run(pyinstaller_args)

# Write build_info.json for runtime version reading
build_info_path = os.path.join(
    "dist", f"{APP_NAME}.app", "Contents", "Resources", "build_info.json"
)
os.makedirs(os.path.dirname(build_info_path), exist_ok=True)
with open(build_info_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "version": APPLIO_VERSION,
            "build_number": BUILD_NUMBER,
            "full_version": VERSION,
        },
        f,
    )
print(f"  Wrote build_info.json: version={VERSION}")

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

            print(
                f"  Cleaned: {dir_path.relative_to(frameworks_path)} ({dir_size / 1024 / 1024:.1f} MB)"
            )

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
                print(
                    f"    Removed {pycache_count} __pycache__ directories from {os.path.basename(base_path)}"
                )

    return True


post_build_cleanup()


# =================================================================
# Post-processing Info.plist
# =================================================================
info_plist_path = os.path.join("dist", f"{APP_NAME}.app", "Contents", "Info.plist")
app_path = os.path.join("dist", f"{APP_NAME}.app")

if os.path.exists(info_plist_path):
    print("\nPatching Info.plist for Metadata...")
    try:
        import plistlib

        with open(info_plist_path, "rb") as f:
            plist = plistlib.load(f)

        # Permissions & Usage Descriptions
        # Realtime voice conversion captures the microphone IN-PROCESS
        # (rvc/realtime/audio.py sd.InputStream) since the single-process merge;
        # macOS auto-denies the TCC prompt without this key. (No audio-input
        # entitlement needed: the app is not sandboxed.)
        plist["NSMicrophoneUsageDescription"] = (
            "Applio uses the microphone for real-time voice conversion."
        )
        plist["NSCameraUsageDescription"] = (
            "Applio needs camera access for visual processing."
        )
        plist["NSDesktopFolderUsageDescription"] = (
            "Applio needs desktop access to save and load models."
        )
        plist["NSDocumentsFolderUsageDescription"] = (
            "Applio needs documents access to save audio exports."
        )
        plist["NSDownloadsFolderUsageDescription"] = (
            "Applio needs downloads access to retrieve models."
        )
        plist["NSAppleEventsUsageDescription"] = (
            "Applio needs apple events access for automation."
        )

        # Branding with version. NOTE: CFBundleVersion / CFBundleShortVersionString
        # must be Apple-valid (≤3 numeric segments) for notarization — use the
        # derived constants, NOT the 4-segment display VERSION.
        plist["CFBundleShortVersionString"] = CFBUNDLE_SHORT_VERSION
        plist["CFBundleVersion"] = CFBUNDLE_VERSION
        plist["NSHumanReadableCopyright"] = (
            f"Copyright © 2026 IAHispano. All rights reserved. Build {VERSION}"
        )

        # High-DPI support
        plist["NSHighResolutionCapable"] = True

        # Minimum macOS version (arm64 build; PyTorch MPS + the frameworks we
        # bundle require at least Monterey). Lets Gatekeeper refuse a launch on
        # an unsupported OS with a clear message instead of a cryptic crash.
        plist["LSMinimumSystemVersion"] = "12.0.0"

        # Prevent multiple app instances (defense in depth for subprocess handling)
        plist["LSMultipleInstancesProhibited"] = True

        with open(info_plist_path, "wb") as f:
            plistlib.dump(plist, f)
        print(
            f"Info.plist patched successfully (version: {VERSION}, build: {CFBUNDLE_VERSION})."
        )

    except Exception as e:
        print(f"Failed to patch Info.plist: {e}")
else:
    print(f"WARNING: Info.plist not found at {info_plist_path}")


# =================================================================
# Code Signing
# =================================================================
# Extensions that are never Mach-O — skip the `file` call entirely (speeds up
# discovery of the ~thousands of files in a 1.6GB PyInstaller bundle).
_MACHO_DATA_EXTS = {
    ".py",
    ".pyc",
    ".pyo",
    ".pyd",
    ".json",
    ".txt",
    ".plist",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
    ".gif",
    ".svg",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".md",
    ".toml",
    ".cfg",
    ".ini",
    ".yaml",
    ".yml",
    ".csv",
    ".npy",
    ".npz",
    ".pt",
    ".pth",
    ".ckpt",
    ".bin",
    ".onnx",
    ".zip",
    ".a",
    ".la",
}


def _is_macho_file(path):
    """True if `path` is a Mach-O binary (via `file -b`). Prefilters by size/extension."""
    try:
        if not os.path.isfile(path):
            return False
        if os.path.islink(path) and not os.path.exists(path):
            return False  # broken symlink — codesign refuses these
        if os.path.getsize(path) < 4096:
            return False  # too small to be a Mach-O
        if os.path.splitext(path)[1].lower() in _MACHO_DATA_EXTS:
            return False
    except OSError:
        return False
    # Use bytes (not text=True): `file -b` can emit non-UTF-8 bytes for some
    # binaries, which would raise UnicodeDecodeError under text mode.
    r = subprocess.run(["file", "-b", path], capture_output=True)
    return b"Mach-O" in (r.stdout or b"")


def _discover_macho(app_path):
    """All Mach-O binaries under Contents/{Frameworks,Resources,MacOS}, deepest-first.

    Covers bare executables PyInstaller scatters in Contents/Resources that the
    old *.so/*.dylib glob missed (those go unsigned → notarization fails). The
    outer .app bundle is excluded (sealed separately as the last step).
    """
    found = []
    app = Path(app_path)
    for sub in ("Contents/Frameworks", "Contents/Resources", "Contents/MacOS"):
        base = app / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_dir() or not p.exists():
                continue
            if _is_macho_file(str(p)):
                found.append(str(p))
    found.sort(key=lambda p: p.count(os.sep), reverse=True)  # deepest-first
    return found


def _repair_python_framework_symlinks(app_path):
    """Recreate Python.framework/Versions/Current if broken (codesign rejects
    bundles with broken symlinks; PyInstaller cache can leave a stale one)."""
    for base in ("Contents/Frameworks", "Contents/Resources"):
        versions_dir = Path(app_path) / base / "Python.framework" / "Versions"
        if not versions_dir.exists():
            continue
        reals = [
            v.name
            for v in versions_dir.iterdir()
            if v.is_dir() and v.name.replace(".", "").isdigit()
        ]
        if not reals:
            continue
        current = versions_dir / "Current"
        try:
            if not current.exists():
                current.symlink_to(reals[0])
        except OSError:
            pass


def sign_app():
    """Sign the application with Developer ID certificate (inside-out, hardened
    runtime). Returns True on success, False on any failure (hard-fail)."""
    if not SIGN_APP:
        # Ad-hoc signing for local use
        print("\nSigning application (ad-hoc for local use)...")
        if os.path.exists(ENTITLEMENTS_PATH):
            result = subprocess.run(
                [
                    "codesign",
                    "--force",
                    "--deep",
                    "--sign",
                    "-",
                    "--entitlements",
                    ENTITLEMENTS_PATH,
                    app_path,
                ],
                capture_output=True,
                text=True,
            )
        else:
            result = subprocess.run(
                ["codesign", "--force", "--deep", "--sign", "-", app_path],
                capture_output=True,
                text=True,
            )

        if result.returncode == 0:
            print("Application signed (ad-hoc).")
        else:
            print(f"WARNING: Ad-hoc signing failed: {result.stderr}")
        return result.returncode == 0

    # ---- Developer ID signing for distribution ----
    print("\nSigning application with Developer ID certificate...")

    # Check if certificate is available
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True,
        text=True,
    )
    if TEAM_ID not in result.stdout:
        print(f"ERROR: Developer ID certificate not found for team {TEAM_ID}")
        print("Available signing identities:")
        print(result.stdout)
        print("\nPlease install your Developer ID certificate and try again.")
        return False

    print(f"  Identity: {DEVELOPER_IDENTITY}")
    _repair_python_framework_symlinks(app_path)

    # Discover all Mach-O binaries (incl. bare executables in Contents/Resources).
    print("  Discovering Mach-O binaries...")
    binaries = _discover_macho(app_path)
    print(f"  Found {len(binaries)} Mach-O binaries")

    # Step 1: strip existing (PyInstaller ad-hoc) signatures — idempotent re-runs.
    print("  Removing existing signatures...")
    for b in binaries:
        subprocess.run(
            ["codesign", "--remove-signature", b], capture_output=True, text=True
        )
    subprocess.run(
        ["codesign", "--remove-signature", app_path], capture_output=True, text=True
    )

    # Step 2: sign every leaf Mach-O inside-out (deepest-first) with hardened
    # runtime + timestamp. NO entitlements on leaf binaries — entitlements apply
    # only to the outer bundle/main executable (applying them to every .so/.dylib
    # is unnecessary and can cause codesign warnings).
    print("  Signing binaries (hardened runtime)...")
    signed = 0
    for b in binaries:
        r = subprocess.run(
            [
                "codesign",
                "--force",
                "--sign",
                DEVELOPER_IDENTITY,
                "--options",
                "runtime",
                "--timestamp",
                b,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            signed += 1
        else:
            print(f"  WARNING: failed to sign {b}: {(r.stderr or '').strip()}")
    print(f"  Signed {signed}/{len(binaries)} binaries")

    # Step 3: seal the outer .app bundle LAST, WITH entitlements, WITHOUT --deep.
    # --deep is deprecated for signing; all nested code is already sealed above.
    print("  Signing app bundle...")
    result = subprocess.run(
        [
            "codesign",
            "--force",
            "--sign",
            DEVELOPER_IDENTITY,
            "--entitlements",
            ENTITLEMENTS_PATH,
            "--options",
            "runtime",
            "--timestamp",
            app_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Bundle signing failed: {result.stderr}")
        return False
    print("Application signed successfully.")

    # Step 4: HARD-FAIL verify gate (cheap — catches a bad bundle before the slow
    # notarize step). --deep IS valid for verification (only signing deprecated it).
    print("  Verifying signature (strict)...")
    verify = subprocess.run(
        [
            "codesign",
            "--verify",
            "--all-architectures",
            "--deep",
            "--strict",
            "--verbose=2",
            app_path,
        ],
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        print(f"ERROR: codesign verification failed:\n{verify.stderr}")
        return False
    print("  Signature verified.")

    # Informational Gatekeeper assessment (pre-notarize: source=Developer ID;
    # becomes "Notarized Developer ID" only after stapling).
    spctl = subprocess.run(
        ["spctl", "-vvv", "--assess", "--type", "execute", app_path],
        capture_output=True,
        text=True,
    )
    print(f"  spctl: {((spctl.stdout or '') + ' ' + (spctl.stderr or '')).strip()}")
    return True


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

    # Copy app to DMG folder. symlinks=True is REQUIRED: Python.framework uses
    # symlinks (Python -> Versions/Current/Python, Resources -> Versions/Current/Resources,
    # Current -> Versions/3.x). The default symlinks=False flattens them into real files,
    # breaking the framework's signature seal → notarization rejects the DMG with
    # "The signature of the binary is invalid" on the Python framework paths.
    print("  Preparing DMG contents...")
    shutil.copytree(
        app_path, os.path.join(dmg_folder, f"{APP_NAME}.app"), symlinks=True
    )

    # Create symbolic link to Applications folder
    applications_link = os.path.join(dmg_folder, "Applications")
    os.symlink("/Applications", applications_link)

    # Create DMG using hdiutil
    print("  Creating DMG image...")
    result = subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            dmg_folder,
            "-ov",
            "-format",
            "UDZO",
            temp_dmg,
        ],
        capture_output=True,
        text=True,
    )

    # Clean up temp folder
    shutil.rmtree(dmg_folder)

    if result.returncode != 0:
        print(f"ERROR: DMG creation failed: {result.stderr}")
        return None

    # NOTE: the DMG is assembled UNSIGNED here. It is signed (with --timestamp)
    # and notarized+stapled by the release flow below (create_dmg just builds it).

    # Rename to final name
    os.rename(temp_dmg, dmg_path)

    # Get DMG size
    dmg_size = os.path.getsize(dmg_path) / 1024 / 1024
    print(f"  DMG created: {dmg_path}")
    print(f"  Size: {dmg_size:.1f} MB")

    return dmg_path


# =================================================================
# Notarization
# =================================================================
def _notarytool_submit(artifact, timeout=7200):
    """Submit `artifact` to Apple's notary service, wait for a terminal state, and
    on failure pull the JSON log (which names the exact offending binary/key).
    Returns True only on `status: Accepted`. Auth comes from the module-level
    `_NOTARY_AUTH` (inline API key for CI, or keychain profile for local)."""
    import re

    print(f"  notarytool submit {artifact} ...")
    r = subprocess.run(
        ["xcrun", "notarytool", "submit", artifact] + _NOTARY_AUTH + ["--wait"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (r.stdout or "") + (r.stderr or "")
    print(out)
    if "status: Accepted" in out:
        return True
    # Invalid / rejected / service error — capture the submission id and fetch the
    # JSON log so the offending binary/key is visible (stderr alone is unhelpful).
    m = re.search(r"id:\s*([0-9a-fA-F-]{36})", out)
    if m:
        sub_id = m.group(1)
        log_path = f"/tmp/notary-{os.path.basename(artifact)}-{sub_id}.json"
        subprocess.run(
            ["xcrun", "notarytool", "log", sub_id] + _NOTARY_AUTH + [log_path],
            capture_output=True,
            text=True,
        )
        try:
            with open(log_path) as f:
                print("=== NOTARIZATION LOG ===\n" + f.read())
        except OSError:
            print(f"  (log written to {log_path})")
    return False


def _staple(artifact):
    """Staple the notarization ticket and validate it. Returns False on failure."""
    sr = subprocess.run(
        ["xcrun", "stapler", "staple", artifact], capture_output=True, text=True
    )
    if sr.returncode != 0:
        print(f"ERROR: staple failed for {artifact}: {sr.stderr}")
        return False
    vr = subprocess.run(
        ["xcrun", "stapler", "validate", artifact], capture_output=True, text=True
    )
    if vr.returncode != 0:
        print(f"ERROR: stapler validate failed for {artifact}: {vr.stderr}")
        return False
    print(f"  stapled + validated: {artifact}")
    return True


def _sign_dmg(path):
    """Sign a DMG with Developer ID + secure timestamp. A DMG is not code, so no
    hardened runtime / entitlements — just --sign --timestamp."""
    r = subprocess.run(
        ["codesign", "--force", "--sign", DEVELOPER_IDENTITY, "--timestamp", path],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"ERROR: DMG signing failed: {r.stderr}")
    return r.returncode == 0


def _final_verify(app, dmg):
    """HARD-FAIL final Gatekeeper check on the notarized+stapled artifacts.

    `spctl --assess` on a DMG reports "rejected (…does not seem to be an app)" — that's
    expected for a disk image, NOT a failure. So the .app is gated on spctl/codesign/
    stapler, but the .dmg is gated ONLY on `xcrun stapler validate`."""
    print("\nFinal verification (Gatekeeper)...")
    ok = True

    # --- .app: spctl (Notarized Developer ID) + codesign deep + stapler validate ---
    sp = subprocess.run(
        ["spctl", "-vvv", "--assess", "--type", "execute", app],
        capture_output=True,
        text=True,
    )
    out = ((sp.stdout or "") + " " + (sp.stderr or "")).strip()
    print(f"  spctl {os.path.basename(app)}: {out}")
    if sp.returncode != 0 or "Notarized Developer ID" not in out:
        print(f"ERROR: {app} is not Notarized Developer ID.")
        ok = False
    cs = subprocess.run(
        ["codesign", "-vvv", "--deep", "--strict", app], capture_output=True, text=True
    )
    print(
        f"  codesign {os.path.basename(app)}: {(cs.stderr or cs.stdout or '').strip()}"
    )
    if cs.returncode != 0:
        ok = False
    st = subprocess.run(
        ["xcrun", "stapler", "validate", app], capture_output=True, text=True
    )
    print(
        f"  stapler validate {os.path.basename(app)}: {(st.stdout or st.stderr or '').strip()}"
    )
    if st.returncode != 0:
        ok = False

    # --- .dmg: stapler validate ONLY (spctl on a disk image is not meaningful) ---
    if dmg and os.path.exists(dmg):
        sd = subprocess.run(
            ["xcrun", "stapler", "validate", dmg], capture_output=True, text=True
        )
        print(
            f"  stapler validate {os.path.basename(dmg)}: {(sd.stdout or sd.stderr or '').strip()}"
        )
        if sd.returncode != 0:
            print(f"ERROR: {dmg} stapler validate failed.")
            ok = False

    if not ok:
        print("ERROR: final verification failed.")
        sys.exit(1)
    print(
        "  All artifacts verified (.app: Notarized Developer ID; .dmg: staple validated)."
    )


# ---- Release pipeline --------------------------------------------------------
# Order per Apple "Customizing the notarization workflow": notarize .app → staple
# .app → build .dmg FROM THE STAPLED APP → notarize .dmg → staple .dmg. Stapling
# the .app before building the DMG is required (the DMG must contain the stapled
# app). The .app is ditto-zipped for submission (notarytool rejects a raw .app
# directory); the .dmg is submitted directly.
dmg_path = None
notarize_success = None

if NOTARIZE and sign_success:
    # --- .app ---
    app_zip = os.path.join("dist", f"{APP_NAME}.zip")
    print("\nNotarizing the .app with Apple...")
    subprocess.run(["ditto", "-c", "-k", "--keepParent", app_path, app_zip], check=True)
    ok = _notarytool_submit(app_zip)
    try:
        os.remove(app_zip)
    except OSError:
        pass
    if not ok or not _staple(app_path):
        sys.exit(1)

    # --- .dmg (built from the now-stapled app) ---
    if CREATE_DMG:
        dmg_path = create_dmg()
        if not dmg_path or not _sign_dmg(dmg_path):
            sys.exit(1)
        if not _notarytool_submit(dmg_path) or not _staple(dmg_path):
            sys.exit(1)

    notarize_success = True
    _final_verify(app_path, dmg_path)  # hard-fail: source=Notarized Developer ID

elif CREATE_DMG and sign_success:
    # Signed DMG, no notarization
    dmg_path = create_dmg()
    if dmg_path:
        _sign_dmg(dmg_path)

elif CREATE_DMG:
    dmg_path = create_dmg()


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
    print(
        f"  Signed:     {'Yes (Developer ID)' if SIGN_APP and sign_success else 'Ad-hoc' if sign_success else 'No'}"
    )
    print(f"  Location:   {app_path}")
    print(
        f"  Size:       {app_size / 1024 / 1024:.1f} MB ({app_size / 1024 / 1024 / 1024:.2f} GB)"
    )

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
