# Applio Fork Differences from Upstream

This document catalogs all changes between this fork (froggeric/applio) and the upstream repository (IAHispano/Applio).

**Comparison:** `upstream/main` vs `HEAD`

---

## Summary

This fork maintains a **minimal delta** from upstream - only macOS native app additions, no modifications to core functionality. All upstream changes are applied via build-time patchers, not by modifying source files directly.

| Category | Count |
|----------|-------|
| Added Files | 14+ |
| Modified Files | 3 (.gitignore, build_macos.py, applio_launcher.py) |

---

## Added Files (macOS Native App Support)

### Core Application Files

| File | Purpose |
|------|---------|
| `applio_launcher.py` | Native macOS launcher with progress window, process group leader, native menu bar |
| `macos_wrapper.py` | Native macOS app wrapper using PyWebView with native dialogs (NSAlert/NSWindow), external data location, process tracking |
| `build_macos.py` | PyInstaller build script for creating `Applio.app` bundle with DMG/PKG options |
| `requirements_macos.txt` | macOS-specific dependencies (pywebview, pyinstaller, pyobjc) |
| `README_MACOS.md` | Build instructions, troubleshooting, and usage documentation |

### Installer Scripts

| File | Purpose |
|------|---------|
| `install_applio_mac.sh` | Standalone macOS installation script with Homebrew dependencies |

### Models Installer (Standalone)

| File | Purpose |
|------|---------|
| `models_installer.py` | Standalone installer that bundles and copies pretrained models to user's data location |
| `ApplioModelsInstaller.spec` | PyInstaller spec for models installer (auto-generated) |

### Build-Time Patches

| File | Purpose |
|------|---------|
| `patches/patch_train_44100.py` | Patches training UI to add 44.1kHz sample rate option |
| `patches/patch_data_paths.py` | Patches core.py to redirect logs_path to external data location |
| `patches/download_pretraineds.py` | Downloads custom pretrained models (KLM49, TITAN, KLM50, VCTK) |
| `patches/patch_refinegan_legacy.py` | Patches RefineGAN for original RVC-Boss pretrained model compatibility |
| `patches/patch_refinegan_legacy_*.py` | Architecture patches for RefineGAN legacy discriminator/generator |
| `patches/patch_process_tracking.py` | Process tracking for training/inference monitoring |
| `patches/patch_static_resources.py` | Static resource path resolution for bundled app |
| `patches/patch_multiprocessing.py` | Multiprocessing fixes for macOS |
| `patches/patch_f0_model_paths.py` | F0 model path resolution |
| `patches/patch_pretrained_selector.py` | Pretrained model selector patches |
| `patches/patch_train_paths.py` | Training path resolution |
| `patches/patch_dataset_paths.py` | Dataset path resolution |
| `patches/patch_extract_error_logging.py` | Enhanced error logging for feature extraction |
| `patches/patch_subprocess_validation.py` | Subprocess validation for training |
| `patches/patch_preflight_validation.py` | Preflight validation for training configuration |

### Assets

| File | Purpose |
|------|---------|
| `assets/entitlements.plist` | macOS code signing entitlements (microphone, JIT, network access) |
| `assets/loading.html` | HTML/CSS loading screen shown during backend startup |
| `assets/pretrains_macos_additions.json` | Additional pretrained model definitions for Download tab |

## Modified Files

| File | Change |
|------|--------|
| `.gitignore` | Added macOS build artifacts, model files (*.pt, *.pth, *.bin), rvc/models/, .archive/ |

---

## Key macOS-Specific Features

### External Data Storage

On first launch, users select where to store all Applio data (models, datasets, training outputs). This location persists in macOS preferences (`com.iahispano.applio`).

**Benefits:**
- Data persists across app updates
- Large files don't bloat the app bundle
- Users can choose external drives for storage

### Build Modes

| Mode | App Size | Models | Use Case |
|------|----------|--------|----------|
| **LITE** (default) | ~820 MB | Download on first launch | Distribution, updates |
| **Models Bundle** | ~5.3 GB | Bundled in PKG | Offline, preservation |

