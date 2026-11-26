# Mac App Store edition implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Mac App Store edition of Applio for macOS from the same sources as the direct-download edition, with the App Sandbox on, and submit it to App Store Connect.

**Architecture:** `build_macos.py --store` switches the build: store entitlements, store-only patchers in `patches/store/`, store signing, output in `dist-store/`. The edition is written into `build_info.json`, and fork-owned code asks `applio_edition.store_edition()` wherever behaviour differs (data location, bookmarks, menu, model downloads). The direct-download edition keeps its build and its behaviour, with one deliberate correction: the minimum macOS version in its Info.plist is computed from the bundle instead of being hand-written.

**Tech Stack:** Python 3.12, PyInstaller 6.22, PyObjC (AppKit, Foundation, Security), pytest, `codesign`, `xcrun altool`, Xcode 27.2.

**Spec:** `docs/APP_STORE_READINESS.md`

**When to run it:** now, on the owner's word of 2026-11-26 ("after compaction, start the store edition"), in a worktree on the branch `store-edition`. The 3.7.2.1 release has priority: when the owner's manual test results arrive (they test on 2026-11-27), leave this plan, switch to `main`, and handle the release first.

## Global Constraints

- **Upstream files are never edited in the repository.** A change to upstream code is a patcher in `patches/store/`, applied only by `--store`, with markers in `PATCH_MARKERS_STORE`. A change to fork-owned code is an `if store_edition():` branch.
- **The direct-download edition does not change, with one exception.** `build_macos.py --sign --notarize --dmg` produces what it produced before, except that `LSMinimumSystemVersion` is now the real floor of the bundle (the bundle of 3.7.2.1 says 12.0 and needs 15.0: `orjson` is built for macOS 15.0 and 113 other binaries for 14.0). The unit tests pass (`venv_macos/bin/python -m pytest -q tests`), and black is clean on changed fork-owned files (`venv_macos/bin/python -m black --check <files>`).
- **A store build never writes into `dist/`.** It writes into `dist-store/`. The build under test and the release disk image live in `dist/` of the main checkout.
- **Nothing is uploaded to App Store Connect without the owner's explicit word.** The same rule as for GitHub releases.
- **Until the owner gives the bundle id string, store test builds use the throwaway bundle id `com.iahispano.applio.storetest`.** Its container is `~/Library/Containers/com.iahispano.applio.storetest`.
- **In the store edition the data never lives inside the app's container.** It lives in a folder the user chose, on any disk (decision 4).
- **Frozen builds are tested on copies** (`cp -cR dist-store/Applio.app .claude/store/X.app`), never by editing the build itself. An edited copy is re-signed ad hoc before its first launch. Test folders and containers are removed when the task is done; a subagent does not delete outside the repository, it reports what it left. `/Volumes/ssd/ai/applio` is the owner's data location: read only.
- **`/usr/bin/open` stays.** It works under App Sandbox (tested 2026-11-26).
- **Upstream's `sys.path.append(now_dir)` stays.** Nothing writes code into the data location once the Plugins page is gone, and the bundle comes first on `sys.path`.
- **The store edition is expected to grow features of its own** (the owner: "significant work and additional features"). New code goes into fork-owned modules named `applio_*`, not into upstream files.
- **Line numbers below are those of commit d5df92bb.** The text anchors are what matters: a patcher fails with exit 2 when an anchor is not found exactly once.
- **VoiceOver:** checklists for the owner go inline in the message, complete, numbered, without tables.

## User decisions (already made)

The owner's answers of 2026-11-26 to the eight questions of the assessment:

- **Name and icon:** "we have iahispano authorisation." Applio and upstream's icon stay. Keep the authorisation where App Review can see it.
- **Bundle id:** "my own bundle id, there is significant work and additional features to warrant a different bundle it". The id string itself has not been given yet: task 8 needs it.
- **Copyleft parts:** "approved inclusion, it is my responsability". `soxr` and `edge-tts` stay and are named in the app.
- **Data location:** the owner asked for a recommendation, with two requirements: the data must survive removing and reinstalling the app, and the user must be able to change it. The plan follows the recommendation given: a folder the user chooses, on any disk, with its bookmark kept in the login keychain so that a new installation finds the folder again (tasks 4 and 5).
- **Real-time conversion:** the owner leans towards leaving it out of the first store version. The plan does that and keeps the cheap test of a pipe-based channel (task 7), for a later version.
- **First download:** "no bundling of models; should be user selectable, 3gb is too big for a first download, and users might not need everything." The download is split into three parts, chosen by the user (task 6).
- **Privacy policy:** on GitHub for now, later the owner's own website. One constant, `PRIVACY_POLICY_URL` in `applio_edition.py`.
- **Minimum macOS version:** the owner asked for a recommendation. The bundle decides: the build computes the highest minimum among its binaries and writes it into the Info.plist (task 1). Today that is 15.0.
- **Order:** "do the 3.7.2.1 release first. i will manually test tomorrow." "keep the dataset for now." "delete the empty folders" (done on 2026-11-26). "after compaction, start the store edition".
- Standing: "no new release on github yet"; "run the experiment" and "measure" (training without worker processes is the accepted route); never modify upstream files directly, use `patches/`.

## Open with the owner

1. The bundle id string (task 8).
2. Whether the recommendation on the data location stands. If the owner prefers another way, tasks 4 and 5 change and nothing else.
3. Whether macOS 15 as the floor stands. It is the bundle's own floor; raising it is one line, lowering it is not possible without changing dependencies.

## Review Focus

Failure modes the tasks' tests do not reach on their own, most likely first:

1. After removing the app and its container and installing it again, the app must find the data folder by itself, or ask once, and never lose data (task 4 tests, task 5 tests, task 8 step 8.6).
2. A first launch with "Not now", or without the optional parts: the app starts, and File, Download Models… completes the download later (task 6 tests, task 7 steps 7.6 and 7.9).
3. A failing extraction must still be reported: the pools reported errors as warnings, and the serial loops keep those messages (task 2 test).
4. `--store` with flags it cannot take must stop before anything is built (task 1 `tests/test_build_options.py`).
5. The minimum macOS version in the Info.plist must equal the bundle's real floor, not a hand-written number (task 1 test of `minimum_macos_version`, task 8 step 8.9).
6. Cancelling the first folder choice: the app asks again or quits; it never starts without a data location (task 5 tests).

## Files

New:

- `applio_edition.py`, fork-owned: reads the edition from `build_info.json`; `store_edition()`, `prepare_for_sandbox()`, `PRIVACY_POLICY_URL`.
- `build_options.py`, fork-owned: argument checks of the build and two pure helpers.
- `applio_bookmarks.py`, fork-owned: the bookmark of the data location, kept in the container and in the login keychain.
- `applio_data_location.py`, fork-owned: the decision which data location this run uses.
- `applio_model_downloads.py`, fork-owned: which model parts to download, the dialog, the download.
- `assets/entitlements_store.plist`: the sandbox entitlements.
- `patches/store/store_patch_common.py` and three patchers: pipeline, checkpoint loading, interface.
- Tests: `tests/test_applio_edition.py`, `tests/test_build_options.py`, `tests/test_store_patchers.py`, `tests/test_applio_bookmarks.py`, `tests/test_applio_data_location.py`, `tests/test_applio_model_downloads.py`, `tests/test_menu_edition.py`.
- `.claude/store/tools/pipe_channel_probe.py` (git-ignored local tool).

Modified:

- `build_macos.py`: `--store` and its companions, store patch list, Info.plist, signing, `build_info.json`, the computed minimum macOS version, the flagged scheme string.
- `menu_spec.py`, `applio_launcher.py`, `macos_wrapper.py`, `applio_native_picker.py`: edition branches.
- `HIDDEN_IMPORTS` in `build_macos.py`: the four new fork modules, each added by the task that creates it.
- `.gitignore`: `dist-store/`.
- `README_MACOS.md`, `FORK_DIFFERENCES.md`, `CHANGELOG.md`, `CLAUDE.md`, `docs/ROADMAP.md`.

---
### Task 0: Prerequisites

**Goal:** Have the worktree and a green baseline before any code changes, and know that the 3.7.2.1 release comes first.

**Files:**
- Read: `docs/APP_STORE_READINESS.md`, `CLAUDE.md` ("Fork Maintenance", "Build process gotchas")

**Acceptance Criteria:**
- [ ] A worktree exists for a branch `store-edition` from `main`, created with the native worktree tool.
- [ ] The baseline is green in the worktree.
- [ ] The owner's test results of 3.7.2.1, when they arrive, are handled on `main` before this plan goes on.

**Verify:** `venv_macos/bin/python -m pytest -q tests` in the worktree → `118 passed` (or more; none failed)

**Steps:**

- [ ] **Step 1: Create the worktree**

Use the worktree tool of the session on a new branch `store-edition` from `main`. Do not work in the main checkout: its `dist/` holds the build under test.

- [ ] **Step 2: Run the baseline**

```bash
cd <worktree>
/Volumes/ssd/github/applio-macOS-native-app/venv_macos/bin/python -m pytest -q tests
```

The worktree has no `venv_macos` of its own (it is git-ignored). Every command in this plan that says `venv_macos/bin/python` means that absolute interpreter, run from the worktree. `.claude/port-tools` is local to the main checkout too: copy the folder when a step needs one of its tools.

- [ ] **Step 3: Note where the models are**

The worktree has no `rvc/models` (git-ignored, 7.1 GB). Builds and tests clone what they need from `/Volumes/ssd/github/applio-macOS-native-app/rvc/models` with `cp -cR` (same volume: no extra space).

- [ ] **Step 4: The rule of priority**

When the owner sends the results of the manual pass of 3.7.2.1: commit or stash the work in the worktree, switch to the main checkout, and handle the release (triage, fix, rebuild, notarize, and on their word the tag and the upload). Come back to this plan afterwards.

---
### Task 1: Edition switch in the build

**Goal:** `build_macos.py --store` produces an app with the sandbox entitlements, signed ad hoc, in `dist-store/`, with `edition: store` in `build_info.json`; the direct build stays as it was; and both get the minimum macOS version their binaries really need.

**Files:**
- Create: `applio_edition.py`, `build_options.py`, `assets/entitlements_store.plist`
- Create: `tests/test_applio_edition.py`, `tests/test_build_options.py`
- Modify: `build_macos.py` (argument parser near line 128-202, the constants read from `args` near 204-215, `pyinstaller_args` near 716, `HIDDEN_IMPORTS` near 606, `pre_build_patch` near 996, `_check_patch_table` near 950, `verify_patch_markers` near 1340, the `build_info.json` writer near 1375, the Info.plist block near 1518-1536, `sign_app` near 1661 and its call near 1825)
- Modify: `.gitignore`

**Acceptance Criteria:**
- [ ] `--store --notarize`, `--store --dmg`, `--store --sign` without a profile, and `--provisioning-profile` without `--sign` each stop with a message before anything is built.
- [ ] `applio_edition.store_edition()` is `False` without `build_info.json`, `False` with `"edition": "direct"`, `True` with `"edition": "store"`.
- [ ] `minimum_macos_version(["11.0", "12.1", "14.0", "15.0", "13.3"])` is `"15.0"`.
- [ ] After `build_macos.py --store --bundle-id com.iahispano.applio.storetest`: `dist-store/Applio.app` exists, `dist/` is untouched, `build_info.json` has `"edition": "store"`, the signature carries `com.apple.security.app-sandbox`, the Info.plist has the category and the encryption key.
- [ ] The Info.plist of that build names `15.0` as `LSMinimumSystemVersion` (the highest minimum among its binaries today).
- [ ] A build without `--store` in the worktree gives the same entitlements as before and `"edition": "direct"`.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_applio_edition.py tests/test_build_options.py` → `16 passed`; then the build commands of steps 20 and 21.

**Steps:**

- [ ] **Step 1: Write the failing tests for the edition reader**

`tests/test_applio_edition.py`:

```python
"""applio_edition: the edition is read from build_info.json, nothing else."""

import json
import mimetypes

import applio_edition


def _edition_with(monkeypatch, tmp_path, info):
    info_file = tmp_path / "build_info.json"
    info_file.write_text(json.dumps(info), encoding="utf-8")
    monkeypatch.setattr(
        applio_edition, "_build_info_candidates", lambda: [str(info_file)]
    )
    applio_edition.store_edition.cache_clear()
    return applio_edition


def test_direct_edition(monkeypatch, tmp_path):
    edition = _edition_with(monkeypatch, tmp_path, {"edition": "direct"})
    assert edition.store_edition() is False


def test_store_edition(monkeypatch, tmp_path):
    edition = _edition_with(monkeypatch, tmp_path, {"edition": "store"})
    assert edition.store_edition() is True


def test_missing_build_info_is_the_direct_edition(monkeypatch, tmp_path):
    edition = _edition_with(monkeypatch, tmp_path, {"edition": "store"})
    monkeypatch.setattr(
        applio_edition,
        "_build_info_candidates",
        lambda: [str(tmp_path / "does-not-exist.json")],
    )
    edition.store_edition.cache_clear()
    assert edition.store_edition() is False


def test_corrupt_build_info_is_the_direct_edition(monkeypatch, tmp_path):
    info_file = tmp_path / "build_info.json"
    info_file.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        applio_edition, "_build_info_candidates", lambda: [str(info_file)]
    )
    applio_edition.store_edition.cache_clear()
    assert applio_edition.store_edition() is False


def test_the_privacy_policy_is_on_github_for_now():
    assert applio_edition.PRIVACY_POLICY_URL == (
        "https://froggeric.github.io/applio-macOS-native-app/privacy/"
    )


def test_prepare_for_sandbox_clears_the_mime_type_files_in_the_store_edition(
    monkeypatch, tmp_path
):
    edition = _edition_with(monkeypatch, tmp_path, {"edition": "store"})
    known = mimetypes.knownfiles
    try:
        edition.prepare_for_sandbox()
        assert mimetypes.knownfiles == []
    finally:
        mimetypes.knownfiles = known


def test_prepare_for_sandbox_leaves_the_mime_type_files_in_the_direct_edition(
    monkeypatch, tmp_path
):
    edition = _edition_with(monkeypatch, tmp_path, {"edition": "direct"})
    known = mimetypes.knownfiles
    try:
        edition.prepare_for_sandbox()
        assert mimetypes.knownfiles == known
    finally:
        mimetypes.knownfiles = known
```

- [ ] **Step 2: Run them and see them fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_edition.py`
Expected: collection error, `ModuleNotFoundError: No module named 'applio_edition'`.

- [ ] **Step 3: Create `applio_edition.py`**

```python
"""Which edition of the app this is.

The direct-download edition (Developer ID certificate, notarized) is the
default. The Mac App Store edition differs at build time (store entitlements,
store-only patches) and in a few places at run time; those places ask here.

The edition is recorded in build_info.json, which build_macos.py writes after
PyInstaller into Contents/Resources. Started from the sources, there is no
such file: that is the direct edition.
"""

import functools
import json
import os
import sys

# Decision 7 of docs/APP_STORE_READINESS.md: on GitHub for now, later the
# owner's own website. Only this line changes then.
PRIVACY_POLICY_URL = "https://froggeric.github.io/applio-macOS-native-app/privacy/"


def _build_info_candidates():
    frozen_base = getattr(sys, "_MEIPASS", None)
    if not frozen_base:
        return []
    resources = os.path.join(
        os.path.dirname(os.path.abspath(frozen_base)), "Resources"
    )
    return [os.path.join(resources, "build_info.json")]


def _read_build_info():
    for path in _build_info_candidates():
        try:
            with open(path, "r", encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(info, dict):
            return info
    return {}


@functools.lru_cache(maxsize=1)
def store_edition() -> bool:
    """True in the Mac App Store edition."""
    return _read_build_info().get("edition") == "store"


def prepare_for_sandbox() -> None:
    """Call before Gradio is first imported. Store edition only.

    App Sandbox denies reading /etc/apache2/mime.types and `import gradio`
    crashes on it. An empty list of system MIME-type files fixes that (tested
    on 2026-11-26); Gradio does not need the system lists.
    """
    if not store_edition():
        return
    import mimetypes

    mimetypes.knownfiles = []
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_edition.py`
Expected: `7 passed`

