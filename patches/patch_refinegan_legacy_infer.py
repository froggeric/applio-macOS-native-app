"""
Patch to add RefineGAN-Legacy architecture detection in infer.py.

This patch adds:
1. A helper function `_detect_refinegan_legacy_from_weights()` to detect legacy model weights
2. Logic to override vocoder to "RefineGAN-Legacy" when legacy weights are detected

This enables loading models trained elsewhere with the legacy RefineGAN architecture
without producing garbage output.
"""

import os


_IDEMPOTENCY_MARKER = "# RefineGAN-Legacy inference detection added"


def patch_infer(base_path: str) -> bool:
    """Patch infer.py to add RefineGAN-Legacy architecture detection.

    Args:
        base_path: Directory containing infer.py (e.g., rvc/infer/)

    Returns:
        True if patched successfully, False otherwise
    """
    infer_path = os.path.join(base_path, "infer.py")

    if not os.path.exists(infer_path):
        raise FileNotFoundError(f"infer.py not found at {infer_path}")

    with open(infer_path, "r", encoding="utf-8") as f:
        content = f.read()

    if _IDEMPOTENCY_MARKER in content:
        print("  [RefineGAN-Legacy infer.py] Already patched, skipping.")
        return True

    print("  [RefineGAN-Legacy infer.py] Patching...")

    # Add helper function for legacy detection
    helper_func = '''def _detect_refinegan_legacy_from_weights(weights: dict) -> bool:
    """Detect if model weights use legacy RefineGAN architecture.

    Legacy architecture (original RVC-Boss) has:
    - dec.source_conv (current has dec.pre_conv)
    - dec.m_source.l_linear (current has dec.m_source.merge.0)

    Args:
        weights: Model state dict

    Returns:
        True if weights use legacy architecture, False otherwise
    """
    try:
        keys = list(weights.keys())
        # Check for legacy keys in decoder (dec.)
        has_legacy_keys = any(
            "dec.source_conv" in k or "dec.m_source.l_linear" in k
        )
        has_current_keys = any(
            "dec.pre_conv" in k or "dec.m_source.merge" in k
        )
        if has_legacy_keys and not has_current_keys:
            return True
        else:
            return False
    except Exception:
        return False
'''

    if helper_func not in content:
        # Find the insertion point after the logging config
        insertion_marker = 'logging.getLogger("faiss.loader").setLevel(logging.WARNING)'
        content = content.replace(
            insertion_marker,
            insertion_marker + "\n\n" + helper_func,
        )

    # Modify setup_network to detect legacy vocoder
    # Note: Handle both single and double quote variations
    old_setup_single = '''    def setup_network(self):
        """
        Sets up the network configuration based on the loaded checkpoint.
        """
        if self.cpt is not None:
            self.tgt_sr = self.cpt["config"][-1]
            self.cpt["config"][-3] = self.cpt["weight"]["emb_g.weight"].shape[0]
            self.use_f0 = self.cpt.get("f0", 1)

            self.version = self.cpt.get("version", "v1")
            self.text_enc_hidden_dim = 768 if self.version == "v2" else 256
            self.vocoder = self.cpt.get("vocoder", "HiFi-GAN")
            self.net_g = Synthesizer(
                *self.cpt["config"],
                use_f0=self.use_f0,
                text_enc_hidden_dim=self.text_enc_hidden_dim,
                vocoder=self.vocoder,
            )
            del self.net_g.enc_q
            self.net_g.load_state_dict(self.cpt["weight"], strict=False)
            self.net_g = self.net_g.to(self.config.device).float()
            self.net_g.eval()'''

    old_setup_double = '''    def setup_network(self):
        """
        Sets up the network configuration based on the loaded checkpoint.
        """
        if self.cpt is not None:
            self.tgt_sr = self.cpt["config"][-1]
            self.cpt["config"][-3] = self.cpt["weight"]["emb_g.weight"].shape[0]
            self.use_f0 = self.cpt.get("f0", 1)

            self.version = self.cpt.get("version", "v1")
            self.text_enc_hidden_dim = 768 if self.version == "v2" else 256
            self.vocoder = self.cpt.get("vocoder", "HiFi-GAN")
            self.net_g = Synthesizer(
                *self.cpt["config"],
                use_f0=self.use_f0,
                text_enc_hidden_dim=self.text_enc_hidden_dim,
                vocoder=self.vocoder,
            )
            del self.net_g.enc_q
            self.net_g.load_state_dict(self.cpt["weight"], strict=False)
            self.net_g = self.net_g.to(self.config.device).float()
            self.net_g.eval()'''

    new_setup = '''    def setup_network(self):
        """
        Sets up the network configuration based on the loaded checkpoint.
        """
        if self.cpt is not None:
            self.tgt_sr = self.cpt["config"][-1]
            self.cpt["config"][-3] = self.cpt["weight"]["emb_g.weight"].shape[0]
            self.use_f0 = self.cpt.get("f0", 1)

            self.version = self.cpt.get("version", "v1")
            self.text_enc_hidden_dim = 768 if self.version == "v2" else 256
            self.vocoder = self.cpt.get("vocoder", "HiFi-GAN")

            # Detect legacy RefineGAN architecture from checkpoint weights
            if self.vocoder == "RefineGAN" and _detect_refinegan_legacy_from_weights(
                self.cpt["weight"]
            ):
                self.vocoder = "RefineGAN-Legacy"
                logging.info("Detected legacy RefineGAN architecture, using RefineGAN-Legacy vocoder")

            self.net_g = Synthesizer(
                *self.cpt["config"],
                use_f0=self.use_f0,
                text_enc_hidden_dim=self.text_enc_hidden_dim,
                vocoder=self.vocoder,
            )
            del self.net_g.enc_q
            self.net_g.load_state_dict(self.cpt["weight"], strict=False)
            self.net_g = self.net_g.to(self.config.device).float()
            self.net_g.eval()'''

    # Try both single and double quote versions
    if old_setup_single in content:
        content = content.replace(old_setup_single, new_setup)
    elif old_setup_double in content:
        content = content.replace(old_setup_double, new_setup)
    else:
        print("  [RefineGAN-Legacy infer.py] Could not find setup_network to patch")
        return False

    # Add idempotency marker
    content = content.rstrip() + "\n" + _IDEMPOTENCY_MARKER + "\n"

    with open(infer_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  [RefineGAN-Legacy infer.py] Patched successfully")
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python patch_refinegan_legacy_infer.py <base_path>")
        sys.exit(1)

    base_path = sys.argv[1]
    success = patch_infer(base_path)
    sys.exit(0 if success else 1)