### `macos_wrapper.py` - Main Features

1. **External Data Location:**
   - First-run folder selection dialog
   - Preferences stored in NSUserDefaults
   - Menu: File → Set Data Location, Open in Finder

2. **Environment Setup:**
   - `PYTORCH_ENABLE_MPS_FALLBACK=1` - GPU fallback for Apple Silicon
   - `PYTORCH_ENABLE_METAL_ACCELERATOR=1` - Metal acceleration
   - Cache redirection to `~/Library/Application Support/Applio/`

3. **Native macOS Dialogs:**
   - About dialog: Native NSPanel with version info, GitHub link, update check
   - Check for Updates: Native NSAlert with version comparison
   - Close confirmation: Native NSAlert when closing with active processes
   - Progress monitor: Native NSWindow with pause/resume/terminate controls

4. **Native Progress Window** (`applio_launcher.py`):
   - Training info panel showing best epoch (lowest loss), current epoch, training speed
   - Rich status card with phase detection, tqdm progress parsing
   - Real-time log tailing with smart buffer management
   - Process controls: Terminate, Pause/Resume, Open Logs, Relaunch App
   - Queue-based architecture with memory limits
   - File rotation detection and race condition handling

4. **Process Tracking:**
   - Background training/inference process monitoring
   - State file: `~/.applio/active_processes.json`
   - POSIX signals: SIGSTOP (pause), SIGCONT (resume), SIGTERM (terminate)

5. **Loading Screen:**
   - Serves `assets/loading.html` during backend startup
   - 600-second timeout for first-time model downloads

6. **Subprocess Support:**
   - Training scripts run from app bundle (not user data location)
   - Script path resolution with fallback to BASE_PATH

### `build_macos.py` - Build Options

```bash
python build_macos.py                    # Basic build (LITE, ad-hoc signed)
python build_macos.py --sign             # Sign with Developer ID
python build_macos.py --dmg              # Create DMG installer
python build_macos.py --notarize         # Notarize with Apple
python build_macos.py --models-pkg       # Build models-only PKG installer
```

### Build-Time Patchers

All upstream modifications happen at build time:

| Patcher | Target | Change |
|---------|--------|--------|
| `patch_data_paths.py` | `core.py` | Redirects `logs_path` to external data location |
| `patch_train_44100.py` | `tabs/train/train.py` | Adds 44.1kHz sample rate option |
| `download_pretraineds.py` | (downloads) | Fetches custom models during build |

---

## File Locations (macOS App)

### User Data Location (User-Selected)

| Purpose | Path (relative to data location) |
|---------|----------------------------------|
| Training outputs | `logs/` |
| Voice models | `logs/{model_name}/*.pth` |
| Datasets | `assets/datasets/` |
| Inference outputs | `assets/audios/` |
| Pretrained models | `rvc/models/pretraineds/` |
| F0 predictors | `rvc/models/predictors/` |
| Embedders | `rvc/models/embedders/` |

### Cache Locations (Fixed)

| Purpose | Location |
|---------|----------|
| HuggingFace cache | `~/Library/Application Support/Applio/huggingface/` |
| Gradio temp files | `~/Library/Caches/Applio/gradio/` |
| App logs | `~/Library/Logs/Applio/applio_wrapper.log` |

### Preferences

| Purpose | Location |
|---------|----------|
| Data path, first-run flag | `~/Library/Preferences/com.iahispano.applio.plist` |

---

## Syncing with Upstream

To update from upstream:

```bash
git fetch upstream
git merge upstream/main
```

Since this fork only adds files that don't exist in upstream, there should be no merge conflicts. Model files in `rvc/models/` are gitignored and will persist.

---

## Building the macOS App

```bash
# Development (requires venv with dependencies)
source venv_macos/bin/activate
python macos_wrapper.py

# Build app bundle (LITE mode)
python build_macos.py
# Output: dist/Applio.app (~820MB, models download on first launch)

# Build models installer (optional)
python build_macos.py --models-pkg
# Output: dist/ApplioModels-{version}.pkg (~5.3GB, all models bundled)
```

See `README_MACOS.md` for detailed instructions.
