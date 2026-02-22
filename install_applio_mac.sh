#!/bin/bash
set -e # Exit immediately if any command fails

# ==========================================
# Applio macOS installer
# Version: 1.9
# Target: Apple Silicon & Intel
# ==========================================

# --- Configuration ---
INSTALL_DIR="applio"
PYTHON_VERSION="3.10"
REPO_URL="https://github.com/IAHispano/Applio.git"

# --- Colors for UI ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}Starting Applio Installation...${NC}"

# --- 1. Pre-flight Checks ---

if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}Error: This script is for macOS only.${NC}"
    exit 1
fi

# Check for Xcode Command Line Tools (Required for compiling fairseq/pyworld)
if ! xcode-select -p &>/dev/null; then
    echo -e "${RED}Error: Xcode Command Line Tools are missing.${NC}"
    echo "Please run: xcode-select --install"
    echo "Follow the pop-up instructions, then re-run this script."
    exit 1
fi

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo -e "${RED}Error: Homebrew is required.${NC}"
    echo "Please install it from https://brew.sh/"
    exit 1
fi

# Optimization: Cache Brew Prefix
BREW_PREFIX=$(brew --prefix)

# --- 2. Install System Dependencies ---
echo -e "${GREEN}📦 Installing build tools and libraries...${NC}"

# Detailed dependency breakdown:
# git-lfs: Handle large model files (Git Large File Storage)
# cmake/rust/protobuf: Build systems required for compiling python packages from source
# libsndfile/espeak-ng: Essential audio headers for processing
# libomp: OpenMP support required by Faiss (Vector Search)
# openblas: Linear algebra acceleration for Numpy
# freetype/libpng: Headers required to build Matplotlib on M1/M2
brew install python@${PYTHON_VERSION} ffmpeg git git-lfs cmake protobuf rust libsndfile wget libomp pkg-config espeak-ng openssl openblas portaudio libmagic freetype libpng

# Initialize Git LFS
git lfs install --skip-repo

# --- 3. Set Compiler Flags (Critical for Apple Silicon) ---
# We explicitly link Homebrew libraries so pip can compile C-extensions successfully.
# Without this, packages like fairseq, pyworld, and matplotlib will fail to build.

OPENSSL_PREFIX=$(brew --prefix openssl)
OPENBLAS_PREFIX=$(brew --prefix openblas)
PORTAUDIO_PREFIX=$(brew --prefix portaudio)
FREETYPE_PREFIX=$(brew --prefix freetype)
LIBPNG_PREFIX=$(brew --prefix libpng)

export CFLAGS="-I${BREW_PREFIX}/include -I${OPENBLAS_PREFIX}/include -I${PORTAUDIO_PREFIX}/include -I${OPENSSL_PREFIX}/include -I${FREETYPE_PREFIX}/include/freetype2"
export LDFLAGS="-L${BREW_PREFIX}/lib -L${OPENBLAS_PREFIX}/lib -L${PORTAUDIO_PREFIX}/lib -L${OPENSSL_PREFIX}/lib"
export PKG_CONFIG_PATH="${BREW_PREFIX}/lib/pkgconfig:${OPENSSL_PREFIX}/lib/pkgconfig:${LIBPNG_PREFIX}/lib/pkgconfig:${FREETYPE_PREFIX}/lib/pkgconfig"

# Fixes for grpcio (Tensorboard) build failures
export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1
export GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1

# Ensure binary wheels match the OS version
if [[ $(uname -m) == 'arm64' ]]; then
    export MACOSX_DEPLOYMENT_TARGET=11.0
else
    export MACOSX_DEPLOYMENT_TARGET=10.15
fi

# --- 4. Locate Python (Keg-Only Support) ---
# Homebrew 3.10 is keg-only, meaning it is not in the global path by default.
PYTHON_CANDIDATE="${BREW_PREFIX}/opt/python@${PYTHON_VERSION}/bin/python${PYTHON_VERSION}"
if [ -f "$PYTHON_CANDIDATE" ]; then
    PYTHON_EXEC="$PYTHON_CANDIDATE"
else
    PYTHON_EXEC="${BREW_PREFIX}/bin/python${PYTHON_VERSION}"
fi

if [ ! -f "$PYTHON_EXEC" ]; then
    echo -e "${RED}Python ${PYTHON_VERSION} not found at $PYTHON_EXEC${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Using Python executable: $PYTHON_EXEC${NC}"

