# Changelog

All notable changes to this macOS-native fork of Applio. Versions follow
`{Applio release}.{build}` (e.g. `3.6.3.5` = Applio 3.6.3, fork build 5).

## [Unreleased]

## [3.6.4.2] — 2026-09-14

Third fork release on the upstream 3.6.4 base. Since the last released build (3.6.4.0,
2026-08-13) this carries the completed accessibility program (all eight of our upstream
PRs merged — the last, #1280, landed 2026-09-11), the quit gate, and two upstream syncs.

### Changed

- **Upstream sync 2026-09-11 (5 commits).** Conflict-free merge. Headline upstream changes:
  **our PR #1280 merged — the upstream accessibility program is now 8/8** (friendly names in
  the file dropdowns: `tabs/inference`, `tabs/realtime`, `tabs/train`, `tabs/tts` now render
  `(label, value)` tuple choices); fdec9456 black format run over main (moved `app.py`'s
  `allowed_paths = ["logs"]` to the unspaced form); 7fa68ec2 disables discriminator gradients
  during generator-loss evaluation in `rvc/train/train.py` (training perf); 9b70d059 model-info
  output fix. **Zero patcher re-pointing needed this round**: all 29 registered patch entries
  applied and compiled clean against the merged tree (browse_buttons' anchors sit on the
  component definitions, which #1280's choices rewrite does not touch;
  `patch_progress_routes`' `allowed_paths` anchor already tolerates both spacings and its
  patched output was verified to keep the single-kwarg extension). 113/113 tests across the
  14 suites; gated cert-free build green.

## [3.6.4.1] — 2026-09-02

First fork release on upstream 3.6.4: the full accessibility program (four manual VoiceOver
rounds of fixes, all of it upstreamed as IAHispano/Applio PRs #1270–#1281), the quit gate, and
two upstream syncs.

### Fixed

- **Quitting during an in-process conversion no longer tears the app down under the worker.**
  Both quit paths (menu ⌘Q and window close) now detect a running or cancelling conversion and
  show the existing confirmation prompt; a confirmed quit cancels cooperatively (cancel flag +
  up to 2.5 s grace) instead of finalizing Python under a live torch thread — the cause of the
  "crash" seen on 2026-08-27 (pybind `set_grad_enabled` teardown error). Stale `cancelling`
  records are swept to `interrupted` at startup.

### Changed

- **Upstream sync 2026-09-02 (within 3.6.4, 20 commits).** Conflict-free merge. Headline
  upstream changes: our upstreamed a11y PRs #1281 (translate the remaining user-facing strings
  + name the languages properly), #1276 (toasts for the remaining long-running jobs), #1277
  (label clarity), #1278 (section headings); fd7c034a multi-speaker training (finetuning uses
  a randomized speaker embedding, sid 1+ helper datasets); 3ea5259b ships
  `allowed_paths = ["logs"]` in `app.py`'s launch call; 383eebec TensorBoard wrong-URL fix;
  9b70d059 model-info output fix; 69b298e6 model-blend fix; 3d989f16 TF32 enabled for the
  training script; #1274 rmvpe high-register corrector (new settings section + `f0.py`
  rework); 0724dd77 "Update translations" (locale regeneration + `assets/i18n/scan.py`
  rewrite — note it dropped the `Language automatically detected in the system` key while
  `lang.py` still references it; i18n falls back to the key text, no visible regression).
  Patch-surface consequences:
  - `patches/patch_job_toasts.py` is DELETED (per template commits 5e634319/bd9e6115):
    upstream #1276 now carries all five remaining toast surfaces natively (voice blender,
    plugins, realtime, model information — the toast lives in
    `tabs/extra/sections/processing.py`, not model_information.py — and TensorBoard).
    `test_patch_fixtures` 6→5; the voice_blender CASES entry left `test_patcher_exit_codes`.
  - `patches/patch_progress_routes.py` is re-pointed: it now EXTENDS upstream's
    `allowed_paths = ["logs"]` list with the fork's launch-time-resolved entries
    (`expanduser("~")` + `APPLIO_DATA_PATH` env, `if p`-filtered) instead of injecting a
    second `allowed_paths` kwarg — post-merge that duplicate was a SyntaxError (keyword
    argument repeated) in the patched `app.py` while every patcher still exited 0. The
    `prevent_thread_lock` flip, route registration, and infinite-sleep parking are unchanged.
  - Every other patcher applied cleanly against the merged sources (verified by running the
    full in-order patch loop + `py_compile` on every touched file) — the multi-speaker
    rewrite of `rvc/train/train.py` and the `tabs/train/train.py` i18n pass moved no anchors.

