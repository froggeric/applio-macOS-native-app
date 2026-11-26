# Manual test plan: Applio macOS 3.7.2.1

**Build under test:** `3.7.2.1` (signed and notarized: `dist/Applio.app` and `dist/Applio-3.7.2.1.dmg`)
**Previous build to compare with:** `3.6.4.2`
**Your data location:** `/Volumes/ssd/ai/applio`
**Time needed:** about 45 to 60 minutes for sections 1 to 4 and 6. Training time and the optional sections come on top.

Each step says what to do and what you should see. Section 9 is the list to fill in.

## 0. Before you start

1. Test the upgrade on a copy of your data first. In Terminal:
   ```bash
   cp -cR /Volumes/ssd/ai/applio /Volumes/ssd/ai/applio-372-test
   APPLIO_DATA_PATH=/Volumes/ssd/ai/applio-372-test /Applications/Applio.app/Contents/MacOS/Applio
   ```
   That run uses the copy and leaves your saved data location untouched. Start the app normally (double-click) only once section 1 passes.
2. Keep the old app for side-by-side comparisons, under a different name.
3. Logs are in `~/Library/Logs/Applio/`: `applio_launcher.log` and `applio_wrapper.log`.
4. Already checked on this build, so you need not repeat it unless you want to: start against a separate data folder that imitated a 3.6.4 installation (old translations and scripts replaced, settings kept and completed); preprocessing; feature extraction on Metal; training with pause and resume; training again for more epochs; training from a 44 kHz RefineGAN-Legacy pretrained pair; index generation; single, batch (stopped, then completed) and RefineGAN-Legacy conversion; text-to-speech; a training started through the interface with its start and end announcements; the 13 Browse buttons in a browser.
5. Not checked on this build, so your results count most there: VoiceOver itself, the native file and folder dialogs of the Browse buttons, the buttons of the Process Dashboard, real-time conversion, and a fresh installation.

## 1. Install and first start (upgrade from 3.6.4.2)

1.1 Do: open the DMG, drag Applio to Applications (replace), open it.
Expect: it opens without a warning. One Dock icon. The loading screen shows `Applio v3.7.2.1`. The main window appears in under a minute because your models are there (about 7 seconds in the automated runs).

1.2 Do: look at the window.
Expect: a new look. A sidebar on the left lists Convert Audio, Realtime, Text to Speech, Models, Training, Voice Blender, TensorBoard, Audio Tools, Plugins, Terminal, Settings and Report a bug. The pages are built as numbered steps. Your theme and your language are kept.

1.3 Do: menu Applio, About Applio.
Expect: `Version 3.7.2.1`.

1.4 Do: menu Applio, Check for Updates.
Expect: no update is offered. The newest published release is 3.6.4.2.

1.5 Do: look into the data folder with Finder.
Expect: `assets/config_template.json` sits next to `assets/config.json`. Your settings in `config.json` are unchanged, two keys were added (`logs_dir`, `rmvpe_high_register`) and `"version"` reads `3.7.2`. `assets/i18n/languages` holds the 15 current language files; files of languages the app no longer ships may still be there, which does no harm.

1.6 Do: open the two log files.
Expect in `applio_wrapper.log`: `Version: 3.7.2.1`, `Added new default settings to …/assets/config.json`, `Gradio backend is responsive.` and `Transitioning to main UI...`. No line with `ERROR`.

## 2. Converting audio

2.1 Do: convert one file with a model you know well (RMVPE, default settings).
Expect: the result plays and sounds at least as good as with 3.6.4.2. The Terminal tab shows `Using Apple Silicon MPS for inference`.

2.2 Do: convert one file in 3.6.4.2 as well and compare.
Expect: the same character. A difference in quality is worth a report, with both files.

2.3 Do: batch-convert a folder with 10 or more files.
Expect: a toast `Batch conversion started: N files`, toasts at 25, 50 and 75 percent, then a toast with the number of converted files and the time. The Terminal tab shows the same lines.

2.4 Do: with that batch still running, open the Process Dashboard (menu Process, Open Dashboard, or ⌘⇧P).
Expect: the batch is listed as running with converted and total counts and a progress bar. Close the dashboard. The app stays usable.

2.5 Do: start the batch again on the same folder and press Stop convert after a few files.
Expect: it stops after the file in progress. The last toast says the batch was cancelled. Start the batch once more: the files already converted are skipped and the rest is converted.

2.6 Do: convert with a RefineGAN-Legacy model (one trained from the KLM50 or VCTK 44 kHz pretrains).
Expect: it loads and converts.

2.7 Do: in Convert Audio, open the advanced settings and find the Browse button next to the output path. Press it.
Expect: a macOS open or save panel opens. Choose a location: the field is filled and VoiceOver reads the new value. The two batch folders and the three fields of Text to Speech have Browse buttons too.

2.8 Do: Text to Speech tab.
Expect: speech is generated and converted.

2.9 Do: convert a long file (10 minutes or more).
Expect: it completes and memory stays reasonable.

If a conversion sounds wrong or crashes on the GPU, enter `-` in the GPU field to run it on the CPU, and say so in your report. It tells a GPU problem apart from a model problem.

## 3. Training end to end

