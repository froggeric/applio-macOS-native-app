"""
Legacy RefineGAN Generator (Original RVC-Boss Architecture)

This module implements the original RefineGAN architecture from RVC-Boss,
which differs from the simplified Applio version. The key differences are:

1. source_conv has bias=True (current pre_conv has no bias)
2. SineGenerator uses flat l_linear + l_tanh (current uses Sequential merge)
3. downsample_blocks are Sequential(AdaIN, ResBlockLegacy) with separate in/out channels
   (current uses single Conv1d with same in/out channels via channel doubling)

This module exists to provide backward compatibility with pretrained models
trained using the original RVC-Boss RefineGAN architecture.
"""

import numpy as np
import torch
import torchaudio
from torch import nn
from torch.nn import functional as F
from torch.nn.utils.parametrizations import weight_norm
from torch.nn.utils import remove_weight_norm
from torch.utils.checkpoint import checkpoint

from rvc.lib.algorithm.commons import init_weights, get_padding


class ResBlockLegacy(nn.Module):
    """
    Legacy residual block with separate in_channels and out_channels.

    Unlike the current ResBlock which uses the same channels for input and output,
    this legacy version supports different in/out channels, matching the original
    RVC-Boss RefineGAN architecture.

    Args:
        in_channels (int): Number of input channels.
        out_channels (int): Number of output channels.
        kernel_size (int, optional): Kernel size for the convolutional layers. Defaults to 7.
        dilation (tuple[int], optional): Tuple of dilation rates. Defaults to (1, 3, 5).
        leaky_relu_slope (float, optional): Slope for Leaky ReLU. Defaults to 0.2.
    """

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int = 7,
        dilation: tuple[int] = (1, 3, 5),
        leaky_relu_slope: float = 0.2,
    ):
        super().__init__()

        self.leaky_relu_slope = leaky_relu_slope

        self.convs1 = nn.ModuleList(
            [
                weight_norm(
                    nn.Conv1d(
                        in_channels,
                        out_channels,
                        kernel_size,
                        stride=1,
                        dilation=d,
                        padding=get_padding(kernel_size, d),
                    )
                )
                for d in dilation
            ]
        )
        self.convs1.apply(init_weights)

        self.convs2 = nn.ModuleList(
            [
                weight_norm(
                    nn.Conv1d(
                        out_channels,
                        out_channels,
                        kernel_size,
                        stride=1,
                        dilation=1,
                        padding=get_padding(kernel_size, 1),
                    )
                )
                for d in dilation
            ]
        )
        self.convs2.apply(init_weights)

    def forward(self, x: torch.Tensor):
        for c1, c2 in zip(self.convs1, self.convs2):
            xt = F.leaky_relu(x, self.leaky_relu_slope)
            xt = c1(xt)
            xt = F.leaky_relu(xt, self.leaky_relu_slope)
            xt = c2(xt)
            x = xt + x

        return x

    def remove_weight_norm(self):
        for c1, c2 in zip(self.convs1, self.convs2):
            remove_weight_norm(c1)
            remove_weight_norm(c2)


class AdaINLegacy(nn.Module):
    """
    Adaptive Instance Normalization layer for legacy architecture.

    Identical to current AdaIN but included here for completeness.

    Args:
        channels (int): Number of input channels.
        leaky_relu_slope (float, optional): Slope for Leaky ReLU. Defaults to 0.2.
    """

    def __init__(
        self,
        *,
        channels: int,
        leaky_relu_slope: float = 0.2,
    ):
        super().__init__()

        self.weight = nn.Parameter(torch.ones(channels) * 1e-4)
        self.activation = nn.LeakyReLU(leaky_relu_slope)

    def forward(self, x: torch.Tensor):
        gaussian = torch.randn_like(x) * self.weight[None, :, None]
        return self.activation(x + gaussian)