- **Upstream sync 2026-08-25 (within 3.6.4).** Merged our upstreamed PRs — #1270 (batch formant
  toggle wired to the batch checkbox), #1271 (job lifecycle toasts), #1275 (batch conversion
  milestone toasts) — plus a formatter run and an upstream preprocess int→float fix.
  Patch-surface consequences:
  - `patches/patch_job_toasts.py` is slimmed from 9 targets to the 5 upstream does NOT
    toast (voice blender blend + drop confirmations, plugin install start/error, realtime
    start/failure, model information, TensorBoard ready), restored verbatim pending a
    follow-up upstream PR: upstream #1271 now carries the inference/tts/train/download
    toasts natively, so the fork patcher would have double-toasted there and its anchors
    on those four targets miss (build-fatal by design).
  - `patches/patch_inference_progress.py` is re-pointed onto upstream's rewritten
    `convert_audio_batch`: it now keeps upstream's `_toast` announcements verbatim and injects
    only the fork machinery (progress file, cooperative cancel, process history, output-dir
    makedirs). The fork's `_infer_toast` helper is gone — one toast path, upstream's.

### Added

- **Accessibility, Phase 4 (VoiceOver-pass fixes).** The five findings from the 2026-08-22
  manual VoiceOver pass, each addressed fork-side:
  - **Job lifecycle toasts.** Long actions now announce themselves through gradio toasts — the
    one channel the pass verified VoiceOver reads: single-file conversion and TTS
    (start/finish/error), training start, preprocessing and feature extraction (start; failures
    via an error-or-failed check on the result), and model downloads.
  - **Batch conversion progress toasts.** Batch inference announces "started: N files",
    25/50/75 % milestones (batches of 8+ files), and completion with file counts and elapsed
    time; failures toast at both raise sites, including starting a second batch while one is
    already running.
  - **Active Processes menu as a live progress surface.** The Process menu lists every running
    job — batch inference included (it runs in-process and previously never appeared) — with
    live titles ("Inference: batch — 43% (2/3 files)", "Training: voice — epoch 34/200"),
    refreshed every ~2 seconds; selecting an entry opens the dashboard.
  - **Process Dashboard readable by VoiceOver.** Run rows announce their summary (epoch, best
    loss, ETA; inference file counts), the loss chart announces its extent and best point, the
    detail progress bar reads "Epoch N of M, P percent" instead of a bare percentage, selecting
    a row announces its summary, and Tab leaves the runs list for the action buttons and cycles
    back.
  - **Announcements: Auto (recommended) — new mode and default.** In-app speech routes through
    the web live region instead of window-level VoiceOver posts, which the pass never heard
    with the VoiceOver cursor inside the web content. "Announcements: Native (experimental)"
    opts back into the old engine; dock attention, sound cues, and the `[A11y]` log lines are
    unchanged either way, and a `mode=` field in the `[A11y] post` diagnostic line records the
    active mode.
  - New test suites `tests/test_menu_jobs.py` and `tests/test_dashboard_ax.py`.
