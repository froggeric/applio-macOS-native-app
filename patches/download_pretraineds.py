#!/usr/bin/env python3
"""
Download pretrained models to bundle in the macOS build.

This script downloads specific pretrained models at build time so they're
pre-installed in the app, eliminating the need for users to download them.

Models downloaded:
- HiFi-GAN: KLM4 (KLM49) 48k, TITAN Medium 48k
- RefineGAN: KLM50 exp1 44k, VCTK 44k

Usage:
    python patches/download_pretraineds.py [--dry-run]
"""

import os
import sys
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tqdm import tqdm


# Base URLs
HUGGINGFACE_BASE = "https://huggingface.co"

# Models to download and bundle
# Format: (name, vocoder, sample_rate, D_url, G_url)
#
# Naming convention for custom models: {vocoder}_{name}_{D|G}_{rate}k.pth
# Examples: hifigan_klm49_D_48k.pth, refinegan_klm50_exp1_D_44k.pth
#
# Note: Default HiFi-GAN (32k/40k/48k) and RefineGAN (24k/32k) are already
# bundled via prerequisites_download.py. This script adds custom models.
#
PRETRAINED_MODELS = [
    # HiFi-GAN custom models
    (
        "KLM49",
        "hifi-gan",
        "48k",
        "SeoulStreamingStation/KLM49_HFG/resolve/main/D_KLM_HFG_48k.pth",
        "SeoulStreamingStation/KLM49_HFG/resolve/main/G_KLM_HFG_48k.pth",
    ),
    (
        "TITAN_Medium",
        "hifi-gan",
        "48k",
        "blaise-tk/TITAN/resolve/main/models/medium/48k/pretrained/D-f048k-TITAN-Medium.pth",
        "blaise-tk/TITAN/resolve/main/models/medium/48k/pretrained/G-f048k-TITAN-Medium.pth",
    ),
    # RefineGAN 44kHz models (not in upstream)
    (
        "KLM50_exp1",
        "refinegan",
        "44k",
        "Politrees/RVC_resources/resolve/cf70ba3207bbaab9d6db46fbfeaa52f8fcdcc82e/pretrained/v2/RefineGAN/44k/KLM/D_KLM50_exp1_RFG_44k.pth",
        "Politrees/RVC_resources/resolve/cf70ba3207bbaab9d6db46fbfeaa52f8fcdcc82e/pretrained/v2/RefineGAN/44k/KLM/G_KLM50_exp1_RFG_44k.pth",
    ),
    (
        "VCTK_v1",
        "refinegan",
        "44k",
        "SimplCup/RefineGanVCTKV1/resolve/main/f0D_RefineGanVCTKV1.pth",
        "SimplCup/RefineGanVCTKV1/resolve/main/f0G_RefineGanVCTKV1.pth",
    ),
]

# Destination paths
BASE_PATH = Path("rvc/models/pretraineds")


def get_file_size(url: str) -> int:
    """Get file size from URL without downloading."""
    try:
        response = requests.head(url, timeout=10, allow_redirects=True)
        return int(response.headers.get("content-length", 0))
    except Exception:
        return 0


def download_file(url: str, dest_path: Path, pbar: tqdm) -> bool:
    """Download a file with progress bar."""
    try:
        response = requests.get(url, stream=True, timeout=300, allow_redirects=True)
        response.raise_for_status()

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))
        return True
    except Exception as e:
        print(f"\n  ERROR downloading {url}: {e}")
        return False


def get_destination_filename(model_name: str, vocoder: str, sample_rate: str, file_type: str) -> str:
    """
    Generate the destination filename for a pretrained model.

    Custom naming convention: {vocoder_short}_{model_name}_{D|G}_{rate}k.pth
    Examples:
    - hifigan_klm49_D_48k.pth
    - hifigan_titan_medium_D_48k.pth
    - refinegan_klm50_exp1_D_44k.pth
    - refinegan_vctk_v1_D_44k.pth
    """
    # Extract rate suffix (e.g., "48k" -> "48", "44k" -> "44")
    rate = sample_rate.rstrip("k")

    # Sanitize model name: lowercase, underscores
    safe_name = model_name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")

    # Vocoder prefix
    vocoder_short = "hifigan" if vocoder == "hifi-gan" else "refinegan"

    return f"{vocoder_short}_{safe_name}_{file_type}_{rate}k.pth"


def download_models(dry_run: bool = False) -> bool:
    """Download all pretrained models."""
    print("=" * 60)
    print("Pretrained Models Download for macOS Build")
    print("=" * 60)
    print()

    # Calculate total size
    print("Calculating download sizes...")
    downloads = []
    total_size = 0

    for model_name, vocoder, sample_rate, d_url, g_url in PRETRAINED_MODELS:
        vocoder_path = BASE_PATH / vocoder

        d_filename = get_destination_filename(model_name, vocoder, sample_rate, "D")
        g_filename = get_destination_filename(model_name, vocoder, sample_rate, "G")

        d_path = vocoder_path / d_filename
        g_path = vocoder_path / g_filename

        # Check if already exists
        d_exists = d_path.exists()
        g_exists = g_path.exists()

        if d_exists and g_exists:
            print(f"  ✓ {model_name} ({vocoder}, {sample_rate}) - already exists")
            continue

        d_size = get_file_size(f"{HUGGINGFACE_BASE}/{d_url}") if not d_exists else 0
        g_size = get_file_size(f"{HUGGINGFACE_BASE}/{g_url}") if not g_exists else 0

        downloads.append({
            "name": model_name,
            "vocoder": vocoder,
            "sample_rate": sample_rate,
            "d_url": f"{HUGGINGFACE_BASE}/{d_url}",
            "g_url": f"{HUGGINGFACE_BASE}/{g_url}",
            "d_path": d_path,
            "g_path": g_path,
            "d_exists": d_exists,
            "g_exists": g_exists,
            "d_size": d_size,
            "g_size": g_size,
        })
        total_size += d_size + g_size

        status = []
        if not d_exists:
            status.append(f"D: {d_size/1024/1024:.1f}MB")
        if not g_exists:
            status.append(f"G: {g_size/1024/1024:.1f}MB")
        print(f"  • {model_name} ({vocoder}, {sample_rate}) - {', '.join(status)}")

    if not downloads:
        print()
        print("All models already downloaded. Nothing to do.")
        return True

    print()
    print(f"Total download size: {total_size/1024/1024:.1f} MB")
    print()

    if dry_run:
        print("DRY RUN - no downloads performed")
        return True

    # Download with progress bar
    print("Downloading models...")
    print()

    success = True
    with tqdm(total=total_size, unit="B", unit_scale=True, desc="Total") as pbar:
        for dl in downloads:
            print(f"  Downloading {dl['name']} ({dl['vocoder']}, {dl['sample_rate']})...")

            if not dl["d_exists"]:
                if not download_file(dl["d_url"], dl["d_path"], pbar):
                    success = False
                    continue
                print(f"    ✓ D: {dl['d_path']}")
            else:
                print(f"    ✓ D: {dl['d_path']} (exists)")

            if not dl["g_exists"]:
                if not download_file(dl["g_url"], dl["g_path"], pbar):
                    success = False
                    continue
                print(f"    ✓ G: {dl['g_path']}")
            else:
                print(f"    ✓ G: {dl['g_path']} (exists)")

    print()
    if success:
        print("✓ All models downloaded successfully")
    else:
        print("✗ Some downloads failed")

    return success


def main():
    parser = argparse.ArgumentParser(
        description="Download pretrained models to bundle in macOS build"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate sizes without downloading"
    )
    args = parser.parse_args()

    success = download_models(dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
