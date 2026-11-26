# Mac App Store edition implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Mac App Store edition of Applio for macOS from the same sources as the direct-download edition, with the App Sandbox on, and submit it to App Store Connect.

**Architecture:** `build_macos.py --store` switches the build: store entitlements, store-only patchers in `patches/store/`, store signing, output in `dist-store/`. The edition is written into `build_info.json`, and fork-owned code asks `applio_edition.store_edition()` wherever behaviour differs (data location, bookmarks, menu, download prompt). The direct-download edition keeps its build and its behaviour.

**Tech Stack:** Python 3.12, PyInstaller 6.22, PyObjC (AppKit, Foundation), pytest, `codesign`, `xcrun altool`, Xcode 27.2.

**Spec:** `docs/APP_STORE_READINESS.md`

**When to run it:** after the owner's manual test pass of 3.7.2.1 and the 3.7.2.1 release, and only on the owner's word ("start the store edition").

## Global Constraints

- **Upstream files are never edited in the repository.** A change to upstream code is a patcher in `patches/store/`, applied only by `--store`, with markers in `PATCH_MARKERS_STORE`. A change to fork-owned code is an `if store_edition():` branch.
- **The direct-download edition must not change.** `build_macos.py --sign --notarize --dmg` produces what it produced before. The unit tests pass (`venv_macos/bin/python -m pytest -q tests`), and black is clean on changed fork-owned files (`venv_macos/bin/python -m black --check <files>`).
- **A store build never writes into `dist/`.** It writes into `dist-store/`. The build under test and the release disk image live in `dist/`.
- **Nothing is uploaded to App Store Connect without the owner's explicit word.** The same rule as for GitHub releases.
- **Until the owner's App ID exists, store test builds use the throwaway bundle id `com.iahispano.applio.storetest`.** Its container is `~/Library/Containers/com.iahispano.applio.storetest`.
- **Frozen builds are tested on copies** (`cp -cR dist-store/Applio.app .claude/store/X.app`), never by editing the build itself. An edited copy is re-signed ad hoc before its first launch. Test folders and containers are removed when the task is done; a subagent does not delete outside the repository, it reports what it left.
- **`/usr/bin/open` stays.** It works under App Sandbox (tested 2026-11-26).
- **Upstream's `sys.path.append(now_dir)` stays.** Nothing writes code into the data location once the Plugins page is gone, and the bundle comes first on `sys.path`.
- **Line numbers below are those of commit 178db176** (the tree before this plan). The text anchors are what matters: a patcher fails with exit 2 when an anchor is not found exactly once.
- **VoiceOver:** checklists for the owner go inline in the message, complete, numbered, without tables.

## User decisions (already made)

- "plan the app store edition" (2026-11-26): this plan. Implementation starts only on the owner's word.
- Recommended order, given to the owner and not contradicted: manual test pass and the 3.7.2.1 release first, then the store edition.
- "no new release on github yet": nothing is published without the owner's explicit word.
- "run the experiment" and "measure" (2026-11-26): the App Sandbox experiment and the measurement were run on the owner's word. Training without worker processes is the accepted route (5 to 11 percent slower).
- Never modify upstream files directly: use `patches/`.

## Decisions that wait for the owner (DECIDE list)

Each one is open because only the owner, or upstream, can answer it. The plan's default is in brackets. A different answer changes only what the line says it changes.