- **Accessibility, Phase 4b wave — completion toasts on every job.** Per the 2026-08-22 owner
  ruling ("we should get a toast when something finishes as well; this is important for
  improving upstream accessibility which does not have a native wrapper"), toast coverage now
  spans every job surface (full table in `ACCESSIBILITY_AUDIT.md` §7):
  - **Training completion toast.** The training handler blocks until training ends, so toasting
    its return announces completion — success or error — the moment a possibly hours-long run
    finishes.
  - **Newly covered surfaces.** Voice blending (start/finish/error, plus "Model added"
    confirmations on both model dropboxes), plugin install (start and error; the success toast
    is upstream's own), realtime engine start/failure — failure detection broadened to the
    yielded validation statuses (invalid audio devices, missing model path) so first-use
    mistakes are no longer silent — model information (loaded), and TensorBoard (ready).
    Download-tab dropbox saves already toasted upstream and are untouched.
  - **Single conversions tracked, not just batches.** A one-file conversion now writes
    start/finish entries into the same progress file the menu, dashboard, and accessibility
    payload read — so a single conversion is visible and its completion announced even when
    the in-app toast stream is unavailable (the failure mode the built app exhibited; batches
    keep exclusive write priority over the progress file).
- **Accessibility, Phase 3 (fork-local hardening).** Seven targeted fixes from the Phase 2 review,
  all fork-side (no upstream files), each with tests:
  - **Localized native strings, completed.** The remaining native English clusters — boot loading
    stages, headings and technical details, dashboard statuses, the About alert, dynamic
    process-status titles — resolve through the app language; locale matching now follows
    upstream's prefix-glob semantics, and a corrupt language file is skipped instead of crashing.
  - **Scoped record-toggle healing.** The injected `aria-pressed` repair no longer stamps every
    Start/Stop-labeled button; it is scoped to the realtime record toggle.
  - **One terminal-words map.** The web payload and the native announcer share a single helper,
    removing a two-place sync point.
  - **Failure log tails in the web UI.** Failed jobs append a bounded log tail (last 1200
    characters, at most 2 jobs) to the "Last result" region — readable with a screen reader;
    spoken announcements are unchanged.
  - **Path validation on every Browse field.** All 13 path fields warn on blur when the typed
    path does not exist (an announced toast), after `~/…` expansion.
  - New test suites `tests/test_a11y_js_invariants.py` and `tests/test_patcher_exit_codes.py`.
- **Accessibility, Phase 2 (web UI, pickers, settings, i18n).** Screen-reader support now reaches
  inside the Gradio web UI, and path fields get native pickers:
  - **Announcements in the web UI.** A live region + "Last result" region are injected into the
    page; job milestones ("25% of epoch 12/50"), completions, failures, and output-text changes are
    announced in external browsers too (the in-app window keeps its native VoiceOver engine — no
    double-speaking). Accordion and tab semantics are healed for VoiceOver, and focus is restored
    after Gradio re-renders.
  - **Browse… buttons on every path field.** All 13 path fields across Training, Inference, TTS,
    Realtime, Voice Blender, and Processing get a "Browse…" button opening a native macOS
    file/folder panel; the chosen path fills the field, and typed `~/…` paths are expanded.
  - **Accessibility settings submenu.** Announcements: Off / Standard / Verbose, plus Sound Cues —
    persisted across launches, applied to both the native engine and the web UI.
  - **Localized native strings.** Menu, picker, and announcement strings resolve through the
    app's language setting (fork-owned translation layer; upstream files untouched).
- **Accessibility, Phase 1 (native wrapper foundation).** Voice support across the native app:
  - **Announced job lifecycle + dock badge.** Posts VoiceOver announcements (with `[A11y]`
    lines in `~/Library/Logs/Applio/applio_launcher.log`) when a training, preprocessing,
    feature-extraction, or batch-inference job starts, finishes, errors, or is cancelled;
    the dock badge shows the active-job count and finished jobs request dock attention.
  - **Edit menu + keyboard shortcuts.** Edit → Cut/Copy/Paste/Select All (⌘X/⌘C/⌘V/⌘A) reaches
    text fields inside the web UI through the responder chain; ⌘L opens the Logs folder, ⇧⌘D
    sets the data location, ⌘0 refocuses the main window, ⇧⌘R reveals the data folder in Finder.
  - **Process menu live jobs submenu.** The Process menu now lists active background jobs;
    selecting one opens the dashboard (Pause/Resume live in its action bar) instead of a
    static disabled status line.
  - **Enabled downloads.** Model export / download links open a native save panel instead of
    being silently swallowed by the webview.
  - **Accessible boot/loading screen.** The startup screen is a polite live region announcing
    each boot stage, its progress bar exposes real values, the window title tracks the stage,
    and a stalled boot raises an alert instead of hanging forever.
- **Mic permission string.** Re-added `NSMicrophoneUsageDescription` so realtime voice
  conversion can request microphone access instead of being silently denied.

### Fixed

- **Single conversions are announced as "conversion" (Phase 4c).** Both job-label builders —
  the native snapshot (which said "batch inference" for every inference job) and the web
  `jobLabel` (scope-blind "inference") — predate single-conversion tracking; both are now
  scope-aware.
- **Converted outputs now load in the UI (built app).** Gradio serves output files only from
  its allowed set (working directory + temp), and the packaged app's working directory is the
  bundle — so a conversion wrote the audio file but the output component never loaded it. The
  app now allows the user's home directory and the configured data directory (resolved at
  launch), covering every location outputs are written to by default or picked via Browse.
- **Truthful accessibility labels.** Dashboard labels track Pause/Resume, inference mode, and
  real status; dashboard rows, the loss chart, and progress bars expose their values to
  VoiceOver; the progress window's live log zone reads as words instead of glyph noise.
- **Safe dialog defaults.** Destructive confirms put Cancel first and never bind Return (Enter
  on the quit confirm does nothing; Escape cancels); update alerts activate properly; progress
  dialogs land focus on a safe first responder. The close confirmation defaults to "Keep
  Running". First run without a chosen data location now asks instead of silently defaulting.
- **Announced Stop/upload feedback.** Stop and file-upload actions in the web UI post
  spoken/spoken-equivalent feedback via a build-time patch instead of failing silently.

### Changed

- **Accessibility is now automatic — nothing to configure (Phase 4c, owner ruling 2026-08-23).**
  Speech is VoiceOver-gated: VoiceOver running → verbose job announcements, VoiceOver off →
  silent, recomputed on the every-2-second heartbeat (the live region flips within one poll
  cycle when VoiceOver starts or stops mid-session). Sound cues now play for everyone on job
  completion and failure. There is no settings UI; two hidden NSUserDefaults keys remain as
  escape hatches — `a11y.speech` (`auto`/`on`/`off`, default `auto`) and `a11y.sound_cues`
  (default on).
- **Announcements default flipped native → Auto (web) — maintainer-facing behavior change.**
  In-app job speech now comes from the web live region (plus toasts) rather than native
  window-level accessibility posts, which the VoiceOver pass never heard; "Announcements:
  Native (experimental)" in the Accessibility submenu restores the old engine. Under Auto, a
  job start/terminal is heard as both a toast and a short live-region line — deliberate
  redundancy; if the next VoiceOver pass reads it as spam, the planned follow-up gates the
  JavaScript start/terminal announcements in-app (not a revert).
- **Build now fails on a missed patch anchor — maintainer-facing behavior change.** A patcher
  that cannot find its anchor after an upstream sync exits with code `2` and the build stops,
  listing every failure; previously an anchor miss could pass silently (exit `1` was read as
  "already patched"). Exit `1` remains the standalone usage guard, and `patches/download_pretraineds.py`
  (model downloader, own invocation path) is exempt.

### Fixed
- Completion chime now plays through the regular output channel (afplay) — previously inaudible when the alert-volume slider was muted.
- **Output changes are visible-only (Phase 4e).** Output-textbox changes are no longer spoken at
  all — job start/milestone/terminal announcements own the spoken channel (a single merged
  live-region write per poll, so simultaneous events announce as one line); the latest output
  text stays readable in the persistent "Last result" region.
- **Dashboard rows speak their metrics (Phase 4e).** Active-run rows now carry their live metrics
  (epoch, best loss, ETA; inference files converted and percent) in the row's visible text, which
  VoiceOver reads reliably — a row view's accessibility value alone proved unreliable under
  VoiceOver.

### Removed

- **Accessibility submenu + Native announcement mode (Phase 4c).** The entire submenu is gone —
  verbosity, the Sound Cues toggle, and "Announcements: Native (experimental)". The window-level
  NSAccessibility post path that mode opted into (never heard by the VoiceOver pass) is deleted
  outright; the `[A11y] terminal post` diagnostic line remains (simplified), as does the
  VoiceOver-gated dashboard selection announcement. Per the owner: "having multiple options is
  confusing and bad ux, especially for disabled users."

---

## [3.6.4.0] - 2026-08-13

First release on the **upstream Applio 3.6.4** base. Signed and notarized — download the DMG and
open it directly (no `xattr -cr` needed).

### Synced with upstream Applio 3.6.4

- **New command-line interface.** Upstream rebuilt Applio's CLI on [Click](https://click.palletsprojects.com/)
  (`python core.py <command>`), replacing the old argparse parser. This is a terminal/developer
  feature; the macOS app is unaffected — its UI, training, inference, TTS, and the script-launching
  functions it calls are unchanged.
- **Realtime voice conversion fixes** from upstream: block-frame processing and a warmup
  progress-bar fix.
- New runtime dependency **`click`** (pinned `click==8.1.8` in `requirements_macos.txt`); it is
  bundled into the app, so users need do nothing.

### Notes

- Every macOS-specific feature carries over unchanged and is validated on this build: the
  single-process native app, the Process Dashboard (training + batch inference), the RefineGAN-Legacy
  vocoder, 44.1 kHz training, the native menu bar, and external data storage.
- Build verified end-to-end: all 24 build-time patches apply cleanly against the upstream-rewritten
  `core.py`/`app.py`, and the app boots to the main UI reporting version 3.6.4.

### Changed

- `BUILD_NUMBER` reset to `0` for the new upstream base — display version `3.6.4.0`,
  `CFBundleVersion` `3060400`.

---

## [3.6.3.7] - 2026-07-31

### Added
- **Process Dashboard: batch voice-conversion progress.** The dashboard now tracks batch inference
  (Process → Open Progress Dashboard, ⌘⇧P): files converted / total, current file, derived ETA, and
  speed (files/min), with an auto-show on batch start. Completed and cancelled batch runs appear in
  the dashboard history, and a stale `running` record left by a crash or quit is marked `interrupted`
  on the next launch so the dashboard never shows a phantom running job.

### Changed
- **Single-process is now the only architecture.** The two-process code and the `APPLIO_SINGLE_PROCESS`
  flag were removed; the app runs as one native process (one dock icon, one menu, one window). The
  previous legacy fallback (`APPLIO_SINGLE_PROCESS=0`) is gone.

### Fixed
- **Inference "Stop" no longer quits the whole app.** In single-process the inference PID was the app
  PID, so the old PID-kill Stop quit Applio mid-batch. Batch inference Stop now cancels cooperatively
  via a cancel flag checked per file. Also fixes a frozen-build issue where batch inference could not
  write its stop-PID file in the read-only app bundle (the PID file is gone, replaced by the cancel
  flag in the writable data directory).
- **Batch conversion creates its output folder.** Batch inference now creates the output folder if it
  does not exist (it previously failed on the first file with an opaque soundfile "System error" when
  the chosen output path was missing). Completed batch runs also show their file counts and duration
  on the dashboard and in history, not just a bare "completed" status.

---

## [3.6.3.6] - 2026-07-30

### Added
- **Process Dashboard** (Process → Open Progress Dashboard, ⌘⇧P): a live training-monitoring window.
  Shows real-time metrics - best epoch + loss, current/total epoch, step, speed, and a derived ETA,
  beside an epoch-fraction progress bar, plus a **loss-vs-epoch curve that highlights significant
  improvements** (green markers + epoch numbers at notable loss drops). An **action bar** offers
  Stop / Pause-Resume / Reveal Log in Finder / Open Log. **Best-epoch metrics are snapshotted into
  history**, so they survive an app restart and re-training the same model. The dashboard
  **auto-shows when a job starts**, and when idle lets you **browse finished runs** from history.
- **Phase 2 single-process merge (now the default):** merges the two-process launcher+wrapper into
  one native process (fixes Hide-not-hiding + menu-swaps-by-focus). The `APPLIO_SINGLE_PROCESS` flag
  default flipped to `"1"`, so single-process is now the standard (the app runs as one process out of
  the box: one dock icon, one menu, one window); two-process is the legacy fallback
  (`APPLIO_SINGLE_PROCESS=0`, byte-for-byte the old path). Functionally complete and
  **frozen-validated** (training, reopen, quit, menu, and dashboard all work in the built app). Tasks
  through 3a done (single-instance surfacing via `bring_to_front`). Remaining: dead two-process code
  removal + drop the flag (Task 4). Plan: `~/.claude/plans/phase2-single-process-merge.md`.
- **Native menu overhaul:** one shared `menu_spec.py` rendered by a PyObjC renderer
  (launcher) and a pywebview static-subset renderer (standalone). New Process + Help menus;
  Reveal-in-Finder rescued; Hide ⌘H / Minimize ⌘M; the dead Menu B deleted.
- **Real update checking:** manual `Check for Updates…` queries GitHub releases, and a silent
  launch-time check alerts only if a newer version exists. Version comparison fixed (was a buggy
  string compare; now `packaging.version`).
- **Studio Production Guide** bundled (rendered HTML) under Help.
- `tests/test_menu_spec.py` - pure-Python structure + version-compare gate.
- **CI: macOS build + signed/notarized releases via GitHub Actions.**
  - `.github/workflows/ci-macos.yml` - path-filtered, build-only smoke test (ad-hoc, no cert) with
    `CFBundleVersion` + `codesign` assertions.
  - `.github/workflows/release-macos.yml` - on a `v*` tag, builds + signs + notarizes + staples the
    `.app`/`.dmg` on a `macos-14` runner and attaches the DMG to the release. Runs in a protected
    `signing` environment; inline App Store Connect API-key auth (no keychain on the runner). Validated
    end-to-end.
- `build_macos.py --api-key/--api-key-id/--api-issuer` - inline notarytool auth (CI/headless);
  `--keychain-profile` remains the default for local runs.

### Fixed
- **Process Dashboard window did not open at all** - `ProcessDashboardController` now subclasses
  `NSObject` (a plain Python class crashed on `conformsToProtocol:`) and the missing `AppKit`
  constants (`NSBoxPrimary`, …) are imported so the window constructs. Loss-vs-epoch axes are fixed
  and the stray "Title" placeholder text removed.
- Post-training `SIGTERM` no longer quits the whole app (single-process).
- `_final_verify` now gates the `.dmg` only on `xcrun stapler validate` (it was hard-failing on
  `spctl`, which reports "does not seem to be an app" for a disk image). Caught by the CI release test.

---

## [3.6.3.5] - 2026-07-26

### Added
- **Developer ID code signing + Apple notarization.** `build_macos.py --sign --notarize --dmg` now
  produces a **Gatekeeper-clean, signed + notarized + stapled** `.app` and `.dmg`. This is the first
  notarized release - end users no longer need `xattr -cr`. Authentication uses an App Store Connect
  API key (`--keychain-profile`); no secrets live in the repo.
- Voice model + FAISS index **merger tool** (`merge_rvc.py`) with weighted merging, auto-naming from
  model metadata, and merge-metadata output. See `MERGE_ALGORITHM.md`.
- `LSMinimumSystemVersion = 12.0.0` in the app `Info.plist` (Gatekeeper gives a clear message on
  unsupported macOS instead of a cryptic crash).

### Fixed (frozen-app reliability)
- Custom-pretrained **dropdown empty** and **downloads landing inside the bundle** - both now resolve
  to the external data directory when frozen (the frozen-CWD invariant).
- **Version surfaces inconsistent** - About dialog, loading screen, wrapper log, and the in-app
  version checker now all read `3.6.3.x` consistently (the checker reads the bundle's
  `config_template.json`, not a stale data-dir copy).
- **Training process tracking** - `verify_process_identity` now treats `psutil.AccessDenied` as
  "alive" so the quit-while-training confirmation fires reliably mid-training.
- **Frozen training pipeline** (preprocess → extract → train) + dev-mode dock icon + error logging.

### Changed
- **Native macOS app lifecycle (Phase 1):** single dock icon, unified quit cascade, crash-recovery
  relaunch, "Keep Running" (hide vs quit), and instant reopen.
- Synced with **upstream Applio 3.6.3** (minimal delta; macOS work stays in fork-only files).

### Internal (build/release)
- Rewrote `build_macos.py` signing/notarization: inside-out Mach-O signing (catches bare executables
  the old `*.so`/`*.dylib` glob missed, including the Python interpreter and `torch/bin/*`),
  entitlements only on the outer bundle, `ditto`-zip submission, `status: Accepted` parsing with
  automatic JSON-log pull on failure, staple-`.app`-before-building-DMG, `shutil.copytree(symlinks=True)`
  to preserve the `Python.framework` symlinks, and hard-fail `codesign --verify` / `spctl` gates.
- Fixed `CFBundleVersion` (was the invalid 4-segment `3.6.3.5`; now a monotonic `3060305`-style integer).
- Removed the orphaned `scripts/sign_bundle.sh`, `scripts/notarize.sh`, `scripts/entitlements_dev_id.plist`.
- `.gitignore` hardened against credential leaks (`*.p8`, `*.p12`, `*.key`).

---

## [3.6.3] - 2026-03-03 (upstream sync baseline)

First release on the upstream 3.6.3 base. See `git log v3.6.3..HEAD` for the full delta.
