# Environment Variable Approach for Static Resources Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:executing-plans to implement this plan task-by-task.

**Goal:** Replace the copy-based approach with an environment variable approach so static resources are read from the app bundle instead of being duplicated to user data location.

**Architecture:** Set `APPLIO_BASE_PATH` environment variable in `macos_wrapper.py` pointing to the app bundle. Patch upstream files to use this env var for static resources while keeping `now_dir` for user data paths.

**Tech Stack:** Python, PyInstaller, macOS app bundling, environment variables

---

## Background

**Problem:** When the working directory is changed from the app bundle to the user's data location, static resources (configs, themes, i18n) accessed via `now_dir = os.getcwd()` are not found.

**Previous Solution (Copy-based):** Copy static resources from app bundle to user data location at startup.

**New Solution (Env Var):** Set `APPLIO_BASE_PATH` environment variable and patch upstream code to check it for static resources.

**Benefits:**
- Single source of truth (no duplication)
- Faster startup (no copy operations)
- Easier maintenance (pattern-based patching)

---

## Files Affected

### New Files
- `patches/patch_static_resources.py` - Build-time patcher

### Modified Files
- `macos_wrapper.py` - Set APPLIO_BASE_PATH, remove copy functions
- `build_macos.py` - Apply new patcher

### Files Patched at Build Time
These files will be patched to use `APPLIO_BASE_PATH` for static resources:

| File | Static Resources Accessed |
|------|---------------------------|
| `assets/i18n/i18n.py` | `assets/i18n/languages/`, `assets/config.json` |
| `assets/themes/loadThemes.py` | `assets/themes/`, `assets/config.json` |
| `assets/version_checker.py` | `assets/config.json` |
| `app.py` | `tabs/realtime/main.js` |
| `rvc/lib/utils.py` | `rvc/models/formant/stftpitchshift` |
| `rvc/train/process/extract_model.py` | `assets/config.json` |
| `rvc/lib/tools/tts.py` | `rvc/lib/tools/tts_voices.json` |
| `tabs/settings/sections/filter.py` | `assets/config.json` |
| `tabs/settings/sections/presence.py` | `assets/config.json` |
| `tabs/settings/sections/lang.py` | `assets/config.json` |
| `tabs/settings/sections/precision.py` | `assets/config.json` |
| `tabs/settings/sections/model_author.py` | `assets/config.json` |
| `tabs/plugins/plugins_core.py` | `assets/config.json` |
| `tabs/report/report.py` | `tabs/report/*.js` |

---

## Task 1: Create patch_static_resources.py

**Files:**
- Create: `patches/patch_static_resources.py`

**Step 1: Write the patcher module**

Create `patches/patch_static_resources.py`:

