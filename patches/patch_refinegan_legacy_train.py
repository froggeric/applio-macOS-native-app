"""
Patch to add RefineGAN-Legacy architecture detection in train.py.

This patch adds:
1. A helper function `_detect_refinegan_legacy()` to detect legacy pretrained models
2. Logic to re-instantiate net_g with RefineGAN-Legacy vocoder when legacy pretrained is detected

The legacy architecture (original RVC-Boss) differs from current Applio RefineGAN:
and requires loading with a compatible vocoder implementation.
"""

import os


_IDEMPOTENCY_MARKER = "# RefineGAN-Legacy detection added"


def patch_train(base_path: str) -> bool:
    """Patch train.py to add RefineGAN-Legacy architecture detection.

    Args:
        base_path: Directory containing train.py (e.g., rvc/train/)

    Returns:
        True if patched successfully,    Raises FileNotFoundError if file not found
    """
    train_path = os.path.join(base_path, "train.py")

    if not os.path.exists(train_path):
        raise FileNotFoundError(f"train.py not found at {train_path}")

    with open(train_path, "r", encoding="utf-8") as f:
        content = f.read()

    if _IDEMPOTENCY_MARKER in content:
        print("  [RefineGAN-Legacy train.py] Already patched, skipping.")
        return True

    print("  [RefineGAN-Legacy train.py] Patching...")

    # Add the detection function after the RefineGAN vocoder config
    detection_func = '''

def _detect_refinegan_legacy(pretrain_path: str) -> bool:
    """Detect if pretrained model uses legacy RefineGAN architecture.

    Legacy architecture (original RVC-Boss) has:
    - source_conv (current has pre_conv)
    - l_linear (current has merge.0)

    Args:
        pretrain_path: Path to pretrained G model checkpoint

    Returns:
        True if pretrained uses legacy architecture, False otherwise
    """
    if not pretrain_path or pretrain_path in ("", "None"):
        return False
    if not os.path.isfile(pretrain_path):
        return False
    try:
        import torch
        ckpt = torch.load(pretrain_path, map_location="cpu", weights_only=True)
        state_dict = ckpt.get("model", ckpt)
        keys = list(state_dict.keys())
        has_legacy_keys = any("source_conv" in k or "l_linear" in k for k in keys)
        has_current_keys = any("pre_conv" in k or "merge.0" in k for k in keys)
        return has_legacy_keys and not has_current_keys
    except Exception:
        return False
'''

    # Insert detection function after the RefineGAN vocoder config block
    refinegan_config_end = 'if vocoder == "RefineGAN":\n    disc_version = "v3"\n    multiscale_mel_loss = True'
    if refinegan_config_end in content:
        content = content.replace(
            refinegan_config_end,
            refinegan_config_end + detection_func,
        )

    # Now patch the pretrained G loading section to detect and handle legacy architecture
    # Find the pretrained G loading block and modify it
    old_pretrain_g_block = '''        if pretrainG not in ("", "None"):
            if rank == 0:
                print(f"Loaded pretrained (G) '{pretrainG}'")
            try:
                ckpt = torch.load(pretrainG, map_location="cpu", weights_only=True)[
                    "model"
                ]
                if hasattr(net_g, "module"):
                    net_g.module.load_state_dict(ckpt)
                else:
                    net_g.load_state_dict(ckpt)
                del ckpt
            except Exception as e:
                print(
                    "The parameters of the pretrain model such as the sample rate or architecture do not match the selected model."
                )
                print(e)
                sys.exit(1)'''

    new_pretrain_g_block = '''        if pretrainG not in ("", "None"):
            if rank == 0:
                print(f"Loaded pretrained (G) '{pretrainG}'")
            try:
                # Detect legacy RefineGAN architecture
                is_legacy = _detect_refinegan_legacy(pretrainG)
                if is_legacy and vocoder == "RefineGAN":
                    if rank == 0:
                        print("Detected legacy RefineGAN architecture, using RefineGAN-Legacy vocoder")
                    # Re-instantiate net_g with legacy vocoder
                    net_g = Synthesizer(
                        config.data.filter_length // 2 + 1,
                        config.train.segment_size // config.data.hop_length,
                        **config.model,
                        use_f0=True,
                        sr=config.data.sample_rate,
                        vocoder="RefineGAN-Legacy",
                        checkpointing=checkpointing,
                        randomized=randomized,
                    )
                    if torch.cuda.is_available():
                        net_g = net_g.cuda(device_id)
                    else:
                        net_g = net_g.to(device)

                ckpt = torch.load(pretrainG, map_location="cpu", weights_only=True)[
                    "model"
                ]
                if hasattr(net_g, "module"):
                    net_g.module.load_state_dict(ckpt)
                else:
                    net_g.load_state_dict(ckpt)
                del ckpt
            except Exception as e:
                print(
                    "The parameters of the pretrain model such as the sample rate or architecture do not match the selected model."
                )
                print(e)
                sys.exit(1)'''

    if old_pretrain_g_block in content:
        content = content.replace(old_pretrain_g_block, new_pretrain_g_block)

    # Add idempotency marker at the end
    content = content.rstrip() + "\n" + _IDEMPOTENCY_MARKER + "\n"

    with open(train_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  [RefineGAN-Legacy train.py] Patched successfully")
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python patch_refinegan_legacy_train.py <base_path>")
        sys.exit(1)
    base_path = sys.argv[1]
    success = patch_train(base_path)
    sys.exit(0 if success else 1)
