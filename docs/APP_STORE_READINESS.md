# Mac App Store edition: what it takes

Assessed on 2026-11-26, decided by the owner the same day. The implementation plan is
[`docs/superpowers/plans/2026-11-26-app-store-edition.md`](superpowers/plans/2026-11-26-app-store-edition.md).
The work is done on the branch `store-edition`. The 3.7.2.1 release has priority: when the
owner's manual test results arrive, the release is handled first.

## Verdict

It can be done. The app for the Mac App Store is a second edition, built from the same sources
as a variant of the normal build, while the direct-download edition (Developer ID certificate,
notarized) stays as it is. The owner expects the store edition to gain features of its own,
which is why it has a bundle id of its own.

Two experiments on 2026-11-26 answered the largest technical questions. The app starts and
trains in the App Sandbox once it stops using worker processes, and training without them costs
about 5 to 11 percent on the build Mac.

One limit showed up while planning: real-time conversion runs its voice changer in a second
process, connected by process queues and events. Those need the named semaphores the sandbox
denied in the experiment, so it is expected to fail there. The owner's choice: the first store
version has no Realtime page; it may return later on another process channel.

## 1. Apple's rules that matter

From the [App Store Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
(version dated 2026-10-16):

- **4.1 (c), name and icon.** "You cannot use another developer’s icon, brand, or product name
  in your app’s icon or name, without approval from the developer." The name Applio and the
  icon are IAHispano's. The owner has IAHispano's authorisation.
- **2.4.5 (i) and 2.5.2, sandbox.** Mac apps "must be appropriately sandboxed" and "may not read
  or write data outside the designated container area, nor may they download, install, or
  execute code which introduces or changes features or functionality of the app".
- **2.4.5 (iv) and (vii), code and updates.** Apps may not download "additional code, or
  resources to add functionality". "They must use the Mac App Store to distribute updates;
  other update mechanisms are not allowed."
- **3.1.1, plug-ins.** A Mac app may host plug-ins that were enabled outside the store. The
  download of plug-in code inside the app is still what 2.5.2 forbids.
- **4.2 and 4.2.3, first download.** The app must be more than a repackaged website, and must
  "disclose the size of the download and prompt users before doing so".
- **5.1.1 (i), privacy policy.** "All apps must include a link to their privacy policy in the
  App Store Connect metadata field and within the app in an easily accessible manner."

Python itself is not a problem. No rule names interpreters. Apple's staff said on the
[developer forums](https://developer.apple.com/forums/thread/782874) that an app written in
Python and wrapped as a double-clickable app is supported, and a PyInstaller app was
[accepted in 2022](https://github.com/pyinstaller/pyinstaller/issues/7123).

Submission facts from Apple's pages:

- Certificate "Apple Distribution" for the upload, "Apple Development" for local runs.
  Profile type "Mac App Store Connect". Upload with Transporter or `altool`.
- App name up to 30 characters. A category. An icon set. A privacy policy URL.
  `ITSAppUsesNonExemptEncryption` in the Info.plist.
- The Account Holder must have accepted the latest agreement before an app can be added.

From [TN3125](https://developer.apple.com/documentation/technotes/tn3125-inside-code-signing-provisioning-profiles):
the Hardened Runtime keys (`cs.*`) and `automation.apple-events` are not restricted for store
apps.

One developer reported a rejection in 2024 that was traced to the string `itms-services` in
Python's `urllib/parse.py` (an iOS app,
[CPython issue 120522](https://github.com/python/cpython/issues/120522)). The bundle holds that
string in two modules, `urllib.parse` and `werkzeug.urls`.

## 2. Where the app stands

Facts from the repository and from build 3.7.2.1:

- `assets/entitlements.plist` has the sandbox switched off. On: camera, user-selected files,
  downloads, network client and server, Apple Events, and the three Hardened Runtime keys
  (`cs.allow-jit`, `cs.allow-unsigned-executable-memory`, `cs.disable-library-validation`).
  No microphone entitlement.
- The built app is arm64 only, has no `LSApplicationCategoryType`, and carries upstream's
  bundle id `com.iahispano.applio`. The usage description for the microphone is in its
  Info.plist.
- **The minimum macOS version in the Info.plist is wrong.** It says 12.0.0. The bundle's own
  binaries say otherwise: `orjson` is built for macOS 15.0, 113 other binaries for 14.0, and
  dyld refuses to load a binary on an older system than it was built for. The app cannot start
  below macOS 15. The plan makes the build compute the number from the bundle, for both
  editions.
- The Plugins page downloads a zip and runs it (`tabs/plugins/plugins_core.py`).
- Upstream's updater (`assets/updater.py`) and version checker ship in the bundle. The fork's
  "Check for Updates" opens the GitHub releases.
- Discord presence (`assets/discord_presence.py`) starts with the app when the setting is on.
- Every start downloads the models that are missing, in one block of about 3 GB: the pitch
  extractors and the embedder (about 0.6 GB), the HiFi-GAN pretrained voices (about 0.6 GB)
  and the RefineGAN pretrained voices (about 2.0 GB). Upstream's helpers
  (`rvc/lib/tools/prerequisites_download.py`) keep the three groups apart, so they can be
  offered one by one.
- Worker processes: preprocessing (`rvc/train/preprocess/preprocess.py`), feature extraction
  (`rvc/train/extract/extract.py`, two pools) and the training DataLoader
  (`rvc/train/train.py`). Real-time conversion: `rvc/realtime/worker.py`.
- Two checkpoint readers fall back to unrestricted `torch.load` when the safe loader rejects a
  file (`rvc/train/process/model_information.py`, `rvc/lib/tools/inspect_checkpoint.py`).
- Upstream's own code puts the data location on `sys.path` (`app.py`, `core.py`,
  `assets/i18n/i18n.py` and several tab modules).
- Licences: Applio is MIT. Copyleft parts that ship: `soxr` (LGPL, resampling; used by
  inference and preprocessing, and required by librosa), `edge-tts` (LGPL-3.0, text to speech).
  PyInstaller is GPLv2 with a bootloader exception. Gradio's frontend ships
  `ffmpeg-core.wasm` (build not checked).
- Hosts the app contacts: huggingface.co, github.com, raw.githubusercontent.com, api.github.com,
  docs.google.com, drive.google.com, drive.usercontent.google.com, download.pytorch.org, and
  Microsoft's Edge service for text to speech.
- On the build Mac: Xcode 27.2 with the macOS 27.2 SDK, `altool`, one "Apple Distribution" and
  two "Apple Development" identities, and a "Mac Team Store Provisioning Profile" for another
  app. Nothing of this exists yet for Applio. The PyInstaller bootloader in the bundle was
  built with the macOS 14.2 SDK.

## 3. What was tested

### The app in the App Sandbox (2026-11-26, about 21:00)

A copy of the build, signed ad hoc with the Hardened Runtime, the three `cs.*` keys and the
sandbox entitlements, under a throwaway bundle id, run without a window.

Worked: signing, PyTorch on Metal, numba, the loopback server, outbound connections, `afplay`,
`/usr/bin/open`, NSWorkspace queries. Paths under the home folder land in the container.

Failed:

- Named POSIX semaphores and shared memory are denied (`ipc-posix-sem-create`,
  `ipc-posix-shm-write-create`). Every worker pool dies before a worker starts.
- `import gradio` crashes on `/etc/apache2/mime.types`. `mimetypes.knownfiles = []` before
  the import fixes it; the server then serves its pages.
- `/tmp/applio_debug.txt` could not be written at training start (fixed on 2026-11-26: the
  file is written only with `APPLIO_DEBUG` set).
- `/bin/ps` cannot run (it is setuid; the app does not use it).

With those edits in the copy only, preprocessing and extraction ran serially and training
completed two epochs with no DataLoader workers.

Not verified: the real interface in the window, the folder picker with a bookmark on an
external volume, the login keychain in the sandbox, text to speech, TensorBoard, and what App
Store Connect says at upload.

### Cost of training without workers (2026-11-26, about 23:00)

Normal build, the owner's M2 Max (12 cores), dataset `Frederic_v6_10min` (236 slices, batch
size 4, 61 steps per epoch, 5 epochs per run):

- Seconds per step: 0.872 and 0.819 with two workers, 0.912 with none. About 5 to 11 percent
  slower: 4 to 10 minutes more per hundred epochs at this dataset size, roughly 25 to 55
  minutes more per hundred epochs for an hour-long dataset.
- Preprocessing: 15.3 s with the pool, 9.5 s serial (a short dataset: twelve frozen worker
  processes cost more than they save). Extraction: 48.8 s with the pool, 39.2 s serial.

Verdict: the simple route, training without worker processes, is acceptable.

### Reading the code for the plan (2026-11-26)

- Real-time conversion (`rvc/realtime/worker.py`, class `VoiceChangerWorker`) runs the voice
  changer in a spawned process and talks to it with three `multiprocessing` queues and two
  events. Those create named semaphores, which the experiment showed denied.
- The pitch extraction pool reports a failed task as a warning and goes on
  (`run_pitch_extraction`). In a sandboxed build that kept the pools, extraction could report
  success without producing features. The embedding pool raises.
- `itms-services` sits in two bundled modules: `urllib.parse` (list `uses_netloc`) and
  `werkzeug.urls` (which adds the scheme to that list).
- PyInstaller appends `--paths` entries to `sys.path`, after the standard library, so a shadow
  copy cannot replace `urllib.parse` at collection time.
- A script-mode start runs with the bundle as working directory and leaves the two
  `runtime_paths.json` files untouched.
- The highest minimum macOS version among the 325 binaries of build 3.7.2.1 is 15.0.

## 4. The store edition

A build-time variant of the same sources, switched on by `build_macos.py --store`:

- **Build.** Sandbox entitlements (`assets/entitlements_store.plist`: sandbox, user-selected
  files, network client and server, microphone, the three `cs.*` keys). Store-only patchers in
  `patches/store/`. Signing with "Apple Distribution" (or "Apple Development" for local runs)
  and an embedded provisioning profile. No notarization, no DMG. Output in `dist-store/`, so
  the release build in `dist/` is never touched. The minimum macOS version is computed from
  the bundle.
- **Pipeline.** No worker processes: serial loops for the three pools, a DataLoader without
  workers. Model checkpoints are loaded as data only.
- **Data location.** A folder the user chooses at the first launch, on any disk. Never inside
  the app's container: macOS may remove the container together with the app, and the data must
  survive that. The folder stays reachable through a security-scoped bookmark, kept in two
  places: in the app's container and in the login keychain, which survives removing the app. So
  a new installation finds the folder again by itself. "Set Data Location" changes it at any
  time.
- **Model downloads.** A dialog at the first launch, with three parts: the base models (about
  0.6 GB, needed to convert and to train), the HiFi-GAN pretrained voices (about 0.6 GB) and
  the RefineGAN pretrained voices (about 2.0 GB). The base part is required; the others are the
  user's choice, also later under File, Download Models…. Nothing is bundled into the app.
- **Interface.** No Plugins page, no updater, no update check, no Discord presence. A link to
  the privacy policy in the app menu and in Settings, with the licences of the copyleft parts
  named. No Realtime page.
- **Bundle.** Category, encryption key, the owner's bundle id. The `itms-services` string
  removed from the two modules. The name Applio and the icon stay (IAHispano's authorisation).

What stays as it is, with reason:

- `/usr/bin/open` for Finder and links: it works in the sandbox.
- The data location on `sys.path` in upstream's modules: nothing writes code there any more
  (the Plugins page is gone), and the bundle comes first on `sys.path`.
- The direct-download edition: unchanged build and behaviour, except for the computed minimum
  macOS version in its Info.plist.

## 5. Work list

The plan has ten tasks (0 to 9). Tasks 0 to 7 need no Apple record: the app is signed ad hoc
with the sandbox entitlements, which enforces the sandbox on this Mac. Tasks 8 and 9 need the
owner's App ID, profiles and App Store Connect record.

- **Task 0, prerequisites.** The worktree, a green baseline, the rule that the 3.7.2.1
  release comes first.
- **Task 1, the build.** `--store` switch, store entitlements, the edition recorded in
  `build_info.json`, the minimum macOS version computed from the bundle.
- **Task 2, pipeline.** No worker processes.
- **Task 3, checkpoints.** Loaded as data only.
- **Task 4, the bookmark.** Kept in the app and in the login keychain.
- **Task 5, data location.** Always a folder the user chose.
- **Task 6, interface.** No plugins, updater, update check or Discord presence; selectable
  downloads; privacy link.
- **Task 7, the sandboxed build on this Mac.** Ends with the owner's VoiceOver pass, and a
  probe of a pipe-based process channel for a later real-time conversion.
- **Task 8, the signed build.** Provisioning profile, the flagged string, the SDK, the
  reinstall.
- **Task 9, App Store Connect.** Upload, TestFlight, the store record, submission.

## 6. Decisions

The owner's answers of 2026-11-26:

1. **Name and icon.** IAHispano's authorisation exists. Applio and the icon stay. The
   authorisation goes into the review notes.
2. **Bundle id.** The owner's own: there is significant work and additional features to warrant
   a different bundle. The id string is still to be given.
3. **Copyleft parts.** Approved for inclusion, the owner's responsibility. `soxr` and
   `edge-tts` stay and are named in the app. This document is not legal advice.
4. **Data location.** The owner asked for a recommendation, with two requirements: the data
   must survive removing and reinstalling the app, and the user must be able to change it.
   Recommendation, followed by the plan: a folder the user chooses, on any disk, with the
   bookmark kept in the login keychain as well. The keychain part is not yet proven in the
   sandbox; if it fails, the app asks for the folder once after a reinstall, and the data is
   never at risk.
5. **Real-time conversion.** Out of the first store version. The plan runs a small probe
   (pipes instead of queues) so that a later version knows which way is open.
6. **First download.** No models bundled. The download is selectable, in three parts, because
   3 GB is too big for a first download and users may not need everything.
7. **Privacy policy.** On GitHub for now (`https://froggeric.github.io/applio-macOS-native-app/privacy/`),
   later the owner's own website. One constant in the code.
8. **Minimum macOS version.** The owner asked for a recommendation. The bundle decides: 15.0,
   computed by the build. It cannot be lower without changing dependencies; it can be raised
   in one line.

Still open with the owner: the bundle id string; whether the two recommendations (4 and 8)
stand.

## 7. Risks and unknowns

- **The keychain in the sandbox.** That a bookmark kept in the login keychain survives removing
  the app and its container, without a prompt, is standard behaviour for an app's credentials
  but has not been shown for this app. Task 8 tests it with the signed build. The fallback is
  one folder choice after a reinstall.
- **SDK at upload.** Apple asks each year for a recent SDK. The bootloader in the bundle was
  built with the macOS 14.2 SDK. The first upload shows whether that passes; if not, the
  bootloader is rebuilt from PyInstaller's sources with Xcode 27. Whether Apple looks at the
  other binaries in the bundle is unknown.
- **macOS 15 and 26.** The build Mac runs 27.2. The floor is 15.0; nothing below 27 has been
  tested. TestFlight testers on those versions close the gap.
- **The review.** A reviewer meets a folder choice and a download before anything works. The
  dialog, the review notes and the "Not now" path must make that plain. Whether a reviewer sees
  model files (torch checkpoints) as "code" under 2.5.2 is a judgement; the store edition
  loads them as data only.
- **Features not yet run in the sandbox:** the interface in the window, text to speech,
  TensorBoard, model download, Voice Blender, Audio Tools. Task 7 runs them.
- **Speed.** Training is 5 to 11 percent slower without workers.
- **Upstream syncs.** The store patchers need re-pointing after each sync, like the others.

## 8. Sources

- https://developer.apple.com/app-store/review/guidelines/
- https://developer.apple.com/documentation/technotes/tn3125-inside-code-signing-provisioning-profiles
- https://developer.apple.com/forums/thread/782874
- https://developer.apple.com/library/archive/documentation/Security/Conceptual/AppSandboxDesignGuide/AppSandboxInDepth/AppSandboxInDepth.html
- https://github.com/python/cpython/issues/120522
- https://github.com/pyinstaller/pyinstaller/issues/7123
- https://www.electronjs.org/docs/latest/tutorial/mac-app-store-submission-guide
