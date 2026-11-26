"""
Patch to add RefineGAN-Legacy architecture detection in train.py (upstream 3.7.2).

This patch adds, both required:
1. A helper function `_detect_refinegan_legacy()` to detect legacy pretrained models
   (module level, right after the RefineGAN vocoder config)
2. Logic inside run(), right after the `try:` that opens the pretrain-G block, that
   re-instantiates net_g with the RefineGAN-Legacy generator, net_d with
   DiscriminatorRLegacy and both optimizers when a legacy pretrained is detected

The legacy architecture (original RVC-Boss) differs from current Applio RefineGAN:
- Generator: source_conv vs pre_conv, l_linear vs merge.0
- Discriminator: (5,1) kernels vs (3,9), channel expansion vs constant channels
and requires loading with compatible implementations.

Both edits are pure insertions, so everything upstream has around them is left
byte for byte, including the "Overriding the pretrain speaker embedding size" print
and the two `ckpt["emb_g.weight"] = ...` overrides.

Exit codes:
  0  applied, or already applied and verified
  2  a required anchor was not found, or verification failed (nothing is written)

Needs patches/patch_refinegan_legacy_discriminator.py (DiscriminatorRLegacy) and
patches/patch_refinegan_legacy.py (the "RefineGAN-Legacy" vocoder) as well.
"""

import argparse
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 2

_IDEMPOTENCY_MARKER = "# RefineGAN-Legacy detection added"

