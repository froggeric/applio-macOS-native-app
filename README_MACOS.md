# Applio macOS Native App

This directory contains the scripts to build Applio as a standalone native macOS application using PyInstaller and PyWebview.

## Prerequisites

- **macOS** (Apple Silicon M1/M2/M3 recommended)
- **Python 3.10** (required - 3.12+ has PyInstaller compatibility issues)
- **Homebrew** packages:
  ```bash
  brew install python@3.10 ffmpeg
  ```

## Quick Start

### Option 1: Build from Source

```bash
# 1. Create virtual environment
/opt/homebrew/opt/python@3.10/bin/python3.10 -m venv venv_macos
source venv_macos/bin/activate

# 2. Install dependencies (includes PyObjC, PyInstaller, Pillow)
pip install -r requirements_macos.txt

# 3. Build the app (must run from within venv_macos)
python build_macos.py

# 4. Run
open dist/Applio.app
```

> **Important:** Always run `build_macos.py` from within `venv_macos`. Running outside the venv will produce "Hidden import not found" warnings and the resulting app will be missing runtime dependencies (PyObjC, torch, gradio, etc.).

### Option 2: Development Mode

Run directly without building (useful for testing):

```bash
source venv_macos/bin/activate
python macos_wrapper.py
```

## Build Mode

The build creates a lightweight app (~1.6GB) with all user data stored externally. Models download automatically on first launch from HuggingFace:

- HiFi-GAN pretraineds: ~800MB
- RefineGAN pretraineds: ~600MB
- F0 predictors (rmvpe, fcpe): ~214MB
- Embedders (contentvec): ~361MB

**Total first-launch download: ~2GB**

## Versioning

Version format: `{APPLIO_VERSION}.{BUILD_NUMBER}`

Example: `3.6.0.1` = Applio 3.6.0, build 1

```bash
# Increment build number
python build_macos.py --build-number 2
```

## DMG Creation

Create a distributable DMG installer:

```bash
# Basic DMG (ad-hoc signed, for personal use)
python build_macos.py --dmg

# For GitHub Releases (signed and notarized)
python build_macos.py --sign --dmg --notarize
```

Output: `dist/Applio-{version}.dmg`

## Models Installer App

For users who want to pre-install all models before launching the main app (or for preservation/offline use), you can create a standalone installer app that bundles all models from the project directory:

```bash
# Build the models installer app
python build_macos.py --models-installer

# Signed version for distribution
python build_macos.py --models-installer --sign
```

Output: `dist/ApplioModelsInstaller.app` (~6.2 GB)

**Note:** The models installer is a standalone .app - no DMG, PKG, or archive needed. Just distribute the .app directly.

### How it Works

1. Double-click `ApplioModelsInstaller.app` to run
2. If you've run Applio before, it shows your existing data location and asks for confirmation
3. If not, it prompts you to select where to store models (with "New Folder" button)
4. Copies all bundled models to the selected location
5. Done - launch Applio and start using voice conversion

### Shared Preferences

Both `Applio.app` and `ApplioModelsInstaller.app` share the same preferences domain (`com.iahispano.applio`), so:
- Running the installer after using Applio will show your existing location
- Running the installer first will pre-configure Applio's data location

### Use Cases

- **Offline installation** - No internet required after downloading the app
- **Preservation** - Models are bundled, protecting against upstream removal
- **Faster setup** - No ~2GB download on first app launch
- **Multiple machines** - Copy the installer app to other machines

### Included Models (21 files, ~5.8 GB)

| Category | Sample Rate | Models |
|----------|-------------|--------|
| **HiFi-GAN Default** | 32k, 40k, 48k | f0D32k, f0G32k, f0D40k, f0G40k, f0D48k, f0G48k |
| **HiFi-GAN Custom** | 48k | KLM49 (D+G), TITAN_Medium (D+G) |
| **RefineGAN Default** | 24k, 32k | f0D24k, f0G24k, f0D32k, f0G32k |
| **RefineGAN Custom** | 44k | KLM50_exp1 (D+G), VCTK_v1 (D+G) |
| **F0 Predictors** | - | rmvpe.pt, fcpe.pt |
| **Embedders** | - | contentvec (pytorch_model.bin, config.json) |

## Model & Index Merger Tool

The `merge_rvc.py` script is a standalone CLI tool for merging RVC voice models and FAISS indexes. It creates a complete merged voice from two source models, with automatic output naming and full metadata tracking.

### Quick Start

```bash
# Activate the environment
source venv_macos/bin/activate

# Simplest usage - auto-naming from model metadata, auto output directory
python merge_rvc.py \
    --model-a '/path/to/Sade/Sade.pth' \
    --model-b '/path/to/Ani Lorak/AnilorakV2.pth' \
    --index-a '/path/to/Sade/Sade.index' \
    --index-b '/path/to/Ani Lorak/AnilorakV2.index'

# This creates:
#   ./Sade + Ani Lorak (0.50)/
#   ├── Sade + Ani Lorak (0.50).pth
#   ├── Sade + Ani Lorak (0.50).index
#   └── metadata.json
```

### All Parameters