class SineGeneratorLegacy(nn.Module):
    """
    Legacy sine generator with flat l_linear and l_tanh layers.

    Unlike the current SineGenerator which uses a Sequential `merge` module,
    this legacy version uses separate `l_linear` and `l_tanh` attributes,
    matching the original RVC-Boss architecture.

    Args:
        samp_rate (int): Sampling rate in Hz.
        harmonic_num (int): Number of harmonic overtones. Defaults to 0.
        sine_amp (float): Amplitude of sine-waveform. Defaults to 0.1.
        noise_std (float): Standard deviation of Gaussian noise. Defaults to 0.003.
        voiced_threshold (float): F0 threshold for voiced/unvoiced classification. Defaults to 0.
    """

    def __init__(
        self,
        samp_rate,
        harmonic_num=0,
        sine_amp=0.1,
        noise_std=0.003,
        voiced_threshold=0,
    ):
        super(SineGeneratorLegacy, self).__init__()
        self.sine_amp = sine_amp
        self.noise_std = noise_std
        self.harmonic_num = harmonic_num
        self.dim = self.harmonic_num + 1
        self.sampling_rate = samp_rate
        self.voiced_threshold = voiced_threshold

        # Legacy: flat attributes instead of Sequential merge
        self.l_linear = nn.Linear(self.dim, 1, bias=False)
        self.l_tanh = nn.Tanh()

    def _f02uv(self, f0):
        """Generate uv signal."""
        uv = torch.ones_like(f0)
        uv = uv * (f0 > self.voiced_threshold)
        return uv

    def _f02sine(self, f0_values):
        """Convert F0 to sine waves.

        Args:
            f0_values: (batchsize, length, dim) where dim indicates fundamental and overtones
        """
        rad_values = (f0_values / self.sampling_rate) % 1

        rand_ini = torch.rand(
            f0_values.shape[0], f0_values.shape[2], device=f0_values.device
        )
        rand_ini[:, 0] = 0
        rad_values[:, 0, :] = rad_values[:, 0, :] + rand_ini

        tmp_over_one = torch.cumsum(rad_values, 1) % 1
        tmp_over_one_idx = (tmp_over_one[:, 1:, :] - tmp_over_one[:, :-1, :]) < 0
        cumsum_shift = torch.zeros_like(rad_values)
        cumsum_shift[:, 1:, :] = tmp_over_one_idx * -1.0

        sines = torch.sin(torch.cumsum(rad_values + cumsum_shift, dim=1) * 2 * np.pi)

        return sines

    def forward(self, f0):
        with torch.no_grad():
            f0_buf = torch.zeros(f0.shape[0], f0.shape[1], self.dim, device=f0.device)
            f0_buf[:, :, 0] = f0[:, :, 0]
            for idx in np.arange(self.harmonic_num):
                f0_buf[:, :, idx + 1] = f0_buf[:, :, 0] * (idx + 2)

            sine_waves = self._f02sine(f0_buf) * self.sine_amp

            uv = self._f02uv(f0)

            noise_amp = uv * self.noise_std + (1 - uv) * self.sine_amp / 3
            noise = noise_amp * torch.randn_like(sine_waves)

            sine_waves = sine_waves * uv + noise

        # Legacy: apply l_linear and l_tanh separately (not as Sequential)
        sine_waves = self.l_linear(sine_waves)
        sine_waves = self.l_tanh(sine_waves)

        return sine_waves