- [ ] **Step 5: Write the failing tests for the build helpers**

`tests/test_build_options.py`:

```python
"""build_options: checks and helpers of build_macos.py that need no build."""

import build_options


def test_direct_build_has_no_problems():
    assert build_options.option_problems(False, True, True, True, None) == []


def test_store_refuses_notarization():
    problems = build_options.option_problems(True, True, True, False, "p")
    assert any("--notarize" in p for p in problems)


def test_store_refuses_a_disk_image():
    problems = build_options.option_problems(True, False, False, True, None)
    assert any("--dmg" in p for p in problems)


def test_store_signing_needs_a_profile():
    problems = build_options.option_problems(True, True, False, False, None)
    assert problems == ["--store --sign needs --provisioning-profile <path>"]


def test_profile_needs_signing():
    problems = build_options.option_problems(True, False, False, False, "p")
    assert problems == ["--provisioning-profile needs --sign"]


def test_store_ad_hoc_build_is_allowed():
    assert build_options.option_problems(True, False, False, False, None) == []


def test_flagged_scheme_is_replaced_byte_for_byte():
    assert build_options.replace_flagged_scheme(
        b"'ws', 'wss', 'itms-services']"
    ) == b"'ws', 'wss', 'x-itms-servic']"


def test_minimum_macos_version_is_the_highest_one():
    versions = ["11.0", "12.1", "14.0", "15.0", "13.3"]
    assert build_options.minimum_macos_version(versions) == "15.0"


def test_minimum_macos_version_of_nothing():
    assert build_options.minimum_macos_version([]) == "0.0.0"
```

- [ ] **Step 6: Run them and see them fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_build_options.py`
Expected: collection error, `No module named 'build_options'`.

- [ ] **Step 7: Create `build_options.py`**

```python
"""Checks and helpers of build_macos.py that need no build to run.

build_macos.py runs the whole build when it is imported, so what the tests
need to import lives here.
"""

FLAGGED_SCHEME = b"itms-services"
SAFE_SCHEME = b"x-itms-servic"  # same length; a scheme this app never uses


def option_problems(store, sign, notarize, dmg, provisioning_profile):
    """Return the messages that stop the build; empty when the options fit."""
    if not store:
        return []
    problems = []
    if notarize:
        problems.append(
            "--store: the Mac App Store edition is not notarized; drop --notarize"
        )
    if dmg:
        problems.append(
            "--store: the store takes the app itself, not a disk image; drop --dmg"
        )
    if sign and not provisioning_profile:
        problems.append("--store --sign needs --provisioning-profile <path>")
    if provisioning_profile and not sign:
        problems.append("--provisioning-profile needs --sign")
    return problems


def replace_flagged_scheme(data: bytes) -> bytes:
    """Remove the scheme name that Apple's scanner flagged in a Python app.

    Same number of bytes, so the file keeps its size. Used for the two
    bundled modules that name the scheme (task 8).
    """
    return data.replace(FLAGGED_SCHEME, SAFE_SCHEME)


def minimum_macos_version(versions):
    """The highest macOS version among those the bundle's binaries need.

    dyld refuses to load a binary built for a newer system than the one it
    runs on, so this, and nothing lower, belongs in LSMinimumSystemVersion.
    """
    highest = (0, 0, 0)
    for version in versions:
        numbers = tuple(int(part) for part in str(version).split(".")[:3])
        numbers += (0,) * (3 - len(numbers))
        highest = max(highest, numbers)
    return ".".join(str(number) for number in highest)
```

- [ ] **Step 8: Run them and see them pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_build_options.py`
Expected: `9 passed`

- [ ] **Step 9: Create `assets/entitlements_store.plist`**

The set that ran in the sandbox experiment of 2026-11-26:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.app-sandbox</key>
    <true/>
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
    <key>com.apple.security.network.server</key>
    <true/>
    <key>com.apple.security.device.microphone</key>
    <true/>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
</dict>
</plist>
```

Check it: `plutil -lint assets/entitlements_store.plist` → `OK`.

- [ ] **Step 10: Add the options to `build_macos.py`**

In `parse_args()`, before `return parser.parse_args()`:

```python
    parser.add_argument(
        "--store",
        action="store_true",
        help="Build the Mac App Store edition: sandbox entitlements and "
        "store-only patches, no notarization, output in dist-store/. "
        "Without --sign the app is signed ad hoc (local sandbox tests).",
    )
    parser.add_argument(
        "--bundle-id",
        type=str,
        default="com.iahispano.applio",
        help="Bundle identifier (default: upstream's)",
    )
    parser.add_argument(
        "--provisioning-profile",
        type=str,
        default=None,
        help="Provisioning profile to embed (.provisionprofile); "
        "store edition with --sign",
    )
```

After `KEYCHAIN_PROFILE = args.keychain_profile` (near line 215):

```python
# ---- Edition ---------------------------------------------------------------
from build_options import option_problems  # noqa: E402

STORE_BUILD = args.store
BUNDLE_ID = args.bundle_id
PROVISIONING_PROFILE = args.provisioning_profile
DIST_DIR = "dist-store" if STORE_BUILD else "dist"

for _message in option_problems(
    STORE_BUILD, SIGN_APP, NOTARIZE, CREATE_DMG, PROVISIONING_PROFILE
):
    print(f"ERROR: {_message}")
    sys.exit(2)

if STORE_BUILD:
    ENTITLEMENTS_PATH = "assets/entitlements_store.plist"
```

In `pyinstaller_args`: `f"--osx-bundle-identifier={BUNDLE_ID}"`, and add `f"--distpath={DIST_DIR}"` after it.

Replace the six `"dist"` literals of the normal build path with `DIST_DIR`: in the `build_info_path` assignment (near 1377), in `clean_bundled_models` (1399), in `post_build_cleanup` (1455 and 1456), in `app_path` and the Info.plist path (1483 and 1484). Leave the literals of the models installer (426), of the disk image (1859 to 1869) and of the notarization (2081): `option_problems` makes the last two unreachable for store builds.

- [ ] **Step 11: Record the edition in `build_info.json`**

In the dictionary written near line 1380, after `"full_version": VERSION,`:

```python
            "edition": "store" if STORE_BUILD else "direct",
```

- [ ] **Step 12: Add the Info.plist keys of a store app**

After `plist["LSMultipleInstancesProhibited"] = True`:

```python
        if STORE_BUILD:
            plist["LSApplicationCategoryType"] = "public.app-category.music"
            plist["ITSAppUsesNonExemptEncryption"] = False
```

The line `plist["LSMinimumSystemVersion"] = "12.0.0"` further up stays as the fallback; step 16 writes the real value before signing.

- [ ] **Step 13: Sign the store edition inside-out**

At the top of `sign_app()`, before `if not SIGN_APP:`:

```python
    if STORE_BUILD:
        return sign_app_store()
