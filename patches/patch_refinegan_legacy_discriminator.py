"""
Patch to add DiscriminatorRLegacy for legacy RVC-Boss RefineGAN models.

This patch:
1. Adds DiscriminatorRLegacy class with (5,1) kernels matching RVC-Boss architecture
2. Modifies MultiPeriodDiscriminator to accept disc_r_class parameter

The legacy discriminator differs from current:
- Uses (5, 1) kernels instead of (3, 9)
- Uses channel expansion 32→128→512→1024→1024 instead of all 32s
- Uses (3, 1) final conv instead of (3, 3)
"""

import os


_IDEMPOTENCY_MARKER = "# DiscriminatorRLegacy support added"


def patch_discriminators(base_path: str) -> bool:
    """Patch discriminators.py to add DiscriminatorRLegacy support.

    Args:
        base_path: Directory containing discriminators.py (e.g., rvc/lib/algorithm/)

    Returns:
        True if patched successfully, False otherwise
    """
    discriminators_path = os.path.join(base_path, "discriminators.py")

    if not os.path.exists(discriminators_path):
        print(f"  [RefineGAN-Legacy discriminator] Error: {discriminators_path} not found")
        return False

    with open(discriminators_path, "r", encoding="utf-8") as f:
        content = f.read()

    if _IDEMPOTENCY_MARKER in content:
        print("  [RefineGAN-Legacy discriminator] Already patched, skipping.")
        return True

    print("  [RefineGAN-Legacy discriminator] Patching discriminators.py...")

    # 1. Add DiscriminatorRLegacy class after DiscriminatorR class
    legacy_class = '''

class DiscriminatorRLegacy(torch.nn.Module):
    """Legacy DiscriminatorR with (5,1) kernels matching RVC-Boss RefineGAN.

    This discriminator uses the original architecture with:
    - (5, 1) kernels for frequency axis processing
    - Channel expansion: 1 -> 32 -> 128 -> 512 -> 1024 -> 1024
    - (3, 1) final convolution
    """

    def __init__(self, resolution, use_spectral_norm=False):
        super().__init__()

        self.resolution = resolution
        self.lrelu_slope = 0.1
        norm_f = spectral_norm if use_spectral_norm else weight_norm

        # Legacy architecture: (5, 1) kernels with channel expansion
        self.convs = torch.nn.ModuleList(
            [
                norm_f(
                    torch.nn.Conv2d(
                        1,
                        32,
                        (5, 1),
                        padding=(2, 0),
                    )
                ),
                norm_f(
                    torch.nn.Conv2d(
                        32,
                        128,
                        (5, 1),
                        stride=(1, 2),
                        padding=(2, 0),
                    )
                ),
                norm_f(
                    torch.nn.Conv2d(
                        128,
                        512,
                        (5, 1),
                        stride=(1, 2),
                        padding=(2, 0),
                    )
                ),
                norm_f(
                    torch.nn.Conv2d(
                        512,
                        1024,
                        (5, 1),
                        stride=(1, 2),
                        padding=(2, 0),
                    )
                ),
                norm_f(
                    torch.nn.Conv2d(
                        1024,
                        1024,
                        (5, 1),
                        padding=(2, 0),
                    )
                ),
            ]
        )
        self.conv_post = norm_f(torch.nn.Conv2d(1024, 1, (3, 1), padding=(1, 0)))

    def forward(self, x):
        fmap = []

        x = self.spectrogram(x).unsqueeze(1)

        for layer in self.convs:
            x = F.leaky_relu(layer(x), self.lrelu_slope)
            fmap.append(x)
        x = self.conv_post(x)
        fmap.append(x)

        return torch.flatten(x, 1, -1), fmap

    def spectrogram(self, x):
        n_fft, hop_length, win_length = self.resolution
        pad = int((n_fft - hop_length) / 2)
        x = F.pad(
            x,
            (pad, pad),
            mode="reflect",
        ).squeeze(1)
        x = torch.stft(
            x,
            n_fft=n_fft,
            hop_length=hop_length,
            win_length=win_length,
            window=torch.ones(win_length, device=x.device),
            center=False,
            return_complex=True,
        )

        mag = torch.norm(torch.view_as_real(x), p=2, dim=-1)  # [B, F, TT]

        return mag
'''

    # Find the end of DiscriminatorR class (after spectrogram method)
    # Look for the return statement at the end of spectrogram
    spectrogram_end = "        return mag\n"
    if spectrogram_end in content:
        # Find the last occurrence (end of DiscriminatorR.spectrogram)
        last_spectrogram_end = content.rfind(spectrogram_end)
        if last_spectrogram_end != -1:
            insert_pos = last_spectrogram_end + len(spectrogram_end)
            content = content[:insert_pos] + legacy_class + content[insert_pos:]

    # 2. Modify MultiPeriodDiscriminator.__init__ signature to add disc_r_class parameter
    old_init = '''    def __init__(
        self,
        use_spectral_norm: bool = False,
        checkpointing: bool = False,
        version: str = "v2",
    ):'''

    new_init = '''    def __init__(
        self,
        use_spectral_norm: bool = False,
        checkpointing: bool = False,
        version: str = "v2",
        disc_r_class: type = None,
    ):'''

    if old_init in content:
        content = content.replace(old_init, new_init)

    # 3. Modify the discriminator list creation to use disc_r_class
    old_disc_list = '''        self.discriminators = torch.nn.ModuleList(
            [DiscriminatorS(use_spectral_norm=use_spectral_norm)]
            + [DiscriminatorP(p, use_spectral_norm=use_spectral_norm) for p in periods]
            + [
                DiscriminatorR(r, use_spectral_norm=use_spectral_norm)
                for r in resolutions
            ]
        )'''

    new_disc_list = '''        _disc_r_class = disc_r_class if disc_r_class is not None else DiscriminatorR
        self.discriminators = torch.nn.ModuleList(
            [DiscriminatorS(use_spectral_norm=use_spectral_norm)]
            + [DiscriminatorP(p, use_spectral_norm=use_spectral_norm) for p in periods]
            + [
                _disc_r_class(r, use_spectral_norm=use_spectral_norm)
                for r in resolutions
            ]
        )'''

    if old_disc_list in content:
        content = content.replace(old_disc_list, new_disc_list)

    # Add idempotency marker at the end
    content = content.rstrip() + "\n" + _IDEMPOTENCY_MARKER + "\n"

    with open(discriminators_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  [RefineGAN-Legacy discriminator] Patched discriminators.py successfully")
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python patch_refinegan_legacy_discriminator.py <base_path>")
        sys.exit(1)

    base_path = sys.argv[1]
    success = patch_discriminators(base_path)
    sys.exit(0 if success else 1)
