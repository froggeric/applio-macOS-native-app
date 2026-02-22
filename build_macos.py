import PyInstaller.__main__
import os
import shutil
import json
import requests

# Clean up previous builds with robustness against Spotlight locks
def clean_dir(path):
    if os.path.exists(path):
        print(f"Cleaning {path}...")
        for i in range(3):
            try:
                shutil.rmtree(path)
                return
            except Exception:
                time.sleep(1)
        os.system(f"rm -rf {path}")

import time
clean_dir("dist")
clean_dir("build")

# =================================================================
# Merge upstream pretrains.json with macOS additions
# =================================================================
def merge_pretrains():
    """Fetch upstream pretrains.json and merge with macOS-specific additions."""
    upstream_url = "https://huggingface.co/IAHispano/Applio/raw/main/pretrains.json"
    additions_path = "assets/pretrains_macos_additions.json"
    output_path = "assets/pretrains.json"

    print("Fetching upstream pretrains.json...")
    try:
        response = requests.get(upstream_url, timeout=30)
        response.raise_for_status()
        upstream_data = response.json()
        print(f"  Found {len(upstream_data)} upstream models")
    except Exception as e:
        print(f"  WARNING: Failed to fetch upstream pretrains: {e}")
        upstream_data = {}

    print("Loading macOS additions...")
    if os.path.exists(additions_path):
        with open(additions_path, 'r', encoding='utf-8') as f:
            additions_data = json.load(f)
        print(f"  Found {len(additions_data)} macOS-specific models")
    else:
        print(f"  WARNING: Additions file not found at {additions_path}")
        additions_data = {}

    # Merge: additions override/extend upstream
    merged_data = {**upstream_data, **additions_data}

    # Write merged file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(merged_data, f, indent=2, ensure_ascii=False)

    print(f"Merged pretrains.json written with {len(merged_data)} models")
    return output_path

merged_pretrains_path = merge_pretrains()

# Define build parameters
APP_NAME = "Applio"
ENTRY_POINT = "macos_wrapper.py"
ICON_FILE = "assets/ICON.ico" 

# Hidden imports common in scientific/ML stacks
HIDDEN_IMPORTS = [
    "pkg_resources",
    "packaging",
    "packaging.version",
    "packaging.specifiers",
    "packaging.requirements",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "gradio.networking",
    "gradio.themes",
    "torch",
    "numpy",
    "tensorboard",
    "tensorboardX",
    "passlib.handlers.bcrypt",
    "scipy.signal",
    "scipy.special.cython_special",
    "scipy.linalg.cy_linalg",
    "sklearn.utils._typedefs",
    "fairseq.models.wav2vec.wav2vec2",
    "fairseq.tasks.audio_pretraining",
    "fairseq.modules.checkpoint_activations",
    "fairseq.dataclass.configs",
    "soundfile",
    "_soundfile",
    "webview.platforms.cocoa",
]

# Collect data files
datas = [
    ("assets", "assets"),
    ("logs", "logs"),
    ("rvc", "rvc"),
    ("tabs", "tabs"),
    ("core.py", "."),
    ("app.py", "."),
]

# Construct --add-data arguments
add_data_args = []
for source, dest in datas:
    if os.path.exists(source):
        add_data_args.append(f"--add-data={source}:{dest}")
    else:
        print(f"WARNING: Source {source} not found, skipping.")

# Construct --hidden-import arguments
hidden_import_args = []
for lib in HIDDEN_IMPORTS:
    hidden_import_args.append(f"--hidden-import={lib}")

# PyInstaller arguments
args = [
    ENTRY_POINT,
    "--name=Applio",
    "--windowed", # No console
    "--noconfirm",
    "--clean",
    f"--icon={ICON_FILE}",
    "--collect-all=torch",
    "--collect-all=torchaudio",
    "--collect-all=gradio",      
    "--collect-all=gradio_client", 
    "--collect-all=safehttpx",    
    "--collect-all=groovy",
    "--collect-all=sounddevice",
    "--target-arch=arm64",
    "--osx-bundle-identifier=com.iahispano.applio",
] + add_data_args + hidden_import_args

# Run PyInstaller
print("Starting Applio macOS Build Sequence...")
PyInstaller.__main__.run(args)

# Post-processing Info.plist
info_plist_path = os.path.join("dist", f"{APP_NAME}.app", "Contents", "Info.plist")
if os.path.exists(info_plist_path):
    print("Patching Info.plist for Microphone access & Metadata...")
    try:
        import plistlib
        with open(info_plist_path, 'rb') as f:
            plist = plistlib.load(f)
        
        # Permissions & Usage Descriptions
        plist['NSMicrophoneUsageDescription'] = "Applio needs microphone access to record audio for voice conversion."
        plist['NSCameraUsageDescription'] = "Applio needs camera access for visual processing."
        plist['NSDesktopFolderUsageDescription'] = "Applio needs desktop access to save and load models."
        plist['NSDocumentsFolderUsageDescription'] = "Applio needs documents access to save audio exports."
        plist['NSDownloadsFolderUsageDescription'] = "Applio needs downloads access to retrieve models."
        plist['NSAppleEventsUsageDescription'] = "Applio needs apple events access for automation."
        
        # Branding
        plist['CFBundleShortVersionString'] = "3.6.0"
        plist['CFBundleVersion'] = "3.6.0"
        plist['NSHumanReadableCopyright'] = "Copyright © 2026 IAHispano. All rights reserved."
        
        # High-DPI support
        plist['NSHighResolutionCapable'] = True
        
        with open(info_plist_path, 'wb') as f:
            plistlib.dump(plist, f)
        print("Info.plist patched successfully.")
        
        # Codesign with entitlements
        entitlements_path = "assets/entitlements.plist"
        if os.path.exists(entitlements_path):
            print("Signing application with entitlements...")
            app_path = os.path.join("dist", f"{APP_NAME}.app")
            # Deep sign the bundle
            os.system(f"codesign --force --deep --sign - --entitlements {entitlements_path} {app_path}")
            print("Application signed.")
        else:
            print(f"WARNING: Entitlements file not found at {entitlements_path}")
            
    except Exception as e:
        print(f"Failed to patch Info.plist or sign app: {e}")
else:
    print(f"WARNING: Info.plist not found at {info_plist_path}")

print("Build complete. Application verified at dist/Applio.app")
