#!/usr/bin/env python3
"""
Patcher: accept 44100 Hz in the built-in pretrained lookup (Applio macOS fork).

Target: rvc/lib/tools/prerequisites_download.py, ensure_pretrained().

Upstream 3.7.2 raises ValueError for any rate outside
    {"HiFi-GAN": (32000, 40000, 48000), "RefineGAN": (24000, 32000)}
so a 44.1 kHz run with "pretrained" enabled cannot start.

What Applio 3.6.2 did (rvc/lib/tools/pretrained_selector.py at 594dcbec): it looked
for rvc/models/pretraineds/<vocoder>/f0G44k.pth and f0D44k.pth
(str(sample_rate)[:2] == "44") and returned ("", "") when either was missing, so the
run continued without pretrains.

Facts this patch relies on:
  - Nothing is hosted for 44100 Hz on IAHispano/Applio: f0G44k.pth and f0D44k.pth
    answer 404 under pretrained_v2/ and refinegan/ (f0G48k.pth answers 200).
  - The 48k pair cannot stand in: rvc/configs/44100.json is a different architecture
    (hop 441, upsample rates 7/7/3/3 against 480 and 12/10/2/2 for 48k).
  - 44k RefineGAN pairs the fork offers (refinegan_klm50_exp1_*, refinegan_vctk_v1_*)
    are community models: users pick them through "Custom Pretrained". They are NOT
    used as a silent built-in default here; that would change training results
    against 3.6.2.

This patch:
  1. adds 44100 to both vocoder rate tuples, so ensure_pretrained() accepts it. File
     names stay f0G44k.pth / f0D44k.pth (int(sample_rate) // 1000), the names 3.6.2
     used;
  2. makes 44100 local-only, never downloaded: when the f0G44k.pth/f0D44k.pth pair
     is installed it is returned; otherwise ensure_pretrained() returns ("", "")
     with a notice and the run continues without pretrains, exactly as in 3.6.2.

Exit codes:
  0  applied, or already applied and verified
  2  a required anchor was not found, or verification failed (nothing is written)

Usage:
    python patches/patch_pretrained_rates.py <dir holding prerequisites_download.py> [--dry-run]
"""

import argparse
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 2

TARGET = "prerequisites_download.py"

RATES_OLD = (
    '    rates = {"HiFi-GAN": (32000, 40000, 48000), "RefineGAN": (24000, 32000)}\n'
)
RATES_NEW = (
    '    rates = {"HiFi-GAN": (32000, 40000, 44100, 48000), '
    '"RefineGAN": (24000, 32000, 44100)}\n'
)

PATHS_ANCHOR = (
    "        for file in files\n"
    "    ]\n"
    "    if not all(is_downloaded(file) for file in paths):\n"
)
LOCAL_ONLY_BLOCK = """    if int(sample_rate) == 44100:
        # Applio macOS fork: nothing is hosted for 44100 Hz, so never download.
        # Use the f0G44k/f0D44k pair Applio 3.6.2 looked for when it is installed;
        # otherwise continue without pretrains, exactly as 3.6.2 did, with a notice.
        if all(is_downloaded(file) for file in paths):
            return tuple(paths)
        print(
            f"No {vocoder} pretrains for {sample_rate} Hz are installed; continuing "
            "without pretrains (44.1 kHz needs a custom 44k pretrained).",
            flush=True,
        )
        return "", ""
"""
PATHS_NEW = (
    "        for file in files\n"
    "    ]\n"
    + LOCAL_ONLY_BLOCK
    + "    if not all(is_downloaded(file) for file in paths):\n"
)

# (sub-patch name, marker); each must appear exactly once once it has landed.
MARKERS = (
    ("rates accept 44100 (HiFi-GAN)", '"HiFi-GAN": (32000, 40000, 44100, 48000)'),
    ("rates accept 44100 (RefineGAN)", '"RefineGAN": (24000, 32000, 44100)'),
    (
        "44100 is resolved locally, never downloaded",
        "    if int(sample_rate) == 44100:\n",
    ),
    (
        "44100 without an installed pair continues without pretrains",
        '        return "", ""\n    if not all(is_downloaded(file) for file in paths):\n',
    ),
)
# Upstream lines around the inserted block; they must survive untouched.
UPSTREAM_KEEP = (
    "            download_mapping_files(mapping, bar)",
    'raise RuntimeError("Default pretrains are missing; training cannot start.")',
)


class PatchError(Exception):
    """A required anchor was not found, or did not behave as expected."""


def patch_content(content):
    """Return (patched content, [(status, sub-patch name), ...])."""
    notes = []

    rates_done = MARKERS[0][1] in content and MARKERS[1][1] in content
    if rates_done:
        notes.append(("already", "rates accept 44100"))
    elif content.count(RATES_OLD) == 1:
        content = content.replace(RATES_OLD, RATES_NEW)
        notes.append(("applied", "rates accept 44100"))
    else:
        raise PatchError("rates: anchor not found: %r" % RATES_OLD.strip())

    if MARKERS[2][1] in content:
        notes.append(("already", "44100 local-only block"))
    elif content.count(PATHS_ANCHOR) == 1:
        content = content.replace(PATHS_ANCHOR, PATHS_NEW)
        notes.append(("applied", "44100 local-only block"))
    else:
        raise PatchError("44100 local-only block: anchor not found: %r" % PATHS_ANCHOR)
    return content, notes


def verify(original, content):
    """Return a list of problems; empty means every sub-patch has landed."""
    problems = []
    for name, marker in MARKERS:
        found = content.count(marker)
        if found != 1:
            problems.append("%s: expected 1 x %r, found %d" % (name, marker, found))
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


def patch_pretrained_rates(base_path, dry_run=False):
    """Patch ensure_pretrained(); returns the process exit code."""
    target_path = Path(base_path) / TARGET

    def fail(message):
        print("[patch_pretrained_rates] [FAIL] %s" % message)
        print("RESULT: FAILED (exit 2), nothing written")
        return EXIT_FAILED

    if not target_path.is_file():
        return fail("file not found: %s" % target_path)

    print("Patching: %s" % target_path)
    print("Mode: %s" % ("dry-run" if dry_run else "apply"))
    print("Results:")
    original = _read(target_path)
    try:
        content, notes = patch_content(original)
    except PatchError as error:
        return fail(error)
    for status, name in notes:
        print("  [%s] %s" % (status, name))

    problems = verify(original, content)
    problem = syntax_problem(target_path, content)
    if problem:
        problems.append(problem)
    if problems:
        return fail("; ".join(problems))

    changed = content != original
    if dry_run:
        print(
            "RESULT: DRY-RUN OK, nothing written (%s)"
            % ("1 file would change" if changed else "already applied")
        )
        return EXIT_OK
    if changed:
        with open(target_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        print("  wrote %s" % target_path)
    print("RESULT: %s" % ("APPLIED" if changed else "ALREADY APPLIED"))
    return EXIT_OK


def main():
    parser = argparse.ArgumentParser(
        description="Accept 44100 Hz in the built-in pretrained lookup"
    )
    parser.add_argument(
        "base_path",
        nargs="?",
        default="rvc/lib/tools",
        help="Directory holding prerequisites_download.py",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything",
    )
    args = parser.parse_args()
    return patch_pretrained_rates(args.base_path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
