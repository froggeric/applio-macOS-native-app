# Applio macOS Wrapper & Build

This directory contains the scripts to build Applio as a standalone native macOS application (App Bundle) using PyInstaller and PyWebview.

## Prequisites

- macOS (Apple Silicon M1/M2/M3 recommended)
- Python 3.9+ (Ideally 3.10)
- `ffmpeg` installed (for audio processing)
  - `brew install ffmpeg`

## Build Instructions

### 1. Set up Environment
Create a clean virtual environment to minimize bundle size.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements_macos.txt
```

### 2. Build the Application
Run the build script. This will use PyInstaller to package the application.

```bash
python build_macos.py
```

This process may take a few minutes. Once complete, you will find the application in:
`dist/Applio.app`

### 3. Running the App
You can run the app directly from the `dist` folder:

```bash
open dist/Applio.app
```

Or double-click it in Finder.

## Troubleshooting

### "Applio" is damaged and can't be opened
Since the app is not signed with an Apple Developer ID, macOS Gatekeeper may block it. To bypass this locally:

```bash
xattr -cr dist/Applio.app
```

### Console Debugging
The app runs without a console window. If you encounter issues, logs are written to:
`~/Library/Logs/Applio/applio_wrapper.log`

You can tail this log file to see what's happening:
```bash
tail -f ~/Library/Logs/Applio/applio_wrapper.log
```

### Microphone Access
The app requires microphone access. The `build_macos.py` script automatically patches the `Info.plist` to include the `NSMicrophoneUsageDescription`. If this fails, you may see a crash or silent failure when recording.

## Development
To test the wrapper without building:
```bash
python macos_wrapper.py
```
This typically opens the window but might fail if dependencies rely on specific PyInstaller paths (though the wrapper attempts to handle this).
