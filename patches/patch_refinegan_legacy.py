"""
Patch to add RefineGAN-Legacy vocoder support at build time.

This patch modifies synthesizers.py to add support for loading pretrained models
that use the original RVC-Boss RefineGAN architecture (legacy).

The legacy architecture differs from the current Applio RefineGAN:
- source_conv with bias=True (current pre_conv has no bias)
- SineGenerator with flat l_linear/l_tanh (current uses Sequential merge)
- downsample_blocks as Sequential(AdaIN, ResBlockLegacy) (current uses Conv1d)
"""

import os


_IDEMPOTENCY_MARKER = "# RefineGAN-Legacy vocoder support added"


def patch_synthesizers(base_path: str) -> bool:
    """Patch synthesizers.py to add RefineGAN-Legacy vocoder support.

    Args:
        base_path: Directory containing rvc/lib/algorithm/synthesizers.py

    Returns:
        True if successful, False otherwise
    """
    synthesizers_path = os.path.join(base_path, "rvc", "lib", "algorithm", "synthesizers.py")

    if not os.path.exists(synthesizers_path):
        print(f"  [RefineGAN-Legacy] Error: {synthesizers_path} not found")
        return False

    with open(synthesizers_path, "r", encoding="utf-8") as f:
        content = f.read()

    if _IDEMPOTENCY_MARKER in content:
        print("  [RefineGAN-Legacy] Already patched, skipping.")
        return True

    print("  [RefineGAN-Legacy] Patching synthesizers.py...")

    # Add import for RefineGANLegacyGenerator
    import_line = "from rvc.lib.algorithm.generators.refinegan_legacy import RefineGANLegacyGenerator"
    if import_line not in content:
        old_import = "from rvc.lib.algorithm.generators.refinegan import RefineGANGenerator"
        content = content.replace(
            old_import,
            old_import + "\n" + import_line,
        )

    # Add RefineGAN-Legacy vocoder case (after RefineGAN case)
    legacy_vocoder_case = '''            elif vocoder == "RefineGAN-Legacy":
                self.dec = RefineGANLegacyGenerator(
                    sample_rate=sr,
                    downsample_rates=upsample_rates[::-1],
                    upsample_rates=upsample_rates,
                    start_channels=16,
                    num_mels=inter_channels,
                    checkpointing=checkpointing,
                )'''

    # Find RefineGAN case and add legacy case after it
    refinegan_case_end = "checkpointing=checkpointing,\n                )"
    if refinegan_case_end in content and legacy_vocoder_case.strip() not in content:
        # Find the position after RefineGAN case
        idx = content.find(refinegan_case_end)
        if idx != -1:
            # Insert after the RefineGAN case
            insert_pos = idx + len(refinegan_case_end)
            content = content[:insert_pos] + "\n" + legacy_vocoder_case + content[insert_pos:]

    # Add RefineGAN-Legacy no-f0 case
    legacy_no_f0_case = '''            elif vocoder == "RefineGAN-Legacy":
                print("RefineGAN-Legacy does not support training without pitch guidance.")
                self.dec = None'''

    refinegan_no_f0 = '''            elif vocoder == "RefineGAN":
                print("RefineGAN does not support training without pitch guidance.")
                self.dec = None'''
    if refinegan_no_f0 in content and legacy_no_f0_case.strip() not in content:
        content = content.replace(refinegan_no_f0, refinegan_no_f0 + "\n" + legacy_no_f0_case)

    # Add idempotency marker
    content = content.rstrip() + "\n" + _IDEMPOTENCY_MARKER + "\n"

    with open(synthesizers_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  [RefineGAN-Legacy] Patched synthesizers.py successfully")
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python patch_refinegan_legacy.py <base_path>")
        sys.exit(1)

    base_path = sys.argv[1]
    success = patch_synthesizers(base_path)
    sys.exit(0 if success else 1)
