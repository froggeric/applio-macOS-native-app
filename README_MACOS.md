# Applio macOS Native App

This directory contains the scripts to build Applio as a standalone native macOS application using PyInstaller and PyWebview.

## Prerequisites

- **macOS** (Apple Silicon M1/M2/M3 recommended)
- **Python 3.10** (recommended - 3.11 may work, 3.12+ not tested)
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

# 2. Install dependencies
pip install -r requirements_macos.txt

# 3. Build the app
python build_macos.py

# 4. Run
open dist/Applio.app
```

### Option 2: Development Mode

Run directly without building (useful for testing):

```bash
source venv_macos/bin/activate
python macos_wrapper.py
```

## Build Output

| Output | Size | Description |
|--------|------|-------------|
| `dist/Applio.app` | ~2.5GB | Complete app bundle with all dependencies and models |
| `build/` | - | PyInstaller intermediate files (can be deleted) |

## File Locations

The app stores user data in standard macOS locations (persists across reinstalls):

| Purpose | Location |
|---------|----------|
| **Models** (HuggingFace, PyTorch) | `~/Library/Application Support/Applio/` |
| **Temp files** (Gradio) | `~/Library/Caches/Applio/` |
| **Logs** | `~/Library/Logs/Applio/applio_wrapper.log` |

## Troubleshooting

### "Applio" is damaged and can't be opened

The app is ad-hoc signed (not notarized). Bypass Gatekeeper:

```bash
xattr -cr dist/Applio.app
```

### App hangs on first launch

First launch downloads ~300MB of models. This can take several minutes depending on your connection. Check progress:

```bash
tail -f ~/Library/Logs/Applio/applio_wrapper.log
```

### Backend timeout / App closes before starting

The wrapper waits up to 10 minutes for the backend to start (for slow connections). If this isn't enough, edit `macos_wrapper.py` and increase `timeout=600` to a higher value.

### ModuleNotFoundError: No module named 'pkg_resources'

This occurs with setuptools 70+. The build requires `setuptools<70`:

```bash
pip install "setuptools<70"
```

### No microphone access / silent recording failure

The app requests microphone permission on first use. If denied:
1. Open **System Settings → Privacy & Security → Microphone**
2. Enable **Applio**

### Icon shows as generic/missing

The build converts `assets/ICON.ico` to `.icns` format. If this fails, ensure Pillow is installed:

```bash
pip install Pillow
```

## Build Requirements

The following packages must be installed in the build environment:

| Package | Purpose |
|---------|---------|
| `pyinstaller>=6.3.0` | App bundling |
| `pywebview>=5.0` | Native window |
| `pyobjc-framework-Cocoa` | macOS integration |
| `pyobjc-framework-AVFoundation` | Microphone permissions |
| `Pillow` | Icon conversion |
| `setuptools<70` | pkg_resources support |

All are included in `requirements_macos.txt`.

## Architecture

```
Applio.app/
├── Contents/
│   ├── MacOS/Applio          # Main executable (PyInstaller bootloader)
│   ├── Frameworks/           # Python runtime and packages
│   ├── Resources/            # App assets (assets/, tabs/, rvc/, etc.)
│   ├── Info.plist           # App metadata and permissions
│   └── _CodeSignature/      # Ad-hoc signature
```

## Code Signing

The build script signs the app with entitlements from `assets/entitlements.plist`:

- `com.apple.security.app-sandbox` = false (file system access)
- `com.apple.security.device.audio-input` = true (microphone)
- `com.apple.security.cs.allow-jit` = true (PyTorch JIT compilation)
- `com.apple.security.network.server` = true (Gradio server)

For distribution, you'll need to sign with a Developer ID and notarize with Apple.