| Parameter | Description |
|-----------|-------------|
| `--model-a` | Path to first model (.pth) |
| `--model-b` | Path to second model (.pth) |
| `--ratio` | Blend ratio (0.0–1.0), higher = more of model A (default: 0.5) |
| `--name` | Custom name for the merged model (default: auto-derived from source metadata/folder) |
| `--output-dir` | Output directory, created if needed (default: `./<merge_name>`) |
| `--output` | Explicit output path for merged .pth (overrides `--output-dir`) |
| `--index-a` | Path to first index (.index) |
| `--index-b` | Path to second index (.index) |
| `--index-output` | Explicit output path for merged .index |
| `--use-weighted` | Weight index concatenation by ratio (replicate dominant model's vectors) |
| `--random-seed` | Seed for reproducible shuffling (default: 42) |
| `--dry-run` | Validate compatibility without creating output files |

### Auto-Naming

When `--name` is not specified, the merge name is derived automatically:

1. **Source metadata.json** - reads `metadata.json` next to each model file and extracts the `title` field, stripping parenthetical context like "(Israeli Singer)" and suffixes like "[RVC V2] [450 Epochs]"
2. **Parent folder name** - falls back to the containing folder name (strips `-Weights`, `-Weights-2`, `_v2` suffixes)
3. **Filename stem** - last resort, strips FAISS naming prefixes

Examples:
- Models with `metadata.json` titles "Sade" and "Ani Lorak (Ukrainian Singer)" → `"Sade + Ani Lorak (0.50)"`
- Models with `metadata.json` titles "Hanan Ben Ari" and "Zucchero" → `"Hanan Ben Ari + Zucchero (0.50)"`
- Models without metadata, folders "Hanan Ben Ari - Weights" and "Zucchero - Weights-2" → `"Hanan Ben Ari + Zucchero (0.50)"`

### Output Directory Structure

```
Tina Daya/
├── Tina Daya.pth          # Merged model (457 weight layers, ~55 MB)
├── Tina Daya.index        # Merged FAISS index (768-dim vectors, ~450–570 MB)
└── metadata.json          # Full merge provenance (see below)
```

The output directory is created automatically. If `--output-dir` is not set, the merge name is used as the folder name in the current working directory.

### Merge Metadata

A `metadata.json` is automatically written to the output directory containing full provenance:

```json
{
  "title": "Tina Daya",
  "type": "merged",
  "merge": {
    "ratio": 0.5,
    "weighted_index": false,
    "random_seed": 42,
    "merged_at": "2026-03-17T16:38:38Z"
  },
  "source_a": {
    "path": "/Volumes/ssd/ai/rvc/Sade/Sade.pth",
    "size_bytes": 55193209,
    "md5": "dc6f367b489d66724353dc916d223548",
    "title": "Sade",
    "author": {"name": "tatersalad6636"},
    "description": "I doubled the epochs from 500 to 1000...",
    "tags": ["RVC v2", "English", "Artist", "Singer"],
    "torch_version": "v2",
    "torch_f0": 1,
    "torch_info": "1000epoch",
    "torch_sr": "40k"
  },
  "source_b": {
    "path": "/Volumes/ssd/ai/rvc/Ani Lorak/AnilorakV2.pth",
    ...
  },
  "model": {
    "layers": 457,
    "sample_rate": "40000",
    "f0": 1,
    "version": "v2",
    "vocoder": "HiFi-GAN",
    "size_bytes": 55218763,
    "md5": "c0ca5117a029c920947a61d920203169"
  },
  "index": {
    "vectors": 146980,
    "dimension": 768,
    "mode": "equal",
    "ratio": 0.5,
    "size_bytes": 464303979
  }
}
```

The metadata includes:
- **Merge parameters** - ratio, weighted mode, seed, timestamp
- **Source provenance** - original file paths, sizes, MD5 checksums, plus data from source `metadata.json` files (title, author, description, tags, training info)
- **Model stats** - layer count, sample rate, f0, version, vocoder, output file size/hash
- **Index stats** - vector count, dimension, mode (equal/weighted), ratio, output file size

### Usage Examples

```bash
# Custom name with automatic output directory
python merge_rvc.py \
    --model-a '/path/to/Sade/Sade.pth' \
    --model-b '/path/to/Ani Lorak/AnilorakV2.pth' \
    --name 'Tina Daya' \
    --index-a '/path/to/Sade/Sade.index' \
    --index-b '/path/to/Ani Lorak/AnilorakV2.index'
# Creates: ./Tina Daya/Tina Daya.pth, Tina Daya.index, metadata.json

# Custom output directory
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.7 \
    --name 'My Blend' --output-dir /Volumes/ssd/rvc/merged \
    --index-a a.index --index-b b.index --use-weighted
# Creates: /Volumes/ssd/rvc/merged/My Blend.pth, My Blend.index, metadata.json

# Explicit output paths (no auto-naming, no metadata.json)
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.5 \
    --output /path/to/merged.pth \
    --index-a a.index --index-b b.index \
    --index-output /path/to/merged.index

# Model only (no index merge)
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.6 \
    --name 'Blend 60-40'
# Creates: ./Blend 60-40/Blend 60-40.pth, metadata.json

# Weighted index merge (70% model A features in index)
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.7 \
    --index-a a.index --index-b b.index \
    --use-weighted --name 'A Dominant'
# Creates: ./A Dominant/A Dominant.pth, A Dominant.index, metadata.json

# Dry run - validate compatibility without creating files
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.5 --dry-run

# Weighted dry run - preview replication counts
python merge_rvc.py \
    --index-a a.index --index-b b.index \
    --use-weighted --ratio 0.8 --dry-run
```

### Compatibility Requirements

Models must have matching:
- Sample rate (e.g., both 48kHz)
- Pitch guidance (f0 on/off)
- Model version (v1 or v2)
- Vocoder type (HiFi-GAN, RefineGAN, etc.)
- Embedder model (if specified)

Indexes must have matching dimensions (768 for standard RVC).

### How It Works

**Model Merging (.pth):**
- Linear weight interpolation: `W_merged = ratio * W_A + (1 - ratio) * W_B`
- Special handling for different speaker embedding dimensions (`emb_g.weight`)
- All 457 layers merged in float32, stored as float16
- Preserves model metadata (config, version, vocoder)

**Index Merging (.index):**
- Reconstructs all 768-dim HuBERT feature vectors from both FAISS indexes
- **Equal mode** (default): concatenates vectors 1:1, shuffles deterministically
- **Weighted mode** (`--use-weighted`): replicates dominant model's vectors with tiny noise (1e-6) to bias k-NN retrieval toward one voice
- Subsamples large datasets (>190K vectors) to stay within memory limits
- Builds new IVF,Flat index matching Applio's construction formula

**Output metadata.json:**
- Reads source `metadata.json` files for provenance (title, author, training info, tags)
- Computes MD5 checksums of source and output files
- Records all merge parameters and output statistics

### Dependencies

- `torch` - Model loading/saving
- `faiss-cpu` - Index manipulation
- `numpy` - Array operations

All dependencies are included in the Applio virtual environment. For full technical details, see `MERGE_ALGORITHM.md`.

## Code Signing & Notarization

### Prerequisites

1. Apple Developer account (paid)
2. **Developer ID Application** certificate installed in Keychain
3. An **App Store Connect API key** stored as a notarytool keychain profile (`applio-notarize`)

### Setting Up Signing

1. **Install the Developer ID Application certificate** (Xcode is fastest):
   - Xcode → Settings → Accounts → your Apple ID → **Manage Certificates…** → **+ → Developer ID Application**.
   - (Manual: Keychain Access → Certificate Assistant → Request a Certificate from a Certificate
     Authority → upload the CSR at
     [developer.apple.com](https://developer.apple.com/account/resources/certificates/list) →
     "Developer ID Application" → download + double-click.)
   - Verify: `security find-identity -v -p codesigning` → shows
     `Developer ID Application: Your Name (TEAMID)`.

2. **Create an App Store Connect API key** (authenticates notarytool - use this, **not** an
   app-specific password):
   - [App Store Connect](https://appstoreconnect.apple.com) → Users and Access → Integrations →
     **App Store Connect API** → **Team Keys** → **+**. Access: **App Manager** (the minimum role
     that can submit for notarization). Download the `.p8` (one-time); note the **Key ID** and
     **Issuer ID**.

3. **Store the notarytool credentials** (one-time):
   ```bash
   xcrun notarytool store-credentials "applio-notarize" \
     --key ~/.private_keys/AuthKey_XXXXXXXXXX.p8 \
     --key-id XXXXXXXXXX \
     --issuer 11111111-2222-3333-4444-555555555555
   # Verify (lists history, submits nothing):
   xcrun notarytool history --keychain-profile "applio-notarize"
   ```

### Build Commands

| Purpose | Command |
|---------|---------|
| Local build (ad-hoc) | `python build_macos.py` |
| Signed app | `python build_macos.py --sign` |
| Signed DMG | `python build_macos.py --sign --dmg` |
| Notarized release DMG | `python build_macos.py --sign --dmg --notarize` |
| Models installer app | `python build_macos.py --models-installer` |
| Signed models installer | `python build_macos.py --models-installer --sign` |

### For GitHub Releases

```bash
# Recommended command for distribution
python build_macos.py --sign --dmg --notarize

# Output: dist/Applio-<VERSION>.dmg + dist/Applio.app (notarized + stapled, ~1.6GB)
```

### CI: signed + notarized releases via GitHub Actions

Two fork-added workflows live in `.github/workflows/`:

- **`ci-macos.yml`** - a build-only smoke test (ad-hoc, **no cert**). Path-filtered to run only on
  build-relevant changes to `main` / PRs; catches build regressions cheaply. No secrets required.
- **`release-macos.yml`** - on a pushed `v*` tag (or "Run workflow"): builds, signs, notarizes,
  staples, and attaches `Applio-<VERSION>.dmg` to the release. Auth uses the App Store Connect API
  key inline (`build_macos.py --api-key …`), so it needs no keychain on the runner. **Validated
  end-to-end 2026-07-27** (test tag → green → notarized DMG attached to the release). Each run pauses
  for **approval** (required reviewers on the `signing` environment) before it builds.

**One-time setup** (repo Settings → Environments → **create environment `signing`**, then add these
secrets **to that environment** + add **Required Reviewers** so the cert can't be exfiltrated):

| Secret | Value |
|--------|-------|
| `MACOS_CERTIFICATE` | `base64` of the Developer ID Application `.p12` - export the cert+key from Keychain Access with a password, then `base64 -i your.p12 \| pbcopy` |
| `MACOS_CERTIFICATE_PWD` | that `.p12`'s export password |
| `APP_STORE_CONNECT_KEY` | `base64` of the App Store Connect API key (`AuthKey_*.p8`) - `base64 -i AuthKey_XXXXXXXXXX.p8 \| pbcopy` |
| `APP_STORE_CONNECT_KEY_ID` | the 10-char Key ID |
| `APP_STORE_CONNECT_ISSUER` | the Issuer ID (UUID) |

**Cut a release:** bump `BUILD_NUMBER` (+ version if needed), commit to `main`, then
`git tag vX.Y.Z && git push --tags`. The workflow builds the notarized DMG and attaches it to the
release for that tag. (The upstream `release.yml` may also fire on a `config_template.json` version
bump and generate notes - `release-macos.yml` only attaches the DMG, so they coexist.)

> **Cost note:** macOS runners bill at ~10× Linux minutes and are metered even on public repos.
> The release build is ~40–60 min; the build-only CI ~20 min. That's why `ci-macos.yml` is
> path-filtered and `release-macos.yml` runs only on tags.

## Build Output

| Output | Size | Notes |
|--------|------|-------|
| `dist/Applio.app` | ~820MB | LITE mode, models download on first launch |
| `dist/Applio-{version}.dmg` | ~820MB | Signed/notarized DMG for distribution |
| `dist/ApplioModelsInstaller.app` | ~6.2GB | Bundled models installer (standalone .app) |
| `build/` | - | PyInstaller intermediates (can be deleted) |

**Note:** You can build the models installer without deleting the main app - both can coexist in `dist/`.

## File Locations

### User Data Location (First-Run Selection)

On first launch, the app prompts for a data storage location. This location stores all training outputs, datasets, voice models, and inference outputs.

Default: `~/Applio/`

Preferences stored in: `~/Library/Preferences/com.iahispano.applio.plist`

**Note:** Both `Applio.app` and `ApplioModelsInstaller.app` share this preferences file, allowing the installer to use your existing data location.

### Cache Locations (Fixed)

These cache locations are fixed and separate from user data:

| Purpose | Location |
|---------|----------|
| **HuggingFace Cache** | `~/Library/Application Support/Applio/huggingface/` |
| **Temp files** (Gradio) | `~/Library/Caches/Applio/` |
| **Logs** | `~/Library/Logs/Applio/applio_wrapper.log` |

### Data Directory Structure

The user data location contains:

```
~/Applio/                          # User-selected location
├── logs/                           # Training outputs, voice models
│   ├── {model_name}/               # Per-model training data
│   │   ├── sliced_audios_16k/      # Preprocessed audio
│   │   ├── f0/, f0_voiced/         # Pitch extraction
│   │   ├── extracted/               # Feature embeddings
│   │   └── *.pth, *.index          # Model weights, feature index
│   └── zips/                        # Downloaded model archives
├── assets/
│   ├── datasets/                   # Training datasets
│   ├── audios/                     # Inference outputs
│   └── presets/                    # Effect presets
└── rvc/
    ├── configs/                    # Sample rate configs (copied at startup)
    │   ├── 24000.json
    │   ├── 32000.json
    │   ├── 40000.json
    │   ├── 44100.json
    │   └── 48000.json
    ├── lib/tools/
    │   └── tts_voices.json         # TTS voice list (copied at startup)
    └── models/
        ├── pretraineds/             # Pretrained models
        │   ├── hifi-gan/           # HiFi-GAN vocoders
        │   ├── refinegan/           # RefineGAN vocoders
        │   └── custom/              # Downloaded community models
        ├── embedders/               # ContentVec embedders
        ├── predictors/              # F0 predictors (rmvpe.pt, fcpe.pt)
        └── formant/                 # Formant shift models
```

**Note:** Static resources (configs, tts_voices.json) are copied from the app bundle to the user data location on first launch. This avoids modifying upstream code while ensuring relative paths work after the working directory change.

### Changing Data Location

Use **File → Set Data Location...** in the menu bar. Requires app restart.

## Pretrained Models

### Pretrained Models (Auto-downloaded)

Models are downloaded on first launch to the user's data location:

| Category | Sample Rates | Size |
|----------|--------------|------|
| HiFi-GAN | 32k, 40k, 48k | ~800MB |
| RefineGAN | 24k, 32k | ~600MB |
| F0 Predictors | rmvpe.pt, fcpe.pt | ~214MB |
| Embedders | contentvec | ~361MB |

### Custom Models (Download Tab)

Additional models available via Download tab in the app:
- Merged from upstream `pretrains.json` + `assets/pretrains_macos_additions.json`
- Downloaded to `rvc/models/pretraineds/custom/`
- Access via "Custom Pretrained" checkbox in Training tab

### Choosing the Right Pretrain (2026 Studio Standards)

#### 1. Female Singing (Pop, Anime, Soprano/Mezzo)
**Goal:** Brightness, breath support, soaring high notes, glossy "expensive microphone" sheen.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | RefineGAN KLM50 exp1 44k | The absolute king for female pop. RefineGAN eliminates high-frequency metallic phase buzz that ruins female belts. |
| **#2** | HiFi-GAN KLM49 48k | Best natively supported option. 48kHz captures the "air" of a female voice beautifully. |
| **#3** | Ov2Super 40k | If your female dataset is very small (under 3 minutes), adapts faster without sounding robotic. |

#### 2. Deep Male Singing (Baritone, Bass, Rock)
**Goal:** Chest resonance, thickness, stability in low-mids (100-300Hz).

| Rank | Model | Why |
|------|-------|-----|
| **#1** | HiFi-GAN TITAN 48k Medium | Undisputed champion for deep voices. Gives baritone voices thick, natural chest resonance. |
| **#2** | HiFi-GAN KLM49 48k | Excellent for softer, breathier songs (ballads). |
| **#3** | RefineGAN VCTK 44k | Very neutral. Ensures low frequencies stay tight without getting muddy. |

#### 3. High Male Singing (Tenor, R&B, K-Pop)
**Goal:** Smooth chest-to-head transitions, clean falsetto, dynamic range.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | HiFi-GAN KLM49 48k | Tenor vocals thrive on this model. Handles falsetto transitions beautifully. |
| **#2** | RefineGAN KLM50 exp1 44k | Flawless phase coherence on extreme high notes. |
| **#3** | HiFi-GAN TITAN 48k | Use if tenor sounds too "thin" on KLM. TITAN anchors with more body. |

#### 4. Spoken Word, Podcasting, Narration
**Goal:** Intelligibility, zero musical artifacts, neutral tone.

| Rank | Model | Why |
|------|-------|-----|
| **#1** | RefineGAN VCTK 44k | VCTK is a speech dataset, so it doesn't add musical vibrato to spoken words. |
| **#2** | HiFi-GAN TITAN 48k | Excellent for deep, rich "Radio Announcer" voice. |
| **#3** | HiFi-GAN KLM49 48k | Can make speakers sound like they're slightly singing, good for anime dubbing. |

## Sample Rate Support

The macOS build patches the training UI at build time to support additional sample rates:

| Rate | HiFi-GAN | RefineGAN | Notes |
|------|----------|-----------|-------|
| 24kHz | - | ✓ | Default |
| 32kHz | ✓ | ✓ | Default |
| 40kHz | ✓ | - | Default |
| 44.1kHz | ✓* | ✓* | Patched (custom models) |
| 48kHz | ✓ | - | Default |

*44.1kHz requires custom pretrained models (KLM50 exp1, VCTK v1)

## Accessibility

Applio is screen-reader-ready out of the box — nothing to configure.

### VoiceOver

Turn VoiceOver on (⌘F5) and Applio speaks automatically. Every job announces its start, progress
milestones (25/50/75% during batch conversions), and completion or failure — conversions (single
and batch), training (including preprocessing and feature-extraction), TTS, model downloads,
voice blending, plugin installs, and realtime conversion. Speech follows VoiceOver: verbose while
it runs, silent otherwise, adapting within a couple of seconds if you toggle it mid-session.

### Visual cues

- Completion and failure toasts appear for every job.
- Output changes (converted audio, reports, statuses) are echoed in a persistent "Last result"
  region, so the latest outcome stays readable after the moment passes.

### Progress monitoring

- **Process → Active Processes** (menu bar) lists live jobs with inline progress —
  "Inference: model — 43% (2/3 files)", "Training: model — epoch 34/200" — refreshed every
  2 seconds; choosing an entry opens the Progress Dashboard.
- **Progress Dashboard** (⌘⇧P): each run's row reads its live metrics (epoch, best loss, ETA;
  inference files converted and percent), the progress bar announces "Epoch 34 of 200, 45 percent"
  instead of a bare percentage, Tab moves between the runs list and the action buttons, and
  selecting a row speaks its summary.

### Paths

Every path field has a **Browse…** button that opens a native macOS folder/file picker. Typed
paths are validated when you leave the field — a missing or wrong-type path produces a spoken
warning toast.

### Hidden preferences (advanced)

Two escape hatches exist as hidden preference keys (defaults: `auto` and on):

```bash
# Speech: "auto" (VoiceOver-gated, default), "on" (always), or "off" (never)
defaults write com.iahispano.applio a11y.speech -string auto
# Disable the completion/failure sound cue
defaults write com.iahispano.applio a11y.sound_cues -bool false
```

The language picker shows each language in its own spelling (Français, 日本語, …) while the
saved setting stays the raw locale code — part of the same accessibility work, contributed
upstream as IAHispano/Applio #1281. File dropdowns (models, audio paths) likewise show
friendly names rather than raw paths, contributed upstream as #1280; with a screen reader
each option reads as its name instead of a long file path.

## Architecture

### Bundle layout
```
Applio.app/
├── Contents/
│   ├── MacOS/Applio          # PyInstaller bootloader → applio_launcher.py (entry)
│   ├── Frameworks/           # Python.framework + all bundled packages (.so/.dylib)
│   ├── Resources/            # tabs/, assets/, rvc/, core.py, app.py, macos_wrapper.py + build_info.json
│   ├── Info.plist            # metadata, usage descriptions, version, LSMinimumSystemVersion
│   └── _CodeSignature/       # Developer ID signature + notarization staple
```
User data (models, datasets, training output) lives in the user-selected external location, **not** the bundle.

### Runtime: a single native process
The app runs as **one process**. `applio_launcher.py` is the `.app` EXE (**Regular** activation
policy): it owns the dock icon, menu bar, and `NSApplicationDelegate`, and hosts the Gradio UI in a
**pywebview** `WKWebView` in the same process (Gradio runs in-process on a daemon thread, port 6969;
loading screen on 5678). It re-execs as training/preprocess/extract **subprocesses** (the entry
detects `argv[1].endswith('.py')` and `runpy.run_path`s the script, so upstream's
`Popen([sys.executable, script])` works against the frozen binary).

One process means one dock icon, one menu bar, and one window, with none of the quirks of the old
two-process layout: Hide actually hides the window, and the menu bar no longer swaps depending on
which window is frontmost. (The previous two-process layout and the `APPLIO_SINGLE_PROCESS` flag
were removed in 3.6.3.7; single-process is now the only architecture.)

### Native Menu

The menu bar is defined once in `menu_spec.py` and rendered by both the bundled app and the
standalone dev wrapper, so they stay in sync. Five menus:

| Menu | Items |
|------|-------|
| **Applio** | About, Check for Updates…, Hide ⌘H, Quit ⌘Q |
| **File** | Set Data Location…, Reveal in Finder (logs / datasets / audios / models / …) |
| **Process** | Active Processes — live jobs with progress (e.g. `Inference: model — 43% (2/3 files)`); selecting one opens the dashboard — + Open Progress Dashboard ⌘⇧P + Open Debug Logs… ⌘L (the pause/resume/stop controls live in the dashboard - see below) |
| **Window** | Minimize ⌘M, Zoom, Show Main |
| **Help** | Studio Production Guide, Online Docs, Report an Issue, Discord |

**Dynamic behavior (bundled app only):** the launcher binds the keyboard shortcuts and runs a
2 s `NSTimer` that refreshes the Active Processes entries and enables each Reveal-in-Finder item only
when its folder actually exists. The **File → data items are disabled until first run** (i.e. until
you've chosen a data location).

**Standalone dev mode** (`python macos_wrapper.py`) shows a **static subset** of the same menu:
pywebview's `Menu`/`MenuAction` are immutable, so it has no keyboard shortcuts and no live Process
status. For the full dynamic menu, run the built app.

**Update checking:** `Check for Updates…` queries GitHub Releases and shows a tri-state NSAlert
(newer / up-to-date / error). A **silent launch-time check** also runs and alerts you **only** if a
newer version exists. Version comparison uses `packaging.version` (the old string compare falsely
flagged downgrades as updates). Network runs off the main thread.

### Process Dashboard

Open from **Process → Open Progress Dashboard** (⌘⇧P). It is a live window that follows a training
run while it runs, and keeps finished runs so you can review them later.

- **Real-time metrics:** best epoch and its loss, current/total epoch, step, speed, and a derived
  ETA, beside an epoch-fraction progress bar.
- **Loss-vs-epoch curve:** plots evaluation loss per epoch and **highlights significant improvements**
  (green markers at notable loss drops), so your model's best checkpoint is visible at a glance.
- **Controls:** Stop, Pause / Resume, Reveal Log in Finder, and Open Log.
- **Durable best epoch:** best-epoch metrics are snapshotted into history, so they survive an app
  restart and re-training the same model.
- **Auto-show:** the dashboard opens itself when a job starts.
- **History:** when no job is running, browse the metrics of finished runs.
- **Batch inference:** converting a folder of audio shows the same live card (files converted / total,
  current file, ETA, speed), auto-opens on start, and finished or cancelled batches appear in history
  with their counts. Stop cancels at the next file without quitting the app.
- **Quit protection:** quitting (⌘Q or closing the window) while a conversion runs asks for
  confirmation first; a confirmed quit cancels the job cooperatively instead of killing it
  mid-file.

The dashboard runs in the app process and parses the training log directly (no RVC import), so it
works identically in dev mode and the frozen app.

### Frozen-CWD invariant
In the frozen app the working directory is the bundle, not the data dir - so upstream's CWD-relative
paths (`logs/`, `assets/config.json`, dataset folders) break. The wrapper does `os.chdir(DATA_PATH)`
before importing Gradio, and build-time patches (`patches/patch_*.py`) resolve paths absolutely via
`APPLIO_DATA_PATH` → `runtime_paths.json` → `~/Applio`. This is the root cause behind most
"works in dev, fails frozen" bugs.

### Build-time patches (minimal upstream delta)
Upstream files are **never** edited in the repo. `build_macos.py:pre_build_patch()` applies
`patches/*.py` to the source just before PyInstaller, then `post_build_restore()` reverts them - so
`git status` stays clean. See "Fork Modifications" below.

### Lite build
The default build is **lite**: `clean_bundled_models()` strips model weights from the bundle
(~1.6 GB without models); ~2 GB of models download on first launch. Local `rvc/models/` is never
touched. (A model-bundled build is the separate `--models-installer` app.)

### Signing & notarization pipeline (technical)
`build_macos.py --sign --notarize --dmg` runs, in order, each step gating the next:
1. **Inside-out sign** - discover every Mach-O under `Contents/{Frameworks,Resources,MacOS}`
   (including bare executables the old `*.so`/`*.dylib` glob missed), sign each leaf with
   `--options runtime --timestamp` (**no** entitlements on leaves), then seal the outer bundle with
   `assets/entitlements.plist` (**no** `--deep`). Hard-fail `codesign --verify`.
2. **Notarize `.app`** - `ditto`-zip → `xcrun notarytool submit --keychain-profile applio-notarize
   --wait` → parse `status: Accepted` (auto-pull the JSON log on failure, which names the offending binary).
3. **Staple `.app`** - `xcrun stapler staple` + `validate`.
4. **Build + sign `.dmg`** from the **stapled** app - `shutil.copytree(symlinks=True)` preserves the
   `Python.framework` symlinks; sign the DMG with `codesign --timestamp` (no runtime/entitlements).
5. **Notarize `.dmg`** → **staple `.dmg`**.
6. **Final Gatekeeper gate** - `spctl` + `stapler validate` must report `source=Notarized Developer ID`.

Authentication is an App Store Connect **Team Key** (role **App Manager**) stored via
`xcrun notarytool store-credentials` - **no secrets live in the repo** (the `.p8` stays outside it,
and `.gitignore` excludes `*.p8`/`*.p12`/`*.key`).

## Fork Modifications (Build-Time Patches)

This fork maintains minimal delta from upstream by patching at build time.

**Fork-only files (can be modified directly):**
- `applio_launcher.py` - Native macOS launcher with progress monitoring (NEW)
- `build_macos.py` - Build script for app bundling (NEW)
- `macos_wrapper.py` - Native window wrapper (NEW)
- `models_installer.py` - Standalone models installer (NEW)
- All `patches/*.py` files (NEW)

**Upstream files (must use build-time patches):**
- `core.py`, `tabs/train/train.py`, `rvc/train/train.py`, etc.
- These are patched during build, then restored to keep repo clean
- Never modify these files directly - always use patches

| Patch | File | Purpose |
|-------|------|---------|
| 44100 Hz support | `patches/patch_train_44100.py` | Patches `tabs/train/train.py` to add 44.1kHz option |
| Data paths | `patches/patch_data_paths.py` | Patches `core.py` to use `now_dir` instead of `__file__` for `logs_path` |
| Pretrained merging | `build_macos.py` | Merges upstream `pretrains.json` + `assets/pretrains_macos_additions.json` |
| App bundling | `build_macos.py` | PyInstaller build with signing, DMG, notarization |
| Native wrapper | `macos_wrapper.py` | PyWebview native macOS window with external data location support |
| Native dialogs | `macos_wrapper.py` | All dialogs use native macOS NSAlert/NSWindow (About, Updates, Progress) |
| Static resources | `macos_wrapper.py` | Copies configs and tts_voices.json to user data at startup |
| RefineGAN-Legacy | `patches/patch_refinegan_legacy*.py` | Support for original RVC-Boss RefineGAN pretrained models |

**No upstream source files are modified in the repo** - all changes happen during the build process or at runtime startup.

### Fork-Only Files

| File | Purpose |
|------|---------|
| `applio_launcher.py` | Native macOS launcher with progress monitoring window |
| `build_macos.py` | Main build script (app, DMG, models installer) |
| `macos_wrapper.py` | Native window wrapper with external data location, native dialogs |
| `models_installer.py` | Standalone models installer (shares preferences with main app) |
| `merge_rvc.py` | Standalone CLI tool for merging voice models and FAISS indexes |
| `install_applio_mac.sh` | Standalone installation script |
| `Applio.spec` | PyInstaller config (generated, gitignored) |
| `ApplioModelsInstaller.spec` | Models installer PyInstaller config (generated) |
| `patches/patch_train_44100.py` | Adds 44100 Hz option to training UI |
| `patches/patch_data_paths.py` | Redirects logs_path to external data location |
| `patches/patch_refinegan_legacy*.py` | RefineGAN legacy model support patches |
| `patches/patch_process_tracking.py` | Process tracking for training monitoring |
| `patches/download_pretraineds.py` | Downloads custom pretrained models |
| `assets/pretrains_macos_additions.json` | Additional pretrained model definitions |
| `assets/entitlements.plist` | Code signing entitlements |
| `assets/loading.html` | Loading screen HTML |
| `requirements_macos.txt` | macOS-specific dependencies |
| `README_MACOS.md` | This documentation |
| `FORK_DIFFERENCES.md` | Fork vs upstream documentation |

## Entitlements

The app is signed with entitlements from `assets/entitlements.plist`:

| Entitlement | Value | Purpose |
|-------------|-------|---------|
| `app-sandbox` | false | Not sandboxed (Developer ID distribution; needs free filesystem access) |
| `device.camera` | true | Camera (declared) |
| `files.user-selected.read-write` | true | User-chosen data/model folders |
| `files.downloads.read-write` | true | Downloads folder |
| `network.client` | true | Outbound HTTPS (model downloads) |
| `network.server` | true | Gradio local server (6969/5678) |
| `automation.apple-events` | true | Automation (declared) |
| `cs.allow-jit` | true | Python/PyTorch under hardened runtime |
| `cs.allow-unsigned-executable-memory` | true | ctypes/libffi (required for PyInstaller+Python) |
| `cs.disable-library-validation` | true | Load bundled third-party .dylib/.so (PyInstaller) |

No `device.audio-input` - audio is captured by the browser in the Gradio UI, not the app process.
These entitlements are applied only to the outer `.app` bundle/main executable; leaf `.so`/`.dylib`
binaries are signed with hardened runtime + timestamp only.

## Troubleshooting

### "Applio" is damaged and can't be opened

For ad-hoc signed builds, bypass Gatekeeper:

```bash
xattr -cr dist/Applio.app
```

For signed/notarized builds, this shouldn't occur.

### App hangs on first launch

First launch downloads models (~2GB for lite build). Check progress:

```bash
tail -f ~/Library/Logs/Applio/applio_wrapper.log
```

### Backend timeout / App closes before starting

The wrapper waits up to 10 minutes for the backend. If needed, edit `macos_wrapper.py` and increase `timeout=600`.

### ModuleNotFoundError: No module named 'pkg_resources'

Requires `setuptools<70`:

```bash
pip install "setuptools<70"
```

### Build shows "Hidden import 'xxx' not found" warnings

This happens when building outside the virtual environment. Always build from within `venv_macos`:

```bash
source venv_macos/bin/activate
python build_macos.py
```

### Build fails with "No module named 'requests'" or icon conversion error

These dependencies are required for the build process. Ensure you've installed all requirements:

```bash
source venv_macos/bin/activate
pip install -r requirements_macos.txt
```

### App fails with "AppHelper is not defined" or "Native APIs not available"

PyObjC is not bundled correctly. This happens when building outside `venv_macos`. Rebuild from within the virtual environment where PyObjC is installed.

### No microphone access / silent recording failure

Grant permission in **System Settings → Privacy & Security → Microphone → Enable Applio**

### Custom pretrained not showing in training

1. Download via Download tab
2. Enable "Custom Pretrained" checkbox in Training tab
3. Select G and D files from dropdowns

### Code signing fails

Verify certificate is installed:

```bash
security find-identity -v -p codesigning
```

Should show your "Developer ID Application" certificate.

### Notarization fails

The build auto-pulls and prints the JSON log on failure (it names the offending binary). To debug:

1. Verify the keychain profile works:
   ```bash
   xcrun notarytool history --keychain-profile "applio-notarize"
   ```
2. Check [Apple System Status](https://developer.apple.com/system-status/) for outages.
3. Review the notarization log for a given submission:
   ```bash
   xcrun notarytool log <submission-id> --keychain-profile "applio-notarize"
   ```

## Build Requirements

| Package | Purpose |
|---------|---------|
| `pyinstaller>=6.3.0` | App bundling |
| `pywebview>=5.0` | Native window |
| `pyobjc-framework-Cocoa` | macOS integration |
| `pyobjc-framework-AVFoundation` | Microphone permissions |
| `Pillow` | Icon conversion |
| `setuptools<70` | pkg_resources support |

All included in `requirements_macos.txt`.

## Release Checklist

### A. Cut a release via CI (recommended)

`release-macos.yml` builds, signs, notarizes, and staples on a GitHub macOS runner and attaches the
DMG to the release automatically.

1. Bump `BUILD_NUMBER` in `build_macos.py` (and `version` in `assets/config_template.json` if the
   Applio release changed). This drives `VERSION` (→ `Applio-<VERSION>.dmg`) and the derived
   `CFBundleVersion`.
2. Commit and push to `main`.
3. Push a tag matching the version - `git tag v<VERSION> && git push --tags` - which triggers
   `release-macos.yml`.
4. **Approve the run** (the `signing` environment uses required reviewers): Actions tab → the run →
   *Review deployments* → tick `signing` → *Approve and deploy*.
5. ~15 min later: a signed + notarized + stapled `Applio-<VERSION>.dmg` is attached to the release.
   The workflow's verify step already asserts Gatekeeper; optionally confirm after download:
   ```bash
   xcrun stapler validate "Applio-<VERSION>.dmg"     # the DMG (authoritative DMG check)
   spctl -vvv --assess --type execute "Applio.app"    # after mounting the DMG (→ Notarized Developer ID)
   ```

### B. Cut a release locally (fallback)

Use this if CI is unavailable or you want the artifact immediately.

1. Ensure the **Developer ID Application** cert is in Keychain and the `applio-notarize` notarytool
   profile exists.
2. Build, sign, notarize, staple (both `.app` and `.dmg`):
   ```bash
   venv_macos/bin/python build_macos.py --sign --notarize --dmg
   ```
   (For inline API-key auth without a keychain profile - e.g. headless - add
   `--api-key <file.p8> --api-key-id <ID> --api-issuer <UUID>`.)
3. Confirm `git status` is clean (restore any dirty upstream file with `git checkout -- <file>`).
4. Smoke-test the DMG on a clean Mac (drag to /Applications, launch - opens **without** `xattr -cr`).
5. Create the release and upload the DMG:
   ```bash
   gh release create v<VERSION> "dist/Applio-<VERSION>.dmg" --generate-notes
   # if `gh release` 403s on scope: create via `gh api .../releases -X POST -f tag_name=v<VERSION>`,
   # then curl-upload the asset to uploads.github.com (see CLAUDE.md "GitHub releases").
   ```

> **Verification reference (either path):** the `.app` must report `source=Notarized Developer ID`
> under `spctl`; the `.dmg` is verified with `xcrun stapler validate` (spctl on a disk image says
> "rejected … does not seem to be an app" - that's expected, not a failure).