Use a small dataset so that each step takes a few minutes.

3.1 Do: preprocess the dataset.
Expect: the job appears in the dashboard with a progress bar. The Terminal tab shows the same lines. A toast and an announcement say when it is done.

3.2 Do: extract features (RMVPE, GPU `0`).
Expect: it completes, on the GPU.

3.3 Do: train 10 to 20 epochs.
Expect: the dashboard shows the epoch, the batch bar, the speed and the best loss so far. "Started training" and later "training completed" are announced, and the completion sound plays. Model files appear in `logs/<model>/` as before.

3.4 Do: press Pause during an epoch, wait 10 seconds, press Resume.
Expect: the job shows as paused and the batch bar stops. After Resume it continues. Training finishes normally afterwards.

3.5 Do: start another training and press Stop.
Expect: training stops and the dashboard reports it. The app stays usable and a new training can be started.

3.6 Do: train the same model again for more epochs than before.
Expect: it continues from the saved epoch. The loss curve in the dashboard shows the earlier epochs too, and the best epoch is kept.

3.7 Do: generate the index, then convert a file with the new model.
Expect: both work.

3.8 Do: train at 44.1 kHz with Pretrained ticked and HiFi-GAN.
Expect: the log says no 44.1 kHz pretrains are installed and training continues without them, as on 3.6.4.2.

3.9 Do: tick Custom Pretrained and open Pretrained Custom Settings.
Expect: the two dropdowns list your downloaded custom pretrains. Each has a Browse button. Train at 44.1 kHz with a KLM50 or VCTK 44 kHz pair and vocoder RefineGAN: the log shows `Detected legacy RefineGAN architecture`, training completes and the model converts.

3.10 Do: train with less than three batches of data.
Expect: training refuses with a message about not enough data. This check is new in upstream.

3.11 Do: start a training and press ⌘Q.
Expect: the confirmation dialog appears. Confirm: training stops and the app quits. Cancel: the app and the training keep running.

## 4. Accessibility (VoiceOver)

4.1 Do: move through the sidebar and choose a page.
Expect: after each choice VoiceOver reads the page title, and the current page button is marked as current.

4.2 Do: open and close an accordion such as the advanced settings.
Expect: the header announces expanded or collapsed.

4.3 Do: run the steps of section 3 with VoiceOver on.
Expect: start, end and failure of each job are spoken once, and the converted counts of a batch are in the Last result region.

4.4 Do: select a row of the Process Dashboard while a job runs.
Expect: the row reads its job name and metrics (epoch, percent, speed).

4.5 Known limitation, no result needed: in the Realtime page, the pressed state of the record Start and Stop button is only marked when the interface language is English.

## 5. Real-time voice conversion (not tested automatically)

5.1 Do: pick the input and output devices and a model, then start.
Expect: the meters move and the converted voice is audible.

5.2 Do: stop, restart the app, return to the page.
Expect: the devices and the model you chose are still selected. Upstream saves these settings now.

5.3 Do: press Stop.
Expect: audio stops at once and the app stays responsive.

## 6. Data location and files

6.1 Do: menu File, Set Data Location, choose another folder, restart the app.
Expect: the app uses the new folder. On 3.6.4.2 this menu item had no effect.

6.2 Do: choose `/Volumes/ssd/ai/applio` back and restart.
Expect: back to normal, with all your models and settings.

6.3 Do: use the File, Open in Finder items (logs, audios, datasets, models).
Expect: each opens the right folder inside your data location.

6.4 Do: in Terminal:
   ```bash
   APPLIO_DATA_PATH=/tmp/applio-test /Applications/Applio.app/Contents/MacOS/Applio
   ```
   Expect: the app runs against that folder for this one launch, with no first-run prompt, and your saved location is untouched.

## 7. Fresh installation (optional)

Nothing here must touch your real data or settings.

7.1 Do: use a new macOS user account, or run the binary with `APPLIO_DATA_PATH` pointing at an empty folder (6.4).
Expect: the folder selection dialog appears.

7.2 Do: choose an empty folder.
Expect: the loading screen shows the model download (about 2 GB). The app reaches the main window within 10 minutes.

7.3 Do: look into the folder.
Expect: `rvc/models/` holds the pretrains, the pitch extractors (`rmvpe.pt`, `fcpe.pt`, `swift.onnx`) and the embedder.

## 8. What changed that you might notice

- The interface is new: sidebar, numbered steps, 15 languages instead of 60.
- The Terminal tab shows what preprocessing, extraction and training print. The dashboard shows the same jobs as before.
- Upstream removed the post-process effects rack, "clean audio" and noisereduce, the split-audio conversion option, and older pitch extraction methods.
- Training needs at least three batches of data.
- Files in your data location that the app ships (translations, themes, tab scripts, sample-rate configs) are replaced by the new app when they differ. Your presets and settings are kept.

## 9. Results

Fill in pass, fail or not tested for each number:

1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3.

## 10. What to include in a bug report

1. The number of the step and what you did.
2. What you expected and what happened.
3. The time it happened, with `applio_launcher.log` and `applio_wrapper.log` from that session.
4. Model, index, dataset and settings used.
5. Whether it also happens on 3.6.4.2, and whether it changes with the GPU set to `-`.