```python
#!/usr/bin/env python3
"""
Patcher to make static resources use APPLIO_BASE_PATH environment variable.

This allows static resources (configs, themes, i18n, JS files) to be read
from the app bundle while user data (models, datasets, logs) goes to the
user-selected data location.

Applied at build time by build_macos.py.
"""

import os
import re


def get_static_resource_base(now_dir_var="now_dir"):
    """
    Generate Python code that gets the base path for static resources.

    Checks APPLIO_BASE_PATH env var first, falls back to now_dir.
    """
    return f'os.environ.get("APPLIO_BASE_PATH", {now_dir_var})'


def patch_file(file_path: str, patterns: list) -> dict:
    """
    Patch a file to use APPLIO_BASE_PATH for static resources.

    Args:
        file_path: Path to the file to patch
        patterns: List of (pattern, replacement) tuples

    Returns:
        Dict with 'modified' (bool) and 'changes' (list of descriptions)
    """
    if not os.path.exists(file_path):
        return {"modified": False, "error": f"File not found: {file_path}"}

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    original_content = content
    changes = []

    for pattern, replacement, description in patterns:
        if re.search(pattern, content):
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                changes.append(description)
                content = new_content

    if content != original_content:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"modified": True, "changes": changes}

    return {"modified": False, "changes": []}


def patch_i18n(base_path: str) -> dict:
    """Patch assets/i18n/i18n.py to use APPLIO_BASE_PATH."""
    file_path = os.path.join(base_path, "assets", "i18n", "i18n.py")

    patterns = [
        # Pattern: os.path.join(now_dir, "assets", "i18n", "languages")
        (
            r'os\.path\.join\(now_dir,\s*["\']assets["\'],\s*["\']i18n["\'],\s*["\']languages["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "i18n", "languages")',
            "i18n languages path"
        ),
        # Pattern: os.path.join(now_dir, "assets", "config.json")
        (
            r'os\.path\.join\(now_dir,\s*["\']assets["\'],\s*["\']config\.json["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
            "config.json path in i18n"
        ),
    ]

    return patch_file(file_path, patterns)


def patch_themes(base_path: str) -> dict:
    """Patch assets/themes/loadThemes.py to use APPLIO_BASE_PATH."""
    file_path = os.path.join(base_path, "assets", "themes", "loadThemes.py")

    patterns = [
        # Pattern: os.path.join(now_dir, "assets", "themes")
        (
            r'os\.path\.join\(now_dir,\s*["\']assets["\'],\s*["\']themes["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "themes")',
            "themes path"
        ),
        # Pattern: os.path.join(now_dir, "assets", "config.json")
        (
            r'os\.path\.join\(now_dir,\s*["\']assets["\'],\s*["\']config\.json["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
            "config.json path in themes"
        ),
    ]

    return patch_file(file_path, patterns)


def patch_version_checker(base_path: str) -> dict:
    """Patch assets/version_checker.py to use APPLIO_BASE_PATH."""
    file_path = os.path.join(base_path, "assets", "version_checker.py")

    patterns = [
        (
            r'os\.path\.join\(now_dir,\s*["\']assets["\'],\s*["\']config\.json["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
            "config.json path in version_checker"
        ),
    ]

    return patch_file(file_path, patterns)


def patch_app_py(base_path: str) -> dict:
    """Patch app.py to use APPLIO_BASE_PATH for tabs/realtime/main.js."""
    file_path = os.path.join(base_path, "app.py")

    patterns = [
        (
            r'os\.path\.join\(now_dir,\s*["\']tabs["\'],\s*["\']realtime["\'],\s*["\']main\.js["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "realtime", "main.js")',
            "realtime main.js path"
        ),
    ]

    return patch_file(file_path, patterns)


def patch_rvc_lib_utils(base_path: str) -> dict:
    """Patch rvc/lib/utils.py to use APPLIO_BASE_PATH for formant binary."""
    file_path = os.path.join(base_path, "rvc", "lib", "utils.py")

    patterns = [
        (
            r'os\.path\.join\(now_dir,\s*["\']rvc["\'],\s*["\']models["\'],\s*["\']formant["\'],\s*["\']stftpitchshift["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "rvc", "models", "formant", "stftpitchshift")',
            "formant stftpitchshift path"
        ),
    ]

    return patch_file(file_path, patterns)


def patch_extract_model(base_path: str) -> dict:
    """Patch rvc/train/process/extract_model.py to use APPLIO_BASE_PATH."""
    file_path = os.path.join(base_path, "rvc", "train", "process", "extract_model.py")

    patterns = [
        (
            r'os\.path\.join\(now_dir,\s*["\']assets["\'],\s*["\']config\.json["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
            "config.json path in extract_model"
        ),
    ]

    return patch_file(file_path, patterns)


def patch_settings_sections(base_path: str) -> dict:
    """Patch all files in tabs/settings/sections/ that access config.json."""
    sections_dir = os.path.join(base_path, "tabs", "settings", "sections")
    results = {}

    files_to_patch = [
        "filter.py",
        "presence.py",
        "lang.py",
        "precision.py",
        "model_author.py",
    ]

    patterns = [
        (
            r'os\.path\.join\(now_dir,\s*["\']assets["\'],\s*["\']config\.json["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
            "config.json path"
        ),
    ]

    for filename in files_to_patch:
        file_path = os.path.join(sections_dir, filename)
        if os.path.exists(file_path):
            result = patch_file(file_path, patterns)
            results[filename] = result

    return results


def patch_plugins_core(base_path: str) -> dict:
    """Patch tabs/plugins/plugins_core.py to use APPLIO_BASE_PATH."""
    file_path = os.path.join(base_path, "tabs", "plugins", "plugins_core.py")

    patterns = [
        (
            r'os\.path\.join\(now_dir,\s*["\']assets["\'],\s*["\']config\.json["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "assets", "config.json")',
            "config.json path in plugins_core"
        ),
    ]

    return patch_file(file_path, patterns)


def patch_report_tab(base_path: str) -> dict:
    """Patch tabs/report/report.py to use APPLIO_BASE_PATH for JS files."""
    file_path = os.path.join(base_path, "tabs", "report", "report.py")

    patterns = [
        (
            r'os\.path\.join\(now_dir,\s*["\']tabs["\'],\s*["\']report["\'],\s*["\']recorder\.js["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "report", "recorder.js")',
            "recorder.js path"
        ),
        (
            r'os\.path\.join\(now_dir,\s*["\']tabs["\'],\s*["\']report["\'],\s*["\']main\.js["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "report", "main.js")',
            "main.js path in report"
        ),
        (
            r'os\.path\.join\(now_dir,\s*["\']tabs["\'],\s*["\']report["\'],\s*["\']record_button\.js["\']\)',
            'os.path.join(os.environ.get("APPLIO_BASE_PATH", now_dir), "tabs", "report", "record_button.js")',
            "record_button.js path"
        ),
    ]

    return patch_file(file_path, patterns)


def patch_all(base_path: str) -> dict:
    """
    Apply all static resource patches.

    Args:
        base_path: Path to the source directory (e.g., dist/Applio.app/Contents/Frameworks)

    Returns:
        Dict with results for each patched file
    """
    results = {
        "i18n": patch_i18n(base_path),
        "themes": patch_themes(base_path),
        "version_checker": patch_version_checker(base_path),
        "app": patch_app_py(base_path),
        "rvc_lib_utils": patch_rvc_lib_utils(base_path),
        "extract_model": patch_extract_model(base_path),
        "settings_sections": patch_settings_sections(base_path),
        "plugins_core": patch_plugins_core(base_path),
        "report_tab": patch_report_tab(base_path),
    }

    return results


if __name__ == "__main__":
    import sys

    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"Patching static resources in: {base_path}")
    print()

    results = patch_all(base_path)

    for component, result in results.items():
        if isinstance(result, dict) and "modified" in result:
            status = "✓ Modified" if result["modified"] else "- No changes"
            changes = result.get("changes", [])
            print(f"  {component}: {status}")
            for change in changes:
                print(f"    - {change}")
        elif isinstance(result, dict):
            # Nested results (e.g., settings_sections)
            print(f"  {component}:")
            for filename, file_result in result.items():
                status = "✓ Modified" if file_result.get("modified") else "- No changes"
                print(f"    {filename}: {status}")
```