# --- 5. Repo Setup & Data Preservation ---
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Directory '$INSTALL_DIR' already exists.${NC}"
    echo "1) Update existing (git pull) - FAST"
    echo "2) Clean Reinstall (Backs up data, deletes app, recompiles) - SAFER"
    read -p "Choose (1/2): " choice
    
    if [ "$choice" == "2" ]; then
        echo -e "${YELLOW}Backing up user data (datasets, weights, logs)...${NC}"
        
        # Move current install to backup
        BACKUP_DIR="${INSTALL_DIR}_backup_$(date +%s)"
        mv "$INSTALL_DIR" "$BACKUP_DIR"
        
        # Clone fresh
        echo -e "${GREEN}⬇️ Cloning Applio repository...${NC}"
        git clone $REPO_URL "$INSTALL_DIR"
        cd "$INSTALL_DIR"
        git submodule update --init --recursive
        cd ..
        
        # Restore Data Logic
        echo -e "${GREEN}♻️ Restoring user data...${NC}"
        
        restore_folder() {
            SRC="$1"; DEST="$2";
            # Only restore if source exists, is not empty, and dest is safe
            if [ -d "$SRC" ] && [ "$(ls -A "$SRC")" ]; then
                # Defensive check: Ensure we aren't deleting root or empty strings
                if [[ -z "$DEST" || "$DEST" == "/" ]]; then
                     echo "⚠️ Safety check failed for restore destination. Skipping $SRC"; return;
                fi
                
                echo "Restoring $(basename $SRC)..."
                mkdir -p "$(dirname $DEST)"
                rm -rf "$DEST"
                mv "$SRC" "$(dirname $DEST)/"
            fi
        }

        # 1. Restore Datasets (WAV files)
        restore_folder "$BACKUP_DIR/assets/datasets" "$INSTALL_DIR/assets/datasets"
        # 2. Restore Custom Embeddings (The .index files)
        restore_folder "$BACKUP_DIR/assets/embeddings" "$INSTALL_DIR/assets/embeddings"
        # 3. Restore Logs
        restore_folder "$BACKUP_DIR/logs" "$INSTALL_DIR/logs"
        
        # 4. Merge Weights (Models) - keep defaults, add customs
        if [ -d "$BACKUP_DIR/assets/weights" ]; then
            mkdir -p "$INSTALL_DIR/assets/weights"
            # cp -rn: Recursive, No-clobber (don't overwrite new defaults)
            cp -rn "$BACKUP_DIR/assets/weights/"* "$INSTALL_DIR/assets/weights/" 2>/dev/null || true
        fi

        # 5. Restore Config
        [ -f "$BACKUP_DIR/config.json" ] && cp "$BACKUP_DIR/config.json" "$INSTALL_DIR/"
        
        # Cleanup
        rm -rf "$BACKUP_DIR"
    else
        cd "$INSTALL_DIR"
        echo -e "${GREEN}🔄 Updating repository...${NC}"
        git pull
        git submodule update --init --recursive
        cd ..
    fi
else
    echo -e "${GREEN}⬇️ Cloning Applio repository...${NC}"
    git clone $REPO_URL "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    git submodule update --init --recursive
    cd ..
fi

cd "$INSTALL_DIR"

# --- 6. Virtual Environment ---
if [ ! -d "venv" ]; then
    echo -e "${GREEN}🔒 Creating virtual environment...${NC}"
    "$PYTHON_EXEC" -m venv venv
fi
source venv/bin/activate

# --- 7. Dependency Management (Surgical Method) ---
echo -e "${GREEN}🛠 Resolving Dependencies...${NC}"

# A. Base Build Tools
# CRITICAL PINS:
# 1. setuptools<70: Newer versions remove 'distutils', breaking fairseq compilation.
# 2. numpy<2: Numpy 2.0 broke C-API compatibility for many older AI libraries (pyworld/fairseq).
pip install --upgrade pip wheel "setuptools<70" "numpy<2" certifi

# B. Pre-install Compilation Prerequisites
# We must install these BEFORE requirements.txt so pip finds them during the build of other packages
echo "Installing build prerequisites (cython)..."
pip install cython