HELPER_MARKER = "def _detect_refinegan_legacy(pretrain_path: str) -> bool:"
HELPER_ANCHOR = (
    'if vocoder == "RefineGAN":\n'
    '    disc_version = "v3"\n'
    "    multiscale_mel_loss = True\n"
)
HELPER_FUNC = '''

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

DETECT_MARKER = "is_legacy = _detect_refinegan_legacy(pretrainG)"
DETECT_ANCHOR = (
    '        if pretrainG not in ("", "None"):\n'
    "            if rank == 0:\n"
    "                print(f\"Loaded pretrained (G) '{pretrainG}'\")\n"
    "            try:\n"
)
# Inserted straight after the anchor (inside the try:). DDP and dist are the
# module-level names train.py already uses; binding them here would shadow them
# for the whole of run().
DETECT_BLOCK = """                # Detect legacy RefineGAN architecture
                is_legacy = _detect_refinegan_legacy(pretrainG)
                if is_legacy and vocoder == "RefineGAN":
                    if rank == 0:
                        print("Detected legacy RefineGAN architecture, using RefineGAN-Legacy vocoder")
                    # Re-instantiate net_g with the legacy generator
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
                    # Also re-instantiate net_d with the legacy discriminator
                    from rvc.lib.algorithm.discriminators import (
                        DiscriminatorRLegacy,
                        MultiPeriodDiscriminator,
                    )

                    net_d = MultiPeriodDiscriminator(
                        config.model.use_spectral_norm,
                        checkpointing=checkpointing,
                        version="v3",
                        disc_r_class=DiscriminatorRLegacy,
                    )
                    if torch.cuda.is_available():
                        net_g = net_g.cuda(device_id)
                        net_d = net_d.cuda(device_id)
                    else:
                        net_g = net_g.to(device)
                        net_d = net_d.to(device)

                    # Re-wrap with DDP, same condition as the initial wrap
                    if n_gpus > 1 and device.type == "cuda" and dist.is_initialized():
                        net_g = DDP(net_g, device_ids=[device_id])
                        net_d = DDP(net_d, device_ids=[device_id])

                    # Re-create optimizers for the new model parameters
                    optim_g = optimizer(
                        net_g.parameters(),
                        config.train.learning_rate * g_lr_coeff,
                        betas=config.train.betas,
                        eps=config.train.eps,
                    )
                    optim_d = optimizer(
                        net_d.parameters(),
                        config.train.learning_rate * d_lr_coeff,
                        betas=config.train.betas,
                        eps=config.train.eps,
                    )
"""

MARKERS = (
    ("helper _detect_refinegan_legacy()", HELPER_MARKER),
    ("pretrain-G legacy rewrite in run()", DETECT_MARKER),
)
# Upstream lines that follow the inserted block; they must survive untouched.
UPSTREAM_KEEP = (
    'f"Overriding the pretrain speaker embedding size to {spk_dim} speakers."',
    'ckpt["emb_g.weight"] = net_g.module.emb_g.weight.detach().clone()',
    'ckpt["emb_g.weight"] = net_g.emb_g.weight.detach().clone()',
    "                net_g.load_state_dict(ckpt)",
)


class PatchError(Exception):
    """A required anchor was not found, or did not behave as expected."""


def patch_content(content):
    """Return (patched content, [(status, sub-patch name), ...])."""
    notes = []

    if HELPER_MARKER in content:
        notes.append(("already", "helper _detect_refinegan_legacy()"))
    elif content.count(HELPER_ANCHOR) == 1:
        content = content.replace(HELPER_ANCHOR, HELPER_ANCHOR + HELPER_FUNC)
        notes.append(("applied", "helper _detect_refinegan_legacy()"))
    else:
        raise PatchError("helper: anchor not found: %r" % HELPER_ANCHOR)

    if DETECT_MARKER in content:
        notes.append(("already", "pretrain-G legacy rewrite in run()"))
    elif content.count(DETECT_ANCHOR) == 1:
        content = content.replace(DETECT_ANCHOR, DETECT_ANCHOR + DETECT_BLOCK)
        notes.append(("applied", "pretrain-G legacy rewrite in run()"))
    else:
        raise PatchError("pretrain-G rewrite: anchor not found: %r" % DETECT_ANCHOR)

    if _IDEMPOTENCY_MARKER in content:
        notes.append(("already", "idempotency marker"))
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += _IDEMPOTENCY_MARKER + "\n"
        notes.append(("applied", "idempotency marker"))
    return content, notes


def verify(original, content):
    """Return a list of problems; empty means every sub-patch has landed."""
    problems = []
    for name, marker in MARKERS:
        found = content.count(marker)
        if found != 1:
            problems.append("%s: expected 1 x %r, found %d" % (name, marker, found))
    if content.count(_IDEMPOTENCY_MARKER) != 1:
        problems.append(
            "idempotency marker: expected exactly 1 x %r" % _IDEMPOTENCY_MARKER
        )
    for line in UPSTREAM_KEEP:
        if content.count(line) != original.count(line):
            problems.append("upstream line changed: %r" % line)
    return problems


def syntax_problem(path, content):
    """Return a message when the content is not valid Python, else None."""
    try:
        compile(content, str(path), "exec")
    except SyntaxError as error:
        return "%s: does not compile: %s" % (path, error)
    return None


def _read(path):
    # newline="" keeps the file's own line endings, byte for byte.
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def patch_train(base_path, dry_run=False):
    """Patch train.py; returns the process exit code."""
    train_path = Path(base_path) / "train.py"
    tag = "[RefineGAN-Legacy train.py]"

    def fail(message):
        print("  %s [FAIL] %s" % (tag, message))
        print("  %s RESULT: FAILED (exit 2), nothing written" % tag)
        return EXIT_FAILED

    if not train_path.is_file():
        return fail("file not found: %s" % train_path)

    print("%s Patching: %s" % (tag, train_path))
    print("%s Mode: %s" % (tag, "dry-run" if dry_run else "apply"))
    original = _read(train_path)
    try:
        content, notes = patch_content(original)
    except PatchError as error:
        return fail(error)
    for status, name in notes:
        print("  %s [%s] %s" % (tag, status, name))

    problems = verify(original, content)
    problem = syntax_problem(train_path, content)
    if problem:
        problems.append(problem)
    if problems:
        return fail("; ".join(problems))

    changed = content != original
    if dry_run:
        print(
            "  %s RESULT: DRY-RUN OK, nothing written (%s)"
            % (tag, "1 file would change" if changed else "already applied")
        )
        return EXIT_OK
    if changed:
        with open(train_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        print("  [RefineGAN-Legacy train.py] wrote %s" % train_path)
    print(
        "  [RefineGAN-Legacy train.py] RESULT: %s"
        % ("APPLIED" if changed else "ALREADY APPLIED")
    )
    return EXIT_OK


def main():
    parser = argparse.ArgumentParser(
        description="Add RefineGAN-Legacy architecture detection to rvc/train/train.py"
    )
    parser.add_argument(
        "base_path",
        nargs="?",
        default="rvc/train",
        help="Directory holding train.py",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything",
    )
    args = parser.parse_args()
    return patch_train(args.base_path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
