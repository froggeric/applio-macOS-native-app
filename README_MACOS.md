# Applio macOS Native App

This directory contains the scripts to build Applio as a standalone native macOS application using PyInstaller and PyWebview.

## Prerequisites

- **macOS** (Apple Silicon M1/M2/M3 recommended)
- **Python 3.10** (required - 3.12+ has PyInstaller compatibility issues)
- **Homebrew** packages:
  ```bash
  brew install python@3.10 ffmpeg
  ```

## Quick Start

### Option 1: Build from Source

```bash
# 1. Create virtual environment
/opt/homebrew/opt/python@3.10/bin/python3.10 -m venv venv_macos
source venv_macos/bin/activate

# 2. Install dependencies (includes PyObjC, PyInstaller, Pillow)
pip install -r requirements_macos.txt

# 3. Build the app (must run from within venv_macos)
python build_macos.py

# 4. Run
open dist/Applio.app
```

> **Important:** Always run `build_macos.py` from within `venv_macos`. Running outside the venv will produce "Hidden import not found" warnings and the resulting app will be missing runtime dependencies (PyObjC, torch, gradio, etc.).

### Option 2: Development Mode

Run directly without building (useful for testing):

```bash
source venv_macos/bin/activate
python macos_wrapper.py
```

## Build Mode

The build creates a lightweight app (~850MB) with all user data stored externally. Models download automatically on first launch from HuggingFace:

- HiFi-GAN pretraineds: ~800MB
- RefineGAN pretraineds: ~600MB
- F0 predictors (rmvpe, fcpe): ~214MB
- Embedders (contentvec): ~361MB

**Total first-launch download: ~2GB**

## Versioning

Version format: `{APPLIO_VERSION}.{BUILD_NUMBER}`

Example: `3.6.0.1` = Applio 3.6.0, build 1

```bash
# Increment build number
python build_macos.py --build-number 2
```

## DMG Creation

Create a distributable DMG installer:

```bash
# Basic DMG (ad-hoc signed, for personal use)
python build_macos.py --dmg

# For GitHub Releases (signed and notarized)
python build_macos.py --sign --dmg --notarize
```

Output: `dist/Applio-{version}.dmg`

## Models Installer App

For users who want to pre-install all models before launching the main app (or for preservation/offline use), you can create a standalone installer app that bundles all models from the project directory:

```bash
# Build the models installer app
python build_macos.py --models-installer

# Signed version for distribution
python build_macos.py --models-installer --sign
```

Output: `dist/ApplioModelsInstaller.app` (~6.2 GB)

**Note:** The models installer is a standalone .app - no DMG, PKG, or archive needed. Just distribute the .app directly.

### How it Works

1. Double-click `ApplioModelsInstaller.app` to run
2. If you've run Applio before, it shows your existing data location and asks for confirmation
3. If not, it prompts you to select where to store models (with "New Folder" button)
4. Copies all bundled models to the selected location
5. Done - launch Applio and start using voice conversion

### Shared Preferences

Both `Applio.app` and `ApplioModelsInstaller.app` share the same preferences domain (`com.iahispano.applio`), so:
- Running the installer after using Applio will show your existing location
- Running the installer first will pre-configure Applio's data location

### Use Cases

- **Offline installation** - No internet required after downloading the app
- **Preservation** - Models are bundled, protecting against upstream removal
- **Faster setup** - No ~2GB download on first app launch
- **Multiple machines** - Copy the installer app to other machines

### Included Models (21 files, ~5.8 GB)

| Category | Sample Rate | Models |
|----------|-------------|--------|
| **HiFi-GAN Default** | 32k, 40k, 48k | f0D32k, f0G32k, f0D40k, f0G40k, f0D48k, f0G48k |
| **HiFi-GAN Custom** | 48k | KLM49 (D+G), TITAN_Medium (D+G) |
| **RefineGAN Default** | 24k, 32k | f0D24k, f0G24k, f0D32k, f0G32k |
| **RefineGAN Custom** | 44k | KLM50_exp1 (D+G), VCTK_v1 (D+G) |
| **F0 Predictors** | - | rmvpe.pt, fcpe.pt |
| **Embedders** | - | contentvec (pytorch_model.bin, config.json) |

## Code Signing & Notarization

### Prerequisites

1. Apple Developer account
2. Developer ID Application certificate installed in Keychain
3. App-specific password stored in Keychain

### Setting Up Signing

1. **Request Certificate** (if not already done):
   ```bash
   # Create CSR
   mkdir -p ~/Desktop/Applio_Certs
   cd ~/Desktop/Applio_Certs
   openssl req -new -newkey rsa:2048 -nodes \
     -keyout applio_dev_private.key \
     -out applio_dev.csr \
     -subj "/emailAddress=your@email.com/C=FR/ST=State/L=City/O=YourName/CN=your@email.com"
   ```

