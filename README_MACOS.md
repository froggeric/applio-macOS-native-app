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

## Pretrained Models Guide

### Available Models (macOS Build)

The macOS build includes these pretrained models (merged from upstream at build time):

| Model | Sample Rate | Vocoder | Best For |
|-------|-------------|---------|----------|
| **KLM49_HFG** | 48kHz | HiFi-GAN | Tenor vocals, female singing, anime dubbing |
| **RefineGanVCTK** | 44kHz | RefineGAN | Spoken word, narration, neutral tone |
| **KLM50 exp1** | 44kHz | RefineGAN | Female pop, high tenor belts |

Additional models (TITAN, Ov2Super, etc.) are available from the Download tab via the merged `pretrains.json`.

### Choosing the Right Pretrain (2026 Studio Standards)

#### 1. Female Singing (Pop, Anime, Soprano/Mezzo)
**Goal:** Brightness, breath support, soaring high notes, glossy "expensive microphone" sheen.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | RefineGAN KLM5.0 (exp1) 44k | The absolute king for female pop. RefineGAN eliminates high-frequency metallic phase buzz that ruins female belts. KLM dataset gives pristine vibrato and breath control. |
| **#2** | HiFi-GAN KLM49 48k | Best natively supported option. 48kHz captures the "air" of a female voice beautifully. HiFi-GAN can introduce slight buzz in 3-5kHz during very loud high notes. |
| **#3** | Ov2Super 40k | If your female dataset is very small (under 3 minutes), Ov2Super adapts faster than TITAN or KLM, preserving female tone without sounding robotic. |

#### 2. Deep Male Singing (Baritone, Bass, Rock, Warmth)
**Goal:** Chest resonance, thickness, stability in low-mids (100-300Hz), grit.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | HiFi-GAN TITAN 48k (Medium/Large) | Undisputed champion for deep voices. Training data was vastly more diverse in low-end spectrum than KLM. Gives baritone voices thick, natural chest resonance. |
| **#2** | HiFi-GAN KLM49 48k | Excellent for softer, breathier songs (ballads). Tends to naturally EQ brighter, which may strip masculine warmth. |
| **#3** | RefineGAN VCTK 44k | Very neutral. Won't add warmth, but RefineGAN ensures low frequencies stay tight and punchy without getting muddy. |

#### 3. High Male Singing (Tenor, R&B, K-Pop)
**Goal:** Smooth chest-to-head transitions, clean falsetto, dynamic range.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | HiFi-GAN KLM49 48k | Tenor vocals thrive on this model. Handles falsetto transitions beautifully—Korean pop training data is full of high-tenor male vocals. |
| **#2** | RefineGAN KLM5.0 (exp1) 44k | Flawless phase coherence on extreme high notes. Ranks second only due to recovery hassle. |
| **#3** | HiFi-GAN TITAN 48k | Use if tenor sounds too "thin" or "whiny" on KLM. TITAN anchors the voice with more body. |

#### 4. Spoken Word, Podcasting, Narration
**Goal:** Intelligibility, zero musical artifacts, neutral tone, natural pauses.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | RefineGAN VCTK 44k | VCTK is a speech dataset—doesn't add musical vibrato to spoken words. Sounds like a dry audiobook in an anechoic chamber. |
| **#2** | HiFi-GAN TITAN 48k | Excellent for deep, rich "Radio Announcer" or podcast voice. Very stable for long talking stretches. |
| **#3** | HiFi-GAN KLM49 48k | Generally too musical for standard talking—can make speakers sound like they're slightly singing. Perfect for high-energy **Anime Dubbing** or emotional voice acting. |

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
