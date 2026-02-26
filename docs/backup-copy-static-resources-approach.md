# Backup: Copy Static Resources Approach

**Date:** 2026-02-25
**Status:** Working (backup in case new approach fails)

## Problem

When the working directory is changed from the app bundle to the user's data location, static resources accessed via `now_dir = os.getcwd()` are not found because they only exist in the app bundle.

## Solution: Copy Static Resources at Startup

Copy all static resources from the app bundle to the user's data location at startup, before changing the working directory.

## Implementation

### File: `macos_wrapper.py`

Add the `setup_bundled_resources()` function that copies:

1. **Individual files:**
   - `assets/config.json` → `assets/config.json`
   - `rvc/lib/tools/tts_voices.json` → `rvc/lib/tools/tts_voices.json`
   - `rvc/configs/*.json` (24000, 32000, 40000, 44100, 48000)
   - `assets/pretrains.json` → `rvc/models/pretraineds/custom/pretrains.json`
   - `tabs/report/recorder.js` → `tabs/report/recorder.js`
   - `tabs/report/main.js` → `tabs/report/main.js`
   - `tabs/report/record_button.js` → `tabs/report/record_button.js`
   - `tabs/realtime/main.js` → `tabs/realtime/main.js`

2. **Directories (only if destination doesn't exist):**
   - `assets/i18n/` → `assets/i18n/`
   - `assets/themes/` → `assets/themes/`
   - `assets/presets/` → `assets/presets/`
   - `assets/formant_shift/` → `assets/formant_shift/`

### Code

```python
def setup_bundled_resources():
    """Copy bundled static resources to user's data location.

    These files are accessed via relative paths from cwd.
    When cwd is changed to user's data location, these files must exist there.
    """
    import shutil

    def copy_file(bundled_rel, dest_rel, desc):
        """Copy a single file if destination doesn't exist."""
        bundled_path = os.path.join(BASE_PATH, bundled_rel)
        dest_path = os.path.join(DATA_PATH, dest_rel)

        if os.path.exists(bundled_path):
            dest_dir = os.path.dirname(dest_path)
            os.makedirs(dest_dir, exist_ok=True)
            if not os.path.exists(dest_path):
                try:
                    shutil.copy2(bundled_path, dest_path)
                    logging.info(f"Copied {desc} to {dest_path}")
                except Exception as e:
                    logging.warning(f"Failed to copy {desc}: {e}")
            else:
                logging.debug(f"{desc} already exists at {dest_path}, skipping")
        else:
            logging.debug(f"No bundled {desc} found at {bundled_path}")

    def copy_dir(bundled_rel, dest_rel, desc):
        """Copy a directory if destination doesn't exist."""
        bundled_path = os.path.join(BASE_PATH, bundled_rel)
        dest_path = os.path.join(DATA_PATH, dest_rel)

        if os.path.exists(bundled_path):
            if not os.path.exists(dest_path):
                try:
                    shutil.copytree(bundled_path, dest_path)
                    logging.info(f"Copied {desc} to {dest_path}")
                except Exception as e:
                    logging.warning(f"Failed to copy {desc}: {e}")
            else:
                logging.debug(f"{desc} already exists at {dest_path}, skipping")
        else:
            logging.debug(f"No bundled {desc} found at {bundled_path}")

    # Copy individual files
    files_to_copy = [
        # Main app config
        ("assets/config.json", "assets/config.json", "App config"),
        # TTS voices list
        ("rvc/lib/tools/tts_voices.json", "rvc/lib/tools/tts_voices.json", "TTS voices list"),
        # Config files for different sample rates
        ("rvc/configs/48000.json", "rvc/configs/48000.json", "48kHz config"),
        ("rvc/configs/44100.json", "rvc/configs/44100.json", "44.1kHz config"),
        ("rvc/configs/40000.json", "rvc/configs/40000.json", "40kHz config"),
        ("rvc/configs/32000.json", "rvc/configs/32000.json", "32kHz config"),
        ("rvc/configs/24000.json", "rvc/configs/24000.json", "24kHz config"),
        # Pretrains download list
        ("assets/pretrains.json", "rvc/models/pretraineds/custom/pretrains.json", "Pretrains list"),
        # JavaScript files for tabs
        ("tabs/report/recorder.js", "tabs/report/recorder.js", "Report tab recorder JS"),
        ("tabs/report/main.js", "tabs/report/main.js", "Report tab main JS"),
        ("tabs/report/record_button.js", "tabs/report/record_button.js", "Report tab button JS"),
        ("tabs/realtime/main.js", "tabs/realtime/main.js", "Realtime tab main JS"),
    ]

    for bundled_rel, dest_rel, desc in files_to_copy:
        copy_file(bundled_rel, dest_rel, desc)

    # Copy directories (only if destination doesn't exist)
    dirs_to_copy = [
        ("assets/i18n", "assets/i18n", "Internationalization files"),
        ("assets/themes", "assets/themes", "Gradio themes"),
        ("assets/presets", "assets/presets", "Effect presets"),
        ("assets/formant_shift", "assets/formant_shift", "Formant shift presets"),
    ]

    for bundled_rel, dest_rel, desc in dirs_to_copy:
        copy_dir(bundled_rel, dest_rel, desc)

setup_bundled_resources()
```

## Pros

- Works without modifying upstream code
- Simple to understand and implement
- Preserves user modifications (doesn't overwrite existing files)

## Cons

- Duplicates static files on disk
- Needs ongoing maintenance as new static resources are added
- First copy takes time if directories are large

## Files Using `now_dir` for Static Resources

These files access static resources via `os.path.join(now_dir, ...)`:

| File | Resource |
|------|----------|
| `assets/themes/loadThemes.py` | `assets/config.json` |
| `assets/i18n/i18n.py` | `assets/config.json`, `assets/i18n/languages` |
| `assets/version_checker.py` | `assets/config.json` |
| `rvc/train/process/extract_model.py` | `assets/config.json` |
| `tabs/plugins/plugins_core.py` | `assets/config.json` |
| `rvc/train/train.py` | `assets/config.json` |
| `tabs/realtime/realtime.py` | `assets/config.json`, `tabs/realtime/main.js` |
| `tabs/settings/sections/*.py` | `assets/config.json` |
| `tabs/report/report.py` | `tabs/report/*.js` |
| `tabs/inference/inference.py` | `assets/audios`, `assets/presets`, `assets/formant_shift` |
| `tabs/train/train.py` | `assets/datasets` |

## How to Restore This Approach

If the new environment variable approach fails, restore by:

1. Copy the `setup_bundled_resources()` function back into `macos_wrapper.py`
2. Call it before changing the working directory
3. Rebuild the app