2. **Get Certificate from Apple**:
   - Go to [Apple Developer Certificates](https://developer.apple.com/account/resources/certificates/list)
   - Create new certificate → "Developer ID Application"
   - Upload the CSR file
   - Download and double-click to install

3. **Store Notarization Password**:
   ```bash
   # Create app-specific password at appleid.apple.com first
   security add-generic-password \
     -a "your@email.com" \
     -s "applio-notarize" \
     -w "xxxx-xxxx-xxxx-xxxx"
   ```

4. **Verify Setup**:
   ```bash
   security find-identity -v -p codesigning
   # Should show: "Developer ID Application: Your Name (TEAMID)"
   ```

### Build Commands

| Purpose | Command |
|---------|---------|
| Local build (ad-hoc) | `python build_macos.py` |
| Signed app | `python build_macos.py --sign` |
| Signed DMG | `python build_macos.py --sign --dmg` |
| Notarized release DMG | `python build_macos.py --sign --dmg --notarize` |
| Models installer app | `python build_macos.py --models-installer` |
| Signed models installer | `python build_macos.py --models-installer --sign` |

### For GitHub Releases

```bash
# Recommended command for distribution
python build_macos.py --sign --dmg --notarize

# Output: dist/Applio-3.6.2.1.dmg (notarized, ~850MB)
```

## Build Output

| Output | Size | Notes |
|--------|------|-------|
| `dist/Applio.app` | ~820MB | LITE mode, models download on first launch |
| `dist/Applio-{version}.dmg` | ~820MB | Signed/notarized DMG for distribution |
| `dist/ApplioModelsInstaller.app` | ~6.2GB | Bundled models installer (standalone .app) |
| `build/` | - | PyInstaller intermediates (can be deleted) |

**Note:** You can build the models installer without deleting the main app - both can coexist in `dist/`.

## File Locations

### User Data Location (First-Run Selection)

On first launch, the app prompts for a data storage location. This location stores all training outputs, datasets, voice models, and inference outputs.

Default: `~/Applio/`

Preferences stored in: `~/Library/Preferences/com.iahispano.applio.plist`

**Note:** Both `Applio.app` and `ApplioModelsInstaller.app` share this preferences file, allowing the installer to use your existing data location.

### Cache Locations (Fixed)

These cache locations are fixed and separate from user data:

| Purpose | Location |
|---------|----------|
| **HuggingFace Cache** | `~/Library/Application Support/Applio/huggingface/` |
| **Temp files** (Gradio) | `~/Library/Caches/Applio/` |
| **Logs** | `~/Library/Logs/Applio/applio_wrapper.log` |

### Data Directory Structure

The user data location contains:

```
~/Applio/                          # User-selected location
├── logs/                           # Training outputs, voice models
│   ├── {model_name}/               # Per-model training data
│   │   ├── sliced_audios_16k/      # Preprocessed audio
│   │   ├── f0/, f0_voiced/         # Pitch extraction
│   │   ├── extracted/               # Feature embeddings
│   │   └── *.pth, *.index          # Model weights, feature index
│   └── zips/                        # Downloaded model archives
├── assets/
│   ├── datasets/                   # Training datasets
│   ├── audios/                     # Inference outputs
│   └── presets/                    # Effect presets
└── rvc/
    ├── configs/                    # Sample rate configs (copied at startup)
    │   ├── 24000.json
    │   ├── 32000.json
    │   ├── 40000.json
    │   ├── 44100.json
    │   └── 48000.json
    ├── lib/tools/
    │   └── tts_voices.json         # TTS voice list (copied at startup)
    └── models/
        ├── pretraineds/             # Pretrained models
        │   ├── hifi-gan/           # HiFi-GAN vocoders
        │   ├── refinegan/           # RefineGAN vocoders
        │   └── custom/              # Downloaded community models
        ├── embedders/               # ContentVec embedders
        ├── predictors/              # F0 predictors (rmvpe.pt, fcpe.pt)
        └── formant/                 # Formant shift models
```

**Note:** Static resources (configs, tts_voices.json) are copied from the app bundle to the user data location on first launch. This avoids modifying upstream code while ensuring relative paths work after the working directory change.

### Changing Data Location

Use **File → Set Data Location...** in the menu bar. Requires app restart.

## Pretrained Models

### Pretrained Models (Auto-downloaded)

Models are downloaded on first launch to the user's data location:

| Category | Sample Rates | Size |
|----------|--------------|------|
| HiFi-GAN | 32k, 40k, 48k | ~800MB |
| RefineGAN | 24k, 32k | ~600MB |
| F0 Predictors | rmvpe.pt, fcpe.pt | ~214MB |
| Embedders | contentvec | ~361MB |

### Custom Models (Download Tab)

Additional models available via Download tab in the app:
- Merged from upstream `pretrains.json` + `assets/pretrains_macos_additions.json`
- Downloaded to `rvc/models/pretraineds/custom/`
- Access via "Custom Pretrained" checkbox in Training tab

### Choosing the Right Pretrain (2026 Studio Standards)

#### 1. Female Singing (Pop, Anime, Soprano/Mezzo)
**Goal:** Brightness, breath support, soaring high notes, glossy "expensive microphone" sheen.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | RefineGAN KLM50 exp1 44k | The absolute king for female pop. RefineGAN eliminates high-frequency metallic phase buzz that ruins female belts. |
| **#2** | HiFi-GAN KLM49 48k | Best natively supported option. 48kHz captures the "air" of a female voice beautifully. |
| **#3** | Ov2Super 40k | If your female dataset is very small (under 3 minutes), adapts faster without sounding robotic. |

#### 2. Deep Male Singing (Baritone, Bass, Rock)
**Goal:** Chest resonance, thickness, stability in low-mids (100-300Hz).

| Rank | Model | Why |
|------|-------|-----|
| **#1** | HiFi-GAN TITAN 48k Medium | Undisputed champion for deep voices. Gives baritone voices thick, natural chest resonance. |
| **#2** | HiFi-GAN KLM49 48k | Excellent for softer, breathier songs (ballads). |
| **#3** | RefineGAN VCTK 44k | Very neutral. Ensures low frequencies stay tight without getting muddy. |

#### 3. High Male Singing (Tenor, R&B, K-Pop)
**Goal:** Smooth chest-to-head transitions, clean falsetto, dynamic range.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | HiFi-GAN KLM49 48k | Tenor vocals thrive on this model. Handles falsetto transitions beautifully. |
| **#2** | RefineGAN KLM50 exp1 44k | Flawless phase coherence on extreme high notes. |
| **#3** | HiFi-GAN TITAN 48k | Use if tenor sounds too "thin" on KLM. TITAN anchors with more body. |

#### 4. Spoken Word, Podcasting, Narration
**Goal:** Intelligibility, zero musical artifacts, neutral tone.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | RefineGAN VCTK 44k | VCTK is a speech dataset—doesn't add musical vibrato to spoken words. |
| **#2** | HiFi-GAN TITAN 48k | Excellent for deep, rich "Radio Announcer" voice. |
| **#3** | HiFi-GAN KLM49 48k | Can make speakers sound like they're slightly singing—good for anime dubbing. |

## Sample Rate Support

The macOS build patches the training UI at build time to support additional sample rates:

| Rate | HiFi-GAN | RefineGAN | Notes |
|------|----------|-----------|-------|
| 24kHz | - | ✓ | Default |
| 32kHz | ✓ | ✓ | Default |
| 40kHz | ✓ | - | Default |
| 44.1kHz | ✓* | ✓* | Patched (custom models) |
| 48kHz | ✓ | - | Default |

*44.1kHz requires custom pretrained models (KLM50 exp1, VCTK v1)

## Architecture

```
Applio.app/
├── Contents/
│   ├── MacOS/Applio          # Main executable (PyInstaller bootloader)
│   ├── Frameworks/           # Python runtime and packages
│   │   ├── tabs/             # UI tabs (patched at build time)
│   │   └── ...               # Other Python packages
│   ├── Resources/            # App assets
│   ├── Info.plist           # App metadata, permissions, version
│   └── _CodeSignature/      # Signature (ad-hoc or Developer ID)
```

**Note:** User data (models, datasets, training outputs) is stored in the user-selected external location, not in the app bundle.

## Fork Modifications (Build-Time Patches)

This fork maintains minimal delta from upstream by patching at build time:

| Patch | File | Purpose |
|-------|------|---------|
| 44100 Hz support | `patches/patch_train_44100.py` | Patches `tabs/train/train.py` to add 44.1kHz option |
| Data paths | `patches/patch_data_paths.py` | Patches `core.py` to use `now_dir` instead of `__file__` for `logs_path` |
| Pretrained merging | `build_macos.py` | Merges upstream `pretrains.json` + `assets/pretrains_macos_additions.json` |
| App bundling | `build_macos.py` | PyInstaller build with signing, DMG, notarization |
| Native wrapper | `macos_wrapper.py` | PyWebview native macOS window with external data location support |
| Native dialogs | `macos_wrapper.py` | All dialogs use native macOS NSAlert/NSWindow (About, Updates, Progress) |
| Static resources | `macos_wrapper.py` | Copies configs and tts_voices.json to user data at startup |
| RefineGAN-Legacy | `patches/patch_refinegan_legacy*.py` | Support for original RVC-Boss RefineGAN pretrained models |

**No upstream source files are modified** - all changes happen during the build process or at runtime startup.

### Fork-Only Files

| File | Purpose |
|------|---------|
| `applio_launcher.py` | Native macOS launcher with progress monitoring window |
| `build_macos.py` | Main build script (app, DMG, models installer) |
| `macos_wrapper.py` | Native window wrapper with external data location, native dialogs |
| `models_installer.py` | Standalone models installer (shares preferences with main app) |
| `install_applio_mac.sh` | Standalone installation script |
| `Applio.spec` | PyInstaller config (generated, gitignored) |
| `ApplioModelsInstaller.spec` | Models installer PyInstaller config (generated) |
| `patches/patch_train_44100.py` | Adds 44100 Hz option to training UI |
| `patches/patch_data_paths.py` | Redirects logs_path to external data location |
| `patches/patch_refinegan_legacy*.py` | RefineGAN legacy model support patches |
| `patches/patch_process_tracking.py` | Process tracking for training monitoring |
| `patches/download_pretraineds.py` | Downloads custom pretrained models |
| `assets/pretrains_macos_additions.json` | Additional pretrained model definitions |
| `assets/entitlements.plist` | Code signing entitlements |
| `assets/loading.html` | Loading screen HTML |
| `requirements_macos.txt` | macOS-specific dependencies |
| `README_MACOS.md` | This documentation |
| `FORK_DIFFERENCES.md` | Fork vs upstream documentation |

## Entitlements

The app is signed with entitlements from `assets/entitlements.plist`:

| Entitlement | Value | Purpose |
|-------------|-------|---------|
| `app-sandbox` | false | Full filesystem access for models |
| `device.audio-input` | true | Microphone access |
| `cs.allow-jit` | true | PyTorch JIT compilation |
| `network.client` | true | Download models |
| `network.server` | true | Gradio local server |

## Troubleshooting

### "Applio" is damaged and can't be opened

For ad-hoc signed builds, bypass Gatekeeper:

```bash
xattr -cr dist/Applio.app
```

For signed/notarized builds, this shouldn't occur.

### App hangs on first launch

First launch downloads models (~2GB for lite build). Check progress:

```bash
tail -f ~/Library/Logs/Applio/applio_wrapper.log
```

### Backend timeout / App closes before starting

The wrapper waits up to 10 minutes for the backend. If needed, edit `macos_wrapper.py` and increase `timeout=600`.

### ModuleNotFoundError: No module named 'pkg_resources'

Requires `setuptools<70`:

```bash
pip install "setuptools<70"
```

### Build shows "Hidden import 'xxx' not found" warnings

This happens when building outside the virtual environment. Always build from within `venv_macos`:

```bash
source venv_macos/bin/activate
python build_macos.py
```

### Build fails with "No module named 'requests'" or icon conversion error

These dependencies are required for the build process. Ensure you've installed all requirements:

```bash
source venv_macos/bin/activate
pip install -r requirements_macos.txt
```

### App fails with "AppHelper is not defined" or "Native APIs not available"

PyObjC is not bundled correctly. This happens when building outside `venv_macos`. Rebuild from within the virtual environment where PyObjC is installed.

### No microphone access / silent recording failure

Grant permission in **System Settings → Privacy & Security → Microphone → Enable Applio**

### Custom pretrained not showing in training

1. Download via Download tab
2. Enable "Custom Pretrained" checkbox in Training tab
3. Select G and D files from dropdowns

### Code signing fails

Verify certificate is installed:

```bash
security find-identity -v -p codesigning
```

Should show your "Developer ID Application" certificate.

### Notarization fails

1. Verify app-specific password in keychain:
   ```bash
   security find-generic-password -a "your@email.com" -s "applio-notarize" -w
   ```
2. Check Apple System Status for outages
3. Review notarization logs:
   ```bash
   xcrun notarytool log <submission-id> --apple-id your@email.com --team-id TEAMID --password "xxxx"
   ```

## Build Requirements

| Package | Purpose |
|---------|---------|
| `pyinstaller>=6.3.0` | App bundling |
| `pywebview>=5.0` | Native window |
| `pyobjc-framework-Cocoa` | macOS integration |
| `pyobjc-framework-AVFoundation` | Microphone permissions |
| `Pillow` | Icon conversion |
| `setuptools<70` | pkg_resources support |

All included in `requirements_macos.txt`.

## Release Checklist

1. Update `BUILD_NUMBER` in `build_macos.py`
2. Build and notarize:
   ```bash
   python build_macos.py --sign --dmg --notarize
   ```
3. Verify DMG installs correctly on clean Mac
4. Upload `dist/Applio-{version}.dmg` to GitHub Releases
