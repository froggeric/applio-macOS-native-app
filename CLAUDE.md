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
applio_launcher.py  # Native app entry (single-process: menu + GUI + Gradio supervisor)
core.py             # Core logic exports (inference, training, TTS)
macos_wrapper.py    # macOS native wrapper (pywebview; started by the launcher)
patches/            # Build-time patchers applied to upstream sources, then restored
menu_spec.py        # Native menu spec - one source of truth for both renderers
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
| Code signing config | `assets/entitlements.plist` |
| Fork differences | `FORK_DIFFERENCES.md` |
| Gradio web UI entry | `app.py` |
| Native app entry (dev + built app) | `applio_launcher.py` |
| Native menu definition | `menu_spec.py` |
| Core function exports | `core.py` |
| Voice conversion logic | `rvc/infer/infer.py` (VoiceConverter class) |
| Conversion pipeline | `rvc/infer/pipeline.py` (Pipeline class) |
| Training logic | `rvc/train/train.py` |
| Neural architectures | `rvc/lib/algorithm/synthesizers.py` |
| App configuration | `assets/config.json` |
| Platform setup | `rvc/lib/platform.py` |
| macOS native wrapper | `macos_wrapper.py` |
| Build configuration | `build_macos.py` (datas / HIDDEN_IMPORTS / pyinstaller_args) - **NOT `Applio.spec`** (gitignored at `.gitignore:34` and never read by the build; the build runs `PyInstaller.__main__.run(pyinstaller_args)` from `build_macos.py`). `menu_spec` and `applio_update_check` (lazy-imported) are in `HIDDEN_IMPORTS`. |

## Code Conventions

- **Formatter**: Black (auto-runs via GitHub Actions on push to main). The inherited
  `code_formatter.yml` runs black+autoflake on every push touching `*.py` and opens a
  **perpetual `formatter/main` PR** (`peter-evans/create-pull-request`, `delete-branch: true`)
  that respawns on each push until the tree is black-clean. To clear it: merge the PR (all
  reformatted files are fork-owned → no upstream-delta cost; black leaves patch-anchor strings
  in `r'''...'''` untouched), after which the workflow is a no-op guardian. PR #1 merged
  2026-08-13; its SHA is in `.git-blame-ignore-revs` (append future bulk-format commits there).
- **Import cleanup**: autoflake
- **Encoding**: UTF-8 for all file operations
- **No formal test suite** - manual testing through Gradio UI
- black 26.5.1 is pip-installed in venv_macos (since 2026-08-27): `venv_macos/bin/python -m
  black` works; older "no local black" notes are obsolete.
- pytest with a path-first argv (e.g. `pytest tests/x.py`) trips the launcher's frozen
  script-dispatch — lead with `-q` or use per-file `venv_macos/bin/python tests/x.py` runners.
- Test requests to the OWNER: always inline the complete checklist in the message (VoiceOver
  user; scrolling/back-referencing is unusable) — never "see the checklist above/earlier".

## Upstream PR Program (owner-directed, 2026-08)

- **Branches off `upstream/main`**, NEVER fork `main` (fork lags after merges; a fork-based
  diff reverses our own merged PRs). Push to `origin`, PR against IAHispano/Applio.