class RefineGANLegacyGenerator(nn.Module):
    """
    Legacy RefineGAN generator matching the original RVC-Boss architecture.

    This generator uses the original architecture structure with:
    - source_conv (with bias=True) instead of pre_conv
    - SineGeneratorLegacy with flat l_linear/l_tanh instead of Sequential merge
    - downsample_blocks as Sequential(AdaINLegacy, ResBlockLegacy)

    Args:
        sample_rate (int, optional): Sampling rate. Defaults to 44100.
        downsample_rates (tuple[int], optional): Downsampling rates. Defaults to (2, 2, 8, 8).
        upsample_rates (tuple[int], optional): Upsampling rates. Defaults to (8, 8, 2, 2).
        leaky_relu_slope (float, optional): Slope for Leaky ReLU. Defaults to 0.2.
        num_mels (int, optional): Number of mel bins. Defaults to 128.
        start_channels (int, optional): Initial channel count. Defaults to 16.
        gin_channels (int, optional): Global conditioning channels. Defaults to 256.
        checkpointing (bool, optional): Use gradient checkpointing. Defaults to False.
        upsample_initial_channel (int, optional): Initial upsampling channels. Defaults to 512.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 44100,
        downsample_rates: tuple[int] = (2, 2, 8, 8),
        upsample_rates: tuple[int] = (8, 8, 2, 2),
        leaky_relu_slope: float = 0.2,
        num_mels: int = 128,
        start_channels: int = 16,
        gin_channels: int = 256,
        checkpointing: bool = False,
        upsample_initial_channel=512,
    ):
        super().__init__()
        self.upsample_rates = upsample_rates
        self.leaky_relu_slope = leaky_relu_slope
        self.checkpointing = checkpointing

        self.upp = np.prod(upsample_rates)
        self.m_source = SineGeneratorLegacy(sample_rate)

        # Legacy: source_conv with bias=True (current pre_conv has no bias)
        self.source_conv = weight_norm(
            nn.Conv1d(
                1,
                16,
                7,
                1,
                padding=3,
                bias=True,
            )
        )

        # f0 downsampling and upchanneling
        # Legacy: Sequential(AdaINLegacy, ResBlockLegacy) instead of single Conv1d
        channels = start_channels
        size = self.upp
        self.downsample_blocks = nn.ModuleList([])
        self.df0 = []
        for i, u in enumerate(upsample_rates):
            new_size = int(size / upsample_rates[-i - 1])
            self.df0.append([size, new_size])
            size = new_size

            new_channels = channels * 2
            # Legacy structure: Sequential(AdaINLegacy, ResBlockLegacy)
            self.downsample_blocks.append(
                nn.Sequential(
                    AdaINLegacy(channels=channels, leaky_relu_slope=leaky_relu_slope),
                    ResBlockLegacy(
                        in_channels=channels,
                        out_channels=new_channels,
                        kernel_size=7,
                        dilation=(1, 3, 5),
                        leaky_relu_slope=leaky_relu_slope,
                    ),
                )
            )
            channels = new_channels

        # mel handling
        channels = upsample_initial_channel

        self.mel_conv = weight_norm(
            nn.Conv1d(
                num_mels,
                channels // 2,
                7,
                1,
                padding=3,
            )
        )

        self.mel_conv.apply(init_weights)

        if gin_channels != 0:
            self.cond = nn.Conv1d(256, channels // 2, 1)

        # upsample blocks (import from current implementation)
        from rvc.lib.algorithm.generators.refinegan import ParallelResBlock

        self.upsample_blocks = nn.ModuleList([])
        self.upsample_conv_blocks = nn.ModuleList([])

        for rate in upsample_rates:
            new_channels = channels // 2

            self.upsample_blocks.append(nn.Upsample(scale_factor=rate, mode="linear"))

            self.upsample_conv_blocks.append(
                ParallelResBlock(
                    in_channels=channels + channels // 4,
                    out_channels=new_channels,
                    kernel_sizes=(3, 7, 11),
                    dilation=(1, 3, 5),
                    leaky_relu_slope=leaky_relu_slope,
                )
            )

            channels = new_channels

        self.conv_post = weight_norm(
            nn.Conv1d(channels, 1, 7, 1, padding=3, bias=False)
        )
        self.conv_post.apply(init_weights)

    def forward(self, mel: torch.Tensor, f0: torch.Tensor, g: torch.Tensor = None):
        f0_size = mel.shape[-1]
        # change f0 helper to full size
        f0 = F.interpolate(f0.unsqueeze(1), size=f0_size * self.upp, mode="linear")
        # get f0 turned into sines harmonics
        har_source = self.m_source(f0.transpose(1, 2)).transpose(1, 2)
        # prepare for fusion to mel
        x = self.source_conv(har_source)
        # downsampled/upchanneled versions for each upscale
        downs = []
        for block, (old_size, new_size) in zip(self.downsample_blocks, self.df0):
            downs.append(x)
            # attempt to cancel spectral aliasing
            x = torchaudio.functional.resample(
                x.contiguous(),
                orig_freq=int(f0_size * old_size),
                new_freq=int(f0_size * new_size),
                lowpass_filter_width=64,
                rolloff=0.9475937167399596,
                resampling_method="sinc_interp_kaiser",
                beta=14.769656459379492,
            )
            x = block(x)

        # expanding spectrogram from 192 to 256 channels
        mel = self.mel_conv(mel)
        if g is not None:
            # adding expanded speaker embedding
            mel = mel + self.cond(g)

        x = torch.cat([mel, x], dim=1)

        for ups, res, down in zip(
            self.upsample_blocks,
            self.upsample_conv_blocks,
            reversed(downs),
        ):
            x = F.leaky_relu(x, self.leaky_relu_slope)

            if self.training and self.checkpointing:
                x = checkpoint(ups, x, use_reentrant=False)
                x = torch.cat([x, down], dim=1)
                x = checkpoint(res, x, use_reentrant=False)
            else:
                x = ups(x)
                x = torch.cat([x, down], dim=1)
                x = res(x)

        x = F.leaky_relu(x, self.leaky_relu_slope)
        x = self.conv_post(x)
        x = torch.tanh(x)

        return x

    def remove_weight_norm(self):
        remove_weight_norm(self.source_conv)
        remove_weight_norm(self.mel_conv)
        remove_weight_norm(self.conv_post)

        for block in self.downsample_blocks:
            # block is Sequential(AdaINLegacy, ResBlockLegacy)
            block[1].remove_weight_norm()

        for block in self.upsample_conv_blocks:
            block.remove_weight_norm()
