# Mac App Store edition: what it takes

Assessed on 2026-11-26. The implementation plan is
[`docs/superpowers/plans/2026-11-26-app-store-edition.md`](superpowers/plans/2026-11-26-app-store-edition.md).
Nothing of it is built yet. The order agreed with the owner: finish the manual test pass and the
3.7.2.1 release first.

## Verdict

It can be done. The app for the Mac App Store would be a second edition, built from the same
sources as a variant of the normal build, while the direct-download edition (Developer ID
certificate, notarized) stays as it is.

Two experiments on 2026-11-26 answered the largest technical questions. The app starts and
trains in the App Sandbox once it stops using worker processes, and training without them
costs about 5 to 11 percent on the build Mac.

One limit showed up while writing the plan: real-time conversion runs its voice changer in a
second process, connected by process queues and events. Those need the named semaphores the
sandbox denied in the experiment, so real-time conversion is expected to fail there (not tested
yet). The first store version would ship without that page unless its process channel is
rebuilt (section 6, decision 5).

What is left is engineering, plus decisions that belong to the owner and to upstream (section 6).

## 1. Apple's rules that matter

From the [App Store Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
(version dated 2026-10-16):

- **4.1 (c), name and icon.** "You cannot use another developer’s icon, brand, or product name
  in your app’s icon or name, without approval from the developer." The name Applio and the
  icon are IAHispano's.
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
- The built app is arm64 only, needs macOS 12.0 or later, has no `LSApplicationCategoryType`,
  and carries upstream's bundle id `com.iahispano.applio`. The usage description for the
  microphone is in its Info.plist.
- The Plugins page downloads a zip and runs it (`tabs/plugins/plugins_core.py`).
- Upstream's updater (`assets/updater.py`) and version checker ship in the bundle. The fork's
  "Check for Updates" opens the GitHub releases.
- Discord presence (`assets/discord_presence.py`) starts with the app when the setting is on.
- Every start runs the first-launch model download when files are missing: about 3 GB
  (pretrained pairs for HiFi-GAN and RefineGAN, pitch extractors, embedder).
- Worker processes: preprocessing (`rvc/train/preprocess/preprocess.py`), feature extraction
  (`rvc/train/extract/extract.py`, two pools) and the training DataLoader
  (`rvc/train/train.py`). Real-time conversion: `rvc/realtime/worker.py`.
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

Not verified: the real interface in the window, the microphone, the folder picker with a
bookmark on an external volume, real-time conversion, text to speech, TensorBoard, and what
App Store Connect says at upload.

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

## 4. The store edition

A build-time variant of the same sources, switched on by `build_macos.py --store`:

- **Build.** Sandbox entitlements (`assets/entitlements_store.plist`: sandbox, user-selected
  files, network client and server, microphone, the three `cs.*` keys). Store-only patchers in
  `patches/store/`. Signing with "Apple Distribution" (or "Apple Development" for local runs)
  and an embedded provisioning profile. No notarization, no DMG. Output in `dist-store/`, so
  the release build in `dist/` is never touched.
- **Pipeline.** No worker processes: serial loops for the three pools, a DataLoader without
  workers.
- **Wrapper.** The MIME-types fix before Gradio is imported. The default data location inside
  the app's container. No Python files copied into the data location. A bookmark for every
  data location chosen with the menu, resolved at each start.
- **Interface.** No Plugins page, no updater, no update check, no Discord presence. A prompt
  before the first model download, with its size. A link to the privacy policy in the app menu
  and in Settings. Real-time conversion according to decision 5.
- **Bundle.** Category, encryption key, the owner's bundle id and, if needed, name and icon.
  The `itms-services` string removed from the two modules.

What stays as it is, with reason:

- `/usr/bin/open` for Finder and links: it works in the sandbox.
- The data location on `sys.path` in upstream's modules: nothing writes code there any more
  (the Plugins page is gone), and the bundle comes first on `sys.path`.
- The direct-download edition: unchanged build, unchanged behaviour.

## 5. Work list

The plan has ten tasks. Tasks 1 to 7 need no Apple record: the app is signed ad hoc with the
sandbox entitlements, which enforces the sandbox on this Mac. Tasks 8 and 9 need the owner's
App ID, profiles and App Store Connect record.

1. `--store` switch in the build, store entitlements, edition recorded in `build_info.json`.
2. Pipeline without worker processes.
3. Model checkpoints loaded as data only (two readers fell back to unrestricted loading).
4. Wrapper in the sandbox: MIME types, data location in the container, no Python files in it.
5. Bookmarks for a data location outside the container.
6. Interface: no plugins, updater, update check or Discord presence; download prompt; privacy
   link.
7. Verification of the sandboxed build on this Mac, ending with the owner's VoiceOver pass.
8. Store signing, provisioning profile, metadata, `itms-services` removal, SDK check.
9. Upload to App Store Connect, TestFlight, the store record, submission.
10. Optional: a test of a process channel that works in the sandbox, for real-time conversion.

## 6. Decisions

Each one says what changes with the answer. The recommendation is the plan's default.

1. **Name and icon (guideline 4.1 (c)).** Either IAHispano's written approval to use "Applio"
   and the icon, or a different name and icon. The plan takes both as build inputs
   (`--app-name`, `--icon`). A different name would also want different wording inside the
   app, which is not in this plan. Recommended: ask upstream first.
2. **Bundle id.** Upstream's `com.iahispano.applio`, or the owner's own (reverse-domain of a
   domain the owner controls). The two editions can then sit side by side, each with its own
   container, preferences and logs. Recommended: the owner's own id.
3. **Copyleft parts.** `soxr` cannot simply be dropped (inference and preprocessing use it).
   `edge-tts` is the text-to-speech feature. Options: accept both knowingly, with their
   licences named in an acknowledgements screen and their sources offered; leave text to
   speech out of the store edition; or replace `soxr` with another resampler (work, and a
   quality question). The WebAssembly FFmpeg build in Gradio's frontend needs a licence check
   in any case. Recommended: accept `soxr` knowingly; text to speech is the owner's call. This
   document is not legal advice.
4. **Data location.** Default inside the container, with "Set Data Location" for any other
   folder (kept through a bookmark). Recommended: both. The bookmark on an external volume is
   the first thing task 4 proves.
5. **Real-time conversion.** Leave it out of the first store version, or rebuild its process
   channel (task 9 proves whether pipes work in the sandbox first). Recommended: leave it out.
6. **First download.** A prompted download of about 3 GB, or the conversion models (about
   0.6 GB: pitch extractors and embedder) bundled into the app with the training pretrains as
   a prompted download. Recommended: the prompted download, as assessed.
7. **Privacy policy.** A page the owner publishes; the plan uses
   `https://froggeric.github.io/applio-macOS-native-app/privacy/` (GitHub Pages of the fork).
   It must name what leaves the Mac: downloads from the hosts in section 2, and the text sent
   to Microsoft's speech service.
8. **Minimum macOS version.** 12.0 today. It can only be tested on the build Mac, so either
   keep 12.0 or raise it to a version that was tested. Recommended: keep 12.0 unless the
   upload or a test says otherwise.

## 7. Risks and unknowns

- **SDK at upload.** Apple asks each year for a recent SDK. The bootloader in the bundle was
  built with the macOS 14.2 SDK. The first upload shows whether that passes; if not, the
  bootloader is rebuilt from PyInstaller's sources with Xcode 27 (task 7). Whether Apple looks
  at the other binaries in the bundle (PyTorch and others) is unknown.
- **The review.** A reviewer meets a 3 GB download before anything works. The prompt, the
  review notes and the "Not now" path must make that plain. Whether a reviewer sees model
  files (torch checkpoints) as "code" under 2.5.2 is a judgement; the plan checks that
  downloaded models are loaded as data only.
- **Real-time conversion** (decision 5).
- **Features not yet run in the sandbox:** the interface in the window, microphone, text to
  speech, TensorBoard, model download, Voice Blender, Audio Tools. Task 6 runs them.
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
