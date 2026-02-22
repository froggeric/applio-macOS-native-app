# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Applio is a voice conversion application built on RVC (Retrieval-Based Voice Conversion). It provides a Gradio web interface for training voice models, performing inference, text-to-speech, and real-time voice conversion. The project supports macOS native app packaging via PyInstaller.

## Build and Run Commands

```bash
# Installation
./run-install.sh              # Linux/macOS
run-install.bat               # Windows

# Running (Gradio web UI)
./run-applio.sh               # Linux/macOS
run-applio.bat                # Windows
python app.py --open          # Direct with auto-browser
python app.py --share         # With public URL
python app.py --port 8080     # Custom port

# macOS Native App
python macos_wrapper.py       # Run with native window
python build_macos.py         # Build .app bundle → dist/Applio.app

# TensorBoard (training monitoring)
./run-tensorboard.sh          # Linux/macOS
python core.py tensorboard    # Direct

# Docker
docker build -t applio .
docker run -p 6969:6969 applio
```

## Architecture Overview

```
app.py              # Main entry - Gradio web UI initialization
core.py             # Core logic exports (inference, training, TTS)
macos_wrapper.py    # macOS native wrapper (pywebview)
tabs/               # Gradio UI tabs (inference/, train/, tts/, realtime/, etc.)
rvc/                # Voice conversion engine
├── infer/          # Inference pipeline (VoiceConverter, Pipeline)
├── train/          # Training pipeline
├── realtime/       # Real-time voice conversion
├── lib/algorithm/  # Neural network architectures (Synthesizer, generators)
├── lib/predictors/ # F0 extractors (CREPE, FCPE, RMVPE)
├── lib/tools/      # Utilities (TTS, model download, prerequisites)
├── configs/        # Model configs (24k-48kHz), Config singleton
└── models/         # Pretrained models storage
assets/
├── config.json     # App configuration (theme, language, precision)
├── i18n/           # Internationalization (50+ languages)
└── themes/         # Gradio theme definitions
```

## Key Files

| Purpose | File |
|---------|------|
| Main entry point | `app.py` |
| Core function exports | `core.py` |
| Voice conversion logic | `rvc/infer/infer.py` (VoiceConverter class) |
| Conversion pipeline | `rvc/infer/pipeline.py` (Pipeline class) |
| Training logic | `rvc/train/train.py` |
| Neural architectures | `rvc/lib/algorithm/synthesizers.py` |
| App configuration | `assets/config.json` |
| Platform setup | `rvc/lib/platform.py` |
| macOS native wrapper | `macos_wrapper.py` |
| Build specification | `Applio.spec` |

## Code Conventions

- **Formatter**: Black (auto-runs via GitHub Actions on push to main)
- **Import cleanup**: autoflake
- **Encoding**: UTF-8 for all file operations
- **No formal test suite** - manual testing through Gradio UI

## Fork Maintenance

This fork maintains minimal delta from upstream - only macOS additions, no core modifications.

**Sync with upstream:**
```bash
git fetch upstream
git merge upstream/main
```

No merge conflicts expected since macOS files don't overlap with upstream.

## Platform Notes

**macOS Development:**
- Use `requirements_macos.txt` (includes pywebview, pyinstaller, pyobjc)
- PyTorch uses MPS (Metal Performance Shaders) on Apple Silicon
- Python 3.10 required for build (3.12+ has PyInstaller compatibility issues)
- Install `setuptools<70` for pkg_resources support
- First run downloads ~300MB models (600s timeout in wrapper)
- User data: `~/Library/Application Support/Applio/`, logs: `~/Library/Logs/Applio/`
- Key environment variables in `macos_wrapper.py`:
  - `PYTORCH_ENABLE_MPS_FALLBACK=1`
  - `GRADIO_TEMP_DIR=~/Library/Caches/Applio/gradio`
  - `HF_HOME=~/Library/Application Support/Applio/huggingface`

**Build outputs:**
- `build/` - PyInstaller intermediate files
- `dist/` - Final `Applio.app` bundle

## Data Flow

**Voice Conversion Pipeline:**
```
Input Audio → AudioProcessor → Hubert embeddings → F0 extraction →
RVC Pipeline → PostProcessor (Pedalboard effects) → Output Audio
```

**Training Pipeline:**
```
Dataset → Preprocess (slicer) → Extract features → Train model →
Checkpoints in logs/{model_name}/
```

## Pretrained Models

**Vocoders** (neural architectures): HiFi-GAN, RefineGAN, MRF HiFi-GAN
**Pretrained models** (trained weights): Titan, KLM, Snowie, etc. - work WITH a vocoder

| Location | Purpose |
|----------|---------|
| `rvc/models/pretraineds/{vocoder}/` | Built-in pretrained weights |
| `rvc/models/pretraineds/custom/` | Community models (via Download tab) |
| `assets/pretrains.json` | Model download manifest |

**Adding new models:**
1. Add entry to `assets/pretrains_macos_additions.json` (format: `{"ModelName": {"48k": {"D": "url", "G": "url"}}}`)
2. For new sample rates, create `rvc/configs/{rate}.json` and add to `version_config_paths` in `config.py`

**Recovering deleted HuggingFace files:**
```
https://huggingface.co/{repo}/resolve/{commit_hash}/{file_path}
```