- **Owner gate on every PR**: draft text to `docs/upstream-prs/NN-*.md` → owner edits/reviews →
  explicit submit command. Default to `--draft`; "actually submit" means ready. Never alter the
  owner's wording (typos included). Series to date: #1270-#1281 (wiring, toasts ×4, labels,
  headings, tuple choices, i18n strings + native language names) — **ALL EIGHT MERGED, program
  complete** (#1280 merged 2026-09-11). The gradio leg (statustracker ARIA) closed
  issue-first: gradio PAUSED outside PRs (CONTRIBUTING 2ae6f97d); issue #13813 + a
  branch-pointer comment is the contribution — see
  `docs/upstream-prs/09-statustracker-aria.md` and memory track-c-gradio-aria.
- **en_US.json rule** (maintainer, learned on #1277): new user-visible strings ship WITH their
  en_US.json keys in the same PR (key=value, alphabetical; their automation syncs all locales).
- **PR-text discipline**: verify every claim against LIVE upstream (counts, cited pre-existing
  labels); no AI tells — the owner wants PRs to read human and edits them personally.
- **CRLF trap**: `tabs/inference/inference.py` is CRLF upstream — rewrites must preserve it or
  the diff explodes to whole-file.
- **Owner test builds**: `test/NN-app` branch = fork main + merge the PR branch + re-drop the
  now-redundant toast patcher (template commits 5e634319/bd9e6115); doubles as pre-sync check.
- **Headless gradio driver**: POST `/gradio_api/queue/join` BEFORE opening the SSE
  `/gradio_api/queue/data` stream; `/gradio_api/config` for component/event discovery; tuple
  dropdowns take the VALUE (raw path).
- **Quit gate for in-process inference** (a4dcae98): BOTH quit paths (menu terminate + wrapper
  X-close) detect running/cancelling conversions via the progress file and prompt; confirmed
  quit writes the cancel flag + ≤2.5 s grace; stale `cancelling` swept at startup
  (tests/test_quit_gate.py, 10 tests).
- **Diagnosis pattern**: a pybind error with an EMPTY overload list (`set_grad_enabled() … got
  (bool)`) is Py_Finalize tearing down under a live worker — a quit RACED the thread, not
  corrupt torch. Check quit timing in the log first.

## Fork Maintenance

This fork maintains minimal delta from upstream - only macOS additions, no core modifications.

**Sync with upstream:**
```bash
git remote add upstream https://github.com/IAHispano/Applio.git   # once
git fetch upstream
git merge upstream/main
```

The fork keeps macOS work in separate files, so the git merge is nearly conflict-free
(last sync 2026-09-11, 5 commits: **conflict-free, ZERO patcher re-pointing** — our PR
**#1280 merged, closing the upstream a11y program at 8/8** (tuple-choices friendly names in
inference/realtime/train/tts dropdowns); fdec9456 black format run (moved app.py's
`allowed_paths = ["logs"]` to unspaced — `patch_progress_routes`' anchor already tolerates
both, patched output verified single-kwarg); 7fa68ec2 discriminator-gradients-off during
generator-loss eval in `rvc/train/train.py`; 9b70d059 model-info fix. All 29 patch entries
applied + compiled clean (browse_buttons anchors sit on component definitions, untouched by
#1280's choices rewrite). 113/113 across 14 suites. NOTE: `tests/test_inference_progress.py`
has NO `__main__` runner — bare `venv_macos/bin/python tests/x.py` imports it silently
(exit 0, no tests run!); invoke `venv_macos/bin/python -m pytest
tests/test_inference_progress.py`. Prior sync within 3.6.4 on 2026-09-02, 20 commits:
**conflict-free** — brought in our own
upstreamed a11y PRs #1281 (i18n strings + language names), #1276 (extra job toasts), #1277
(label clarity), #1278 (section headings), plus fd7c034a multi-speaker training, #1274 rmvpe
high-register, TF32, TensorBoard/model-info/model-blend fixes, and "Update translations";
consequences: the slim `patches/patch_job_toasts.py` DELETED for good — upstream #1276 now
carries all five remaining toast surfaces (model-info's toast lives in
`tabs/extra/sections/processing.py`, NOT model_information.py) — and
`patches/patch_progress_routes.py` re-pointed because upstream 3ea5259b ships its own
`allowed_paths = ["logs"]` in app.py's launch call: the patcher now EXTENDS that list with
the fork's launch-time entries instead of injecting a second `allowed_paths` kwarg (a second
kwarg = SyntaxError "keyword argument repeated" in the patched app.py while every patcher
still exits 0 — compile the patched file, don't trust exit codes alone). No other anchors
moved; multi-speaker's rewrite of `rvc/train/train.py` + the i18n pass over
`tabs/train/train.py` left all three train.py patchers intact. Prior sync 2026-08-25:
**conflict-free** — merged our own upstreamed PRs #1270 formant-batch wiring, #1271
job-lifecycle toasts, #1275 batch-milestone toasts, a formatter run, and an upstream
preprocess int→float fix; consequence: `patches/patch_job_toasts.py` first DELETED (upstream
toasts natively in inference/tts/train/download; the patcher's anchors there missed, exit 2)
then same-day RESTORED as a slim 5-target patcher for the surfaces upstream did NOT take —
and `patches/patch_inference_progress.py` re-pointed onto upstream's post-#1275
`convert_audio_batch`: it now KEEPS upstream's `_toast` calls verbatim and injects only the
fork machinery (progress file, cancel, history, makedirs); `_infer_toast` is gone. Prior sync
3.6.3 → 3.6.4 on 2026-08-13: **conflict-free** — all 12 upstream-changed files were
pristine on the fork side, and the CLI-revamp rewrite of `core.py` left the `run_*_script` functions
our patches anchor on untouched, so all 24 patches applied with zero re-pointing; new dep `click`
pinned in `requirements_macos.txt`. Prior sync 3.6.2 → 3.6.3 on 2026-07-24 touched `.gitignore`,
`rvc/train/preprocess/preprocess.py`, and `tabs/train/train.py` on both sides; only `.gitignore`
actually conflicted.
**The real work after a merge is re-pointing build-time patches** (see "Re-pointing patches
after an upstream sync" below), because upstream rewrites the source our `patches/*.py` anchor on.

**Re-pointing patches after an upstream sync:**
- Iterate WITHOUT a full build: `build_macos.py` runs the *entire* build at module level
  (module-level `patched_files = pre_build_patch()` → PyInstaller), so **never `import build_macos`** for testing.
  Instead run each patcher directly, e.g. `venv_macos/bin/python patches/patch_X.py <arg>`,
  then `git checkout -- <source>` to restore.
- Each patcher prints `Pattern not found` / `patch failed` when upstream changed its anchor;
  re-point the regex/string to the new code, then verify the patched file `py_compile`s and the
  injected code is correctly placed before committing.
- **Patcher exit codes:** `0` = patched/already applied, `2` = anchor miss (fatal), `1` = usage
  guard (fires only when run standalone without an argument - never in the build loop).
  `pre_build_patch()` fails the build on ANY nonzero patcher exit (plus missing patcher/source
  file), listing every failure. A miss can no longer silently skip. Guarded by
  `tests/test_patcher_exit_codes.py`; `patches/download_pretraineds.py` is exempt (model
  downloader, its own invocation path).
- **Patcher indent capture:** in `patch_process_tracking.py` capture the leading indent with
  `\n+([ \t]+)` (horizontal only), NOT `(\n\s+)`. `patch_preflight_validation` runs first and
  leaves a blank line before `result = subprocess.run(...)`, so `(\n\s+)` grabs that newline and
  every injected line gets a spurious blank line. Each replacement reproduces one leading newline
  (start content on the line after `r'''`).
- **Tracking patches that switch `subprocess.run`→`Popen`/`communicate()`** (e.g. TTS): wrap in
  `try/finally` so `_untrack_process()` always runs, and use `stdout=PIPE, stderr=PIPE` +
  `communicate()` to preserve upstream's `RuntimeError(stderr)` behavior.

**Safe-to-modify files** (macOS-only, not in upstream):
- `assets/entitlements.plist`
- `patches/`, `macos_wrapper.py`, `build_macos.py`, `Applio.spec`
- `menu_spec.py`, `applio_update_check.py`, `tests/test_menu_spec.py`, `STUDIO_PRODUCTION_GUIDE.html`
- `applio_launcher.py`, `applio_inference_stats.py`, `tests/test_inference_progress.py`,
  `DEBUGGING_HISTORY.md`, `CHANGELOG.md`
- `install_applio_mac.sh`, `requirements_macos.txt`, `CLAUDE.md`
- Fork-only additions also live INSIDE `rvc/`: `rvc/lib/algorithm/generators/refinegan_legacy.py`,
  `rvc/lib/tools/applio_paths.py`, `rvc/lib/tools/process_log_parser.py` (verify any path with the
  `git ls-tree` command below).

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

**Python 3.10 vs upstream's 3.11+ stack (post-3.6.3 sync):** Upstream now pins packages
that require Python 3.11+ (numpy 2.4.6, scipy 1.18, matplotlib 3.11, pandas 2.3+). The fork
stays on 3.10 (PyInstaller), so `requirements_macos.txt` uses the latest py3.10-compatible
versions instead: **numpy 2.2.6, scipy 1.15.3, numba 0.66.0, matplotlib 3.10.9, pandas 2.2.x+**.
(pandas 2.3.x imports fine on 3.10 but needs numpy 2.x ABI - the old numpy 1.26 caused
`pandas._libs.tslibs.vectorized` failures.) If the fork ever moves to Python 3.11, these can
re-align to upstream's exact pins; that needs `brew install python@3.11` + a fresh `venv_macos`.

**Phase 2 - single-process merge (shipped in 3.6.3.7):**
The two-process launcher+wrapper was merged into ONE native process (fixed: Hide not hiding the
Gradio window; the menu swapping by which process was frontmost). Single-process is now the only
architecture; the two-process code and the `APPLIO_SINGLE_PROCESS` flag were removed in 3.6.3.7. The
app runs as one process (one dock icon, one menu, one window). **Frozen-validated** (training,
reopen, quit, menu, and dashboard all work in the built `dist/Applio.app` on Apple Silicon). The
**Process Dashboard** shows real-time metrics (best epoch/loss, current/total epoch, step, speed,
derived ETA + epoch-fraction bar), a loss-vs-epoch curve with always-on green highlights at
significant improvements, an action bar (Stop / Pause-Resume / Reveal Log / Open Log), best-epoch
durability across restart + retraining the same model, auto-show on job start, and idle-state
history browsing.
- **Run (dev):** `venv_macos/bin/python applio_launcher.py`
- **Run (built app):** `open dist/Applio.app`
- **Architecture:** the launcher calls `macos_wrapper.start_gui(launcher=self)` (import-safe - `import macos_wrapper` has zero side effects) then `webview.start(func=self._reassert_menu_and_delegate)`. pywebview clobbers `NSApp.delegate()` and wipes the main menu once at `first_show`; the func re-seats both on the main thread via `AppHelper.callAfter`. With NO `menu=` passed, pywebview does NOT re-wipe on focus (`windowDidBecomeKey_`'s `if i and i.menu` guard is False when `i.menu` is None) - verified against `venv_macos/.../webview/platforms/cocoa.py`.
- **Gotchas:** (1) `NSApplication.delegate` is a WEAK (assign) ref - REUSE `self._app_delegate` (created in `_setup_menu`); NEVER inline `ApplioAppDelegate.alloc()…` in `_reassert_menu_and_delegate` (its only Python ref would GC → dangling delegate → crash on next reopen/quit). (2) `on_window_closing` runs on the MAIN thread - quit via `AppHelper.callAfter(lambda: NSApp.terminate_(None))`, NEVER synchronous (the ≤5 s `killpg`-wait would block the close event + re-enter AppKit → spinning cursor); `_user_confirmed_quit` (set before the deferred terminate) prevents the double-prompt. (3) The Gradio supervisor `_supervised_backend` (N=3, linear backoff) wraps `start_backend`, which RAISES on failure; `OSError` (e.g. EADDRINUSE) fails fast; `exc_info=True` keeps the traceback. (4) `setup_logging` is ADDITIVE (no `removeHandler`, no `sys.stdout`/`stderr` reassign) so launcher logs reach `applio_launcher.log`. (5) A hard GUI crash (segfault) is unrecoverable - accepted tradeoff; training checkpoints + `active_processes.json` mitigate data loss.
- **DEV can't run training/dataset scripts** - they resolve to `~/Applio/rvc/train/*` (data dir), not the repo → `No such file`. Training works only in the FROZEN build (scripts bundled, resolved via `_MEIPASS`). Validate training on `dist/Applio.app`, not dev.
- **Dev hides Gradio/training stdout** - a "generic error" in the UI is invisible in the log. Read the background-launch task's stdout file (`/private/tmp/.../tasks/<id>.output`) or run in a foreground terminal.

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
- macOS has no `timeout` command - use `gtimeout` (coreutils) or background-launch + poll; never bare `timeout N` in a run/test command.

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

**CRITICAL: Build environment:**
- MUST run `build_macos.py` from within `venv_macos` - running outside produces broken app
- Outside venv: PyObjC not bundled → runtime error "AppHelper is not defined"
- Outside venv: "Hidden import 'xxx' not found" warnings for torch, gradio, etc.
- Setup: `/opt/homebrew/bin/brew install python@3.10` then `/opt/homebrew/bin/python3.10 -m venv venv_macos`

**Debugging Frozen Apps:**
- Use file-based logging (`/tmp/applio_debug.txt`) for code that runs before stdout capture
- **Silent exception handling:** In multiprocessing spawn mode, stdout is lost. Use file-based logging (e.g., `~/Library/Logs/Applio/extraction_errors.log`)
- Check `DEBUGGING_HISTORY.md` for documented debugging sessions and solutions
- After fixes, verify build timestamp is AFTER commit timestamp: `stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio`
- All fixes must go through `patches/` - NEVER modify upstream files directly
- **After patching, verify `git status` shows no upstream files have patch markers.** If present, restore with `git checkout` before committing.
- When stuck after 3+ fix attempts: STOP and question the architecture (per systematic-debugging skill)
- **Launch `macos_wrapper.py` from a foreground terminal**, not `nohup ... &` - pywebview's
  AppKit event loop needs an interactive GUI session and blocks/idles when backgrounded.
- **Local `rvc/models` must NOT be deleted.** The default `build_macos.py` is a *lite*
  build: `clean_bundled_models()` strips model weights from `dist/Applio.app` (the bundle
  only - shipped app stays ~1.6GB) and never touches the local filesystem. So keeping the
  ~1.8G of models in gitignored `rvc/models/` does NOT bloat the shipped app, and `rm -rf
  rvc/models/*` only forces a costly ~2G re-download. Leave local models in place; the
  bundle is re-stripped on every build. (A model-bundled build is `--models-installer`, a
  separate app - there is no CLI flag to bundle models into the main app; `--lite` is
  `store_true, default=True`, i.e. always on.)
- **Corrupted `venv_macos` package:** if `import torch`/`pandas` fails with a partial-init /
  circular-import error, the installed wheel is corrupt → fix with
  `venv_macos/bin/python -m pip install --force-reinstall --no-deps <pkg>`.
- **Frozen subprocess CWD is the bundle (`sys._MEIPASS`/Frameworks), not the data dir**,
  so `os.getcwd()`/`now_dir`-relative paths break. Resolve user/data paths absolutely:
  `APPLIO_DATA_PATH` env → `runtime_paths.json` `data_path` → `~/Applio`.
- **`logging.basicConfig` is a no-op once an earlier import configured the root logger** →
  launcher/wrapper logs silently lost. Own the root logger: clear handlers + add a `FileHandler`
  explicitly (see `applio_launcher.py` logging setup, `macos_wrapper.py:setup_logging`).
- **`core.py`'s `from datetime import datetime` rebinds `datetime` to the class**, so injected
  `datetime.datetime.now()` in patches throws `AttributeError`. In patches use
  `import datetime as <alias>` + `<alias>.datetime.now()`.
- **`os._exit(N)` skips stdout flushing** - a preceding diagnostic `print` is lost (e.g.
  `rvc/train/train.py` sample-rate error). Recover via a line-buffered tee (`open(...,buffering=1)`)
  or `PYTHONUNBUFFERED=1`.
- **Post-training SIGTERM**: `rvc/train/train.py` ends with `os._exit(...)` which orphans its persistent DataLoader workers; their teardown signals the launcher's process group (session leader via `setsid`) -> spurious SIGTERM. In single-process, `_handle_terminate` ignores SIGTERM (Cmd+Q still quits via `applicationShouldTerminate_`).
- **Frozen module importability**: modules NOT in PyInstaller's traced graph (e.g. `rvc.lib.tools.process_log_parser` - nothing imports it) ship as DATA in `Contents/Resources`, NOT importable modules in `Contents/Frameworks`. A `from rvc... import ...` works in dev, fails (ImportError) frozen. Inline what you need into fork-owned code, or add to HIDDEN_IMPORTS. Check: `find dist/Applio.app/Contents/Frameworks -path "*<module>*"` (absent = not importable).
- **Reproduce frozen-subprocess behavior without the GUI:** `dist/Applio.app/Contents/MacOS/Applio
  /tmp/script.py args` - entry `applio_launcher.py` dispatches to the script (CWD=bundle).
- `ps -E -p <pid>` (macOS) dumps a frozen process's env - check inherited `APPLIO_*`/`PATH`.

**Build process gotchas:**
- Single entitlements file: `assets/entitlements.plist` (the old `scripts/entitlements_dev_id.plist` was deleted - it had drifted). Signing/notarization is built into `build_macos.py --sign --notarize --dmg` (the standalone `scripts/*.sh` were removed).
- No microphone entitlement needed - pywebview wrapper doesn't capture audio; Gradio handles it via browser
- **Patcher escape sequences:** In triple-quoted strings, `\\n` produces literal newline. Use `chr(10)` for newlines in patched code.
- Patches in `patches/` are applied to source files before PyInstaller, then source files are restored to pristine state
- **`post_build_restore` reliably leaves `tabs/train/train.py` dirty** (3 patchers touch it: dataset_paths, train_44100, browse_buttons). After EVERY build run `git checkout -- assets core.py rvc tabs`; never commit it patched
- PyInstaller cleans `dist/` at start - never delete while builds running
- Before `rm -rf dist build`: no `Applio` process may run from `dist/` (it holds file handles, so `rm` fails with "Directory not empty"). Quit it (`osascript -e 'tell application "Applio" to quit'`) + `sleep 3` first
- Build size: ~1.6GB lite (post-3.6.3 dependency stack; ~2GB models download on first launch)
- **Smoke = cert-free** `venv_macos/bin/python build_macos.py` (no flags; ad-hoc, runs locally) validates functionality; reserve `--sign --notarize --dmg` for the actual release
- Signing requires handling broken symlinks (use `path.exists()` before `rglob`)
- PyInstaller cache corruption: clear `~/Library/Application Support/pyinstaller/`
- **Signing & notarization (working):** `venv_macos/bin/python build_macos.py --sign --notarize --dmg`
  produces a notarized+stapled `.app` and `.dmg`. Auth = `--keychain-profile applio-notarize`
  (App Store Connect **Team Key**, **App Manager** role - stored via
  `xcrun notarytool store-credentials`). Pipeline: inside-out Mach-O sign (leaf binaries get
  `--options runtime --timestamp` only; entitlements only on the outer bundle) → notarize `.app`
  (ditto zip) → staple `.app` → build+sign `.dmg` (`--timestamp`) → notarize `.dmg` → staple `.dmg`.
  `CFBundleVersion` must be ≤3 numeric segments (derived `3060305`-style integer, NOT the 4-segment
  display VERSION). A stapled artifact should not need `xattr -cr` from end users. **Validated
  end-to-end 2026-07-26** - `v3.6.3.5` is the first notarized release (both `.app` + `.dmg` pass
  `spctl`/`stapler validate` as `Notarized Developer ID`). Cut a release: `build_macos.py --sign
  --notarize --dmg` → commit/push → `git tag v<VERSION>` → `gh release create v<VERSION>
  dist/Applio-<VERSION>.dmg` (if `gh release` 403s on scope, use `gh api` to create + `curl` to upload
  the asset - see "GitHub releases" below).
- **CI signing:** `.github/workflows/release-macos.yml` (tag `v*` → build+sign+notarize+staple, attaches
  the DMG to the release) and `ci-macos.yml` (build-only, path-filtered, no cert). The release job runs
  in a protected `signing` **environment** and uses inline API-key auth (`build_macos.py --api-key …
  --api-key-id … --api-issuer …` - no keychain on the runner; the `--keychain-profile` path is for
  local). Secrets in the `signing` env: `MACOS_CERTIFICATE` (base64 .p12), `MACOS_CERTIFICATE_PWD`,
  `APP_STORE_CONNECT_KEY` (base64 .p8), `APP_STORE_CONNECT_KEY_ID`, `APP_STORE_CONNECT_ISSUER`. These
  are GitHub-side settings - a human must create the env + secrets; can't be done from code. macOS
  runners bill at ~10× and are metered even on public repos, hence the path-filtering + tag-only triggers.
  **Validated end-to-end 2026-07-27** (test tag → green run → notarized DMG auto-attached to the release;
  ~15 min). Each release run PAUSES for manual approval (required reviewers on the `signing` env);
  approve via Actions UI → *Review deployments* → `signing` → *Approve and deploy*; can't be done from code.
- **DMG symlink trap:** `create_dmg` MUST use `shutil.copytree(..., symlinks=True)`. Python.framework
  uses symlinks (`Python -> Versions/Current/Python`, `Resources -> Versions/Current/Resources`,
  `Current -> Versions/3.x`); the default `symlinks=False` flattens them into real files, breaking
  the framework's signature seal → the DMG notarization is rejected with "The signature of the binary
  is invalid" on the Python framework paths (the `.app` zip notarization still passes - only the DMG
  copy breaks). Staple the `.app` before building the DMG.
- **Mach-O detection must use bytes mode:** `file -b <path>` can emit non-UTF-8 bytes → `subprocess.run(text=True)`
  raises UnicodeDecodeError mid-sign. Use `capture_output=True` (no `text=True`) and test `b"Mach-O" in r.stdout`.
- **Verifying a notarized DMG:** `spctl --assess --type execute <dmg>` reports "rejected (…does not seem to be an
  app)" / "Insufficient Context" - expected for a disk image. The authoritative DMG check is
  `xcrun stapler validate <dmg>` → "The validate action worked!". (`.app` uses spctl; `.dmg` uses stapler.)
  Applied in `_final_verify`: the `.app` is gated on spctl/codesign/stapler, the `.dmg` ONLY on stapler
  validate - do NOT regress to gating the DMG on spctl (it hard-fails the whole build on a valid DMG;
  this exact bug shipped once and was caught by the CI release test).
- **Background build exit codes:** don't end a backgrounded build with `; echo "exit=$?"` - the task reports the
  LAST command's exit (the echo = 0), masking a failed build. Make the build the final command and read its real
  exit/output (`tail` the output file, check for `BUILD COMPLETE` / hard-fail markers).
- **Cert-free gates for signing changes:** a plain `build_macos.py` run (no `--sign`) is safe (`--help`/`py_compile`
  exit before the module-level build) and verifies `CFBundleVersion` in the built Info.plist + git-cleanliness
  without the cert; unit-test Mach-O detection by copying the fn to a temp script (`import build_macos` runs the build).
- **GHA macOS runners have no `rg`:** use `grep -E`/`grep -Eq` in workflow steps (a `rg -q` in
  `ci-macos.yml` once failed the run with "command not found"; locally `rg` exists, so this is CI-only).
- **Monitoring a CI run:** `gh run watch <id> -R froggeric/applio-macOS-native-app --exit-status`
  (make it the LAST command - a trailing `echo` masks its real exit). `status=waiting` = the `signing`
  environment's required-reviewer gate (approve in the Actions UI, not from code); `status=queued` =
  waiting for a runner. `gh run view <id> --log-failed` pulls the failed step's output.
- **Testing `release-macos.yml`:** push a throwaway tag (`git tag vX-citest && git push --tags`),
  approve the run, confirm, then tear down with `gh release delete vX-citest --cleanup-tag -y` (unlike
  `gh release create`, `gh release delete` needs no workflow scope). Don't use a real version tag for tests.
- **Upstream 3.6.3 changed `subprocess.run` calls:** upstream now assigns
  `result = subprocess.run(...)` and adds `if result.returncode != 0: return ...` after each.
  Patches that anchored on bare `subprocess.run(command)\n return f"..."` must be re-pointed to
  the new shape. In the 2026-07-24 sync this broke `patch_process_tracking` (5 sub-fns),
  `patch_subprocess_validation` (2), and `patch_preflight_validation`; `patch_loading_html` also
  needed type `"dir"` (not `"file"`) so `patch_all()` resolves the path. `patch_preprocess_warning`
  was removed as obsolete (upstream now handles empty datasets).

**Pywebview gotchas:**
- Menu callbacks need lambda wrappers: `MenuAction("About", lambda: show_about_dialog())` not `MenuAction("About", show_about_dialog)`
- **Menu is spec-driven (`menu_spec.py`):** ONE source of truth rendered by both processes. The launcher renders the full dynamic menu (PyObjC); the standalone wrapper renders a STATIC subset (pywebview `Menu`/`MenuAction` are immutable and cannot bind shortcuts - `venv_macos/.../webview/menu.py`). Standalone renderer MUST: title the app menu `__app__` (NOT "Applio" - that duplicates it), set `webview.settings['SHOW_DEFAULT_MENUS']=False` BEFORE `webview.start` (else pywebview auto-adds View/Edit; note: `webview.start` has NO `webview_settings` kwarg - use `webview.settings[...]`), and omit `app.about/hide/hide_others/quit` from its `__app__` payload (pywebview's unconditional `_add_app_menu` injects them). Verify with `venv_macos/bin/python tests/test_menu_spec.py`.
- **Update-check version compare must use `packaging.version`** (already a hiddenimport). The old `check_for_updates` used string `!=` (flagged downgrades as updates). Shared logic lives in `applio_update_check.py`; the manual item + a silent launch-time check both use it; network runs off the main thread (NSAutoreleasePool on the worker thread).

**Native macOS dialogs (PyObjC):**
- All dialogs use native NSAlert/NSWindow/NSPanel instead of pywebview HTML
- CRITICAL: Event loop choice matters - `AppHelper.runEventLoop()` for GUI apps with windows, NOT `runConsoleEventLoop()` (console tools only - causes window freeze)
- NSAlert for confirmations, NSWindow for complex UIs, NSPanel for utility windows
- Dialog classes: `ProgressWindowController`, `ProcessDashboardController` in `applio_launcher.py` (About is a plain NSAlert via `_show_about_alert`; no AboutWindowController exists)
- CRITICAL: PyObjC method names - `method:with:param:` becomes `method_with_param_` (colons→underscores, append trailing underscore), e.g., `systemFontOfSize:weight:` → `systemFontOfSize_weight_` NOT `systemFontOfSize_ofWeight_`
- CRITICAL: NSBox doesn't have `setFillColor_()` in PyObjC - use bordered style or layer-based background instead
- `addSubview:positioned:relativeTo:` → `addSubview_positioned_relativeTo_` (NOT `addSubview_positioned_relative_`)
- CRITICAL: any class used as an NSWindow/NSTableView delegate, dataSource, or NSNotificationCenter observer MUST be an NSObject subclass (`class X(NSObject)` + `alloc().initWith…_()` + `objc.super(X, self).init()`) - a plain Python class crashes on `conformsToProtocol:` (ProcessDashboardController hit this). Same pattern as MenuActionHandler/ApplioAppDelegate.
- PyObjC NSTrackingArea in a frozen app: `NSTrackingActiveInActiveApp` may NOT deliver `mouseMovedWithEvent_` (the frozen app's "active" state is unreliable). Use `NSTrackingActiveAlways` + `window.setAcceptsMouseMovedEvents_(True)` for reliable hover/tracking on a custom NSView.
- PyObjC preserves ObjC selector case - `-[NSColor CGColor]` is `.CGColor()`, not `.cgColor()`. Verify a name imports (`python -c "from AppKit import X"`) BEFORE adding it to the `try/except`-wrapped top-level AppKit import (L72-89) - a bad name silently flips `NATIVE_APIS_AVAILABLE=False` app-wide.

**Progress window responsiveness:**
- Timer must be started AFTER background thread: call `_start_timer()` after `_start_file_thread()`
- Initial log read limited to last 50 lines (not entire file) to prevent queue flooding
- Window needs `activateIgnoringOtherApps_(True)` to receive mouse/keyboard events
- Text buffer limited to 100 lines with batch updates to prevent UI slowdown
- CRITICAL: Never use bare `except:` in queue processing - use `except queue.Empty:` to catch empty queue; bare except silently swallows AttributeError from typos, hiding real bugs

**Smart log display:**
- Live zone shows active tqdm progress in single line (not spam of hundreds of lines)
- Log zone shows only phase transitions, errors, and completions
- Phase completion includes duration (e.g., "[14:32:15] Preprocessing complete (2m 35s)")
- tqdm detection: regex `^\s*\d+%\|.*\|\s*\d+/\d+\s*\[` matches progress bar lines
- Phase detection: strips timestamps, matches "Starting X", "Xing", "X started" patterns
- 2-second timeout without tqdm activity triggers phase completion logging

**Rich Status Card:**
- Phase icon + name (📁 Preprocessing, 🔬 Feature extraction, 🎯 Training, 🎵 Inference, 🗣️ TTS)
- Visual progress bar with Unicode blocks (████░░░) + percentage
- Stats grid: Speed, ETA, Phase Time, Items

**Log syntax highlighting:**
- Timestamps in gray
- Phase starts (→) in blue
- Completions (✓) in green
- Errors (✗) in red
- Warnings (⚠) in orange
- Epoch milestones (◆) in purple
- Monospace font (Menlo 11pt)

**Status badge:**
- Pill-shaped, color-coded: Running (green), Paused (orange), Completed (blue), Error (red)

**Patch idempotency pattern:**
- Each patch function must check for its OWN specific marker (e.g., `if '_track_process("training"' in content`)
- DO NOT use a shared `IDEMPOTENCY_MARKER` check that returns early - this prevents actual patches from being applied

- **"dir" type patchers:** base_path is the directory containing the source file, use `os.path.join(base_path, "filename.py")` not the full path
- **runtime_paths.json keys:** Uses `data_path` for the data directory (not `base_path`)

**Version management:**
- Upstream renamed `assets/config.json` → `assets/config_template.json` (3.6.3) and now
  **gitignores `config.json`**; `app.py` creates `config.json` at runtime by copying the template.
- Check upstream version: `git show upstream/main:assets/config_template.json | grep version`
- At **build time** the template is the source of truth (`config.json` is gitignored + locally
  regenerated), so `build_macos.py` and `patches/patch_loading_html.py` read `config_template.json`
  FIRST, then fall back to `config.json` (reading config.json first would embed a stale dev-local
  version). Runtime reads of `config.json` elsewhere are fine (app regenerates it).
- `macos_wrapper.py` copies the bundled template out as `config.json` for the running app.
- `macos_wrapper.py` reads VERSION dynamically from the config + BUILD_NUMBER
- `build_macos.py` uses same source - both must stay in sync
- `patch_loading_html.py` reads from the config for loading screen version

**Background process tracking:**
- State file: `~/.applio/active_processes.json` (single source of truth)
- Process types: training, preprocess, extract, tts (inference is in-process and tracked separately - see below)
- POSIX signals: SIGSTOP (pause), SIGCONT (resume), SIGTERM (terminate)
- Patch order: `patch_process_tracking.py` runs before `patch_subprocess_validation.py`.
  After the 3.6.3 rework, `subprocess_validation` anchors on the success-`return` line (which
  survives process_tracking's Popen transformation), so it injects only its post-run output
  validation (model_info.json / extracted-dir checks) - both patches now coexist on the same
  functions instead of being mutually exclusive.

**Batch-inference progress tracking (3.6.3.7):** inference runs IN-PROCESS (not a subprocess), so it
is NOT in `active_processes.json`. Tracked separately:
- `patches/patch_inference_progress.py` injects into `rvc/infer/infer.py:convert_audio_batch` to write
  `~/Applio/.applio/inference_progress.json` (single writer, atomic temp+`os.replace`, no lock) +
  check a cancel flag per file + append a schema-compatible history entry; it also
  `os.makedirs(audio_output_path, exist_ok=True)` (batch inference failed with an opaque soundfile
  "System error" on a missing output folder).
- `patches/patch_stop_infer.py` rewrites `stop_infer` to write `~/Applio/.applio/inference_cancel.flag`
  (cooperative) - the old PID-kill killed the whole app because the inference PID == the app PID in
  single-process.
- The dashboard synthesizes an `_is_inference` proc into `_active_processes` from the progress file
  (`_synthesize_inference_proc` in `applio_launcher.py`, at BOTH `update_process_list` +
  `refresh_process_list`); the stats math lives in the AppKit-free `applio_inference_stats.py`
  (pytest-importable). `_render_inference_detail` normalizes the history schema (ISO started_at /
  completed_at to epoch) so completed runs show counts/duration. `_sweep_stale_inference_progress`
  marks a stale `running` record `interrupted` on startup.

**Accessibility (a11y) Phase 2 — web payload, native pickers, settings, i18n:**
Phase 1 (native announcements, badge, Edit menu, live-jobs submenu) lives in `applio_a11y.py` +
`applio_launcher.py` (see CHANGELOG [Unreleased]). Phase 2 extends a11y INTO the Gradio web UI.
Fork-owned modules (all lazy-importing AppKit or nothing; all in HIDDEN_IMPORTS):
- `applio_progress_api.py` — serves `GET /applio-a11y/progress` (FastAPI route registered on the
  gradio app by `patches/patch_progress_routes.py`): live jobs + metrics (training log tails parsed
  via `rvc.lib.tools.process_log_parser`; inference stats via `applio_inference_stats`), history-derived
  terminal words, and an a11y-settings echo. AppKit-free; the LAUNCHER pushes state in
  (`set_settings`/`set_layout_changed_callback`; 4c: `set_announce_owner` unused by the launcher). The launcher runs as `__main__`
  (frozen entry AND dev), so launcher resolution is `sys.modules.get("applio_launcher")` with a
  `__main__` fallback — a plain `get()` always misses.
- `assets/applio_a11y.js` — injected at build time by `patches/patch_web_a11y_payload.py`, which
  swaps upstream `app.py`'s inline `js=` entry for a `_applio_a11y_js(client_mode)` helper reading
  the file from `now_dir`/`sys._MEIPASS` (ships via the `("assets","assets")` datas). Creates a
  live region + "Last result" region client-side, polls the route every 2 s, announces job
  milestones/terminals, heals accordion/tab semantics (selectors pinned against gradio 6.20.0), restores focus after gradio re-renders, and records output-textbox changes in the
  "Last result" region (visible-ONLY since Phase 4e — output-change speech removed; one joined
  `announce()` per poll is the payload's only speaker).
- `applio_native_picker.py` — `native_browse(mode)` opens NSOpenPanel via `AppHelper.callAfter`
  (gradio handlers run on worker threads; the panel MUST run on the main AppKit thread; the worker
  blocks on an Event). Availability is an EXPLICIT `mark_native_loop_available()` flag set by the
  launcher — "NSApp is None" CANNOT detect headless (PyObjC materializes a non-None proxy), so
  without the flag dev/tests return `("unavailable", None)` immediately instead of hanging 600 s.
- `applio_browse_ui.py` — `browse_button(mode, target, elem_id)` factory; `patches/patch_browse_buttons.py`
  injects a "Browse…" button after each of 13 path fields across 6 tab files (train ×3, inference ×3,
  tts ×3, realtime ×1, voice_blender ×2, processing ×1 — see its `FIELDS`). Handler runs the native
  picker, writes the path into the field, and `expanduser()`s BOTH the picked path and a typed value
  passing through. Picker-unavailable (external browser) explains itself via `gr.Info` (announced toast).
- `applio_i18n.py` — AppKit-free translator for native-side strings (menu/picker/announcements).
  Keys are the English text; an OPTIONAL fork-owned `assets/applio_i18n_overrides.json`
  (`{locale: {key: tr}}`) layers over upstream locale files, which stay pristine.
- **Per-request announce-owner rule (kept for API completeness):** the payload's `announce.owner`
  is `"native"` only when the global owner is native AND the request carries `client=native` (the
  JS sends it when `window.pywebview` exists — i.e. the in-app WKWebView); any other client
  (external browser at the same port) gets `"web"` and the JS announces. Since Phase 4c NO
  launcher path sets the global owner "native" (the window-level AX engine is deleted), so in
  practice every client gets `"web"` — the rule stays so external/API clients keep a well-defined
  payload and the route remains per-request, not a static flag.
- **`prevent_thread_lock` flip:** `patch_progress_routes.py` flips upstream `app.py`'s
  `launch(prevent_thread_lock=client_mode)` to `True` so `launch()` returns the FastAPI app and the
  routes can be registered, then (when not client_mode) parks the calling thread in a
  `while True: sleep(5)` — `launch_gradio()` still never returns (the supervisor's contract).
  Everything after the launch call — including the TensorBoard proxy — stays DEAD in normal mode
  (status quo). Bind failures still raise on the calling thread (gradio raises before the thread
  lock matters), so the supervisor's OSError fail-fast is preserved.
- **a11y settings — AUTOMATIC since Phase 4c (2026-08-23, `6efb07e9`):** NO settings UI; the
  Phase 2/4 Accessibility submenu (menu_spec `a11y.*` keys + launcher dispatch + refresher) is
  REMOVED (`test_menu_spec` guards against its return). Speech is VOICEOVER-GATED:
  `effective_speech(override, vo)` is recomputed on each 2-s heartbeat from the HIDDEN
  NSUserDefaults (`com.iahispano.applio`) key `a11y.speech` (`auto` default / `on` / `off`) and
  pushed to the web payload via `applio_progress_api.set_settings` on change (module pre-push
  default is silent; launcher startup replaces it). Sound cues fire for EVERYONE on
  terminal events (hidden `a11y.sound_cues` bool, default ON). The window-level NSAccessibility
  post path + `announce_mode` are DELETED — the web live region is the only speech channel;
  `_a11y_post` is terminal-only (dock attention + sound + the `[A11y] terminal post` diagnostic),
  and the dashboard selection announcement is VO-gated.
- **Patcher order note:** the two `app.py` patchers (`patch_progress_routes`, `patch_web_a11y_payload`)
  anchor on DISJOINT text (the `prevent_thread_lock=` kwarg line + TensorBoard import vs the
  `"js": (` entry + `def launch_gradio(`) and are order-independent; `patch_browse_buttons`'s
  insertions collide with none of the other `tabs/train/train.py` patchers. Tests:
  `tests/test_applio_a11y.py`, `test_native_picker.py`, `test_browse_ui.py`, `test_progress_api.py`,
  `test_patch_fixtures.py`, `test_applio_i18n.py`, `test_a11y_js_invariants.py` (Phase 3: payload-JS
  invariants), `test_patcher_exit_codes.py` (Phase 3: patcher exit-code contract),
  `test_menu_jobs.py` (Phase 4: live menu titles), `test_dashboard_ax.py` (Phase 4: dashboard AX
  summaries), `test_a11y_auto_speech.py` (Phase 4c: `effective_speech` + hidden-keys plumbing),
  `test_quit_gate.py` (quit-gate for in-process inference) —
  suite counts after Phase 4e: `test_menu_spec.py` 14 (incl. the a11y-submenu-GONE guard),
  `test_progress_api.py` 13 (echo without announce_mode + scope forwarding),
  `test_a11y_js_invariants.py` 5 (scope-aware jobLabel, output-change-speech-removed, one
  combined `announce()` per poll), `test_dashboard_ax.py` 7 (row AX summaries + 4e
  `_row_display_text` cell-text metrics incl. the ≤80-char truncation), `test_a11y_auto_speech.py`
  6 (`effective_speech` + hidden-keys plumbing + the afplay chime runner).
- **Deferred to Phase 3:** error surfacing with full log tails (terminal announcements carry status
  words; full tails need upstream `gr.Error` routing); typed-path on-change validation for the
  remaining fields (Browse's `expanduser` is the partial Phase 2 fix); upstream Applio + gradio PRs
  for the semantic gaps found in audit §5 [U]/§6 (repo `docs/superpowers/plans/` a11y audit).

**Accessibility (a11y) Phase 3 — fork-local hardening (shipped 2026-08-22, `feat/a11y-phase3`):**
Seven review-driven fixes, all fork-side, each with tests: `applio_i18n` locale matching mirrors
upstream's prefix-glob semantics + guards corrupt language JSONs (`cfa2b955`); `healRecordToggles`
in `assets/applio_a11y.js` scoped to the realtime record accordion via `#browse-record_audio_path`
(`3cc24700`); ONE shared `terminal_words_from_history` helper — `applio_progress_api._collect_words`
and the launcher's `_a11y_terminal_words` both delegate (`cb745b53`); bounded failure log tails in
the web payload (`payload.errors`, ≤2 entries, 1200-char tails) appended to the JS "Last result"
region, spoken announcements unchanged (`4bf27536`); blur-time path validation on all 13 Browse
fields (`attach_path_validation` in `applio_browse_ui.py`, `gr.Warning` announced toasts)
(`e636927c`); the remaining native English clusters i18n-wrapped (loading stages + headings +
technical_details, dashboard statuses, About alert, status-title maps; `62a511e4` + `26385528`);
patcher anchor-miss exit codes (`b5d036bd` — convention documented at "Patcher exit codes" above).
The first two deferrals listed above (log tails, typed-path validation) are thereby delivered
fork-side; full-tail routing via upstream `gr.Error` stays with the upstream program. The upstream
Applio + gradio PR program is DEFERRED to its own plan until the manual VoiceOver pass comes back
clean (audit §7 checklist step 4 bisect still pending) — owner's gate: "no PR until we have
everything 100% test, verified, and confirmed working with 0 regression bug."

**Accessibility (a11y) Phase 4 — VoiceOver-pass fixes (shipped 2026-08-22, `feat/a11y-phase4`):**
The five 2026-08-22 manual-pass findings (audit §7, resolutions + re-test checklist there) fixed
fork-side. **Announce mode Auto (Phase 4; SUPERSEDED by Phase 4c automatic speech):** in-app
speech routed through the WEB live region — `_a11y_post` skipped the window-level
NSAccessibility post (unheard when the VO cursor is in web content) but kept dock attention,
sound cues, and `[A11y]` log lines; "Native (experimental)" opted back into the old engine.
Phase 4c (2026-08-23, `6efb07e9`) made this AUTOMATIC and deleted the toggle: the
`a11y.announce.*` menu keys, the `a11y.announce_mode` defaults key, `_apply_announce_mode`, and
the window-level AX post path are GONE (`set_announce_owner` remains in `applio_progress_api`
for API completeness); speech is VO-gated per the Phase 2 a11y-settings bullet above.
**Batch-toast split rule (Phase 4b wave, 2026-08-22/23; TAB side retired by the 2026-08-25
upstream merge of #1271/#1275 — the paragraph below is kept as history):** TAB-side toasts
(`patches/patch_job_toasts.py`, registered as 9 dir-type tuples — inference.py, tts.py, train.py,
download.py, voice_blender.py, plugins.py, realtime.py, processing.py (model info), tensorboard.py)
coverED single-file inference, tts (start/finish/error), train start + TERMINAL (owner ruling
2026-08-22: `run_train_script` blocks the handler thread for hours, so toasting its return
announces completion), preprocess/extract/download wrappers (error|failed predicate), blender mix
+ both drop confirmations, plugins start/error (finish is upstream's own gr.Info),
realtime start/failure (GENERATOR wrapper scanning yielded statuses — broadened predicate:
error/failed/stopping/aborting/"please select"/"not provided"; benign yields silent), model-info
finish, and TensorBoard ready — jobs whose mid-run progress the tab thread cannot see.
The 2026-08-25 sync slimmed the patcher to those five targets: upstream #1271 now carries the
inference/tts/train/download toasts natively (the patcher's anchors there missed → build-fatal
exit 2; re-adding them would double-toast), so voice_blender (blend mix + both drop
confirmations), plugins (start/error), realtime (start/failure, broadened yield predicate),
model-info (finish) and tensorboard (ready) remainED fork-patched — pending the Track B
upstream PR. The 2026-09-02 sync DELETED the slim patcher for good (template commits
5e634319/bd9e6115): upstream #1276 took all five surfaces natively (model-info's toast lives
in `tabs/extra/sections/processing.py`); `test_patch_fixtures` is 5, the voice_blender CASES
entry is gone from `test_patcher_exit_codes`, and `tabs/train/train.py` was never re-added as
a target (its patcher count stays 3: dataset_paths, train_44100, browse_buttons).
ENGINE-side toasts: since the same merge, upstream #1275 provides them natively
(module-level `_toast`, lazy gradio import) and the re-pointed
`patches/patch_inference_progress.py` KEEPS those calls verbatim — batch start / 25-50-75 % milestones (total≥8,
threshold-FIRST-crossing; terminal suppresses the 100 % milestone) / terminal (counts+elapsed) +
errors at BOTH raise sites (incl. the concurrent-run RuntimeError, which fires BEFORE the try).
SINGLE conversions are ALSO tracked engine-side (Phase 4b): `_infer_single_begin/_infer_single_end`
wrap `convert_audio`'s body (endpoints: after `get_vc`, before the `elapsed_time` tail) writing
`scope: "single"` records + history rows into `inference_progress.json` — SSE-independent (the
built app's single-inference silence; see audit §7 Phase 4b wave); batch guard = an existing
running/cancelling record with `scope != "single"` skips ALL single writes, which also no-ops the
batch loop's per-file `convert_audio` calls. `patch_progress_routes.py` additionally injects
`allowed_paths=[expanduser("~"), APPLIO_DATA_PATH]` (launch-time, `if p`-filtered — a raw None
would stringify to a bogus `<cwd>/None` entry in gradio's abspath, not crash) into the launch
kwargs; WITHOUT it the FROZEN app's converted outputs never load in the UI (gradio serves only
cwd+temp; frozen cwd is the bundle → InvalidPathError in postprocess). **Frozen-safe enrichment
rule:** launcher-side metrics use `_last_training_metrics` (seek-tail + backwards
`_parse_training_log_line`) and `applio_inference_stats` (bundled) — NEVER
`applio_progress_api.enrich_jobs`, which imports `rvc.lib.tools.process_log_parser` (ships only as
a DATA file in the frozen bundle, not importable from the launcher). Menu: `_merged_live_procs` is
the ONE merge (subprocess jobs + synthesized inference batch) for the menu AND both dashboard merge
sites; `_menu_job_title` renders live titles (name capped 30 chars, line 64); the submenu
skip-rebuild guard requires titles unchanged AND parent isEnabled() (a titles-only skip leaves the
status parent disabled from the static spec). Dashboard AX: module-level
`_row_ax_summary`/`_chart_ax_summary` + a DUAL row hook (the guaranteed `willDisplayCell` path
stamps what the delegate hook can miss), template progress values ("Epoch N of M, P percent") +
indeterminate-bar fix, key-view loop (process_table → stop → pause → reveal → open → back), and a
selection announcement (VO-gated since Phase 4c). **Phase 4d/4e (round-2/3 fixes, `a4c9163b` +
`0cf8b0a7`):** the terminal sound cue plays via `/usr/bin/afplay` on the REGULAR output channel
(Basso on failure / Glass on success — NSSound honors the muted alert-volume slider), then was
PARKED per owner ("forget about the chimes": code stays, no further testing); output-change
SPEECH is removed entirely (the JS Last-result region is visible-only; one joined `announce()`
per poll is the payload's only speaker — the jobsRunning gate and its lag windows are gone);
and dashboard ACTIVE rows carry their metrics in the visible cell text (`_row_display_text`,
≤80 chars, reusing `_row_ax_summary`; history rows byte-unchanged) because VoiceOver does not
reliably speak a row view's accessibilityValue. Round 4 (2026-08-23) CONFIRMED WORKING by the
owner — gate open; the start/terminal layering stands accepted-by-silence. The toast + live-region layering at job
start/terminal under automatic (VO-gated) speech is
DELIBERATE redundancy; the pre-agreed follow-up if the pass calls it spam: gate the JS
start/terminal announcements on client!=native (NOT a revert).

**GitHub releases:**
- Repo name for releases: `froggeric/applio-macOS-native-app`
- `gh release create` needs `workflow` scope; use `gh api` as fallback
- Create release via API: `gh api repos/{owner}/{repo}/releases -X POST -f tag_name=v{version}`
- Upload assets via curl when `gh release upload` fails: `curl -X POST -H "Authorization: token $(gh auth token)" -H "Content-Type: application/zip" --data-binary @file.zip "https://uploads.github.com/repos/{owner}/{repo}/releases/{release_id}/assets?name=file.zip"`
- Delete release: `gh api repos/{owner}/{repo}/releases/{id} -X DELETE`
- Delete a release ASSET: `gh api -X DELETE repos/{owner}/{repo}/releases/assets/{asset_id}` (path is `releases/assets/{asset_id}`, NOT `releases/{release_id}/assets/{id}`, which 404s)
- **Manual release vs CI:** pushing a `v*` tag auto-runs `release-macos.yml` (build+sign+attach). If you cut a release MANUALLY (local signed DMG + curl upload), `gh run cancel <id>` the triggered run right after tagging; otherwise it clashes on the same asset name + bills macOS minutes

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