**Step 2: Test the patcher locally (dry run)**

Run: `python patches/patch_static_resources.py .`
Expected: Lists what would be patched without modifying (if run without args)

**Step 3: Commit**

```bash
git add patches/patch_static_resources.py
git commit -m "feat: add patch_static_resources.py for env var approach"
```

---

## Task 2: Modify macos_wrapper.py to Set APPLIO_BASE_PATH

**Files:**
- Modify: `macos_wrapper.py`

**Step 1: Add APPLIO_BASE_PATH environment variable**

In `macos_wrapper.py`, add this line BEFORE the `os.chdir(DATA_PATH)` call:

```python
# Set environment variable for static resources (before changing cwd)
os.environ["APPLIO_BASE_PATH"] = BASE_PATH
logging.info(f"APPLIO_BASE_PATH set to: {BASE_PATH}")
```

Find the section around line 316-318 and modify it:

```python
# Change working directory to user data location
# This causes all relative paths (now_dir = os.getcwd()) to resolve here
os.environ["APPLIO_BASE_PATH"] = BASE_PATH  # Static resources use this
os.chdir(DATA_PATH)
logging.info(f"Working directory changed to: {DATA_PATH}")
```

**Step 2: Commit**

```bash
git add macos_wrapper.py
git commit -m "feat: set APPLIO_BASE_PATH env var for static resources"
```

---

## Task 3: Update build_macos.py to Apply the New Patcher

**Files:**
- Modify: `build_macos.py`

**Step 1: Add import and call to patch_static_resources.py**

Find the section where patchers are applied (around "Applying fork patches") and add:

```python
# Apply static resources patcher (env var approach)
print("  Patching: static resources to use APPLIO_BASE_PATH...")
import subprocess
patch_result = subprocess.run(
    [sys.executable, "patches/patch_static_resources.py", FRAMEWORKS_PATH],
    capture_output=True,
    text=True
)
if patch_result.stdout:
    for line in patch_result.stdout.strip().split("\n"):
        print(f"    {line}")
if patch_result.returncode != 0:
    print(f"    Warning: patch_static_resources.py returned non-zero")
```

**Step 2: Commit**

```bash
git add build_macos.py
git commit -m "feat: apply patch_static_resources.py at build time"
```

---

## Task 4: Remove Copy-Based Approach from macos_wrapper.py

**Files:**
- Modify: `macos_wrapper.py`

**Step 1: Remove setup_bundled_resources() function and its call**

Delete the entire `setup_bundled_resources()` function (approximately lines 336-415) and its call.

The function to remove starts with:
```python
# =================================================================
# 1.5. Copy bundled static resources to user's data location
# =================================================================

def setup_bundled_resources():
```