```

Above `sign_app`, add:

```python
def sign_app_store():
    """Mac App Store edition: inside-out signing with the store entitlements.

    Ad hoc when --sign is not given (local sandbox tests). Otherwise with the
    identity from --identity, which must be "Apple Distribution" or "Apple
    Development", and with the provisioning profile embedded before the
    bundle is sealed. Nothing is notarized: the store does not use it.
    """
    import shutil

    identity = "-"
    if SIGN_APP:
        kind = DEVELOPER_IDENTITY or ""
        if "Apple Distribution" not in kind and "Apple Development" not in kind:
            print(
                'ERROR: --store --sign needs --identity "Apple Distribution: ..." '
                'or "Apple Development: ..."'
            )
            return False
        identity = SIGNING_IDENTITY
        embedded = os.path.join(app_path, "Contents", "Embedded.provisionprofile")
        shutil.copyfile(PROVISIONING_PROFILE, embedded)

    _repair_python_framework_symlinks(app_path)
    binaries = _discover_macho(app_path)
    if not binaries:
        print("ERROR: no Mach-O binaries found inside the app bundle")
        return False
    for b in binaries:
        subprocess.run(
            ["codesign", "--remove-signature", b], capture_output=True, text=True
        )
    subprocess.run(
        ["codesign", "--remove-signature", app_path], capture_output=True, text=True
    )

    # The Hardened Runtime stays on, with the cs.* keys of the entitlements:
    # that is the configuration the sandbox experiment ran with.
    extra = ["--options", "runtime"]
    if identity != "-":
        extra.append("--timestamp")

    errors = []
    for b in binaries:
        r = subprocess.run(
            ["codesign", "--force", "--sign", identity, *extra, b],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            errors.append(f"{b}: {(r.stderr or '').strip()}")
    if errors:
        print(f"ERROR: {len(errors)} binaries could not be signed. First error:")
        print(f"  {errors[0]}")
        return False

    r = subprocess.run(
        [
            "codesign",
            "--force",
            "--sign",
            identity,
            "--entitlements",
            ENTITLEMENTS_PATH,
            *extra,
            app_path,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"ERROR: Bundle signing failed: {r.stderr}")
        return False
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
    print("Application signed (Mac App Store edition).")
    return True
```

- [ ] **Step 14: Hook the store patch list in**

Above `pre_build_patch`, after the `PATCH_MARKERS` dictionary:

```python
# Applied only by `build_macos.py --store` (tasks 2, 3 and 6 add the patchers).
STORE_PATCHES = []
PATCH_MARKERS_STORE = {}


def active_patch_markers():
    """PATCH_MARKERS, plus the store markers in a store build."""
    if STORE_BUILD:
        return {**PATCH_MARKERS, **PATCH_MARKERS_STORE}
    return PATCH_MARKERS
```

In `pre_build_patch()`, after the `patches_to_apply = [...]` list and before `_check_patch_table(patches_to_apply)`:

```python
    patches_to_apply += STORE_PATCHES
```

In `_check_patch_table`: replace `set(PATCH_MARKERS)` with `set(active_patch_markers())` (both lines). In `verify_patch_markers`: `for patcher_path, markers in active_patch_markers().items():`.

- [ ] **Step 15: Make the edition reader importable in the frozen app**

In `HIDDEN_IMPORTS`, add:

```python
    "applio_edition",
```

- [ ] **Step 16: Compute the minimum macOS version of the bundle**

The Info.plist said 12.0.0 by hand. The bundle of 3.7.2.1 cannot start there: `orjson` is built for macOS 15.0, 113 other binaries for 14.0, and dyld refuses to load them on an older system. Both editions get the real number.

In `build_macos.py`, after `_discover_macho` (so it can use it):

```python
def bundle_minimum_macos_version():
    """The highest `minos` among the app's Mach-O files, as "X.Y" or "X.Y.Z"."""
    highest = (0,)
    for binary in _discover_macho(app_path):
        info = subprocess.run(
            ["otool", "-l", binary], capture_output=True, text=True
        )
        lines = info.stdout.splitlines()
        for index, line in enumerate(lines):
            if line.strip() != "cmd LC_BUILD_VERSION":
                continue
            for field in lines[index + 1 : index + 6]:
                if field.strip().startswith("minos"):
                    numbers = tuple(int(p) for p in field.split()[1].split("."))
                    highest = max(highest, numbers)
    return ".".join(str(number) for number in highest) or None


def set_minimum_macos_version():
    """Write the bundle's real floor into Info.plist, before signing."""
    import build_options

    version = build_options.minimum_macos_version(
        [found for found in [bundle_minimum_macos_version()] if found]
    )
    if version in (None, "0.0.0"):
        print("WARNING: no LC_BUILD_VERSION found; LSMinimumSystemVersion left as it is")
        return
    with open(info_plist_path, "rb") as f:
        plist = plistlib.load(f)
    plist["LSMinimumSystemVersion"] = version
    with open(info_plist_path, "wb") as f:
        plistlib.dump(plist, f)
    print(f"LSMinimumSystemVersion set to {version} (the bundle's highest minimum).")
```

`import plistlib` goes with the other imports. Immediately before `sign_success = sign_app()` (near line 1825):

```python
set_minimum_macos_version()
```

Change the comment above the hand-written `"12.0.0"` line to: `# Fallback only: set_minimum_macos_version() writes the bundle's real floor before signing.`

- [ ] **Step 17: Ignore the store output**

In `.gitignore`, next to `dist/`:

```
dist-store/
```

- [ ] **Step 18: Run the tests and the checks of the direct edition**

```bash
venv_macos/bin/python -m pytest -q tests
venv_macos/bin/python -m black --check build_macos.py build_options.py applio_edition.py tests/test_applio_edition.py tests/test_build_options.py
venv_macos/bin/python .claude/port-tools/applio_run_patch_stage.py .
```

Expected: all tests pass, black leaves the files unchanged, the tool ends with `PATCH STAGE OK`.

- [ ] **Step 19: Build the store edition ad hoc and check it**

```bash
venv_macos/bin/python build_macos.py --store --bundle-id com.iahispano.applio.storetest > .claude/store-build.log 2>&1
grep -E "LSMinimumSystemVersion set|BUILD COMPLETE" .claude/store-build.log
plutil -p dist-store/Applio.app/Contents/Resources/build_info.json
plutil -p dist-store/Applio.app/Contents/Info.plist | grep -E "LSMinimumSystemVersion|LSApplicationCategoryType|ITSAppUsesNonExemptEncryption"
codesign -d --entitlements :- dist-store/Applio.app 2>/dev/null | grep -c app-sandbox
ls dist
```

Expected: `LSMinimumSystemVersion set to 15.0`; `BUILD COMPLETE`; `"edition" => "store"`; `"LSMinimumSystemVersion" => "15.0"`, the category `public.app-category.music`, the encryption key `false`; the grep prints `1`; `ls dist` shows nothing new (or nothing, in the worktree).

- [ ] **Step 20: Build the direct edition in the worktree and compare**

```bash
venv_macos/bin/python build_macos.py > .claude/direct-build.log 2>&1
plutil -p dist/Applio.app/Contents/Resources/build_info.json
plutil -p dist/Applio.app/Contents/Info.plist | grep LSMinimumSystemVersion
codesign -d --entitlements :- dist/Applio.app 2>/dev/null | grep -A1 app-sandbox
```

Expected: `"edition" => "direct"`; `"LSMinimumSystemVersion" => "15.0"` (the one intended difference); the sandbox key of `assets/entitlements.plist` (`false`), and otherwise the entitlements of that file.

- [ ] **Step 21: Commit**

```bash
git add applio_edition.py build_options.py assets/entitlements_store.plist build_macos.py .gitignore tests/test_applio_edition.py tests/test_build_options.py
git commit -m "build: add --store for the Mac App Store edition and compute the minimum macOS version"
```

---
### Task 2: Pipeline without worker processes

**Goal:** In the store edition, preprocessing, extraction and training run without worker processes, which the sandbox denies.

**Files:**
- Create: `patches/store/store_patch_common.py`, `patches/store/patch_store_pipeline.py`
- Create: `tests/test_store_patchers.py`
- Modify: `build_macos.py` (`STORE_PATCHES`, `PATCH_MARKERS_STORE`)
- Patched at build time only: `rvc/train/train.py` (DataLoader near line 395), `rvc/train/preprocess/preprocess.py` (near 289), `rvc/train/extract/extract.py` (near 178 and 291)

**Acceptance Criteria:**
- [ ] The patcher exits 0 on copies of the three files, and each result compiles.
- [ ] No `ProcessPoolExecutor` remains in `preprocess.py` and `extract.py`; `num_workers=0`, no `persistent_workers` and no `prefetch_factor` in the DataLoader.
- [ ] The extraction loops keep upstream's two warning messages, and the embedding loop keeps its `raise`.
- [ ] A second run changes nothing and exits 0. A moved anchor exits 2 and leaves the file as it was.
- [ ] `PATCH_MARKERS_STORE` has four markers for this patcher, and the build stops when one is missing.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py -k pipeline` → all pass

**Steps:**

- [ ] **Step 1: Write the failing test**

`tests/test_store_patchers.py` (tasks 3 and 6 extend it):

```python
"""The store-only patchers: anchors land, results compile, a second run is a no-op.

Runs each patcher as the build does, on copies of the pristine sources.
"""

import os
import py_compile
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

PIPELINE_FILES = [
    "rvc/train/train.py",
    "rvc/train/preprocess/preprocess.py",
    "rvc/train/extract/extract.py",
]


def _copy(relative, root):
    dest = os.path.join(root, relative)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy(os.path.join(REPO, relative), dest)
    return dest


def _run(name, *args):
    return subprocess.run(
        [PY, os.path.join(REPO, "patches", "store", name), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def test_pipeline_patcher_applies(tmp_path):
    copied = [_copy(relative, tmp_path) for relative in PIPELINE_FILES]
    assert "num_workers=2 if device.type" in _read(copied[0])

    result = _run("patch_store_pipeline.py", os.path.join(tmp_path, "rvc", "train"))

    assert result.returncode == 0, result.stdout + result.stderr
    for path in copied:
        py_compile.compile(path, doraise=True)
        assert "_APPLIO_STORE_" in _read(path), path


def test_pipeline_result_has_no_worker_processes(tmp_path):
    train, preprocess, extract = (
        _copy(relative, tmp_path) for relative in PIPELINE_FILES
    )
    assert (
        _run("patch_store_pipeline.py", os.path.join(tmp_path, "rvc", "train")).returncode
        == 0
    )

    train_text = _read(train)
    assert "num_workers=0," in train_text
    assert "persistent_workers" not in train_text
    assert "prefetch_factor" not in train_text

    assert "ProcessPoolExecutor" not in _read(preprocess)
    extract_text = _read(extract)
    assert "ProcessPoolExecutor" not in extract_text


def test_extraction_still_reports_errors(tmp_path):
    _copy("rvc/train/train.py", tmp_path)
    _copy("rvc/train/preprocess/preprocess.py", tmp_path)
    extract = _copy("rvc/train/extract/extract.py", tmp_path)

    assert (
        _run("patch_store_pipeline.py", os.path.join(tmp_path, "rvc", "train")).returncode
        == 0
    )

    extract_text = _read(extract)
    assert extract_text.count("[!] Warning: Pitch extraction task encountered error") == 1
    assert (
        extract_text.count("[!] Warning: Embedding extraction task encountered error")
        == 1
    )
    embedding = extract_text[extract_text.index("_APPLIO_STORE_EXTRACT_EMBEDDING_") :]
    assert "raise" in embedding[:1200]


def test_pipeline_patcher_is_a_no_op_the_second_time(tmp_path):
    for relative in PIPELINE_FILES:
        _copy(relative, tmp_path)
    train_dir = os.path.join(tmp_path, "rvc", "train")
    assert _run("patch_store_pipeline.py", train_dir).returncode == 0
    before = [_read(os.path.join(tmp_path, relative)) for relative in PIPELINE_FILES]

    result = _run("patch_store_pipeline.py", train_dir)

    assert result.returncode == 0
    assert [_read(os.path.join(tmp_path, r)) for r in PIPELINE_FILES] == before


def test_pipeline_patcher_stops_on_a_moved_anchor(tmp_path):
    for relative in PIPELINE_FILES:
        _copy(relative, tmp_path)
    train = os.path.join(tmp_path, "rvc", "train", "train.py")
    text = _read(train).replace("num_workers=2 if device.type", "num_workers=9 if device.type")
    with open(train, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    result = _run("patch_store_pipeline.py", os.path.join(tmp_path, "rvc", "train"))

    assert result.returncode == 2
    assert "anchor found 0x" in result.stdout
    assert "num_workers=9 if device.type" in _read(train)  # nothing half-applied


def test_store_patchers_exit_1_without_an_argument():
    for name in (
        "patch_store_pipeline.py",
        "patch_store_safe_load.py",
        "patch_store_app.py",
    ):
        result = _run(name)
        assert result.returncode == 1, name
        assert "usage:" in result.stdout, name
```

- [ ] **Step 2: Run it and see it fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py -k "pipeline or extraction"`
Expected: 5 failures, each with `No such file or directory` for `patch_store_pipeline.py`. (The tests for the other two patchers and the no-argument test wait for tasks 3 and 6.)

- [ ] **Step 3: Create `patches/store/store_patch_common.py`**

```python
"""Helpers shared by the store-only patchers in this directory.

A patcher describes its work as edits per file: (label, old text, new text).
The old text must appear exactly once, so an anchor that upstream moved fails
the build (exit 2) instead of being skipped, and a file is never written
half-patched.
"""

import os


def read_source(path):
    """Read a source file and keep its line endings as they are."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_source(path, content):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def patch_file(path, edits):
    """Apply (label, old, new) edits to one file. Returns the problems."""
    content = read_source(path)
    if all(new in content for _, _, new in edits):
        return []  # already applied
    problems = []
    for label, old, new in edits:
        count = content.count(old)
        if count != 1:
            problems.append(
                f"{os.path.basename(path)} ({label}): anchor found {count}x, "
                "expected once"
            )
            continue
        content = content.replace(old, new)
    if not problems:
        write_source(path, content)
    return problems


def run(patcher_name, files):
    """`files` maps each path to its list of edits. Returns True on success."""
    problems = []
    for path, edits in files.items():
        if not os.path.exists(path):
            print(f"[{patcher_name}] not found: {path}")
            return False
        problems += patch_file(path, edits)
    for problem in problems:
        print(f"[{patcher_name}] {problem}")
    if problems:
        return False
    print(f"[{patcher_name}] Applied")
    return True


def main(patcher_name, usage, build_files):
    """The `__main__` block every patcher here shares.

    `build_files(argument)` returns the {path: edits} mapping, or None when
    the argument is missing.
    """
    import sys

    files = build_files(sys.argv[1] if len(sys.argv) > 1 else "")
    if files is None:
        print(f"usage: {patcher_name} {usage}")
        sys.exit(1)
    sys.exit(0 if run(patcher_name, files) else 2)
```

- [ ] **Step 4: Create `patches/store/patch_store_pipeline.py`**

```python
#!/usr/bin/env python3
"""Store edition: preprocessing, extraction and training without worker processes.

App Sandbox denies the named POSIX semaphores and shared memory that a
process pool or a DataLoader with workers needs, so they die before a worker
starts (tested 2026-11-26). This patcher replaces the three
ProcessPoolExecutor blocks with serial loops and takes the workers away from
the DataLoader. Training is about 5 to 11 percent slower that way.

Applied only by `build_macos.py --store`. Argument: the directory rvc/train.
Exit codes: 0 patched or already applied, 2 anchor missed, 1 usage.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store_patch_common import main  # noqa: E402

LOADER_OLD = '''    train_loader = DataLoader(
        train_dataset,
        num_workers=2 if device.type == "mps" else 4,
        shuffle=False,
        pin_memory=device.type == "cuda",
        collate_fn=collate_fn,
        batch_sampler=train_sampler,
        persistent_workers=True,
        prefetch_factor=2 if device.type == "mps" else 8,
    )'''

LOADER_NEW = '''    # _APPLIO_STORE_LOADER_ store edition: no DataLoader workers (App Sandbox).
    # With num_workers=0, persistent_workers must be False and prefetch_factor
    # must be left out.
    train_loader = DataLoader(
        train_dataset,
        num_workers=0,
        shuffle=False,
        pin_memory=device.type == "cuda",
        collate_fn=collate_fn,
        batch_sampler=train_sampler,
    )'''

PREPROCESS_OLD = '''    with tqdm(total=len(files)) as pbar:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=num_processes
        ) as executor:
            futures = [
                executor.submit(
                    process_audio_wrapper,
                    (
                        pp,
                        file,
                        cut_preprocess,
                        process_effects,
                        chunk_len,
                        overlap_len,
                        normalization_mode,
                    ),
                )
                for file in files
            ]
            for future in concurrent.futures.as_completed(futures):
                audio_length.append(future.result())
                pbar.update(1)'''

PREPROCESS_NEW = '''    with tqdm(total=len(files)) as pbar:
        # _APPLIO_STORE_PREPROCESS_ store edition: one file at a time. A process
        # pool needs semaphores that App Sandbox denies.
        for file in files:
            audio_length.append(
                process_audio_wrapper(
                    (
                        pp,
                        file,
                        cut_preprocess,
                        process_effects,
                        chunk_len,
                        overlap_len,
                        normalization_mode,
                    )
                )
            )
            pbar.update(1)'''

PITCH_OLD = '''    with concurrent.futures.ProcessPoolExecutor(max_workers=len(devices)) as executor:
        tasks = [
            executor.submit(
                process_files,
                files[i :: len(devices)],
                f0_method,
                devices[i],
                threads // len(devices),
            )
            for i in range(len(devices))
        ]
        for task in concurrent.futures.as_completed(tasks):
            try:
                task.result()
            except Exception as task_err:
                print(
                    f"[!] Warning: Pitch extraction task encountered error: {task_err}"
                )'''

PITCH_NEW = '''    # _APPLIO_STORE_EXTRACT_PITCH_ store edition: call the per-device work
    # directly. A process pool needs semaphores that App Sandbox denies.
    # Errors are reported the way the pool reported them.
    for i in range(len(devices)):
        try:
            process_files(
                files[i :: len(devices)],
                f0_method,
                devices[i],
                threads // len(devices),
            )
        except Exception as task_err:
            print(
                f"[!] Warning: Pitch extraction task encountered error: {task_err}"
            )'''

EMBEDDING_OLD = '''    with concurrent.futures.ProcessPoolExecutor(max_workers=len(devices)) as executor:
        tasks = [
            executor.submit(
                process_file_embedding,
                files[i :: len(devices)],
                embedder_model,
                embedder_model_custom,
                i,
                devices[i],
                threads // len(devices),
            )
            for i in range(len(devices))
        ]
        for task in concurrent.futures.as_completed(tasks):
            try:
                task.result()
            except Exception as task_err:
                print(
                    f"[!] Warning: Embedding extraction task encountered error: {task_err}"
                )
                raise'''

EMBEDDING_NEW = '''    # _APPLIO_STORE_EXTRACT_EMBEDDING_ store edition: call the per-device work
    # directly. A process pool needs semaphores that App Sandbox denies.
    # An error stops the job, as it did in the pool.
    for i in range(len(devices)):
        try:
            process_file_embedding(
                files[i :: len(devices)],
                embedder_model,
                embedder_model_custom,
                i,
                devices[i],
                threads // len(devices),
            )
        except Exception as task_err:
            print(
                f"[!] Warning: Embedding extraction task encountered error: {task_err}"
            )
            raise'''


def _files(train_dir):
    if not train_dir:
        return None
    return {
        os.path.join(train_dir, "train.py"): [
            ("DataLoader", LOADER_OLD, LOADER_NEW)
        ],
        os.path.join(train_dir, "preprocess", "preprocess.py"): [
            ("process pool", PREPROCESS_OLD, PREPROCESS_NEW)
        ],
        os.path.join(train_dir, "extract", "extract.py"): [
            ("pitch pool", PITCH_OLD, PITCH_NEW),
            ("embedding pool", EMBEDDING_OLD, EMBEDDING_NEW),
        ],
    }


if __name__ == "__main__":
    main("patch_store_pipeline", "<path to rvc/train>", _files)
```

- [ ] **Step 5: Register the patcher in `build_macos.py`**

```python
STORE_PATCHES = [
    (
        "patches/store/patch_store_pipeline.py",
        "rvc/train/train.py",
        "store edition: no worker processes in preprocessing, extraction, training",
        "dir",
    ),
]
PATCH_MARKERS_STORE = {
    "patches/store/patch_store_pipeline.py": [
        ("rvc/train/train.py", "_APPLIO_STORE_LOADER_", 1),
        ("rvc/train/preprocess/preprocess.py", "_APPLIO_STORE_PREPROCESS_", 1),
        ("rvc/train/extract/extract.py", "_APPLIO_STORE_EXTRACT_PITCH_", 1),
        ("rvc/train/extract/extract.py", "_APPLIO_STORE_EXTRACT_EMBEDDING_", 1),
    ],
}
```

- [ ] **Step 6: Run the tests and see them pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py -k "pipeline or extraction"`
Expected: `5 passed`

- [ ] **Step 7: Prove that the build stops on a missing marker**

Temporarily change the loader marker's count in `PATCH_MARKERS_STORE` to 2, run the patch-stage tool, and read `stopped as expected` for the store markers: the tool only runs the direct list, so run instead `venv_macos/bin/python build_macos.py --store --bundle-id com.iahispano.applio.storetest` and read the first lines of the output: the build must stop with `expected at least 2`. Put the count back to 1.

- [ ] **Step 8: Commit**

```bash
git add patches/store/store_patch_common.py patches/store/patch_store_pipeline.py tests/test_store_patchers.py build_macos.py
git commit -m "store: run preprocessing, extraction and training without worker processes"
```

---

### Task 3: Checkpoints loaded as data only

**Goal:** In the store edition, the two checkpoint readers that fall back to unrestricted loading (Model Information and the inference worker's inspection) load as data only.

**Why:** A model file can come from a download. An unrestricted `torch.load` runs whatever the file's pickle holds, which is what guideline 2.5.2 is about. Conversion itself already loads with `weights_only=True`.

**Files:**
- Create: `patches/store/patch_store_safe_load.py`
- Modify: `tests/test_store_patchers.py`, `build_macos.py` (`STORE_PATCHES`, `PATCH_MARKERS_STORE`)
- Patched at build time only: `rvc/train/process/model_information.py` (`_load_checkpoint`, line 42), `rvc/lib/tools/inspect_checkpoint.py` (`inspect_checkpoint`, line 26)

**Acceptance Criteria:**
- [ ] After the patch neither file contains `weights_only=False`, and both contain exactly one `torch.load(... weights_only=True)`.
- [ ] Both results compile; a second run is a no-op; no argument exits 1.
- [ ] Two markers in `PATCH_MARKERS_STORE`.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py -k safe_load` → all pass

**Steps:**

- [ ] **Step 1: Add the failing tests to `tests/test_store_patchers.py`**

```python
SAFE_LOAD_FILES = [
    "rvc/train/process/model_information.py",
    "rvc/lib/tools/inspect_checkpoint.py",
]


def test_safe_load_patcher_applies(tmp_path):
    copied = [_copy(relative, tmp_path) for relative in SAFE_LOAD_FILES]

    result = _run(
        "patch_store_safe_load.py",
        os.path.join(tmp_path, "rvc", "train", "process", "model_information.py"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for path in copied:
        py_compile.compile(path, doraise=True)
        text = _read(path)
        assert text.count("_APPLIO_STORE_SAFE_LOAD_") == 1, path
        assert "weights_only=False" not in text, path
        assert "pickle_module=_TolerantPickle" not in text, path


def test_safe_load_patcher_is_a_no_op_the_second_time(tmp_path):
    for relative in SAFE_LOAD_FILES:
        _copy(relative, tmp_path)
    argument = os.path.join(
        tmp_path, "rvc", "train", "process", "model_information.py"
    )
    assert _run("patch_store_safe_load.py", argument).returncode == 0
    before = [_read(os.path.join(tmp_path, r)) for r in SAFE_LOAD_FILES]

    assert _run("patch_store_safe_load.py", argument).returncode == 0

    assert [_read(os.path.join(tmp_path, r)) for r in SAFE_LOAD_FILES] == before
```

- [ ] **Step 2: Run them and see them fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py -k safe_load`
Expected: 2 failures, the patcher does not exist yet.

- [ ] **Step 3: Create `patches/store/patch_store_safe_load.py`**

```python
#!/usr/bin/env python3
"""Store edition: model checkpoints are loaded as data only.

Upstream's Model Information tool and the inference worker's checkpoint
inspection fall back to unrestricted loading when the safe loader rejects a
file. A model file can come from a download, and an unrestricted load runs
whatever its pickle holds (App Store guideline 2.5.2). In the store edition
such a file is reported as unreadable instead.

Applied only by `build_macos.py --store`. Argument: the path of
rvc/train/process/model_information.py. Exit codes: 0 patched or already
applied, 2 anchor missed, 1 usage.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store_patch_common import main  # noqa: E402

INFORMATION_OLD = '''def _load_checkpoint(path):
    """Load a checkpoint, tolerating legacy pickles and old torch versions.

    Trusted local file: fall back to unrestricted, then tolerant, unpickling
    when the safe loader rejects custom/missing globals.
    """
    try:
        try:
            return torch.load(path, map_location="cpu", weights_only=True)
        except TypeError:
            # torch without the weights_only flag.
            return torch.load(path, map_location="cpu")
        except Exception:
            return torch.load(path, map_location="cpu", weights_only=False)
    except Exception:
        return torch.load(
            path,
            map_location="cpu",
            weights_only=False,
            pickle_module=_TolerantPickle,
        )'''

INFORMATION_NEW = '''def _load_checkpoint(path):
    # _APPLIO_STORE_SAFE_LOAD_ store edition: load as data only. A model file
    # can come from a download, and an unrestricted load runs whatever its
    # pickle holds (App Store guideline 2.5.2).
    return torch.load(path, map_location="cpu", weights_only=True)'''

INSPECT_OLD = '''    data = None
    load_error = None
    try:
        try:
            data = torch.load(path, map_location="cpu", weights_only=True)
        except TypeError:
            data = torch.load(path, map_location="cpu")
        except Exception:
            data = torch.load(path, map_location="cpu", weights_only=False)
    except Exception:
        try:
            data = torch.load(
                path,
                map_location="cpu",
                weights_only=False,
                pickle_module=_TolerantPickle,
            )
        except TypeError:
            try:
                data = torch.load(path, map_location="cpu")
            except Exception as e:
                load_error = str(e)[:1000]
                data = None
        except Exception as e:
            load_error = str(e)[:1000]
            data = None'''

INSPECT_NEW = '''    data = None
    load_error = None
    # _APPLIO_STORE_SAFE_LOAD_ store edition: load as data only. A model file
    # can come from a download, and an unrestricted load runs whatever its
    # pickle holds (App Store guideline 2.5.2). A file the safe loader cannot
    # read ends as LOAD_FAILED below, like any unreadable file.
    try:
        data = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as e:
        load_error = str(e)[:1000]
        data = None'''


def _files(model_information_py):
    if not model_information_py:
        return None
    rvc = os.path.dirname(os.path.dirname(os.path.dirname(model_information_py)))
    return {
        model_information_py: [("checkpoint loading", INFORMATION_OLD, INFORMATION_NEW)],
        os.path.join(rvc, "lib", "tools", "inspect_checkpoint.py"): [
            ("checkpoint inspection", INSPECT_OLD, INSPECT_NEW)
        ],
    }


if __name__ == "__main__":
    main("patch_store_safe_load", "<path to rvc/train/process/model_information.py>", _files)
```

- [ ] **Step 4: Register it in `build_macos.py`**

Add to `STORE_PATCHES`:

```python
    (
        "patches/store/patch_store_safe_load.py",
        "rvc/train/process/model_information.py",
        "store edition: checkpoints loaded as data only",
        "file",
    ),
```

Add to `PATCH_MARKERS_STORE`:

```python
    "patches/store/patch_store_safe_load.py": [
        ("rvc/train/process/model_information.py", "_APPLIO_STORE_SAFE_LOAD_", 1),
        ("rvc/lib/tools/inspect_checkpoint.py", "_APPLIO_STORE_SAFE_LOAD_", 1),
    ],
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py -k safe_load`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add patches/store/patch_store_safe_load.py tests/test_store_patchers.py build_macos.py
git commit -m "store: load model checkpoints as data only"
```

---

### Task 4: The bookmark of the data location

**Goal:** Keep access to a data folder outside the app's container across launches, and across removing and reinstalling the app.

**Why:** The data lives in a folder the user chose (decision 4). The sandbox grants access through the folder picker for one session; a security-scoped bookmark keeps it. The bookmark is kept in two places: in the app's container, which macOS may remove together with the app, and in the login keychain, which stays.

**Files:**
- Create: `applio_bookmarks.py`
- Create: `tests/test_applio_bookmarks.py`
- Modify: `build_macos.py` (`HIDDEN_IMPORTS`)

**Acceptance Criteria:**
- [ ] A bookmark saved for a folder resolves back to that folder (path comparison after `os.path.realpath`).
- [ ] `resolve_saved` returns the folder only when the bookmark leads to the saved location.
- [ ] `resolve_remembered` reads the keychain first and the file second.
- [ ] `save` writes the same bytes to the file and to the keychain.
- [ ] A keychain that cannot be reached is logged and never raises.
- [ ] A folder that does not exist gets no bookmark.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_applio_bookmarks.py` → `9 passed`

**Steps:**

- [ ] **Step 1: Write the failing test**

`tests/test_applio_bookmarks.py`. The tests never touch the owner's keychain: the two keychain functions are replaced, and one test makes the keychain fail on purpose.

```python
"""applio_bookmarks: a saved folder resolves back to the same folder."""

import os

import pytest

import applio_bookmarks


@pytest.fixture(autouse=True)
def keychain_replaced(monkeypatch):
    """No test reads or writes the real keychain."""
    calls = []
    monkeypatch.setattr(applio_bookmarks, "read_keychain", lambda: None)
    monkeypatch.setattr(
        applio_bookmarks, "write_keychain", lambda data: calls.append(data) or True
    )
    return calls


def _store(tmp_path):
    return str(tmp_path / "support" / "data_location.bookmark")


def test_bookmark_round_trip(tmp_path):
    folder = tmp_path / "data location"
    folder.mkdir()
    store_at = _store(tmp_path)

    assert applio_bookmarks.save(str(folder), store_at) is True

    resolved = applio_bookmarks.resolve_saved(str(folder), store_at)
    assert resolved is not None
    assert os.path.realpath(resolved) == os.path.realpath(str(folder))


def test_resolve_saved_rejects_another_location(tmp_path):
    folder = tmp_path / "data location"
    folder.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    store_at = _store(tmp_path)
    assert applio_bookmarks.save(str(folder), store_at)

    assert applio_bookmarks.resolve_saved(str(other), store_at) is None


def test_resolve_remembered_falls_back_to_the_file(tmp_path):
    folder = tmp_path / "data location"
    folder.mkdir()
    store_at = _store(tmp_path)
    assert applio_bookmarks.save(str(folder), store_at)

    resolved = applio_bookmarks.resolve_remembered(store_at)

    assert os.path.realpath(resolved) == os.path.realpath(str(folder))


def test_resolve_remembered_prefers_the_keychain(tmp_path, monkeypatch):
    in_keychain = tmp_path / "from keychain"
    in_file = tmp_path / "from file"
    in_keychain.mkdir()
    in_file.mkdir()
    at_file = _store(tmp_path)
    assert applio_bookmarks.save(str(in_file), at_file)
    in_memory = applio_bookmarks._create(str(in_keychain))
    monkeypatch.setattr(applio_bookmarks, "read_keychain", lambda: in_memory)

    resolved = applio_bookmarks.resolve_remembered(at_file)

    assert os.path.realpath(resolved) == os.path.realpath(str(in_keychain))


def test_save_keeps_the_same_bytes_in_the_keychain(tmp_path, keychain_replaced):
    folder = tmp_path / "data location"
    folder.mkdir()
    store_at = _store(tmp_path)

    assert applio_bookmarks.save(str(folder), store_at)

    with open(store_at, "rb") as f:
        assert keychain_replaced == [f.read()]


def test_a_missing_bookmark_resolves_to_nothing(tmp_path):
    assert applio_bookmarks.resolve_saved("/nowhere", str(tmp_path / "none")) is None
    assert applio_bookmarks.resolve_remembered(str(tmp_path / "none")) is None


def test_the_bookmark_lives_in_application_support():
    assert applio_bookmarks.bookmark_path() == os.path.expanduser(
        "~/Library/Application Support/Applio/data_location.bookmark"
    )


def test_a_folder_that_does_not_exist_gets_no_bookmark(tmp_path):
    store_at = _store(tmp_path)

    assert applio_bookmarks.save(str(tmp_path / "missing"), store_at) is False
    assert not os.path.exists(store_at)


def test_a_keychain_that_cannot_be_reached_is_logged_not_raised(
    tmp_path, monkeypatch, caplog
):
    def broken():
        raise RuntimeError("no keychain here")

    monkeypatch.setattr(applio_bookmarks, "_keychain_query", broken)

    assert applio_bookmarks.read_keychain() is None
    assert applio_bookmarks.write_keychain(b"x") is False
    assert "Keychain" in caplog.text
```

- [ ] **Step 2: Run it and see it fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_bookmarks.py`
Expected: collection error, `No module named 'applio_bookmarks'`; that is 9 tests that do not run.

- [ ] **Step 3: Create `applio_bookmarks.py`**

```python
"""Security-scoped bookmark of the data location (Mac App Store edition).

In the sandbox a folder outside the app's container is reachable through the
folder picker for the session in which it was picked. A bookmark keeps that
access across launches. It is kept twice:

- in the app's Application Support folder, which is inside the container;
- in the login keychain, which stays when the app and its container are
  removed, so a new installation finds the folder again by itself.

The keychain part needs a build signed with the owner's identity: an ad hoc
signed test build may be refused or prompted for, and then only the file
copy works. A failure there is logged, never raised.

Importing this module has no side effects.
"""

import logging
import os

BOOKMARK_NAME = "data_location.bookmark"
KEYCHAIN_ACCOUNT = "data_location"


def bookmark_path() -> str:
    return os.path.expanduser(
        os.path.join("~/Library/Application Support/Applio", BOOKMARK_NAME)
    )


def _keychain_query():
    from Foundation import NSBundle
    from Security import (
        kSecAttrAccount,
        kSecAttrService,
        kSecClass,
        kSecClassGenericPassword,
    )

    bundle_id = NSBundle.mainBundle().bundleIdentifier() or "Applio"
    return {
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: f"{bundle_id}.{KEYCHAIN_ACCOUNT}",
        kSecAttrAccount: KEYCHAIN_ACCOUNT,
    }


def read_keychain() -> bytes | None:
    """The bookmark an earlier installation left in the login keychain."""
    from Security import SecItemCopyMatching, errSecSuccess, kSecReturnData

    try:
        status, data = SecItemCopyMatching(
            {**_keychain_query(), kSecReturnData: True}, None
        )
    except Exception as error:  # no keychain available
        logging.warning(f"[Bookmarks] Keychain not readable: {error}")
        return None
    if status != errSecSuccess or data is None:
        return None
    return bytes(data)


def write_keychain(data: bytes) -> bool:
    from Security import (
        SecItemAdd,
        SecItemUpdate,
        errSecItemNotFound,
        errSecSuccess,
        kSecValueData,
    )

    try:
        query = _keychain_query()
        status, _ = SecItemUpdate(query, {kSecValueData: data})
        if status == errSecItemNotFound:
            status, _ = SecItemAdd({**query, kSecValueData: data}, None)
    except Exception as error:  # no keychain available
        logging.warning(f"[Bookmarks] Keychain not writable: {error}")
        return False
    if status != errSecSuccess:
        logging.warning(f"[Bookmarks] Keychain item not saved (status {status}).")
        return False
    return True


def _create(path):
    """Bookmark bytes for `path`, or None."""
    from Foundation import NSURL

    if not os.path.exists(path):
        logging.warning(f"[Bookmarks] Not a folder that exists: {path}")
        return None
    url = NSURL.fileURLWithPath_(path)
    data, error = (
        url.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(
            0, None, None, None
        )
    )
    if data is None:
        logging.warning(f"[Bookmarks] Could not create a bookmark for {path}: {error}")
        return None
    return bytes(data)


def _resolve(data):
    """Resolve bookmark bytes and start accessing the folder. Its path, or None.

    The access stays on for the life of the process: a security-scoped
    resource may be released only as often as it was started.
    """
    from Foundation import NSURL

    url, stale, error = (
        NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
            data, 0, None, None, None
        )
    )
    if url is None:
        logging.warning(f"[Bookmarks] Could not resolve the stored bookmark: {error}")
        return None
    url.startAccessingSecurityScopedResource()
    return url.path()


def _read_file(store_at):
    try:
        with open(store_at, "rb") as f:
            return f.read()
    except OSError:
        return None


def save(path: str, store_at: str | None = None) -> bool:
    """Make a bookmark for `path` and keep it in the file and the keychain."""
    data = _create(path)
    if data is None:
        return False
    store_at = store_at or bookmark_path()
    os.makedirs(os.path.dirname(store_at), exist_ok=True)
    with open(store_at, "wb") as f:
        f.write(data)
    write_keychain(data)
    return True


def resolve_saved(saved_path: str, store_at: str | None = None) -> str | None:
    """The saved location, when a bookmark still reaches it. None otherwise."""
    if not saved_path:
        return None
    store_at = store_at or bookmark_path()
    data = _read_file(store_at)
    if not data:
        data = read_keychain()
    if not data:
        return None
    path = _resolve(data)
    if path and os.path.isdir(path):
        if os.path.realpath(path) == os.path.realpath(saved_path):
            return path
    return None


def resolve_remembered(store_at: str | None = None) -> str | None:
    """Any location a bookmark still reaches: the keychain's, else the file's."""
    store_at = store_at or bookmark_path()
    data = read_keychain()
    if not data:
        data = _read_file(store_at)
    if not data:
        return None
    return _resolve(data)
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_bookmarks.py`
Expected: `9 passed`. If PyObjC raises a `TypeError` on the two `NSURL` calls, the installed PyObjC does not take `None` for the out parameters: drop the trailing `None` of `error:` (the returned tuples stay `(data, error)` and `(url, stale, error)`), then run again.

- [ ] **Step 5: Register the module**

In `HIDDEN_IMPORTS` (`build_macos.py`), add `"applio_bookmarks",` next to `"applio_edition",`.

- [ ] **Step 6: Commit**

```bash
venv_macos/bin/python -m pytest -q tests
venv_macos/bin/python -m black --check applio_bookmarks.py build_macos.py tests/test_applio_bookmarks.py
git add applio_bookmarks.py build_macos.py tests/test_applio_bookmarks.py
git commit -m "store: keep the data location's bookmark in the app and in the login keychain"
```

---
### Task 5: Data location: always a folder the user chose

**Goal:** In the store edition the data lives in a folder the user chose, on any disk, and is found again after a restart and after a reinstall; cancelling the first choice asks again or quits.

**Why:** Decision 4. The container goes when the app goes, so the data cannot live there. The location is the saved preference, then a bookmark of an earlier installation, then the user's choice.

**Files:**
- Create: `applio_data_location.py`
- Create: `tests/test_applio_data_location.py`
- Modify: `macos_wrapper.py` (imports; `start_gui`, the data-location block near line 2036-2046; a new `confirm_store_data_location` next to `confirm_data_location` near 616; `start_backend` near 1576; the inner `copy_file` of `setup_bundled_resources` near 923)
- Modify: `applio_launcher.py` (`setDataLocation_`, near line 6505)
- Modify: `build_macos.py` (`HIDDEN_IMPORTS`)

**Acceptance Criteria:**
- [ ] A saved location whose bookmark resolves is used without asking.
- [ ] With nothing saved, a bookmark of an earlier installation restores the location and it becomes the saved one.
- [ ] A first choice is saved in the preferences, marked as first run done, and gets its bookmark.
- [ ] An unwritable choice asks again; cancelling asks again or quits; the function returns `None` when the user quits.
- [ ] In the store edition Gradio is imported after the MIME-type fix, and no Python file is copied into the data location.
- [ ] `setDataLocation_` saves a bookmark in the store edition.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_applio_data_location.py` → `6 passed`; `venv_macos/bin/python -c "import macos_wrapper"` → no output, exit 0.

**Steps:**

- [ ] **Step 1: Write the failing test**

`tests/test_applio_data_location.py`:

```python
"""applio_data_location: which data location a run of the store edition uses."""

import pytest

import applio_data_location


class FakePrefs:
    def __init__(self, saved=None):
        self.saved = saved
        self.first_run_complete = False

    def set_data_path(self, path):
        self.saved = path

    def mark_first_run_complete(self):
        self.first_run_complete = True


class FakeBookmarks:
    def __init__(self, saved=None, remembered=None):
        self.saved_result = saved
        self.remembered_result = remembered
        self.saved_paths = []

    def resolve_saved(self, saved_path):
        return self.saved_result

    def resolve_remembered(self):
        return self.remembered_result

    def save(self, path):
        self.saved_paths.append(path)
        return True


def _never_quit():
    pytest.fail("the app must not quit here")


def test_a_saved_location_that_still_resolves_is_used(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    prefs = FakePrefs(str(folder))
    bookmarks = FakeBookmarks(saved=str(folder))

    path = applio_data_location.resolve(
        prefs.saved, prefs, bookmarks, None, None, _never_quit
    )

    assert path == str(folder)


def test_a_bookmark_of_an_earlier_installation_restores_the_location(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    prefs = FakePrefs()
    bookmarks = FakeBookmarks(remembered=str(folder))

    path = applio_data_location.resolve(
        None, prefs, bookmarks, None, None, _never_quit
    )

    assert path == str(folder)
    assert prefs.saved == str(folder)


def test_the_first_choice_is_saved_with_its_bookmark(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    prefs, bookmarks = FakePrefs(), FakeBookmarks()
    picks = iter([str(folder)])

    path = applio_data_location.resolve(
        prefs.saved,
        prefs,
        bookmarks,
        lambda: next(picks),
        lambda reason: pytest.fail(f"unexpected prompt: {reason}"),
        _never_quit,
    )

    assert path == str(folder)
    assert prefs.saved == str(folder)
    assert prefs.first_run_complete is True
    assert bookmarks.saved_paths == [str(folder)]


def test_an_unwritable_choice_asks_again(tmp_path):
    (tmp_path / "blocker").write_text("not a folder", encoding="utf-8")
    good = tmp_path / "data"
    good.mkdir()
    prefs, bookmarks = FakePrefs(), FakeBookmarks()
    picks = iter([str(tmp_path / "blocker" / "data"), str(good)])
    reasons = []

    path = applio_data_location.resolve(
        prefs.saved,
        prefs,
        bookmarks,
        lambda: next(picks),
        lambda reason: reasons.append(reason) or True,
        _never_quit,
    )

    assert path == str(good)
    assert reasons == ["not_writable"]


def test_cancelling_and_choosing_quit_quits(tmp_path):
    prefs, bookmarks = FakePrefs(), FakeBookmarks()
    quit_calls = []

    path = applio_data_location.resolve(
        prefs.saved,
        prefs,
        bookmarks,
        lambda: None,
        lambda reason: False,
        lambda: quit_calls.append(True),
    )

    assert path is None
    assert quit_calls == [True]


def test_a_saved_location_that_is_gone_says_so(tmp_path):
    gone = str(tmp_path / "unplugged disk")
    good = tmp_path / "data"
    good.mkdir()
    prefs, bookmarks = FakePrefs(gone), FakeBookmarks(saved=None)
    picks = iter([None, str(good)])
    reasons = []

    path = applio_data_location.resolve(
        prefs.saved,
        prefs,
        bookmarks,
        lambda: next(picks),
        lambda reason: reasons.append(reason) or True,
        _never_quit,
    )

    assert path == str(good)
    assert reasons == ["unreachable"]
```

- [ ] **Step 2: Run it and see it fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_data_location.py`
Expected: collection error, `No module named 'applio_data_location'`.

- [ ] **Step 3: Create `applio_data_location.py`**

```python
"""Where the store edition keeps its data: a folder the user chose.

Never inside the app's container, which macOS may remove together with the
app. Access to a folder outside the container is a security-scoped bookmark
(applio_bookmarks). This module decides, in this order:

1. The bookmark of the location saved in the preferences resolves: use it.
2. A bookmark kept from an earlier installation resolves: use it, and make
   it the saved location.
3. Otherwise the user chooses a folder. A choice that cannot be used, or a
   cancelled dialog, asks again or quits: the store edition has no default
   folder it could write to.

AppKit is not imported here. The picker, the confirmation and quitting are
passed in, so the logic runs in tests with plain functions.
"""

import logging
import os


def real_home():
    """The user's home folder. In the sandbox `~` is the app's container."""
    import pwd

    return pwd.getpwuid(os.getuid()).pw_dir


def is_writable(path):
    """True when files can be created in `path`."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w") as f:
            f.write("test")
        os.remove(probe)
        return True
    except OSError:
        return False


def resolve(saved_path, prefs, bookmarks, pick_folder, confirm_continue, quit_app):
    """Return the data location for this run, or None when the user quits.

    `confirm_continue(reason)` returns True to go on asking ("not_writable",
    "cancelled" or "unreachable"). `quit_app()` ends the app.
    """
    unreachable = None
    if saved_path:
        path = bookmarks.resolve_saved(saved_path)
        if path:
            return path
        unreachable = saved_path
        logging.warning(f"[Data location] Not reachable: {saved_path}")
    path = bookmarks.resolve_remembered()
    if path and os.path.isdir(path):
        logging.info(f"[Data location] Restored from an earlier installation: {path}")
        prefs.set_data_path(path)
        return path
    while True:
        chosen = pick_folder()
        if chosen and is_writable(chosen):
            prefs.set_data_path(chosen)
            prefs.mark_first_run_complete()
            bookmarks.save(chosen)
            return chosen
        if chosen:
            reason = "not_writable"
        elif unreachable:
            reason = "unreachable"
        else:
            reason = "cancelled"
        if not confirm_continue(reason):
            quit_app()
            return None
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_data_location.py`
Expected: `6 passed`

- [ ] **Step 5: The wrapper uses it**

At the top of `macos_wrapper.py`, with the other fork imports:

```python
import applio_bookmarks
import applio_data_location
from applio_edition import prepare_for_sandbox, store_edition
```

In `start_gui`, replace:

```python
    else:
        DATA_PATH = _prefs.get_data_path()

    if not DATA_PATH:
```

by:

```python
    else:
        DATA_PATH = _prefs.get_data_path()
        if store_edition():
            DATA_PATH = applio_data_location.resolve(
                DATA_PATH,
                _prefs,
                applio_bookmarks,
                lambda: select_data_folder(applio_data_location.real_home()),
                confirm_store_data_location,
                quit_app=lambda: os._exit(0),
            )
            if not DATA_PATH:
                return

    if not DATA_PATH:
```

The direct edition keeps its first-run prompt: `store_edition()` is `False` there and the block below is unchanged.

Next to `confirm_data_location`, add:

```python
def confirm_store_data_location(reason):
    """Store edition: there is no default folder, so the choice is a folder or Quit.

    `reason` is "not_writable", "cancelled" or "unreachable". Returns True to
    ask for a folder again.
    """
    from AppKit import NSAlert, NSApp, NSAlertFirstButtonReturn

    import applio_i18n

    _t = applio_i18n.native_tr

    NSApp.activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    if reason == "not_writable":
        alert.setMessageText_(_t("The selected location is not writable."))
        alert.setInformativeText_(
            _t("Choose a folder Applio can write to.")
        )
    elif reason == "unreachable":
        alert.setMessageText_(_t("The data location cannot be reached."))
        alert.setInformativeText_(
            _t(
                "Connect the disk that holds it, or choose another folder. "
                "Applio keeps models, datasets and training results there, "
                "and they stay when the app is removed."
            )
        )
    else:
        alert.setMessageText_(_t("No data location was chosen."))
        alert.setInformativeText_(
            _t(
                "Applio keeps models, datasets and training results in a "
                "folder you choose, on any disk. They stay there when the "
                "app is removed."
            )
        )
    alert.addButtonWithTitle_(_t("Choose Folder"))
    alert.addButtonWithTitle_(_t("Quit"))
    return alert.runModal() == NSAlertFirstButtonReturn
```

- [ ] **Step 6: The MIME-type fix before Gradio, and no Python file in the data location**

In `start_backend`, before `from app import launch_gradio`:

```python
            prepare_for_sandbox()
```

In `setup_bundled_resources`, as the first line of the inner `copy_file`:

```python
        if store_edition() and dest_rel.endswith(".py"):
            # Store edition: code is loaded from the bundle only.
            return
```

- [ ] **Step 7: A new choice in the menu gets its bookmark**

In `applio_launcher.py`, in `setDataLocation_`, after `new_path = urls[0].path()` and its `logging.info(...)` line:

```python
                from applio_edition import store_edition

                if store_edition():
                    import applio_bookmarks

                    applio_bookmarks.save(new_path)
```

- [ ] **Step 8: Register the module, check, commit**

In `HIDDEN_IMPORTS` (`build_macos.py`), add `"applio_data_location",`.

```bash
venv_macos/bin/python -c "import macos_wrapper"
venv_macos/bin/python -m pytest -q tests
venv_macos/bin/python -m black --check macos_wrapper.py applio_launcher.py applio_data_location.py build_macos.py tests/test_applio_data_location.py
git add applio_data_location.py macos_wrapper.py applio_launcher.py build_macos.py tests/test_applio_data_location.py
git commit -m "store: the data lives in a folder the user chose, never in the container"
```

---
### Task 6: Interface for the store, and selectable model downloads

**Goal:** The store edition has no Plugins page, no updater, no update check and no Discord presence; it asks which model parts to download instead of taking about 3 GB, and offers the rest later under File, Download Models…; it links to the privacy policy and names its licences. The Realtime page is left out (decision 5).

**Files:**
- Create: `patches/store/patch_store_app.py`, `applio_model_downloads.py`
- Create: `tests/test_applio_model_downloads.py`, `tests/test_menu_edition.py`
- Modify: `tests/test_store_patchers.py`, `build_macos.py` (`STORE_PATCHES`, `PATCH_MARKERS_STORE`, `post_build_cleanup` near 1444, `HIDDEN_IMPORTS`), `applio_native_picker.py`, `menu_spec.py`, `applio_launcher.py` (the menu source near 5724, `_launch_time_update_check` near 6252, the action dictionary near 6301)
- Patched at build time only: `app.py` (lines 10-12, 118, 120, 124-131, 138-144, 187, 193), `tabs/settings/settings.py` (lines 13, 51-57)

**Acceptance Criteria:**
- [ ] After the patch `app.py` has no `ensure_not_updating`, `plugins_tab`, `RPCManager`, `load_config_presence`, `realtime_tab` nor `run_prerequisites_script`; `first_launch(now_dir)` stands where the download ran.
- [ ] `tabs/settings/settings.py` has no `presence_tab`, shows "Privacy Policy" and names soxr and edge-tts.
- [ ] Both files compile; second run is a no-op; no argument exits 1.
- [ ] `missing_parts` names the parts with a missing file and nothing else.
- [ ] `first_launch` asks and downloads only when the base models are missing, and only what was chosen.
- [ ] Without a native loop nothing is asked.
- [ ] The store menu has no `app.check_updates`, has `app.privacy_policy` and `file.download_models`; the shared `MENU` is not modified.
- [ ] Seven markers in `PATCH_MARKERS_STORE`.
- [ ] The store bundle ships no `tabs/plugins/`, `assets/updater.py`, `tabs/settings/sections/presence.py` or `assets/discord_presence.py`.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py tests/test_applio_model_downloads.py tests/test_menu_edition.py` → all pass (`10 + 7 + 4`)

**Steps:**

- [ ] **Step 1: Add the failing tests to `tests/test_store_patchers.py`**

```python
APP_FILES = ["app.py", "tabs/settings/settings.py"]


def test_app_patcher_applies(tmp_path):
    copied = [_copy(relative, tmp_path) for relative in APP_FILES]

    result = _run("patch_store_app.py", os.path.join(tmp_path, "app.py"))

    assert result.returncode == 0, result.stdout + result.stderr
    for path in copied:
        py_compile.compile(path, doraise=True)
    app_text = _read(copied[0])
    for gone in (
        "ensure_not_updating",
        "plugins_tab",
        "RPCManager",
        "load_config_presence",
        "realtime_tab",
        "run_prerequisites_script",
    ):
        assert gone not in app_text, gone
    for marker in (
        "_APPLIO_STORE_NO_UPDATER_",
        "_APPLIO_STORE_NO_PLUGINS_",
        "_APPLIO_STORE_NO_PRESENCE_",
        "_APPLIO_STORE_DOWNLOAD_",
        "_APPLIO_STORE_NO_REALTIME_",
    ):
        assert app_text.count(marker) == 1, marker
    assert app_text.count("first_launch(now_dir)") == 1
    settings_text = _read(copied[1])
    assert "presence_tab" not in settings_text
    assert "Privacy Policy" in settings_text
    assert "soxr" in settings_text and "edge-tts" in settings_text
    assert settings_text.count("_applio_privacy_policy_tab(") == 2


def test_app_patcher_is_a_no_op_the_second_time(tmp_path):
    for relative in APP_FILES:
        _copy(relative, tmp_path)
    assert _run("patch_store_app.py", os.path.join(tmp_path, "app.py")).returncode == 0
    before = [_read(os.path.join(tmp_path, r)) for r in APP_FILES]

    assert _run("patch_store_app.py", os.path.join(tmp_path, "app.py")).returncode == 0

    assert [_read(os.path.join(tmp_path, r)) for r in APP_FILES] == before
```

- [ ] **Step 2: Run them and see them fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py -k app_patcher`
Expected: 2 failures, the patcher does not exist yet.

- [ ] **Step 3: Write the failing test for the downloads**

`tests/test_applio_model_downloads.py`:

```python
"""applio_model_downloads: ask which parts, download only those, only once."""

import applio_model_downloads
import applio_native_picker
from rvc.lib.tools import prerequisites_download as upstream


def _all_lists():
    return (
        upstream.models_list
        + upstream.embedders_list
        + upstream.pretraineds_hifigan_list
        + upstream.pretraineds_refinegan_list
    )


def test_everything_is_missing_on_an_empty_data_location(tmp_path):
    assert applio_model_downloads.missing_parts(str(tmp_path)) == [
        "base",
        "hifigan",
        "refinegan",
    ]


def test_nothing_is_missing_when_every_file_is_there(tmp_path):
    for remote_folder, files in _all_lists():
        folder = tmp_path / upstream.folder_mapping_list[remote_folder]
        folder.mkdir(parents=True)
        for name in files:
            (folder / name).write_bytes(b"x")

    assert applio_model_downloads.missing_parts(str(tmp_path)) == []


def test_a_part_with_one_missing_file_counts_as_missing(tmp_path):
    for remote_folder, files in _all_lists():
        folder = tmp_path / upstream.folder_mapping_list[remote_folder]
        folder.mkdir(parents=True)
        for name in files:
            (folder / name).write_bytes(b"x")
    (tmp_path / upstream.folder_mapping_list["pretrained_v2/"] / "f0G48k.pth").unlink()

    assert applio_model_downloads.missing_parts(str(tmp_path)) == ["hifigan"]


def test_nothing_is_asked_without_a_native_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(applio_native_picker, "_native_loop_available", False)
    assert applio_model_downloads.ask_which_parts(["base"], required=True) is None


def test_first_launch_asks_only_when_the_base_is_missing(tmp_path, monkeypatch):
    for remote_folder, files in upstream.models_list + upstream.embedders_list:
        folder = tmp_path / upstream.folder_mapping_list[remote_folder]
        folder.mkdir(parents=True)
        for name in files:
            (folder / name).write_bytes(b"x")
    asked = []
    monkeypatch.setattr(
        applio_model_downloads,
        "ask_which_parts",
        lambda missing, required: asked.append((missing, required)) or [],
    )

    applio_model_downloads.first_launch(str(tmp_path))

    assert asked == []  # the optional parts are left to the File menu


def test_first_launch_downloads_what_was_chosen(tmp_path, monkeypatch):
    downloaded = []
    monkeypatch.setattr(
        applio_model_downloads, "ask_which_parts", lambda missing, required: ["base"]
    )
    monkeypatch.setattr(
        applio_model_downloads, "download_parts", lambda parts: downloaded.append(parts)
    )

    applio_model_downloads.first_launch(str(tmp_path))

    assert downloaded == [["base"]]


def test_first_launch_downloads_nothing_when_the_answer_is_not_now(tmp_path, monkeypatch):
    monkeypatch.setattr(
        applio_model_downloads, "ask_which_parts", lambda missing, required: None
    )
    monkeypatch.setattr(
        applio_model_downloads,
        "download_parts",
        lambda parts: pytest.fail("must not download"),
    )

    applio_model_downloads.first_launch(str(tmp_path))
```

- [ ] **Step 4: Run it and see it fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_model_downloads.py`
Expected: collection error, `No module named 'applio_model_downloads'`.

- [ ] **Step 5: Create `applio_model_downloads.py`**

```python
"""Store edition: which models are downloaded, and when.

The direct edition downloads everything at every start until it is all
there: about 3 GB. The store edition asks first (App Store guideline 4.2.3)
and takes the parts separately:

- base: the pitch extractors and the voice embedder, about 0.6 GB. Needed to
  convert and to train.
- hifigan: the HiFi-GAN pretrained voices, about 0.6 GB. Optional.
- refinegan: the RefineGAN pretrained voices, about 2.0 GB. Optional.

At the first launch only the missing base part triggers the dialog. File,
Download Models… fetches whatever is still missing later on. Upstream's
download helpers do the work; they resolve the destination folders from the
working directory, which is the data location in the app.

Importing this module has no side effects.
"""

import logging
import os
import threading

import applio_native_picker

BASE = "base"
PARTS = (
    (BASE, "Pitch extractors and voice embedder", "about 0.6 GB"),
    ("hifigan", "HiFi-GAN pretrained voices", "about 0.6 GB"),
    ("refinegan", "RefineGAN pretrained voices", "about 2.0 GB"),
)
DIALOG_TIMEOUT_S = 600  # the user may leave the dialog on screen


def _lists():
    """Upstream's lists of (remote folder, files), per part."""
    from rvc.lib.tools import prerequisites_download as upstream

    return {
        BASE: (upstream.models_list, upstream.embedders_list),
        "hifigan": (upstream.pretraineds_hifigan_list,),
        "refinegan": (upstream.pretraineds_refinegan_list,),
    }


def missing_parts(data_path):
    """The parts with at least one file missing under `data_path`."""
    from rvc.lib.tools import prerequisites_download as upstream

    lists = _lists()
    missing = []
    for part, _, _ in PARTS:
        for remote_folder, files in lists[part]:
            local_folder = upstream.folder_mapping_list.get(remote_folder, "")
            here = any(
                not upstream.is_downloaded(os.path.join(data_path, local_folder, name))
                for name in files
            )
            if here:
                missing.append(part)
                break
    return missing


def download_parts(parts):
    """Download what is missing of `parts`. The working directory must be the
    data location: upstream resolves the destination folders from it."""
    from tqdm import tqdm

    from rvc.lib.tools import prerequisites_download as upstream

    lists = _lists()
    chosen = [item for part in parts for item in lists[part]]
    total = sum(upstream.get_file_size_if_missing(item) for item in chosen)
    with tqdm(
        total=total or None, unit="iB", unit_scale=True, desc="Downloading models"
    ) as bar:
        for item in chosen:
            upstream.download_mapping_files(item, bar)


def _title(part):
    return next(
        (title, size) for key, title, size in PARTS if key == part
    )


def _ask_on_main_thread(missing, required, result):
    import applio_i18n
    from AppKit import NSAlert, NSApp, NSCheckBox, NSView, NSAlertFirstButtonReturn
    from Foundation import NSMakeRect

    _t = applio_i18n.native_tr
    NSApp.activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    if not missing:
        alert.setMessageText_(_t("All models are downloaded."))
        alert.addButtonWithTitle_(_t("OK"))
        alert.runModal()
        result["chosen"] = []
        return
    alert.setMessageText_(_t("Download the models?"))
    alert.setInformativeText_(
        _t(
            "Choose what Applio downloads now. The first part is needed to "
            "convert and to train. The others can be downloaded later with "
            "File, Download Models."
        )
    )
    row_height = 24
    view = NSView.alloc().initWithFrame_(
        NSMakeRect(0, 0, 380, row_height * len(missing) + 4)
    )
    boxes = {}
    for row, part in enumerate(missing):
        title, size = _title(part)
        box = NSCheckBox.alloc().initWithFrame_(
            NSMakeRect(0, row_height * (len(missing) - 1 - row) + 2, 370, 22)
        )
        box.setTitle_(f"{title} ({size})")
        box.setState_(1)
        box.setEnabled_(not (part == BASE and required))
        view.addSubview_(box)
        boxes[part] = box
    alert.setAccessoryView_(view)
    alert.addButtonWithTitle_(_t("Download"))
    alert.addButtonWithTitle_(_t("Not now"))
    if alert.runModal() != NSAlertFirstButtonReturn:
        result["chosen"] = None
        return
    result["chosen"] = [part for part in missing if boxes[part].state()]


def ask_which_parts(missing, required):
    """The parts the user chose, [] when nothing is missing, None for Not now.

    None too when no native loop runs (started from the sources, drivers,
    tests): then nothing may be waited for.
    """
    if not applio_native_picker.native_loop_is_available():
        return None
    from PyObjCTools import AppHelper

    result = {"chosen": None}
    done = threading.Event()

    def _run():
        try:
            _ask_on_main_thread(missing, required, result)
        finally:
            done.set()

    AppHelper.callAfter(_run)
    if not done.wait(timeout=DIALOG_TIMEOUT_S):
        return None
    return result["chosen"]


def _report(message):
    """Show a short message on the main thread, or log it without a loop."""
    if not applio_native_picker.native_loop_is_available():
        logging.info(f"[Downloads] {message}")
        return
    from PyObjCTools import AppHelper

    done = threading.Event()

    def _run():
        try:
            import applio_i18n
            from AppKit import NSAlert, NSApp

            NSApp.activateIgnoringOtherApps_(True)
            alert = NSAlert.alloc().init()
            alert.setMessageText_(applio_i18n.native_tr(message))
            alert.addButtonWithTitle_(applio_i18n.native_tr("OK"))
            alert.runModal()
        finally:
            done.set()

    AppHelper.callAfter(_run)
    done.wait(timeout=DIALOG_TIMEOUT_S)


def first_launch(data_path):
    """Stands where the direct edition starts its download at every start.

    Asks once, when the base models are missing. The optional parts are left
    to the File menu.
    """
    missing = missing_parts(data_path)
    if BASE not in missing:
        return
    chosen = ask_which_parts(missing, required=True)
    if chosen:
        download_parts(chosen)


def download_from_menu(data_path):
    """File, Download Models… (store edition). Asks, then downloads, on a
    worker thread; the native loop must keep running meanwhile."""
    from PyObjCTools import AppHelper

    def _work():
        chosen = ask_which_parts(missing_parts(data_path), required=False)
        if not chosen:
            return  # Not now, or nothing was missing: the dialog said so
        try:
            download_parts(chosen)
        except Exception as error:  # reported to the user, not raised in a thread
            logging.exception("[Downloads] Model download failed")
            _report(f"The download failed: {error}")
            return
        _report("Models downloaded.")

    threading.Thread(target=_work, name="applio-model-downloads", daemon=True).start()
```

- [ ] **Step 6: Add the accessor to `applio_native_picker.py`**

After `mark_native_loop_available`:

```python
def native_loop_is_available():
    """True once mark_native_loop_available() was called: the launcher runs."""
    return _native_loop_available
```

- [ ] **Step 7: Run the download tests and see them pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_model_downloads.py`
Expected: `7 passed`

- [ ] **Step 8: Create `patches/store/patch_store_app.py`**

```python
#!/usr/bin/env python3
"""Store edition: the interface Apple's rules ask for.

- No updater and no update check (guideline 2.4.5 (vii)).
- No Plugins page: it downloads code and runs it (2.5.2).
- No Discord presence. Its card in Settings becomes the privacy policy link
  and the licence notes (5.1.1 (i)).
- The model download asks which parts to take instead of downloading about
  3 GB (4.2.3; decision 6 of docs/APP_STORE_READINESS.md).
- No Realtime page: its worker process needs process queues that App Sandbox
  denies (decision 5).

Applied only by `build_macos.py --store`. Argument: the path of app.py.
Exit codes: 0 patched or already applied, 2 anchor missed, 1 usage.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store_patch_common import main  # noqa: E402

UPDATER_OLD = '''from assets.updater import ensure_not_updating

ensure_not_updating(now_dir)
'''
UPDATER_NEW = '''# _APPLIO_STORE_NO_UPDATER_ store edition: no updater (App Store guideline 2.4.5 (vii)).
'''

PLUGINS_IMPORT_OLD = "from tabs.plugins.plugins import plugins_tab\n"
PLUGINS_IMPORT_NEW = "# _APPLIO_STORE_NO_PLUGINS_ store edition: no plug-ins (guideline 2.5.2)\n"
PLUGINS_PAGE_OLD = '            "plugins": plugins_tab,\n'

PRESENCE_OLD = '''# Start Discord presence if enabled
from tabs.settings.sections.presence import load_config_presence

if load_config_presence():
    from assets.discord_presence import RPCManager

    RPCManager.start_presence()
'''
PRESENCE_NEW = '''# _APPLIO_STORE_NO_PRESENCE_ store edition: no Discord presence.
'''

DOWNLOAD_OLD = '''# Run prerequisites
from core import run_prerequisites_script

run_prerequisites_script(
    pretraineds_hifigan=True,
    models=True,
    exe=True,
)
'''
DOWNLOAD_NEW = '''# _APPLIO_STORE_DOWNLOAD_ store edition: guideline 4.2.3 asks to disclose a
# download and to prompt before it starts. The user picks the parts.
from applio_model_downloads import first_launch

first_launch(now_dir)
'''

REALTIME_IMPORT_OLD = "from tabs.realtime.realtime import realtime_tab\n"
REALTIME_IMPORT_NEW = (
    "# _APPLIO_STORE_NO_REALTIME_ store edition: real-time conversion needs "
    "process queues that App Sandbox denies\n"
)
REALTIME_PAGE_OLD = '            "realtime": realtime_tab,\n'

SETTINGS_IMPORT_OLD = "from tabs.settings.sections.presence import presence_tab\n"
SETTINGS_IMPORT_NEW = '''# _APPLIO_STORE_PRIVACY_ store edition: the Discord card becomes the privacy link


def _applio_privacy_policy_tab():
    import gradio as gr

    from applio_edition import PRIVACY_POLICY_URL

    gr.Markdown(f"[Read the privacy policy]({PRIVACY_POLICY_URL})")
    gr.Markdown(
        "Applio is open source (MIT licence). This app includes soxr "
        "(LGPL-2.1) and edge-tts (LGPL-3.0)."
    )
'''

SETTINGS_CARD_OLD = '''        with step_card(
            3,
            "Discord Integration",
            i18n,
            description="Show your current Applio activity in Discord.",
        ):
            presence_tab()
'''
SETTINGS_CARD_NEW = '''        with step_card(
            3,
            "Privacy Policy",
            i18n,
            description="How Applio handles your data.",
        ):
            _applio_privacy_policy_tab()
'''


def _files(app_py):
    if not app_py:
        return None
    return {
        app_py: [
            ("updater", UPDATER_OLD, UPDATER_NEW),
            ("plugins import", PLUGINS_IMPORT_OLD, PLUGINS_IMPORT_NEW),
            ("plugins page", PLUGINS_PAGE_OLD, ""),
            ("Discord presence", PRESENCE_OLD, PRESENCE_NEW),
            ("model download", DOWNLOAD_OLD, DOWNLOAD_NEW),
            ("realtime import", REALTIME_IMPORT_OLD, REALTIME_IMPORT_NEW),
            ("realtime page", REALTIME_PAGE_OLD, ""),
        ],
        os.path.join(os.path.dirname(app_py), "tabs", "settings", "settings.py"): [
            ("presence import", SETTINGS_IMPORT_OLD, SETTINGS_IMPORT_NEW),
            ("presence card", SETTINGS_CARD_OLD, SETTINGS_CARD_NEW),
        ],
    }


if __name__ == "__main__":
    main("patch_store_app", "<path to app.py>", _files)
```

- [ ] **Step 9: Register it, and take the removed code out of the bundle**

Add to `STORE_PATCHES`:

```python
    (
        "patches/store/patch_store_app.py",
        "app.py",
        "store edition: no updater, plugins, update check or Discord presence; selectable downloads; privacy link",
        "file",
    ),
```

Add to `PATCH_MARKERS_STORE`:

```python
    "patches/store/patch_store_app.py": [
        ("app.py", "_APPLIO_STORE_NO_UPDATER_", 1),
        ("app.py", "_APPLIO_STORE_NO_PLUGINS_", 1),
        ("app.py", "_APPLIO_STORE_NO_PRESENCE_", 1),
        ("app.py", "_APPLIO_STORE_DOWNLOAD_", 1),
        ("app.py", "_APPLIO_STORE_NO_REALTIME_", 1),
        ("tabs/settings/settings.py", "_APPLIO_STORE_PRIVACY_", 1),
        ("tabs/settings/settings.py", "_applio_privacy_policy_tab(", 2),
    ],
```

In `post_build_cleanup` (`build_macos.py`), add at its end:

```python
    if STORE_BUILD:
        # Code the store edition must not ship, also not as data files.
        import shutil

        resources = os.path.join(DIST_DIR, f"{APP_NAME}.app", "Contents", "Resources")
        for relative in (
            "tabs/plugins",
            "tabs/settings/sections/presence.py",
            "assets/updater.py",
            "assets/discord_presence.py",
        ):
            target = os.path.join(resources, relative)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            elif os.path.exists(target):
                os.remove(target)
```

In `HIDDEN_IMPORTS`, add `"applio_model_downloads",`.

- [ ] **Step 10: Write the failing menu test**

`tests/test_menu_edition.py`:

```python
"""menu_spec.menu_for_edition: the store menu swaps the update check for the
privacy link and adds Download Models."""

import menu_spec


def _keys(menu):
    return [leaf.key for leaf in menu_spec.iter_leaves(menu) if leaf.key]


def test_the_direct_edition_keeps_the_update_check():
    keys = _keys(menu_spec.menu_for_edition(False))
    assert "app.check_updates" in keys
    assert "app.privacy_policy" not in keys
    assert "file.download_models" not in keys


def test_the_store_edition_has_the_privacy_link_and_no_update_check():
    keys = _keys(menu_spec.menu_for_edition(True))
    assert "app.check_updates" not in keys
    assert "app.privacy_policy" in keys


def test_the_store_edition_has_download_models_after_the_data_location():
    keys = _keys(menu_spec.menu_for_edition(True))
    assert keys.index("file.download_models") == keys.index("file.set_data_location") + 1


def test_building_the_store_menu_leaves_the_shared_tree_alone():
    before = len(_keys(menu_spec.MENU))
    menu_spec.menu_for_edition(True)
    assert "app.check_updates" in _keys(menu_spec.MENU)
    assert len(_keys(menu_spec.MENU)) == before
```

- [ ] **Step 11: Run it and see it fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_menu_edition.py`
Expected: 4 failures with `AttributeError: module 'menu_spec' has no attribute 'menu_for_edition'`.

- [ ] **Step 12: Add `menu_for_edition` to `menu_spec.py`**

After the `MENU` list (the import of `replace` goes to the top, with `from dataclasses import dataclass, field`):

```python
def menu_for_edition(store_edition=False):
    """The menu tree of one edition.

    The store edition has no "Check for Updates" (App Store guideline
    2.4.5 (vii)); its place is taken by the link to the privacy policy
    (guideline 5.1.1 (i)). File gains Download Models… (decision 6). The
    shared MENU is not modified, and the store-only keys are not added to
    the key sets above: the tests of the direct menu stay as they are.
    """
    if not store_edition:
        return MENU
    menu = []
    for top in MENU:
        if not top.submenu:
            menu.append(top)
            continue
        submenu = []
        for item in top.submenu:
            if item.key == "app.check_updates":
                item = MenuItem(key="app.privacy_policy", title="Privacy Policy…")
            submenu.append(item)
            if item.key == "file.set_data_location":
                submenu.append(
                    MenuItem(key="file.download_models", title="Download Models…")
                )
        menu.append(replace(top, submenu=submenu))
    return menu
```

- [ ] **Step 13: Use it in the launcher, stop the update check, add the two actions**

In `applio_launcher.py`, where the menu tree is passed to the renderer (near line 5724), replace `menu_spec.MENU,` by:

```python
            menu_spec.menu_for_edition(store_edition()),
```

Near the other fork imports at the top of the file:

```python
from applio_edition import PRIVACY_POLICY_URL, store_edition
```

As the first lines of `_launch_time_update_check`:

```python
        if store_edition():
            return
```

In the action dictionary (near line 6302), after `d["app.check_updates"] = lambda: self.checkUpdates_(None)`:

```python
        d["app.privacy_policy"] = lambda: self.openPrivacyPolicy_(None)
        d["file.download_models"] = lambda: self.downloadModels_(None)
```

Next to `checkUpdates_`:

```python
    def openPrivacyPolicy_(self, sender):
        """Open the privacy policy page (store edition)."""
        subprocess.Popen(["open", PRIVACY_POLICY_URL])

    def downloadModels_(self, sender):
        """File, Download Models… (store edition): ask, then download."""
        import applio_model_downloads

        applio_model_downloads.download_from_menu(self._resolve_data_dir())
```

- [ ] **Step 14: Run everything**

```bash
venv_macos/bin/python -m pytest -q tests
venv_macos/bin/python -m black --check build_macos.py menu_spec.py applio_launcher.py applio_native_picker.py applio_model_downloads.py patches/store/patch_store_app.py tests/test_store_patchers.py tests/test_applio_model_downloads.py tests/test_menu_edition.py
```

Expected: all tests pass (`tests/test_store_patchers.py` complete, 10 tests: 5 pipeline, 1 no-argument, 2 safe load, 2 app); black leaves the files unchanged.

- [ ] **Step 15: Commit**

```bash
git add patches/store/patch_store_app.py applio_model_downloads.py applio_native_picker.py menu_spec.py applio_launcher.py build_macos.py tests/test_store_patchers.py tests/test_applio_model_downloads.py tests/test_menu_edition.py
git commit -m "store: no updater, plugins or Discord presence; selectable model downloads; privacy link"
```

---
### Task 7: The sandboxed build on this Mac

**Goal:** Run the ad hoc signed store build in the sandbox and record what works: the data location, the downloads, the pipeline in script mode, the interface in the window (the owner's VoiceOver pass), and the pipe probe for a later real-time conversion.

**Files:**
- Create (local tool, git-ignored): `.claude/store/tools/pipe_channel_probe.py`
- No repository change, unless a defect is found (then a fix in its own commit and a new build)

**Acceptance Criteria:**
- [ ] Steps 7.1 to 7.10 pass with captured output.
- [ ] The owner's VoiceOver checklist (step 7.11) comes back with a result for every item.
- [ ] The pipe probe and the queue probe print their lines, and the result is written into `docs/APP_STORE_READINESS.md` (section 3).
- [ ] No file was written into `/Volumes/ssd/ai/applio`, and `dist/` of the main checkout is unchanged.
- [ ] Test folders, the container and the logs are removed at the end.

**Verify:** the outputs named in each step.

**Steps:**

- [ ] **Step 7.1: Build and copy**

In the worktree:

```bash
venv_macos/bin/python build_macos.py --store --bundle-id com.iahispano.applio.storetest > .claude/store-build.log 2>&1
grep -E "BUILD COMPLETE|LSMinimumSystemVersion set" .claude/store-build.log
mkdir -p .claude/store
cp -cR dist-store/Applio.app .claude/store/ApplioStore.app
```

Expected: both lines, the second with `15.0`.

- [ ] **Step 7.2: The first launch asks for a folder, then for the downloads**

```bash
open -n .claude/store/ApplioStore.app
```

Expected, in this order: the folder dialog ("Select Applio Data Location"), opening at the real home folder, not at the app's container. Choose a new folder on the SSD, for example `/Volumes/ssd/github/<worktree>/.claude/store/data` (create it in the dialog). Then the dialog "Download the models?" with three lines; the first is ticked and greyed out. Leave it for step 7.4 and choose Download now.

- [ ] **Step 7.3: The download, and what the app wrote**

After the main window appears:

```bash
find .claude/store/data -name "*.py" | wc -l
ls .claude/store/data/rvc/models/predictors
```

Expected: `0` Python files; `fcpe.pt`, `rmvpe.pt`, `swift.onnx` (all three parts were ticked, so the pretrained voices arrive too).

- [ ] **Step 7.4: A start with nothing missing asks nothing**

Quit (⌘Q) and start again. Expected: no folder dialog, no download dialog; the main window appears. The bookmark kept the folder.

- [ ] **Step 7.5: Cancelling the folder dialog**

Quit. Remove the app's container and preferences so that the app starts as a first launch again: `rm -r ~/Library/Containers/com.iahispano.applio.storetest` (from the main session; the path is literal; if the permission system refuses, ask the owner to run it). Start, press Escape in the folder dialog. Expected: "No data location was chosen." with Choose Folder and Quit. Choose Folder and pick the same folder as in step 7.2: the app uses it, with the models already there. Then repeat once and choose Quit: the app quits without a further dialog.

If, with the container removed, the app uses the old folder without asking instead, that is the keychain bookmark of task 4 at work already: record it, then delete that keychain item (Keychain Access, service `com.iahispano.applio.storetest.data-location`) and repeat the step.

- [ ] **Step 7.6: Not now, and File, Download Models…**

Start with a data folder that has nothing: with the container removed again, pick a new empty folder and choose Not now. Expected: the main window appears; a conversion says that the models are missing. Menu File, Download Models…: the dialog with the three parts; untick the two optional ones; after the download the message "Models downloaded."; conversion works. Menu File, Download Models… again after all three parts: "All models are downloaded."

- [ ] **Step 7.7: Preprocess, extract and train in script mode**

A script-mode start has no bookmark, so its data folder must be inside the container:

```bash
C="$HOME/Library/Containers/com.iahispano.applio.storetest/Data"
mkdir -p "$C/bench-data/rvc/models/pretraineds" "$C/bench-data/assets/datasets" "$C/bench-data/logs"
cp -R /Volumes/ssd/github/applio-macOS-native-app/rvc/models/predictors "$C/bench-data/rvc/models/"
cp -R /Volumes/ssd/github/applio-macOS-native-app/rvc/models/embedders "$C/bench-data/rvc/models/"
cp -R /Volumes/ssd/github/applio-macOS-native-app/rvc/models/pretraineds/hifi-gan "$C/bench-data/rvc/models/pretraineds/"
SYNC_MODEL=storetest SYNC_TOTAL_EPOCH=2 APPLIO_DATA_PATH="$C/bench-data" \
  .claude/store/ApplioStore.app/Contents/MacOS/Applio \
  /absolute/path/to/.claude/port-tools/applio_port_frozen_driver.py \
  "$C/bench-data" dataset,preprocess,extract,train > .claude/store/pipeline.log 2>&1
grep -c "ipc-posix" .claude/store/pipeline.log
grep "history entries" .claude/store/pipeline.log | cut -c1-160
ls "$C/bench-data/logs/storetest" | grep -c "="
```

Expected: `0` sandbox denials; three `completed` entries; `0` folders named like `331=2.3850`. Do not run the driver's `prep` phase: it downloads the models. About 1.2 GB go to the system volume; removed in step 7.12.

- [ ] **Step 7.8: The pages served, without a window**

Start the windowed app against a folder that has the models and run `.claude/port-tools/applio_sync_web_check.py <data dir>` from the main checkout's tools, as for the direct build.

Expected: no JavaScript error; the sidebar has no Plugins and no Realtime entry; Settings step 3 is "Privacy Policy".

- [ ] **Step 7.9: The log**

```bash
grep -n "ERROR" ~/Library/Containers/com.iahispano.applio.storetest/Data/Library/Logs/Applio/applio_wrapper.log | tail -5
```

Expected: no `ERROR` after the last `Version: 3.7.2.1` line, or every one understood and harmless.

- [ ] **Step 7.10: The probe for real-time conversion**

`.claude/store/tools/pipe_channel_probe.py` (git-ignored):

```python
"""Run under the sandboxed store build: does a pipe work where a queue does not?"""

import multiprocessing as mp


def child_pipe(conn):
    conn.send({"from": "worker"})
    conn.close()


def child_queue(queue):
    queue.put("hello")


def probe_pipe():
    ctx = mp.get_context("spawn")
    parent, child_end = ctx.Pipe(duplex=True)
    process = ctx.Process(target=child_pipe, args=(child_end,))
    process.start()
    child_end.close()
    message = parent.recv()
    process.join(10)
    print("PIPE_OK", message)


def probe_queue():
    ctx = mp.get_context("spawn")
    queue = ctx.Queue(maxsize=2)
    process = ctx.Process(target=child_queue, args=(queue,))
    process.start()
    print("QUEUE_OK", queue.get(timeout=10))
    process.join(10)


if __name__ == "__main__":
    probe_pipe()
    try:
        probe_queue()
    except Exception as error:  # the expected outcome in the sandbox
        print("QUEUE_FAILED", type(error).__name__, str(error)[:200])
```

```bash
.claude/store/ApplioStore.app/Contents/MacOS/Applio /absolute/path/to/.claude/store/tools/pipe_channel_probe.py
```

Expected: `PIPE_OK {'from': 'worker'}` and then `QUEUE_FAILED ...`. Write both lines, with the date, into section 3 of `docs/APP_STORE_READINESS.md`. A later version can then replace the three queues and two events of `rvc/realtime/worker.py` (`VoiceChangerWorker`) with pipe-based equivalents, behind a store patcher; that needs the list of the queue methods the worker uses first.

- [ ] **Step 7.11: The owner's VoiceOver pass**

Send this checklist inline, complete:

1. Start the app. The main window appears with no dialog: the folder and the models are remembered.
2. Menu Applio: About Applio, Privacy Policy, then Hide Applio. There is no Check for Updates. Privacy Policy opens the policy page in the browser.
3. Menu File: Set Data Location, Download Models, then the Open in Finder items. Download Models shows "All models are downloaded."
4. Settings: step 3 is Privacy Policy; its link opens the page; the licences of soxr and edge-tts are named under it.
5. Convert one file with a model you know. The result sounds as with 3.7.2.1.
6. Convert a folder with 10 or more files. The toasts and the dashboard show the batch as before.
7. Training: preprocess a small dataset, extract, train 3 epochs. Each step finishes; the dashboard shows the epochs.
8. Generate the index and convert with the new model.
9. Text to Speech: speech is generated and converted.
10. TensorBoard opens.
11. File, Set Data Location: choose another folder on the SSD, restart: the app uses it. Menu File, Open in Finder, Logs opens the right folder.

- [ ] **Step 7.12: Clean up**

From the main session, with literal paths: remove `.claude/store`, `.claude/store-build.log`, the test folders on the SSD, the `bench-data` folder inside the container, and the container itself once nothing else is to be tested with this build id.

---
### Task 8: Store signing, profile, flagged string, SDK, reinstall

**Goal:** The build that goes to Apple: signed with the owner's identity and bundle id, with the embedded profile and the store metadata, without the `itms-services` string, with what Apple asks of the SDK, and proven to find its data folder again after a reinstall.

**Files:**
- Modify: `build_macos.py` (the PyInstaller call near line 1370, a check after it)
- Modify: `tests/test_build_options.py`, `docs/APP_STORE_READINESS.md`
- Owner: the App ID and profiles in the Apple developer account, the bundle id string, the privacy policy page

**Acceptance Criteria:**
- [ ] `dist-store/Applio.app` carries `Embedded.provisionprofile`; `codesign -d --entitlements` shows the sandbox key; `codesign --verify --deep --strict` passes.
- [ ] A scan of the built executable finds `itms-services` in no module.
- [ ] The sources of `urllib.parse` and `werkzeug.urls` on disk are byte-identical to before the build.
- [ ] The Info.plist names the owner's bundle id and `LSMinimumSystemVersion` `15.0`.
- [ ] After removing the app and its container and starting it again, the app uses the data folder with no folder dialog, or (recorded) asks once.
- [ ] The main executable's `LC_BUILD_VERSION` names an SDK Apple accepts, as shown by `altool --validate-app`.
- [ ] The privacy policy URL answers with the page.

**Verify:** the commands of steps 8.5, 8.6, 8.7 and 8.9.

**Steps:**

- [ ] **Step 8.1: Owner: the Apple records**

The bundle id string (still open). In the Apple developer account: an App ID with that bundle id, with the capabilities App Sandbox and microphone; a "Mac App Store Connect" profile for distribution and a development profile for local runs. The "Apple Distribution" identity is on the build Mac already. The page at `PRIVACY_POLICY_URL` is published on GitHub Pages. IAHispano's authorisation for the name and the icon is kept where it can be shown to App Review.

- [ ] **Step 8.2: Strip the flagged string around the PyInstaller call**

In `build_macos.py`, replace the `PyInstaller.__main__.run(pyinstaller_args)` of the normal build path (near line 1370) by:

```python
    if STORE_BUILD:
        with flagged_schemes_replaced():
            PyInstaller.__main__.run(pyinstaller_args)
    else:
        PyInstaller.__main__.run(pyinstaller_args)
```

Above it:

```python
def _module_file(import_name):
    return subprocess.run(
        [sys.executable, "-c", f"import {import_name}; print({import_name}.__file__)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@contextlib.contextmanager
def flagged_schemes_replaced():
    """Store edition: replace a scheme name Apple's scanner flagged in a
    Python app, in the two bundled modules that name it, for the time of the
    PyInstaller run. The original bytes are kept under build/ and put back in
    a finally. urllib.parse belongs to the interpreter this venv uses: it is
    restored even when the build fails."""
    import build_options

    backups = os.path.join("build", "scheme-string-backups")
    originals = {}
    try:
        for import_name in ("urllib.parse", "werkzeug.urls"):
            path = _module_file(import_name)
            with open(path, "rb") as f:
                data = f.read()
            backup = os.path.join(backups, import_name + ".orig")
            if build_options.FLAGGED_SCHEME not in data and os.path.exists(backup):
                with open(backup, "rb") as f:  # an interrupted build left it
                    data = f.read()
            if build_options.FLAGGED_SCHEME not in data:
                continue
            os.makedirs(backups, exist_ok=True)
            with open(backup, "wb") as f:
                f.write(data)
            originals[path] = data
            with open(path, "wb") as f:
                f.write(build_options.replace_flagged_scheme(data))
        yield
    finally:
        for path, data in originals.items():
            with open(path, "wb") as f:
                f.write(data)
```

`import contextlib` goes with the other imports.

- [ ] **Step 8.3: Check the result after the build**

Right after that PyInstaller call, outside the `with`:

```python
    if STORE_BUILD:
        problems = flagged_schemes_in_bundle(
            os.path.join(DIST_DIR, f"{APP_NAME}.app", "Contents", "MacOS", APP_NAME)
        )
        for problem in problems:
            print(f"ERROR: {problem}")
        if problems:
            sys.exit(1)
```

With:

```python
def flagged_schemes_in_bundle(executable):
    """Return the modules of the frozen executable that still name the scheme."""
    import build_options
    import tempfile
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    archive = CArchiveReader(executable)
    pyz_bytes = archive.extract("PYZ.pyz")
    if isinstance(pyz_bytes, tuple):
        pyz_bytes = pyz_bytes[0]
    handle, pyz_path = tempfile.mkstemp(suffix=".pyz")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(pyz_bytes)
        pyz = ZlibArchiveReader(pyz_path)
        return [
            name
            for name in pyz.toc
            if build_options.FLAGGED_SCHEME in (pyz.extract(name, raw=True) or b"")
        ]
    finally:
        os.remove(pyz_path)
```

- [ ] **Step 8.4: Test the byte replacement on a known input**

Add to `tests/test_build_options.py`:

```python
def test_the_flagged_scheme_is_found_and_the_replacement_is_not():
    assert build_options.FLAGGED_SCHEME in b"'wss', 'itms-services']"
    assert (
        build_options.FLAGGED_SCHEME
        not in build_options.replace_flagged_scheme(b"'wss', 'itms-services']")
    )
```

- [ ] **Step 8.5: Build with the owner's identity, bundle id and profile**

With the values of step 8.1 (the profile path is outside the repository; the identity is the name `security find-identity -v -p codesigning` lists):

```bash
venv_macos/bin/python build_macos.py --store --sign \
  --bundle-id "<the owner's bundle id>" \
  --identity "<Apple Development or Apple Distribution, as listed>" \
  --provisioning-profile "<path>.provisionprofile" > .claude/store-sign.log 2>&1
tail -4 .claude/store-sign.log
codesign --verify --deep --strict --verbose=2 dist-store/Applio.app 2>&1 | tail -1
plutil -p dist-store/Applio.app/Contents/Info.plist | grep -E "CFBundleIdentifier|LSMinimumSystemVersion"
security cms -D -i dist-store/Applio.app/Contents/Embedded.provisionprofile | plutil -extract Entitlements xml1 -o - - | grep -c app-sandbox
git status --porcelain
```

Expected: `BUILD COMPLETE`; `valid on disk` and `satisfies its Designated Requirement`; the owner's bundle id and `15.0`; `1`; and `git status` shows nothing modified (the interpreter's sources are outside the repository: compare them with the backups under `build/scheme-string-backups/` by `cmp`).

- [ ] **Step 8.6: Run it locally, and the reinstall**

With the build signed for development ("Apple Development" and the development profile), using the owner's bundle id in the paths:

1. Start: the folder dialog; choose a test folder on the SSD; the download dialog; Download. The main window appears. Quit.
2. Remove the app and what macOS keeps for it: move `Applio.app` to the Trash, then, from the main session, `rm -r ~/Library/Containers/<the owner's bundle id>` (the preferences and the bookmark file live inside the container; if the permission system refuses the removal, ask the owner to run it).
3. Put the app back from `dist-store/` and start it.

Expected: no folder dialog; the app uses the test folder (File, Open in Finder, Logs). That is the keychain bookmark. If the folder dialog appears, or macOS asks for keychain access: write down which, and record in `docs/APP_STORE_READINESS.md`: "the keychain route does not work in the sandbox; the app asks for the folder once after a reinstall". Nothing else changes: the data was never at risk.

- [ ] **Step 8.7: The SDK of the main executable**

```bash
otool -l dist-store/Applio.app/Contents/MacOS/Applio | grep -A4 LC_BUILD_VERSION | grep -E "minos|sdk"
ditto -c -k --keepParent dist-store/Applio.app .claude/Applio-store.zip
xcrun altool --validate-app --type macos -f .claude/Applio-store.zip --apiKey "<key id>" --apiIssuer "<issuer id>" 2>&1 | tail -12
```

Expected today: `sdk 14.2`. `altool` needs the App Store Connect key file (`.p8`) in `~/.private_keys/`; the key id and the issuer id are the owner's and are never printed into the repository. If `altool` reports no SDK problem, go on. If it reports one (an `ITMS-` line about the SDK), the bootloader needs a newer SDK:

- [ ] **Step 8.8: Only if step 8.7 asks for it: rebuild the bootloader**

```bash
venv_macos/bin/python -c "import PyInstaller; print(PyInstaller.__version__)"
git clone --depth 1 --branch v<that version> https://github.com/pyinstaller/pyinstaller.git /Volumes/ssd/tmp/pyinstaller-src
cd /Volumes/ssd/tmp/pyinstaller-src/bootloaders
python3 ./waf all --target-arch=arm64
```

The flags are those of `bootloaders/README.md` in that source tree. Copy the resulting `run` over `venv_macos/lib/python3.12/site-packages/PyInstaller/bootloader/Darwin-64bit/run` after keeping the original as `run.before-store-build`. Build again; `otool` must then name the SDK of Xcode 27. Record the change in `CLAUDE.md`: it changes the direct edition's builds too.

- [ ] **Step 8.9: The floor and the privacy page**

```bash
plutil -p dist-store/Applio.app/Contents/Info.plist | grep LSMinimumSystemVersion
curl -s -o /dev/null -w "%{http_code}\n" https://froggeric.github.io/applio-macOS-native-app/privacy/
```

Expected: `"15.0"` and `200`.

- [ ] **Step 8.10: Commit**

```bash
venv_macos/bin/python -m pytest -q tests
git add build_macos.py tests/test_build_options.py docs/APP_STORE_READINESS.md
git commit -m "store: remove the flagged scheme string from the bundle and check the result"
```

---
### Task 9: Upload, TestFlight and the store record

**Goal:** The build is in App Store Connect, installable through TestFlight, and the record is complete, ready for the owner's word to submit.

**Files:**
- Modify: `README_MACOS.md`, `FORK_DIFFERENCES.md`, `CHANGELOG.md`, `CLAUDE.md`, `docs/ROADMAP.md`

**Acceptance Criteria:**
- [ ] `altool --upload-app` ends without error and the build appears in App Store Connect.
- [ ] The build installs from TestFlight on the build Mac and converts one file.
- [ ] The App Store Connect record has: name Applio, the owner's bundle id, category Music, minimum macOS 15, the privacy policy URL, privacy "Data Not Collected", age rating, at least one macOS screenshot, review notes that name IAHispano's authorisation.
- [ ] The documentation names the store edition, its build command and its limits.
- [ ] Nothing was submitted for review: that waits for the owner's word.

**Verify:** App Store Connect shows the build with the status "Ready to Submit".

**Steps:**

- [ ] **Step 9.1: Upload**

Only on the owner's word. With the zip of step 8.7:

```bash
xcrun altool --upload-app --type macos -f .claude/Applio-store.zip --apiKey "<key id>" --apiIssuer "<issuer id>" 2>&1 | tail -8
```

- [ ] **Step 9.2: TestFlight**

Add the owner as an internal tester, install from TestFlight, convert one file, start one training for two epochs. If a tester with macOS 15 or 26 is available, the same there: those two versions are not tested on the build Mac.

- [ ] **Step 9.3: The record**

Name Applio (IAHispano's authorisation covers the name and the icon), the owner's bundle id, category Music, the privacy policy URL of decision 7, privacy practices "Data Not Collected" (text sent to Microsoft's speech service is the user's own action in text to speech; say so in the notes), age rating, at least one screenshot at 1280 by 800, 1440 by 900, 2560 by 1600 or 2880 by 1800.

- [ ] **Step 9.4: Review notes**

```text
Applio converts voices with voice models that the user trains or downloads.
It is the macOS edition of the open-source project Applio by IAHispano, made
with IAHispano's permission to use the name and the icon.

First launch: the app asks for a folder for its data, then which models to
download. The first part (about 0.6 GB, pitch extractors and voice embedder)
is needed to convert and to train. Two optional sets of pretrained voices
(about 0.6 GB and 2 GB) can be downloaded later under File, Download Models.
Choose Download; on a normal broadband line the first part takes about two
minutes.

To try a conversion without training: Models, download one of the pretrained
voice models, then Convert Audio: choose that model, drop any audio file,
Convert.

To try training: Training, any folder with a minute of speech at 48 kHz;
preprocess, extract, train a few epochs.

The app is written in Python and wrapped with PyInstaller. It runs in the
App Sandbox. It has no plug-in system, no updater and no analytics. Network
use: model downloads from huggingface.co and github.com, and text to speech
through Microsoft's online service when the user asks for it.
```

- [ ] **Step 9.5: Documentation**

`README_MACOS.md`: a section "Mac App Store edition" with what differs from the direct download. `FORK_DIFFERENCES.md`: the three store patchers. `CHANGELOG.md`: an entry under `[Unreleased]`, including the computed minimum macOS version of the direct edition. `CLAUDE.md`: the `--store` command, `dist-store/`, the rule that store patchers live in `patches/store/` and are re-pointed after an upstream sync, and that `LSMinimumSystemVersion` is computed. `docs/ROADMAP.md`: the store edition moves from "Later" to done, with the date.

```bash
git add README_MACOS.md FORK_DIFFERENCES.md CHANGELOG.md CLAUDE.md docs/ROADMAP.md
git commit -m "docs: the Mac App Store edition"
```

- [ ] **Step 9.6: Submission**

Only on the owner's explicit word, after TestFlight.

- [ ] **Step 9.7: Back to `main`**

When the owner agrees, merge `store-edition` into `main` (the direct edition gains the computed minimum macOS version; the next direct build publishes it). Until then the branch stays separate.

---
## Self-review

**Spec coverage** (each point of `docs/APP_STORE_READINESS.md` section 4 has a task):

- Build: sandbox entitlements, store-only patchers, store signing with profile, no notarization, no disk image, `dist-store/`: tasks 1 and 8.
- Pipeline without worker processes: task 2. Checkpoints as data only: task 3.
- Data in a folder the user chose, with its bookmark in the app and in the keychain, found again after a restart and a reinstall: tasks 4, 5 and step 8.6.
- Wrapper: MIME types, no Python files in the data location: task 5.
- Interface: no plugins, updater, update check, Discord presence; selectable downloads with File, Download Models…; privacy link and licence notes; no Realtime: task 6.
- Verification in the sandbox, and the pipe probe for a later real-time conversion: task 7.
- Bundle: category, encryption key, the owner's bundle id, the computed minimum macOS version, the flagged string, the SDK: tasks 1 and 8.
- Upload, TestFlight, the record with IAHispano's authorisation in the notes: task 9.

**The owner's eight answers:** 1 (name and icon) in task 9; 2 (own bundle id) in tasks 1 and 8, the string still open; 3 (copyleft parts stay) in task 6; 4 (data location) in tasks 4 and 5; 5 (no real-time conversion) in tasks 6 and 7; 6 (selectable downloads) in task 6; 7 (privacy policy on GitHub) in tasks 1, 6 and 8; 8 (minimum macOS version) in task 1.

**Placeholder scan:** no task leaves its content to be written later. The places that depend on facts only the run shows are explicit steps with an expected outcome and an alternative: the PyObjC out-parameter form (task 4 step 4), the keychain route (task 8 step 8.6) and the SDK (task 8 steps 8.7 and 8.8).

**Names used consistently:** `store_edition()`, `prepare_for_sandbox()`, `PRIVACY_POLICY_URL` (`applio_edition`); `option_problems()`, `replace_flagged_scheme()`, `minimum_macos_version()`, `FLAGGED_SCHEME` (`build_options`); `bookmark_path()`, `save(path, store_at=None)`, `resolve_saved(saved_path, store_at=None)`, `resolve_remembered(store_at=None)`, `read_keychain()`, `write_keychain(data)`, `_create(path)`, `_resolve(data)` (`applio_bookmarks`); `real_home()`, `is_writable(path)`, `resolve(saved_path, prefs, bookmarks, pick_folder, confirm_continue, quit_app)` (`applio_data_location`); `BASE`, `PARTS`, `missing_parts(data_path)`, `download_parts(parts)`, `ask_which_parts(missing, required)`, `first_launch(data_path)`, `download_from_menu(data_path)` (`applio_model_downloads`); `native_loop_is_available()` (`applio_native_picker`); `menu_for_edition(store_edition=False)` (`menu_spec`); `confirm_store_data_location(reason)` (`macos_wrapper.py`); `openPrivacyPolicy_`, `downloadModels_` (`applio_launcher.py`); `STORE_PATCHES`, `PATCH_MARKERS_STORE`, `active_patch_markers()`, `sign_app_store()`, `bundle_minimum_macos_version()`, `set_minimum_macos_version()`, `flagged_schemes_replaced()`, `flagged_schemes_in_bundle()` (`build_macos.py`); `read_source`, `write_source`, `patch_file`, `run`, `main` (`patches/store/store_patch_common.py`).

**Review Focus:** each line has its test or its step: 1 in tasks 4, 5 and step 8.6; 2 in task 6 and steps 7.4 and 7.6; 3 in task 2; 4 in task 1; 5 in tasks 1 and 8; 6 in task 5 and step 7.5.