# C. Install Torch (Explicitly for Mac)
# Ensure we get the correct arm64/MPS supported version
echo "Installing PyTorch for Apple Silicon..."
pip install torch torchvision torchaudio

# D. Pre-install PyWorld
# Use --no-build-isolation to force it to use the numpy<2 we just installed, 
# preventing it from spinning up a temp env with incompatible numpy 2.0.
echo "Installing PyWorld..."
pip install pyworld --no-build-isolation

# E. Sanitize Requirements
if [ -f "requirements.txt" ]; then
    echo "Sanitizing requirements.txt..."
    cp requirements.txt requirements_mac.txt
    
    # 1. Remove GPU-only libraries (crash on Mac)
    sed -i '' '/onnxruntime-gpu/d' requirements_mac.txt
    sed -i '' '/faiss-gpu/d' requirements_mac.txt
    sed -i '' '/tensorflow/d' requirements_mac.txt
    
    # 2. Remove Windows-specific libraries
    sed -i '' '/[Pp]ython-[Mm]agic-[Bb]in/d' requirements_mac.txt
    
    # 3. Remove Torch packages (Installed manually above)
    # Regex protects 'torchcrepe', 'torchfcpe'
    sed -i '' -E '/^torch(==|>=|$)/d' requirements_mac.txt
    sed -i '' -E '/^torchvision/d' requirements_mac.txt
    sed -i '' -E '/^torchaudio/d' requirements_mac.txt
    
    # 4. Remove numpy if present (to respect our <2 pin)
    sed -i '' -E '/^numpy/d' requirements_mac.txt

    # F. Install the rest
    pip install -r requirements_mac.txt
fi

# G. Post-Install Mac Fixes
echo -e "${GREEN}🚑 Applying macOS patches...${NC}"
pip install faiss-cpu        # CPU version required for Indexing
pip install onnxruntime      # Standard version (CoreML/CPU)
pip install pyobjc-core      # Audio drivers
pip install pyobjc-framework-Cocoa 

# --- 8. Model Downloads ---
echo -e "${GREEN}📥 Verifying Pre-trained Models...${NC}"

mkdir -p assets/pretrained/vec
mkdir -p assets/rmvpe

download_file() {
    URL="$1"; DEST="$2";
    if [ ! -f "$DEST" ]; then
        echo "Downloading $(basename $DEST)..."
        # Try wget, fall back to curl
        wget -q --show-progress -O "$DEST" "$URL" || curl -L -o "$DEST" "$URL"
    fi
}

# HuBERT (Required for Feature Extraction)
download_file "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt" "assets/pretrained/vec/hubert_base.pt"

# RMVPE (Required for Pitch Extraction)
download_file "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt" "assets/rmvpe.pt"
# Copy RMVPE to subfolder for compatibility
cp assets/rmvpe.pt assets/rmvpe/rmvpe.pt 2>/dev/null || true

# --- 9. Create Launcher ---
cat > start_applio.sh <<EOF
#!/bin/bash
cd "\$(dirname "\$0")"
source venv/bin/activate

# --- Optimization Flags for Mac ---
export PYTORCH_ENABLE_MPS_FALLBACK=1
export OMP_NUM_THREADS=1
export NO_CUDA=1
export GRADIO_SERVER_PORT=7860

# CRITICAL FIXES for macOS Crashes
# 1. Fixes multiprocessing crash during Feature Extraction (Fork Safety)
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
# 2. Fixes OpenMP library conflict (Error #15)
export KMP_DUPLICATE_LIB_OK=TRUE

echo "🚀 Launching Applio..."
echo "---------------------------------------------------"
echo "👉 HOW TO GENERATE YOUR INDEX:"
echo "1. Put your wav files in a folder inside: \$(pwd)/assets/datasets/"
echo "2. Go to the 'Train' tab."
echo "3. Enter the folder name as your Dataset Path."
echo "4. Click 'Process Data' -> 'Feature Extraction' -> 'Train Feature Index'"
echo "5. Your .index file will be in 'logs/(Experiment Name)'"
echo "---------------------------------------------------"

# Launch
python app.py --open
EOF

chmod +x start_applio.sh

echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo -e "To start, run: ${YELLOW}cd $INSTALL_DIR && ./start_applio.sh${NC}"
echo -e "${GREEN}==============================================${NC}"

# Auto-start check
read -p "Launch Applio now? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    ./start_applio.sh
fi