And ends with:
```python
setup_bundled_resources()
```

Remove all of it.

**Step 2: Commit**

```bash
git add macos_wrapper.py
git commit -m "refactor: remove copy-based static resource approach"
```

---

## Task 5: Build and Test

**Files:**
- Test: `dist/Applio.app`

**Step 1: Clean previous test data (optional)**

```bash
# Optional: Reset to test fresh
# defaults delete com.iahispano.applio
# rm -rf /Volumes/ssd/ai/applio/assets/config.json
```

**Step 2: Rebuild the app**

```bash
source venv_macos/bin/activate
python build_macos.py
```

Expected output should include:
```
Patching: static resources to use APPLIO_BASE_PATH...
  i18n: ✓ Modified
  themes: ✓ Modified
  ...
```

**Step 3: Launch and verify**

```bash
# Clear log
: > ~/Library/Logs/Applio/applio_wrapper.log

# Launch app
open dist/Applio.app

# Wait and check log
sleep 15
cat ~/Library/Logs/Applio/applio_wrapper.log
```

Expected log output:
```
APPLIO_BASE_PATH set to: /path/to/Applio.app/Contents/Frameworks
Working directory changed to: /Volumes/ssd/ai/applio
```

Should NOT see:
- "Copied ..." messages (copy approach removed)
- "No such file or directory" errors (env var working)

**Step 4: Verify static resources are read from app bundle**

```bash
# Check that config.json is NOT in user data location (or is the old copy)
ls -la /Volumes/ssd/ai/applio/assets/config.json 2>/dev/null || echo "No config.json in user data (expected)"
```

**Step 5: Commit if working**

```bash
git add -A
git commit -m "test: verify env var approach works"
```

---

## Task 6: Update Documentation

**Files:**
- Modify: `README_MACOS.md`
- Modify: `docs/backup-copy-static-resources-approach.md` (add note about new approach)

**Step 1: Update README_MACOS.md Fork Modifications table**

Update the table to reflect the new patcher:

```markdown
| Patch | File | Purpose |
|-------|------|---------|
| 44100 Hz support | `patches/patch_train_44100.py` | Patches `tabs/train/train.py` to add 44.1kHz option |
| Data paths | `patches/patch_data_paths.py` | Patches `core.py` to use `now_dir` instead of `__file__` for `logs_path` |
| Static resources | `patches/patch_static_resources.py` | Patches files to use `APPLIO_BASE_PATH` for static resources |
| Pretrained merging | `build_macos.py` | Merges upstream `pretrains.json` + `assets/pretrains_macos_additions.json` |
| App bundling | `build_macos.py` | PyInstaller build with signing, DMG, notarization |
| Native wrapper | `macos_wrapper.py` | PyWebview native macOS window with external data location support |
```

**Step 2: Update backup doc with recovery instructions**

Add to `docs/backup-copy-static-resources-approach.md`:

```markdown
## How to Restore This Approach

If the new environment variable approach fails, restore by:

1. Copy the `setup_bundled_resources()` function back into `macos_wrapper.py`
2. Call it before changing the working directory
3. Remove the `os.environ["APPLIO_BASE_PATH"]` line
4. Remove the `patch_static_resources.py` call from `build_macos.py`
5. Rebuild the app

The full function code is preserved above.
```

**Step 3: Commit**

```bash
git add README_MACOS.md docs/backup-copy-static-resources-approach.md
git commit -m "docs: update documentation for env var approach"
```

---

## Verification Checklist

After completing all tasks:

- [ ] `patches/patch_static_resources.py` exists and runs without error
- [ ] `macos_wrapper.py` sets `APPLIO_BASE_PATH` before `os.chdir()`
- [ ] `build_macos.py` applies the new patcher
- [ ] `setup_bundled_resources()` function removed from `macos_wrapper.py`
- [ ] Build completes successfully
- [ ] App launches without "No such file or directory" errors
- [ ] Log shows `APPLIO_BASE_PATH set to: ...`
- [ ] Log does NOT show "Copied ..." messages
- [ ] Documentation updated

---

## Rollback Instructions

If the new approach fails:

1. Restore `macos_wrapper.py` from backup:
   ```bash
   cp docs/macos_wrapper_backup_copy_approach.py macos_wrapper.py
   ```

2. Revert `build_macos.py` changes:
   ```bash
   git checkout HEAD~1 -- build_macos.py
   ```

3. Delete the new patcher:
   ```bash
   rm patches/patch_static_resources.py
   ```

4. Rebuild the app

The backup documentation at `docs/backup-copy-static-resources-approach.md` contains the full copy-based implementation.