1. **Name and icon** (guideline 4.1 (c)). Applio and its icon belong to IAHispano. Either IAHispano's written approval, or another name and icon. [Default: ask upstream first; build with `--app-name` and `--icon`, which default to today's values.] A different name would also need different wording inside the app, which is not in this plan.
2. **Bundle id.** Today the app carries upstream's `com.iahispano.applio`. An id of the owner's lets both editions sit side by side, each with its own container, preferences and logs. [Default: the owner's own id, passed with `--bundle-id`.] Nothing else changes.
3. **Copyleft parts.** `soxr` (LGPL) is used by inference and preprocessing and cannot simply be dropped. `edge-tts` (LGPL-3.0) is text to speech. [Default: accept `soxr` knowingly and name it in an acknowledgements text; text to speech stays.] Leaving text to speech out would remove one page in task 6. Not legal advice.
4. **Data location.** [Default: inside the container, with "Set Data Location" for any other folder through a bookmark.] Only the container is possible without the bookmark work of task 5.
5. **Real-time conversion.** `rvc/realtime/worker.py` runs a second process with process queues and events, which the sandbox is expected to deny. [Default: the first store version has no Realtime page (task 6); task 10 shows whether a pipe-based channel works, for a later version.]
6. **First download.** [Default: a prompt, then the download of about 3 GB.] Bundling the conversion models (about 0.6 GB) into the app instead is more work and is not in this plan.
7. **Privacy policy URL.** [Default: `https://froggeric.github.io/applio-macOS-native-app/privacy/`, a GitHub Pages page of the fork that the owner writes in task 9.] A different URL is one constant, `PRIVACY_POLICY_URL` in `applio_edition.py`.
8. **Minimum macOS version.** [Default: 12.0, as today.] A higher version is one line in `build_macos.py`.

## Review Focus

Failure modes the tasks' tests do not reach on their own, most likely first:

1. A data folder on an external disk, chosen once, must still be readable after a restart (task 5 round trip; task 7 step 7.9).
2. "Not now" on the first-launch prompt: the app must start and say that conversion needs the models (task 6 tests the answer; task 7 step 7.7 looks at the app).
3. A failing extraction must still be reported: the pools reported errors as warnings, and the serial loops keep those messages (task 2 test).
4. `--store` with flags it cannot take must stop before anything is built (task 1 `tests/test_build_options.py`).
5. A bookmark that no longer resolves (folder renamed, disk unplugged) must lead to the existing "not writable" dialog, not to a crash (task 5 test for a missing bookmark; task 7 step 7.10).

## Files

New:

- `applio_edition.py`, fork-owned: reads the edition from `build_info.json`; `store_edition()`, `default_data_location()`, `prepare_for_sandbox()`, `PRIVACY_POLICY_URL`.
- `build_options.py`, fork-owned: argument checks of the build that need no build to run.
- `applio_bookmarks.py`, fork-owned: security-scoped bookmark of the data location.
- `applio_download_prompt.py`, fork-owned: the prompt before the first model download.
- `assets/entitlements_store.plist`: the sandbox entitlements.
- `patches/store/store_patch_common.py` and three patchers: pipeline, checkpoint loading, interface.
- Tests: `tests/test_applio_edition.py`, `tests/test_build_options.py`, `tests/test_store_patchers.py`, `tests/test_applio_bookmarks.py`, `tests/test_applio_download_prompt.py`, `tests/test_menu_edition.py`.
- `.claude/store/tools/pipe_channel_probe.py` (git-ignored local tool).

Modified:

- `build_macos.py`: `--store` and its companions, store patch list, Info.plist, signing, `build_info.json`, the flagged scheme string.
- `menu_spec.py`, `applio_launcher.py`, `macos_wrapper.py`, `applio_native_picker.py`: edition branches.
- `HIDDEN_IMPORTS` in `build_macos.py`: the three new fork modules.
- `.gitignore`: `dist-store/`.
- `README_MACOS.md`, `FORK_DIFFERENCES.md`, `CHANGELOG.md`, `CLAUDE.md`, `docs/ROADMAP.md`.

---

### Task 0: Prerequisites

**Goal:** Have the branch, the checkout and the decisions ready before any code changes.

**Files:**
- Read: `docs/APP_STORE_READINESS.md`, `CLAUDE.md` ("Fork Maintenance", "Build process gotchas")

**Acceptance Criteria:**
- [ ] The owner has answered decisions 1 to 8 of the DECIDE list, or accepted the defaults.
- [ ] The manual test pass of 3.7.2.1 has a result and the 3.7.2.1 release is out, or the owner said to start anyway.
- [ ] A worktree exists for a branch `store-edition`, created with the native worktree tool.
- [ ] The baseline is green in the worktree.

**Verify:** `venv_macos/bin/python -m pytest -q tests` in the worktree → `118 passed` (or more; none failed)

**Steps:**

- [ ] **Step 1: Record the decisions**

Write the answers into the "User decisions (already made)" section of this plan, one line each, before task 1 starts.

- [ ] **Step 2: Create the worktree**

Use the worktree tool of the session on a new branch `store-edition` from `main`. Do not work in the main checkout: its `dist/` holds the build under test.

- [ ] **Step 3: Run the baseline**

```bash
cd <worktree>
/Volumes/ssd/github/applio-macOS-native-app/venv_macos/bin/python -m pytest -q tests
```

The worktree has no `venv_macos` of its own (it is git-ignored). Every command in this plan that says `venv_macos/bin/python` means that absolute interpreter, run from the worktree.

- [ ] **Step 4: Note where the models are**

The worktree has no `rvc/models` (git-ignored, 7.1 GB). Builds and tests clone what they need from `/Volumes/ssd/github/applio-macOS-native-app/rvc/models` with `cp -cR` (same volume: no extra space).

---

### Task 1: Edition switch in the build

**Goal:** `build_macos.py --store` produces an app with the sandbox entitlements, signed ad hoc, in `dist-store/`, with `edition: store` in `build_info.json`, and leaves the direct build as it was.

**Files:**
- Create: `applio_edition.py`, `build_options.py`, `assets/entitlements_store.plist`
- Create: `tests/test_applio_edition.py`, `tests/test_build_options.py`
- Modify: `build_macos.py` (argument parser near line 128-202, the constants read from `args` near 204-215, `pyinstaller_args` near 716, `HIDDEN_IMPORTS` near 606, `pre_build_patch` near 996, `_check_patch_table` near 950, `verify_patch_markers` near 1340, the `build_info.json` writer near 1375, the Info.plist block near 1518-1536, `sign_app` near 1661)
- Modify: `.gitignore`

**Acceptance Criteria:**
- [ ] `--store --notarize`, `--store --dmg`, `--store --sign` without a profile, and `--provisioning-profile` without `--sign` each stop with a message before anything is built.
- [ ] `applio_edition.store_edition()` is `False` without `build_info.json`, `False` with `"edition": "direct"`, `True` with `"edition": "store"`.
- [ ] The default data location is `~/Applio` in the direct edition and `~/Library/Application Support/Applio/data` in the store edition.
- [ ] After `build_macos.py --store --bundle-id com.iahispano.applio.storetest`: `dist-store/Applio.app` exists, `dist/` is untouched, `build_info.json` has `"edition": "store"`, the signature carries `com.apple.security.app-sandbox`.
- [ ] A build without `--store` in the worktree gives the same entitlements as before and `"edition": "direct"`.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_applio_edition.py tests/test_build_options.py` → all pass; then the build commands in step 9.

**Steps:**

- [ ] **Step 1: Write the failing tests for the edition reader**

`tests/test_applio_edition.py`:

```python
"""applio_edition: the edition is read from build_info.json, nothing else."""

import json
import mimetypes
import os

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
    assert edition.default_data_location() == os.path.expanduser("~/Applio")


def test_store_edition(monkeypatch, tmp_path):
    edition = _edition_with(monkeypatch, tmp_path, {"edition": "store"})
    assert edition.store_edition() is True
    assert edition.default_data_location() == os.path.expanduser(
        "~/Library/Application Support/Applio/data"
    )


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

# Decision 7 of docs/APP_STORE_READINESS.md. The page must exist before the
# app is submitted (guideline 5.1.1 (i)).
PRIVACY_POLICY_URL = "https://froggeric.github.io/applio-macOS-native-app/privacy/"


def _frozen_base():
    return getattr(sys, "_MEIPASS", None)


def _build_info_candidates():
    frozen_base = _frozen_base()
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


def default_data_location() -> str:
    """Where the data lives when the user never chose a folder.

    In the store edition that is inside the app's sandbox container: there
    `~` resolves to the container, so the path needs no bookmark.
    """
    if store_edition():
        return os.path.expanduser("~/Library/Application Support/Applio/data")
    return os.path.expanduser("~/Applio")


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
Expected: `6 passed`

- [ ] **Step 5: Write the failing tests for the argument checks**

`tests/test_build_options.py`:

```python
"""build_options: what --store may and may not be combined with."""

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
```

- [ ] **Step 6: Run them and see them fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_build_options.py`
Expected: collection error, `No module named 'build_options'`.

- [ ] **Step 7: Create `build_options.py`**

```python
"""Checks on the options of build_macos.py that need no build to run.

build_macos.py runs the whole build when it is imported, so its argument
checks live here where the tests can import them.
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
```

- [ ] **Step 8: Run them and see them pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_build_options.py`
Expected: `7 passed`

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
        "--app-name",
        type=str,
        default=None,
        help="App name of the bundle (default: Applio; store edition, decision 1)",
    )
    parser.add_argument(
        "--icon",
        type=str,
        default=None,
        help="Icon file of the bundle (default: assets/ICON.ico)",
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
APP_NAME = args.app_name or "Applio"
ICON_FILE = args.icon or "assets/ICON.ico"
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

In `pyinstaller_args`:

```python
        f"--name={APP_NAME}",
        ...
        f"--icon={ICON_FILE}",
        ...
        f"--osx-bundle-identifier={BUNDLE_ID}",
        f"--distpath={DIST_DIR}",
```

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
            if args.app_name:
                plist["CFBundleDisplayName"] = args.app_name
```

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

- [ ] **Step 15: Make the new fork modules importable in the frozen app**

In `HIDDEN_IMPORTS`, add:

```python
    "applio_edition",
    "applio_bookmarks",
    "applio_download_prompt",
```

- [ ] **Step 16: Ignore the store output**

In `.gitignore`, next to `dist/`:

```
dist-store/
```

- [ ] **Step 17: Fix the summary of the build**

In the final summary of `build_macos.py`, replace `Note: Models (~2GB) will download on first launch` by `about 3 GB`, and print `Edition: Mac App Store` when `STORE_BUILD`.

- [ ] **Step 18: Run the tests and the checks of the direct edition**

```bash
venv_macos/bin/python -m pytest -q tests
venv_macos/bin/python -m black --check build_macos.py build_options.py applio_edition.py tests/test_applio_edition.py tests/test_build_options.py
venv_macos/bin/python .claude/port-tools/applio_run_patch_stage.py .
```

Expected: all tests pass, black leaves the files unchanged, the tool ends with `PATCH STAGE OK`. (`applio_run_patch_stage.py` is a local tool of the main checkout; when the worktree has no `.claude/port-tools`, copy the folder from the main checkout.)

- [ ] **Step 19: Build the store edition ad hoc and check it**

```bash
venv_macos/bin/python build_macos.py --store --bundle-id com.iahispano.applio.storetest > .claude/store-build.log 2>&1
tail -5 .claude/store-build.log
plutil -p dist-store/Applio.app/Contents/Resources/build_info.json
codesign -d --entitlements :- dist-store/Applio.app 2>/dev/null | grep -c app-sandbox
ls dist
```

Expected: the log ends with `BUILD COMPLETE`; the plist shows `"edition" => "store"`; the grep prints `1`; `ls dist` shows nothing new (or nothing, in the worktree).

- [ ] **Step 20: Build the direct edition in the worktree and compare**

```bash
venv_macos/bin/python build_macos.py > .claude/direct-build.log 2>&1
plutil -p dist/Applio.app/Contents/Resources/build_info.json
codesign -d --entitlements :- dist/Applio.app 2>/dev/null | grep -c app-sandbox
```

Expected: `"edition" => "direct"` and `0` (the sandbox key is false in `assets/entitlements.plist`, so the count is 0 or the key appears with `false`: check with `codesign -d --entitlements :- dist/Applio.app` that the entitlements are those of `assets/entitlements.plist`).

- [ ] **Step 21: Commit**

```bash
git add applio_edition.py build_options.py assets/entitlements_store.plist build_macos.py .gitignore tests/test_applio_edition.py tests/test_build_options.py
git commit -m "build: add --store for the Mac App Store edition"
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

### Task 4: Wrapper in the sandbox

**Goal:** The store edition starts in the sandbox without the folder prompt, keeps its data in the container, imports Gradio, and copies no Python file into the data location.

**Files:**
- Modify: `macos_wrapper.py` (`start_gui`, the data-location block near line 2030-2046; `start_backend` near 1576; `setup_bundled_resources`, inner `copy_file`, near 923)
- Test: `tests/test_applio_edition.py` (already covers the defaults)

**Acceptance Criteria:**
- [ ] In the store edition a start without a saved location does not open the folder prompt and uses `default_data_location()`.
- [ ] `mimetypes.knownfiles` is `[]` before `from app import launch_gradio` runs, in the store edition only.
- [ ] After a store start, the data location contains no `.py` file.
- [ ] The direct edition still opens the prompt on first run and still copies the tab scripts.

**Verify:** task 7 steps 7.2 to 7.5 run the frozen app; here: `venv_macos/bin/python -c "import macos_wrapper"` → no output, exit 0 (the module stays free of side effects at import).

**Steps:**

- [ ] **Step 1: Import the edition helper**

At the top of `macos_wrapper.py`, with the other fork imports:

```python
from applio_edition import default_data_location, prepare_for_sandbox, store_edition
```

- [ ] **Step 2: No folder prompt in the store edition**

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
        if store_edition() and not DATA_PATH:
            # First run of the store edition: no folder prompt. The data goes
            # to the app's own container; the File menu can move it later.
            DATA_PATH = default_data_location()

    if not DATA_PATH:
```

The direct edition keeps the prompt: `store_edition()` is `False` there and `DATA_PATH` stays unset.

- [ ] **Step 3: The MIME-type fix before Gradio**

In `start_backend`, before `from app import launch_gradio`:

```python
            prepare_for_sandbox()
```

- [ ] **Step 4: No Python file in the data location**

In `setup_bundled_resources`, as the first line of the inner `copy_file`:

```python
        if store_edition() and dest_rel.endswith(".py"):
            # Store edition: code is loaded from the bundle only.
            return
```

- [ ] **Step 5: Check and commit**

```bash
venv_macos/bin/python -c "import macos_wrapper"
venv_macos/bin/python -m pytest -q tests
venv_macos/bin/python -m black --check macos_wrapper.py
git add macos_wrapper.py
git commit -m "store: data in the container, no tab scripts copied, Gradio imports in the sandbox"
```

---

### Task 5: Bookmarks for the data location

**Goal:** A data location chosen with "Set Data Location" outside the container stays reachable after a restart.

**Files:**
- Create: `applio_bookmarks.py`
- Create: `tests/test_applio_bookmarks.py`
- Modify: `applio_native_picker.py` (one accessor after `mark_native_loop_available`), `applio_launcher.py` (`setDataLocation_`, near line 6505), `macos_wrapper.py` (the block changed in task 4)

**Acceptance Criteria:**
- [ ] A bookmark saved for a folder resolves back to that folder (path comparison after `os.path.realpath`).
- [ ] A missing bookmark file resolves to `None` and raises nothing.
- [ ] `bookmark_path()` is under `~/Library/Application Support/Applio/` (inside the container in the sandbox).
- [ ] `setDataLocation_` saves a bookmark in the store edition; the wrapper resolves it at start.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_applio_bookmarks.py` → all pass

**Steps:**

- [ ] **Step 1: Write the failing test**

`tests/test_applio_bookmarks.py`:

```python
"""applio_bookmarks: a saved folder resolves back to the same folder."""

import os

import applio_bookmarks


def test_bookmark_round_trip(tmp_path):
    folder = tmp_path / "data location"
    folder.mkdir()
    store_at = str(tmp_path / "support" / "data_location.bookmark")

    assert applio_bookmarks.save_bookmark(str(folder), store_at) is True
    assert os.path.exists(store_at)

    resolved = applio_bookmarks.resolve_bookmark(store_at)

    assert resolved is not None
    assert os.path.realpath(resolved) == os.path.realpath(str(folder))


def test_a_missing_bookmark_resolves_to_nothing(tmp_path):
    assert applio_bookmarks.resolve_bookmark(str(tmp_path / "none")) is None


def test_the_bookmark_lives_in_application_support():
    assert applio_bookmarks.bookmark_path() == os.path.expanduser(
        "~/Library/Application Support/Applio/data_location.bookmark"
    )


def test_a_folder_that_does_not_exist_gets_no_bookmark(tmp_path):
    store_at = str(tmp_path / "support" / "data_location.bookmark")

    assert (
        applio_bookmarks.save_bookmark(str(tmp_path / "missing"), store_at) is False
    )
    assert not os.path.exists(store_at)
```

- [ ] **Step 2: Run it and see it fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_bookmarks.py`
Expected: collection error, `No module named 'applio_bookmarks'`.

- [ ] **Step 3: Create `applio_bookmarks.py`**

```python
"""Security-scoped bookmark of the data location (Mac App Store edition).

In the sandbox a folder outside the app's container is reachable through the
folder picker for the session in which it was picked. A bookmark keeps that
access across launches. The bookmark itself is stored in the app's own
Application Support folder, which is inside the container.

AppKit is imported lazily: importing this module has no side effects.
"""

import logging
import os

BOOKMARK_NAME = "data_location.bookmark"


def bookmark_path() -> str:
    return os.path.expanduser(
        os.path.join("~/Library/Application Support/Applio", BOOKMARK_NAME)
    )


def save_bookmark(path: str, store_at: str | None = None) -> bool:
    """Create a security-scoped bookmark for `path` and write it. False on failure."""
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(path)
    data, error = url.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(
        0, None, None, None
    )
    if data is None:
        logging.warning(f"[Bookmarks] Could not create a bookmark for {path}: {error}")
        return False
    store_at = store_at or bookmark_path()
    os.makedirs(os.path.dirname(store_at), exist_ok=True)
    with open(store_at, "wb") as f:
        f.write(data)
    return True


def resolve_bookmark(store_at: str | None = None) -> str | None:
    """Resolve the saved bookmark and start accessing the folder.

    Returns the folder's path, or None when there is no bookmark or it cannot
    be resolved. The access stays on for the life of the process: a
    security-scoped resource may be released only as often as it was started.
    """
    store_at = store_at or bookmark_path()
    if not os.path.exists(store_at):
        return None
    from Foundation import NSURL

    with open(store_at, "rb") as f:
        data = f.read()
    url, stale, error = (
        NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
            data, 0, None, None, None
        )
    )
    if url is None:
        logging.warning(f"[Bookmarks] Could not resolve {store_at}: {error}")
        return None
    url.startAccessingSecurityScopedResource()
    path = url.path()
    if stale:
        save_bookmark(path, store_at)
    return path
```

- [ ] **Step 4: Run the test and see it pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_bookmarks.py`
Expected: `4 passed`. If PyObjC raises a `TypeError` on the two calls, the installed PyObjC does not take `None` for the out parameters: drop the trailing `None` arguments of `error:` and pass no value for `isStale:` (the returned tuple stays `(url, stale, error)`), then run again.

- [ ] **Step 5: Save the bookmark when a location is chosen**

In `applio_launcher.py`, in `setDataLocation_`, after `new_path = urls[0].path()` and its `logging.info(...)` line:

```python
                from applio_edition import store_edition

                if store_edition():
                    import applio_bookmarks

                    applio_bookmarks.save_bookmark(new_path)
```

- [ ] **Step 6: Resolve it at start**

In `macos_wrapper.py`, the block written in task 4 step 2 becomes:

```python
    else:
        DATA_PATH = _prefs.get_data_path()
        if store_edition() and DATA_PATH:
            # A folder outside the container is reachable only through the
            # bookmark made when it was chosen.
            import applio_bookmarks

            DATA_PATH = applio_bookmarks.resolve_bookmark() or DATA_PATH
        if store_edition() and not DATA_PATH:
            # First run of the store edition: no folder prompt. The data goes
            # to the app's own container; the File menu can move it later.
            DATA_PATH = default_data_location()

    if not DATA_PATH:
```

When the bookmark no longer resolves, the existing write test in the first-run block of the direct edition does not run (the location is set); the folder is simply not writable, and the app's own file errors say so. Task 7 step 7.10 looks at what the user sees and decides whether a clearer message is needed.

- [ ] **Step 7: Commit**

```bash
venv_macos/bin/python -m pytest -q tests
venv_macos/bin/python -m black --check applio_bookmarks.py applio_launcher.py macos_wrapper.py tests/test_applio_bookmarks.py
git add applio_bookmarks.py applio_launcher.py macos_wrapper.py tests/test_applio_bookmarks.py
git commit -m "store: keep a chosen data location reachable with a bookmark"
```

---

### Task 6: Interface for the store

**Goal:** The store edition has no Plugins page, no updater, no update check and no Discord presence; it asks before the first model download and links to the privacy policy. The Realtime page is left out (decision 5).

**Files:**
- Create: `patches/store/patch_store_app.py`, `applio_download_prompt.py`
- Create: `tests/test_applio_download_prompt.py`, `tests/test_menu_edition.py`
- Modify: `tests/test_store_patchers.py`, `build_macos.py` (`STORE_PATCHES`, `PATCH_MARKERS_STORE`, `post_build_cleanup` near 1444), `applio_native_picker.py`, `menu_spec.py`, `applio_launcher.py` (`_launch_time_update_check` near 6252, the menu source near 5724, the action dictionary near 6301)
- Patched at build time only: `app.py` (lines 10-12, 118, 120, 124-131, 138-144, 187, 193), `tabs/settings/settings.py` (lines 13, 51-57)

**Acceptance Criteria:**
- [ ] After the patch `app.py` has no `ensure_not_updating`, no `plugins_tab`, no `RPCManager`, no `realtime_tab`; the `run_prerequisites_script(` call sits inside `if confirm_first_download(now_dir):`.
- [ ] `tabs/settings/settings.py` has no `presence_tab` and shows "Privacy Policy".
- [ ] Both files compile; second run is a no-op.
- [ ] `confirm_first_download` returns `True` when the models are there and when no native loop runs; `False` or `True` as answered otherwise.
- [ ] The store menu has no `app.check_updates` and has `app.privacy_policy`; the shared `MENU` is not modified.
- [ ] Seven markers in `PATCH_MARKERS_STORE`.
- [ ] The store bundle contains no `tabs/plugins/`, no `assets/updater.py`, no `tabs/settings/sections/presence.py`, no `assets/discord_presence.py`.

**Verify:** `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py tests/test_applio_download_prompt.py tests/test_menu_edition.py` → all pass

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
    settings_text = _read(copied[1])
    assert "presence_tab" not in settings_text
    assert "Privacy Policy" in settings_text
    assert settings_text.count("_applio_privacy_policy_tab(") == 2


def test_the_download_is_asked_for_first(tmp_path):
    app = _copy("app.py", tmp_path)
    _copy("tabs/settings/settings.py", tmp_path)

    assert _run("patch_store_app.py", os.path.join(tmp_path, "app.py")).returncode == 0

    app_text = _read(app)
    guard = app_text.index("if confirm_first_download(now_dir):")
    call = app_text.index("run_prerequisites_script(", guard)
    assert call > guard
    assert "run_prerequisites_script(" not in app_text[:guard]


def test_app_patcher_is_a_no_op_the_second_time(tmp_path):
    for relative in APP_FILES:
        _copy(relative, tmp_path)
    assert _run("patch_store_app.py", os.path.join(tmp_path, "app.py")).returncode == 0
    before = [_read(os.path.join(tmp_path, r)) for r in APP_FILES]

    assert _run("patch_store_app.py", os.path.join(tmp_path, "app.py")).returncode == 0

    assert [_read(os.path.join(tmp_path, r)) for r in APP_FILES] == before
```

- [ ] **Step 2: Run them and see them fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_store_patchers.py -k "app_patcher or asked_for_first"`
Expected: 3 failures, the patcher does not exist yet.

- [ ] **Step 3: Write the failing test for the download prompt**

`tests/test_applio_download_prompt.py`:

```python
"""applio_download_prompt: ask once, before the first model download."""

import os

import applio_download_prompt
import applio_native_picker


def _models(data_path):
    marker = os.path.join(data_path, applio_download_prompt.MODEL_MARKER)
    os.makedirs(os.path.dirname(marker))
    with open(marker, "wb") as f:
        f.write(b"")


def test_models_absent(tmp_path):
    assert applio_download_prompt.models_are_present(str(tmp_path)) is False


def test_models_present(tmp_path):
    _models(str(tmp_path))
    assert applio_download_prompt.models_are_present(str(tmp_path)) is True


def test_no_data_path_counts_as_absent():
    assert applio_download_prompt.models_are_present("") is False


def test_no_prompt_when_the_models_are_there(tmp_path, monkeypatch):
    _models(str(tmp_path))
    monkeypatch.setattr(
        applio_download_prompt,
        "_confirm_on_main_thread",
        lambda result: result.update({"shown": True, "answer": False}),
    )

    # Present models: the answer is True even though the prompt would say no.
    assert applio_download_prompt.confirm_first_download(str(tmp_path)) is True


def test_no_native_loop_means_yes(tmp_path, monkeypatch):
    monkeypatch.setattr(applio_native_picker, "_native_loop_available", False)
    assert applio_download_prompt.confirm_first_download(str(tmp_path)) is True


def _answer(monkeypatch, answer):
    monkeypatch.setattr(applio_native_picker, "_native_loop_available", True)
    monkeypatch.setattr(
        "PyObjCTools.AppHelper.callAfter", lambda function: function()
    )
    monkeypatch.setattr(
        applio_download_prompt,
        "_confirm_on_main_thread",
        lambda result: result.update({"shown": True, "answer": answer}),
    )


def test_a_declined_download_is_false(tmp_path, monkeypatch):
    _answer(monkeypatch, False)
    assert applio_download_prompt.confirm_first_download(str(tmp_path)) is False


def test_an_accepted_download_is_true(tmp_path, monkeypatch):
    _answer(monkeypatch, True)
    assert applio_download_prompt.confirm_first_download(str(tmp_path)) is True
```

- [ ] **Step 4: Run it and see it fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_download_prompt.py`
Expected: collection error, `No module named 'applio_download_prompt'`.

- [ ] **Step 5: Create `applio_download_prompt.py`**

```python
"""Store edition: ask before the first model download (guideline 4.2.3).

The backend that calls this module is a worker thread, so the alert is
handed to the main AppKit thread with AppHelper.callAfter, like the native
picker does. Importing this module has no side effects.
"""

import os
import threading

import applio_native_picker

# One file of the downloaded set: when it exists, the models are there.
MODEL_MARKER = os.path.join("rvc", "models", "predictors", "rmvpe.pt")
PROMPT_TIMEOUT_S = 600  # the user may leave the alert on screen
DOWNLOAD_SIZE_TEXT = "about 3 GB"


def models_are_present(data_path: str) -> bool:
    """True when the first-launch model download has already happened."""
    return bool(data_path) and os.path.exists(os.path.join(data_path, MODEL_MARKER))


def _confirm_on_main_thread(result):
    import applio_i18n
    from AppKit import NSAlert, NSApp, NSAlertFirstButtonReturn

    _t = applio_i18n.native_tr
    NSApp.activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    alert.setMessageText_(_t("Download the models?"))
    alert.setInformativeText_(
        _t(
            "Applio needs {size} of models to convert and train. They are "
            "downloaded once and stored in the app's data folder. Without "
            "them nothing can be converted; the question is asked again at "
            "the next start."
        ).format(size=DOWNLOAD_SIZE_TEXT)
    )
    alert.addButtonWithTitle_(_t("Download"))
    alert.addButtonWithTitle_(_t("Not now"))
    result["answer"] = alert.runModal() == NSAlertFirstButtonReturn
    result["shown"] = True


def confirm_first_download(data_path: str) -> bool:
    """True to go on with the download, False when the user chose Not now.

    No prompt, and True, when the models are there or when no native loop
    runs (started from the sources, drivers, tests).
    """
    if models_are_present(data_path):
        return True
    if not applio_native_picker.native_loop_is_available():
        return True
    from PyObjCTools import AppHelper

    result = {"shown": False, "answer": False}
    done = threading.Event()

    def _run():
        try:
            _confirm_on_main_thread(result)
        finally:
            done.set()

    AppHelper.callAfter(_run)
    if not done.wait(timeout=PROMPT_TIMEOUT_S):
        return True
    return result["answer"]
```

- [ ] **Step 6: Add the accessor to `applio_native_picker.py`**

After `mark_native_loop_available`:

```python
def native_loop_is_available():
    """True once mark_native_loop_available() was called: the launcher runs."""
    return _native_loop_available
```

- [ ] **Step 7: Run the prompt test and see it pass**

Run: `venv_macos/bin/python -m pytest -q tests/test_applio_download_prompt.py`
Expected: `7 passed`

- [ ] **Step 8: Create `patches/store/patch_store_app.py`**

```python
#!/usr/bin/env python3
"""Store edition: the interface Apple's rules ask for.

- No updater and no update check (guideline 2.4.5 (vii)).
- No Plugins page: it downloads code and runs it (2.5.2).
- No Discord presence. Its card in Settings becomes the privacy policy link
  (5.1.1 (i)).
- A prompt before the first model download, with its size (4.2.3).
- No Realtime page: its worker process needs process queues that App Sandbox
  denies (decision 5 of docs/APP_STORE_READINESS.md).

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
DOWNLOAD_NEW = '''# Run prerequisites
from core import run_prerequisites_script

# _APPLIO_STORE_DOWNLOAD_ store edition: guideline 4.2.3 asks to disclose a
# large download and to prompt before it starts.
from applio_download_prompt import confirm_first_download

if confirm_first_download(now_dir):
    run_prerequisites_script(
        pretraineds_hifigan=True,
        models=True,
        exe=True,
    )
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
            ("first download", DOWNLOAD_OLD, DOWNLOAD_NEW),
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
        "store edition: no updater, plugins, update check or Discord presence; download prompt; privacy link",
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

- [ ] **Step 10: Write the failing menu test**

`tests/test_menu_edition.py`:

```python
"""menu_spec.menu_for_edition: the store menu swaps the update check for the privacy link."""

import menu_spec


def _keys(menu):
    return {leaf.key for leaf in menu_spec.iter_leaves(menu)}


def test_the_direct_edition_keeps_the_update_check():
    keys = _keys(menu_spec.menu_for_edition(False))
    assert "app.check_updates" in keys
    assert "app.privacy_policy" not in keys


def test_the_store_edition_has_the_privacy_link_and_no_update_check():
    keys = _keys(menu_spec.menu_for_edition(True))
    assert "app.check_updates" not in keys
    assert "app.privacy_policy" in keys
    assert len(keys) == len(_keys(menu_spec.MENU))


def test_building_the_store_menu_leaves_the_shared_tree_alone():
    menu_spec.menu_for_edition(True)
    assert "app.check_updates" in _keys(menu_spec.MENU)
```

- [ ] **Step 11: Run it and see it fail**

Run: `venv_macos/bin/python -m pytest -q tests/test_menu_edition.py`
Expected: 3 failures with `AttributeError: module 'menu_spec' has no attribute 'menu_for_edition'`.

- [ ] **Step 12: Add `menu_for_edition` to `menu_spec.py`**

After the `MENU` list (the import of `replace` goes to the top, with `from dataclasses import dataclass, field`):

```python
def menu_for_edition(store_edition=False):
    """The menu tree of one edition.

    The store edition has no "Check for Updates" (App Store guideline
    2.4.5 (vii)); its place is taken by the link to the privacy policy
    (guideline 5.1.1 (i)). The shared MENU is not modified.
    """
    if not store_edition:
        return MENU
    return [
        replace(
            top,
            submenu=[
                (
                    MenuItem(key="app.privacy_policy", title="Privacy Policy…")
                    if item.key == "app.check_updates"
                    else item
                )
                for item in top.submenu
            ],
        )
        if top.submenu
        else top
        for top in MENU
    ]
```

- [ ] **Step 13: Use it in the launcher, and stop the update check**

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
```

Next to `checkUpdates_`:

```python
    def openPrivacyPolicy_(self, sender):
        """Open the privacy policy page (store edition)."""
        subprocess.Popen(["open", PRIVACY_POLICY_URL])
```

- [ ] **Step 14: Run everything**

```bash
venv_macos/bin/python -m pytest -q tests
venv_macos/bin/python -m black --check build_macos.py menu_spec.py applio_launcher.py applio_native_picker.py applio_download_prompt.py patches/store/patch_store_app.py tests/test_store_patchers.py tests/test_applio_download_prompt.py tests/test_menu_edition.py
```

Expected: all tests pass (`tests/test_store_patchers.py` now runs complete, 11 tests); black leaves the files unchanged.

- [ ] **Step 15: Commit**

```bash
git add patches/store/patch_store_app.py applio_download_prompt.py applio_native_picker.py menu_spec.py applio_launcher.py build_macos.py tests/test_store_patchers.py tests/test_applio_download_prompt.py tests/test_menu_edition.py
git commit -m "store: no updater, plugins or Discord presence; ask before the first download; privacy link"
```

---

### Task 7: The sandboxed build on this Mac

**Goal:** Run the ad hoc signed store build in the sandbox and record what works: the pipeline in script mode, then the interface in the window, including the owner's VoiceOver pass.

**Files:**
- No repository change, unless a defect is found (then a fix in its own commit and a new build).

**Acceptance Criteria:**
- [ ] Steps 7.1 to 7.8 pass with captured output.
- [ ] The owner's VoiceOver checklist (steps 7.11 to 7.20) comes back with a result for every step.
- [ ] No file was written into `/Volumes/ssd/ai/applio`, and `dist/` of the main checkout is unchanged.

**Verify:** the outputs named in each step.

**Steps:**

- [ ] **Step 7.1: Build and copy**

In the worktree:

```bash
venv_macos/bin/python build_macos.py --store --bundle-id com.iahispano.applio.storetest > .claude/store-build.log 2>&1
tail -3 .claude/store-build.log
mkdir -p .claude/store
cp -cR dist-store/Applio.app .claude/store/ApplioStore.app
```

Expected: the log ends with `BUILD COMPLETE` and names the Mac App Store edition.

- [ ] **Step 7.2: Start once with the window, to create the container**

```bash
open -n .claude/store/ApplioStore.app
```

Expected: the loading screen appears, then the prompt "Download the models?". Leave it unanswered only for step 7.7; otherwise choose Download for now and let it run, or choose Not now for the first pass. Quit with ⌘Q. Then check that the container exists: `ls ~/Library/Containers/com.iahispano.applio.storetest/Data/Library/Application\ Support/Applio/data`.

- [ ] **Step 7.3: Check what the app put into its data location**

```bash
find ~/Library/Containers/com.iahispano.applio.storetest/Data/Library/Application\ Support/Applio/data -name "*.py" | wc -l
grep -c "Notarized\|ERROR" ~/Library/Containers/com.iahispano.applio.storetest/Data/Library/Logs/Applio/applio_wrapper.log
```

Expected: `0` Python files; read any `ERROR` line found.

- [ ] **Step 7.4: Seed a test data folder inside the container**

```bash
C="$HOME/Library/Containers/com.iahispano.applio.storetest/Data"
mkdir -p "$C/bench-data/rvc/models/pretraineds" "$C/bench-data/assets/datasets" "$C/bench-data/logs"
cp -R /Volumes/ssd/github/applio-macOS-native-app/rvc/models/predictors "$C/bench-data/rvc/models/"
cp -R /Volumes/ssd/github/applio-macOS-native-app/rvc/models/embedders "$C/bench-data/rvc/models/"
cp -R /Volumes/ssd/github/applio-macOS-native-app/rvc/models/pretraineds/hifi-gan "$C/bench-data/rvc/models/pretraineds/"
```

About 1.2 GB on the system volume; removed in step 7.21. Do not run the driver's `prep` phase: it downloads the models.

- [ ] **Step 7.5: Preprocess, extract and train in script mode**

Use the local driver `.claude/port-tools/applio_port_frozen_driver.py` of the main checkout (copy the folder into the worktree). It makes its own small dataset (phase `dataset`), then calls `core.run_preprocess_script`, `run_extract_script` and `run_train_script` of the bundle, with `SYNC_TOTAL_EPOCH` epochs:

```bash
SYNC_MODEL=storetest SYNC_TOTAL_EPOCH=2 APPLIO_DATA_PATH="$C/bench-data" \
  .claude/store/ApplioStore.app/Contents/MacOS/Applio \
  /absolute/path/to/.claude/port-tools/applio_port_frozen_driver.py \
  "$C/bench-data" dataset,preprocess,extract,train > .claude/store/pipeline.log 2>&1
grep -c "ipc-posix" .claude/store/pipeline.log
tail -4 "$C/bench-data/logs/storetest/training.log" | cut -c1-200
ls "$C/bench-data/logs/storetest" | grep -c "="
ls /tmp/applio_debug.txt
```

Expected: `0` sandbox denials; the training log shows two epochs; `0` folders named like `331=2.3850` (empty folders of that shape came from the 3.6.2.5 build); no `/tmp/applio_debug.txt`.

- [ ] **Step 7.6: Headless check of the pages served**

Start the windowed app against the seeded folder and run `.claude/port-tools/applio_sync_web_check.py` as for the direct build.

Expected: no JavaScript error; the sidebar has no Plugins and no Realtime entry; Settings step 3 is "Privacy Policy".

- [ ] **Step 7.7: The first download, both answers**

Start with an empty data location (remove the folder named in step 7.2's `ls`, then start again).

Expected: the prompt names the size. Not now: the app reaches the main window and a conversion says that the models are missing. Download: the loading screen shows the download and the app reaches the main window.

- [ ] **Step 7.8: The log**

```bash
grep -n "ERROR" ~/Library/Containers/com.iahispano.applio.storetest/Data/Library/Logs/Applio/applio_wrapper.log | tail -5
```

Expected: no `ERROR` after the line `Version: 3.7.2.1` of the last start, or every one understood and harmless.

- [ ] **Steps 7.9 and 7.10: Data location outside the container**

In the windowed app: File, Set Data Location, choose a folder on `/Volumes/ssd` (for example a new `applio-store-test` folder). Quit and start again: the app uses that folder (File, Open in Finder, Logs opens it). Then rename that folder in Finder and start again: note what the app says (task 5 step 6). Rename it back.

- [ ] **Step 7.11 to 7.20: The owner's VoiceOver pass**

Send this checklist inline, complete:

1. Start the app. The loading screen appears, then the main window. The sidebar lists Convert Audio, Text to Speech, Models, Training, Voice Blender, TensorBoard, Audio Tools, Terminal, Settings and Report a bug. There is no Realtime and no Plugins entry.
2. Menu Applio: About Applio, Privacy Policy, then Hide Applio. There is no Check for Updates. Privacy Policy opens the policy page in the browser.
3. Settings: step 3 is Privacy Policy and its link opens the page.
4. Convert one file with a model you know. The result sounds as with 3.7.2.1.
5. Convert a folder with 10 or more files. The toasts and the dashboard show the batch as before.
6. Training: preprocess a small dataset, extract, train 3 epochs. Each step finishes; the dashboard shows the epochs.
7. Generate the index and convert with the new model.
8. Text to Speech: speech is generated and converted.
9. TensorBoard opens.
10. File, Set Data Location: choose a folder on the SSD, restart: the app uses it. Menu File, Open in Finder, Logs opens the right folder.

- [ ] **Step 7.21: Clean up**

From the main session, with literal paths: remove `.claude/store`, `.claude/store-build.log`, the test folder on the SSD, the data folder inside the container, and the container itself once nothing else is to be tested with this build id.

---

### Task 8: Store signing, profile, metadata, flagged string, SDK

**Goal:** The build that goes to Apple: signed with the owner's identity, with the embedded profile and the store metadata, without the `itms-services` string, and with what Apple asks of the SDK.

**Files:**
- Modify: `build_macos.py` (the PyInstaller call near line 1370, a check after it), `build_options.py` (already has `replace_flagged_scheme`), `tests/test_build_options.py`
- Owner: the App ID and profiles in the Apple developer account, the privacy policy page

**Acceptance Criteria:**
- [ ] `dist-store/Applio.app` carries `Embedded.provisionprofile`; `codesign -d --entitlements` shows the sandbox key; `codesign --verify --deep --strict` passes.
- [ ] A scan of the built executable finds `itms-services` in no module.
- [ ] The sources of `urllib.parse` and `werkzeug.urls` on disk are byte-identical to before the build.
- [ ] The main executable's `LC_BUILD_VERSION` names an SDK Apple accepts, as shown by `altool --validate-app`.
- [ ] The privacy policy URL answers with the page.

**Verify:** the commands of steps 8.5, 8.7 and 8.9.

**Steps:**

- [ ] **Step 8.1: Owner: the Apple records**

Decisions 1 and 2 answered. Then in the Apple developer account: an App ID with the owner's bundle id, with the capabilities App Sandbox and microphone; a "Mac App Store Connect" profile for distribution and a development profile for it; the "Apple Distribution" identity is on the build Mac already. The page at `PRIVACY_POLICY_URL` is published.

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

After the PyInstaller call, for store builds:

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

`import tempfile` goes with the other imports.

- [ ] **Step 8.4: Test the check on a known input**

Add to `tests/test_build_options.py`:

```python
def test_the_flagged_scheme_is_found_and_the_replacement_is_not():
    assert build_options.FLAGGED_SCHEME in b"'wss', 'itms-services']"
    assert (
        build_options.FLAGGED_SCHEME
        not in build_options.replace_flagged_scheme(b"'wss', 'itms-services']")
    )
```

- [ ] **Step 8.5: Build with the owner's identity and profile**

With the values of step 8.1 (the profile path is outside the repository; the identity is the name `security find-identity -v -p codesigning` lists):

```bash
venv_macos/bin/python build_macos.py --store --sign \
  --bundle-id "<the owner's bundle id>" \
  --identity "<Apple Development or Apple Distribution, as listed>" \
  --provisioning-profile "<path>.provisionprofile" > .claude/store-sign.log 2>&1
tail -4 .claude/store-sign.log
codesign --verify --deep --strict --verbose=2 dist-store/Applio.app 2>&1 | tail -1
security cms -D -i dist-store/Applio.app/Contents/Embedded.provisionprofile | plutil -extract Entitlements xml1 -o - - | grep -c app-sandbox
git status --porcelain
```

Expected: `BUILD COMPLETE`; `valid on disk` and `satisfies its Designated Requirement`; `1`; and `git status` shows nothing modified (the interpreter's sources are outside the repository: compare them with the backups under `build/scheme-string-backups/` by `cmp`).

- [ ] **Step 8.6: Run the signed build locally**

The build signed with "Apple Development" and the development profile must start on this Mac and pass steps 7.2, 7.4 and 7.5 with the owner's bundle id in the paths.

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

- [ ] **Step 8.9: Check the privacy page**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://froggeric.github.io/applio-macOS-native-app/privacy/
```

Expected: `200`.

- [ ] **Step 8.10: Commit**

```bash
venv_macos/bin/python -m pytest -q tests
git add build_macos.py tests/test_build_options.py
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
- [ ] The App Store Connect record has: name, bundle id, category Music, privacy policy URL, privacy "Data Not Collected", age rating, at least one macOS screenshot, review notes.
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

Add the owner as an internal tester, install from TestFlight, convert one file, start one training for two epochs.

- [ ] **Step 9.3: The record**

Name (30 characters at most), the owner's bundle id, category Music, the privacy policy URL of decision 7, privacy practices "Data Not Collected" (text sent to Microsoft's speech service is the user's own action in text to speech; say so in the notes), age rating, at least one screenshot at 1280 by 800, 1440 by 900, 2560 by 1600 or 2880 by 1800.

- [ ] **Step 9.4: Review notes**

```text
Applio converts voices with voice models that the user trains or downloads.

First launch: the app asks to download its models (about 3 GB) before it can
convert anything. Choose Download. On a normal broadband line this takes
about 10 minutes.

To try a conversion without training: Models, download one of the pretrained
voice models, then Convert Audio: choose that model, drop any audio file,
Convert.

To try training: Training, any folder with a minute of speech at 48 kHz;
preprocess, extract, train a few epochs.

The app is an open-source project (MIT licence) wrapped for macOS with
PyInstaller (Python). It runs in the App Sandbox. It has no plug-in system,
no updater and no analytics. Network use: model downloads from
huggingface.co and github.com, and text to speech through Microsoft's online
service when the user asks for it.
```

- [ ] **Step 9.5: Documentation**

`README_MACOS.md`: a section "Mac App Store edition" with what differs from the direct download. `FORK_DIFFERENCES.md`: the three store patchers. `CHANGELOG.md`: an entry under `[Unreleased]`. `CLAUDE.md`: the `--store` command, `dist-store/`, the rule that store patchers live in `patches/store/` and are re-pointed after an upstream sync. `docs/ROADMAP.md`: the store edition moves from "Later" to done, with the date.

```bash
git add README_MACOS.md FORK_DIFFERENCES.md CHANGELOG.md CLAUDE.md docs/ROADMAP.md
git commit -m "docs: the Mac App Store edition"
```

- [ ] **Step 9.6: Submission**

Only on the owner's explicit word, after TestFlight.

---

### Task 10: A process channel that works in the sandbox (optional)

**Goal:** Know whether real-time conversion can return in a later store version: pipes work in the sandbox, process queues do not.

**Files:**
- Create (local tool, git-ignored): `.claude/store/tools/pipe_channel_probe.py`

**Acceptance Criteria:**
- [ ] Under the sandboxed build, the pipe probe prints `PIPE_OK` and exits 0.
- [ ] Under the same build, the queue probe fails at `ctx.Queue()` with a permission error, which is recorded in `docs/APP_STORE_READINESS.md`.
- [ ] The result is written into the assessment (section 3), with the date.

**Verify:** the two outputs below.

**Steps:**

- [ ] **Step 1: Write the probe**

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

- [ ] **Step 2: Run it under the sandboxed build**

```bash
.claude/store/ApplioStore.app/Contents/MacOS/Applio /absolute/path/to/.claude/store/tools/pipe_channel_probe.py
```

Expected: `PIPE_OK {'from': 'worker'}` and then `QUEUE_FAILED ...`.

- [ ] **Step 3: Record it**

If both lines are as expected, a later plan can replace the three queues and two events of `rvc/realtime/worker.py` (`VoiceChangerWorker`) with pipe-based equivalents, behind a store patcher. That plan needs the worker's use of the queue methods first (`put`, `get`, `empty`, `is_set`, `set`, `wait`), which nobody has listed yet.

---

## Self-review

**Spec coverage** (each requirement of `docs/APP_STORE_READINESS.md` section 4 has a task):

- Build: sandbox entitlements, store-only patchers, store signing with profile, no notarization, no disk image, `dist-store/`: task 1 and task 8.
- Pipeline without worker processes: task 2.
- Checkpoints as data: task 3.
- Wrapper: MIME types, data in the container, no Python files in the data location, bookmarks: tasks 4 and 5.
- Interface: no plugins, updater, update check, Discord presence; download prompt; privacy link; no Realtime: task 6.
- Bundle: category, encryption key, bundle id, name and icon as inputs: task 1; flagged string: task 8; SDK: task 8.
- Verification in the sandbox: task 7. Upload and record: task 9. Real-time conversion: decision 5 and task 10.
- Decisions 1 to 8: the DECIDE list, with the build inputs that carry them.

**Placeholder scan:** no task leaves its content to be written later. The three places that depend on facts only the run shows are explicit steps with an expected and an alternative outcome: the PyObjC out-parameter form (task 5 step 4), the SDK (task 8 steps 8.7 and 8.8) and the renamed data folder (task 7 step 7.9).

**Names used consistently:** `store_edition()`, `default_data_location()`, `prepare_for_sandbox()`, `PRIVACY_POLICY_URL` (`applio_edition`); `option_problems()`, `replace_flagged_scheme()`, `FLAGGED_SCHEME` (`build_options`); `bookmark_path()`, `save_bookmark(path, store_at=None)`, `resolve_bookmark(store_at=None)` (`applio_bookmarks`); `models_are_present(path)`, `confirm_first_download(path)`, `MODEL_MARKER` (`applio_download_prompt`); `native_loop_is_available()` (`applio_native_picker`); `menu_for_edition(store_edition=False)` (`menu_spec`); `STORE_PATCHES`, `PATCH_MARKERS_STORE`, `active_patch_markers()`, `sign_app_store()`, `flagged_schemes_replaced()`, `flagged_schemes_in_bundle()` (`build_macos.py`); `read_source`, `write_source`, `patch_file`, `run`, `main` (`patches/store/store_patch_common.py`).

**Review Focus:** each line has its test or its step: 1 in task 5 and step 7.9, 2 in task 6 and step 7.7, 3 in task 2, 4 in task 1, 5 in task 5 and step 7.9.
