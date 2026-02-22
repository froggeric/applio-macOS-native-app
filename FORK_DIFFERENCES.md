# Applio Fork Differences from Upstream

This document catalogs all changes between this fork (froggeric/applio) and the upstream repository (IAHispano/Applio).

**Comparison:** `upstream/main` vs `HEAD`

---

## Summary

This fork maintains a **minimal delta** from upstream - only macOS native app additions, no modifications to core functionality.

| Category | Count |
|----------|-------|
| Added Files | 7 |
| Modified Files | 1 (.gitignore) |
| Total Commits Ahead | 2 |

---

## Commit History

| Commit | Description |
|--------|-------------|
| `53c19a45` | fix: resolve PyInstaller build issues for macOS |
| `72fcfebb` | feat: add macOS native app support |
| `594dcbec` | 3.6.2 (upstream) |

---

## Added Files (macOS Native App Support)

| File | Lines | Purpose |
|------|-------|---------|
| `macos_wrapper.py` | 362 | Native macOS app wrapper using PyWebView with loading screen, permissions management, and environment setup |
| `build_macos.py` | 155 | PyInstaller build script for creating `Applio.app` bundle |
| `requirements_macos.txt` | 50 | macOS-specific dependencies (pywebview, pyinstaller, pyobjc) |
| `README_MACOS.md` | 68 | Build instructions and troubleshooting for macOS |
| `install_applio_mac.sh` | 311 | Standalone macOS installation script with Homebrew dependencies |
| `assets/entitlements.plist` | 39 | macOS code signing entitlements (microphone, JIT, network access) |
| `assets/loading.html` | 252 | HTML/CSS loading screen shown during backend startup |

## Modified Files

| File | Change |
|------|--------|
| `.gitignore` | Added macOS build artifacts (venv_macos/, build/, dist/, Applio.spec, .DS_Store) and exception for requirements*.txt |

---

## Key macOS-Specific Features

### `macos_wrapper.py` - Main Features

1. **Environment Setup:**
   - `PYTORCH_ENABLE_MPS_FALLBACK=1` - GPU fallback for Apple Silicon
   - `PYTORCH_ENABLE_METAL_ACCELERATOR=1` - Metal acceleration
   - `GRADIO_ALLOWED_PATHS` - File access permissions
   - Cache redirection to `~/Library/Application Support/Applio/`

2. **Permissions Management:**
   - `PermissionsManager` class for microphone TCC permissions
   - Uses AVFoundation for native permission requests

3. **Loading Screen:**
   - Serves `assets/loading.html` during backend startup
   - Real-time log monitoring via HTTP server
   - Graceful transition to main Gradio UI
   - 600-second timeout for first-time model downloads

4. **Native Menu:**
   - Application menu with About, Edit, Window sections

### `build_macos.py` - Build Configuration

- Entry point: `macos_wrapper.py`
- Windowed mode (no console)
- Collects all torch, torchaudio, gradio packages
- Hidden imports for ML stack including `pkg_resources`, `packaging`
- Patches `Info.plist` with microphone usage description
- Signs with entitlements for JIT/audio/network access

### `assets/entitlements.plist` - Code Signing

- Disables App Sandbox for file access
- Enables: audio-input, camera, network client/server
- JIT and unsigned memory execution (required for PyTorch)

---

## File Locations (macOS App)

The macOS app stores user data in standard macOS locations:

| Purpose | Location |
|---------|----------|
| HuggingFace models | `~/Library/Application Support/Applio/huggingface/` |
| PyTorch models | `~/Library/Application Support/Applio/torch/` |
| Gradio temp files | `~/Library/Caches/Applio/gradio/` |
| App logs | `~/Library/Logs/Applio/applio_wrapper.log` |
| Matplotlib config | `~/Library/Application Support/Applio/matplotlib/` |

These locations persist across app updates/reinstalls.

---

## Syncing with Upstream

To update from upstream:

```bash
git fetch upstream
git merge upstream/main
```

Since this fork only adds files that don't exist in upstream, there should be no merge conflicts.

---

## Building the macOS App

```bash
# Development (requires venv with dependencies)
source venv_macos/bin/activate
python macos_wrapper.py

# Build app bundle
python build_macos.py
# Output: dist/Applio.app (~2.5GB with models)
```

See `README_MACOS.md` for detailed instructions.
