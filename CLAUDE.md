# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Applio is a voice conversion application built on RVC (Retrieval-Based Voice Conversion). It provides a Gradio web interface for training voice models, performing inference, text-to-speech, and real-time voice conversion. The project supports macOS native app packaging via PyInstaller.

## Efficiency Notes

**Use interminai for file edits >100 lines** - Edit tool consumes ~10 tokens/line; interminai has fixed ~300 token overhead. See global `~/.claude/CLAUDE.md` for vim workflow patterns.

## Build and Run Commands

```bash
# Installation
./run-install.sh              # Cross-platform (Python 3.12, creates .venv)
./install_applio_mac.sh       # macOS native (Python 3.10, creates venv_macos)
run-install.bat               # Windows

# Running (Gradio web UI)
./run-applio.sh               # Linux/macOS
run-applio.bat                # Windows
python app.py --open          # Direct with auto-browser
python app.py --share         # With public URL
python app.py --port 8080     # Custom port

# macOS Native App
python macos_wrapper.py       # Run with native window
venv_macos/bin/python build_macos.py  # Build .app bundle → dist/Applio.app (requires venv_macos)

# Build options (combine as needed):
python build_macos.py --dmg           # Create DMG installer after build
python build_macos.py --sign          # Sign with Developer ID
python build_macos.py --notarize      # Notarize with Apple (requires --sign)

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
| macOS installer | `install_applio_mac.sh` |
| 44.1kHz patch | `patches/patch_train_44100.py` |
| Code signing config | `assets/entitlements.plist`, `scripts/entitlements_dev_id.plist` |
| Fork differences | `FORK_DIFFERENCES.md` |
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

**Safe-to-modify files** (macOS-only, not in upstream):
- `assets/entitlements.plist`, `scripts/entitlements_dev_id.plist`
- `patches/`, `macos_wrapper.py`, `build_macos.py`, `Applio.spec`
- `install_applio_mac.sh`, `requirements_macos.txt`, `CLAUDE.md`

**Verify file origin:** `git ls-tree upstream/main --name-only | grep <path>`

## Platform Notes

**Python Version Requirements:**
| Context | Python | Virtual Env |
|---------|--------|-------------|
| `install_applio_mac.sh` | 3.10 | `venv_macos` |
| `build_macos.py` | 3.10 | `venv_macos` |
| `run-install.sh` | 3.12 | `.venv` |
| `run-applio.sh` | 3.12 | `.venv` |

**Important:** PyInstaller builds require Python 3.10 (3.12+ has compatibility issues).

**macOS Development:**
- Use `requirements_macos.txt` (includes pywebview, pyinstaller, pyobjc)
- PyTorch uses MPS (Metal Performance Shaders) on Apple Silicon
- Install `setuptools<70` for pkg_resources support
- First run downloads ~300MB models (600s timeout in wrapper)
- User data: `~/Library/Application Support/Applio/` (cache), external path for models/training
- Logs: `~/Library/Logs/Applio/`
- Key environment variables in `macos_wrapper.py`:
  - `PYTORCH_ENABLE_MPS_FALLBACK=1`
  - `GRADIO_TEMP_DIR=~/Library/Caches/Applio/gradio`
  - `HF_HOME=~/Library/Application Support/Applio/huggingface`

**External Data Storage:**
- First-run prompts user to select data location via native macOS folder dialog
- Preferences stored in NSUserDefaults (`com.iahispano.applio`)
- Default location: `~/Applio/`
- Build-time patcher (`patches/patch_data_paths.py`) redirects `core.py`'s `logs_path` to use `now_dir`
- Menu: File → Set Data Location..., Open in Finder (various subfolders)

**Subprocess Script Path Resolution:**
- Script execution mode in `macos_wrapper.py` searches BASE_PATH as fallback
- Required because scripts (in app bundle) won't exist in DATA_PATH (user data location)
- Scripts found at `os.path.join(BASE_PATH, script_relative_path)` when not in cwd

**Subprocess Environment Variables:**
- macOS uses "spawn" not "fork" - subprocesses DON'T inherit parent's env vars
- `macos_wrapper.py` must set `APPLIO_DATA_PATH`, `APPLIO_LOGS_PATH` BEFORE `runpy.run_path()`
- File-based config at `~/Library/Application Support/Applio/runtime_paths.json` provides process-safe path resolution
- See `DEBUGGING_HISTORY.md` for full investigation of this issue

**Build outputs:**
- `build/` - PyInstaller intermediate files
- `dist/` - Final `Applio.app` bundle

**Debugging Frozen Apps:**
- Use file-based logging (`/tmp/applio_debug.txt`) for code that runs before stdout capture
- Check `DEBUGGING_HISTORY.md` for documented debugging sessions and solutions
- All fixes must go through `patches/` - NEVER modify upstream files directly
- When stuck after 3+ fix attempts: STOP and question the architecture (per systematic-debugging skill)

**Build process gotchas:**
- Two entitlements files must stay in sync: `assets/entitlements.plist` (full) and `scripts/entitlements_dev_id.plist` (minimal for Developer ID)
- No microphone entitlement needed - pywebview wrapper doesn't capture audio; Gradio handles it via browser
- Patches in `patches/` are applied to source files before PyInstaller, then source files are restored to pristine state
- PyInstaller cleans `dist/` at start - never delete while builds running
- Build size: ~850MB (~2GB downloads on first launch)
- Signing requires handling broken symlinks (use `path.exists()` before `rglob`)
- PyInstaller cache corruption: clear `~/Library/Application Support/pyinstaller/`
- Notarization fails for PyInstaller apps - users run `xattr -cr Applio.app`

**Pywebview gotchas:**
- Windows created with `webview.create_window()` MUST be assigned to a global variable (e.g., `_about_window`, `_update_window`) to prevent garbage collection
- Menu callbacks need lambda wrappers: `MenuAction("About", lambda: show_about_dialog())` not `MenuAction("About", show_about_dialog)`

**Patch idempotency pattern:**
- Each patch function must check for its OWN specific marker (e.g., `if '_track_process("training"' in content`)
- DO NOT use a shared `IDEMPOTENCY_MARKER` check that returns early - this prevents actual patches from being applied

**Version management:**
- `macos_wrapper.py` reads VERSION dynamically from `assets/config.json` + BUILD_NUMBER
- `build_macos.py` uses same source - both must stay in sync
- `patch_loading_html.py` reads from `assets/config.json` for loading screen version

**Background process tracking:**
- State file: `~/.applio/active_processes.json` (single source of truth)
- Process types: training, preprocess, extract, inference, tts
- POSIX signals: SIGSTOP (pause), SIGCONT (resume), SIGTERM (terminate)
- Patch order: `patch_process_tracking.py` MUST run before `patch_subprocess_validation.py`

**GitHub releases:**
- Repo name for releases: `froggeric/applio-macOS-native-app`
- `gh release create` needs `workflow` scope; use `gh api` as fallback
- Create release via API: `gh api repos/{owner}/{repo}/releases -X POST -f tag_name=v{version}`

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

**44.1kHz Sample Rate (macOS fork only):**
- Config: `rvc/configs/44100.json`
- Applied at build time via `patches/patch_train_44100.py`
- Modifies `tabs/train/train.py` to add 44100 Hz option

**Recovering deleted HuggingFace files:**
```
https://huggingface.co/{repo}/resolve/{commit_hash}/{file_path}
```
