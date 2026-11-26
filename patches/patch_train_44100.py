#!/usr/bin/env python3
"""
Patcher for the fork-only 44.1 kHz training sample rate (upstream 3.7.2).

Sub-patches, all required:
  1. tabs/train/train.py: the sampling-rate widget gets "44100" in its choices.
     Upstream 97e2fdc3 turned the widget from gr.Radio into gr.Dropdown; both are
     accepted.
  2. tabs/train/train.py: toggle_vocoder() HiFi-GAN choices get "44100".
  3. tabs/train/train.py: toggle_vocoder() RefineGAN choices get "44100".
  4. core.py (repository root, located relative to the train tab): the CLI
     --sample-rate choices of `preprocess` and `train` get "44100". `extract`
     already lists it upstream.

Exit codes:
  0  applied, or already applied and verified
  2  a required anchor was not found, or the patched result failed verification
     (nothing is written in that case)

Usage:
    python patches/patch_train_44100.py [path/to/train.py | path/to/its/dir] [--dry-run]
"""

import argparse
import re
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 2

RATES_OLD = '"32000", "40000", "48000"'
RATES_NEW = '"32000", "40000", "44100", "48000"'
REFINEGAN_OLD = '"24000", "32000"'
REFINEGAN_NEW = '"24000", "32000", "44100"'

CLI_OLD = "click.Choice([%s])" % RATES_OLD
CLI_NEW = "click.Choice([%s])" % RATES_NEW
# `extract` already lists 44100 upstream: 3 = preprocess + train + extract.
CLI_MIN_COUNT = 3

# (sub-patch name, marker, exact number of occurrences once it has landed)
TRAIN_TAB_MARKERS = (
    ("sampling-rate widget choices", "choices=[%s]" % RATES_NEW, 1),
    ("toggle_vocoder HiFi-GAN choices", '"choices": [%s]' % RATES_NEW, 1),
    ("toggle_vocoder RefineGAN choices", '"choices": [%s]' % REFINEGAN_NEW, 1),
)

WIDGET_RE = re.compile(r"sampling_rate\s*=\s*gr\.(?:Radio|Dropdown)\(")
HIFIGAN_RE = re.compile(
    r'(if\s+vocoder\s*==\s*"HiFi-GAN":\s*return\s*\{[^}]*"choices":\s*\[)'
    r'("32000",\s*"40000",\s*"48000")(\])',
    re.DOTALL,
)
REFINEGAN_RE = re.compile(
    r'(def\s+toggle_vocoder\(vocoder\):[^}]+if\s+vocoder\s*==\s*"HiFi-GAN"[^}]+\}'
    r'[^}]*else:\s*return\s*\{[^}]*"choices":\s*\[)'
    r'("24000",\s*"32000")(\])',
    re.DOTALL,
)


class PatchError(Exception):
    """A required anchor was not found, or did not behave as expected."""


def _call_end(text, open_index):
    """Index of the ")" that closes the "(" at open_index, or -1."""
    depth = 0
    quote = None
    i = open_index
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def patch_widget_choices(content):
    """Add 44100 to the choices of the sampling-rate widget (Radio or Dropdown)."""
    name = "sampling-rate widget choices"
    matches = list(WIDGET_RE.finditer(content))
    if len(matches) != 1:
        raise PatchError(
            "%s: expected exactly one 'sampling_rate = gr.Radio/gr.Dropdown(' "
            "definition, found %d" % (name, len(matches))
        )
    match = matches[0]
    close_index = _call_end(content, match.end() - 1)
    if close_index == -1:
        raise PatchError("%s: unbalanced parentheses after the widget" % name)
    section = content[match.start() : close_index]
    if '"44100"' in section:
        return content, "already"
    old = "choices=[%s]" % RATES_OLD
    if old not in section:
        raise PatchError(
            "%s: widget found but its choices are not %r (upstream changed again?)"
            % (name, old)
        )
    section = section.replace(old, "choices=[%s]" % RATES_NEW, 1)
    return content[: match.start()] + section + content[close_index:], "applied"


def patch_toggle_vocoder_hifigan(content):
    """Add 44100 to the HiFi-GAN choices returned by toggle_vocoder()."""
    name = "toggle_vocoder HiFi-GAN choices"
    if '"choices": [%s]' % RATES_NEW in content:
        return content, "already"
    new, count = HIFIGAN_RE.subn(
        lambda match: match.group(1) + RATES_NEW + match.group(3), content
    )
    if count != 1:
        raise PatchError("%s: anchor not found (%d matches)" % (name, count))
    return new, "applied"


def patch_toggle_vocoder_refinegan(content):
    """Add 44100 to the RefineGAN choices returned by toggle_vocoder()."""
    name = "toggle_vocoder RefineGAN choices"
    if '"choices": [%s]' % REFINEGAN_NEW in content:
        return content, "already"
    new, count = REFINEGAN_RE.subn(
        lambda match: match.group(1) + REFINEGAN_NEW + match.group(3), content
    )
    if count != 1:
        raise PatchError("%s: anchor not found (%d matches)" % (name, count))
    return new, "applied"


def patch_cli_choices(content):
    """Add 44100 to every 3-rate CLI --sample-rate choice list in core.py."""
    name = "core.py CLI --sample-rate choices"
    old_count = content.count(CLI_OLD)
    new_count = content.count(CLI_NEW)
    if old_count == 0:
        if new_count < CLI_MIN_COUNT:
            raise PatchError("%s: anchor %r not found" % (name, CLI_OLD))
        return content, "already"
    new = content.replace(CLI_OLD, CLI_NEW)
    if CLI_OLD in new or new.count(CLI_NEW) != new_count + old_count:
        raise PatchError("%s: replacement did not land as expected" % name)
    return new, "applied"


def verify(train_content, core_content):
    """Return a list of problems; empty means every sub-patch has landed."""
    problems = []
    for name, marker, expected in TRAIN_TAB_MARKERS:
        found = train_content.count(marker)
        if found != expected:
            problems.append(
                "tabs/train/train.py: %s: expected %d x %r, found %d"
                % (name, expected, marker, found)
            )
    found = core_content.count(CLI_NEW)
    if CLI_OLD in core_content or found < CLI_MIN_COUNT:
        problems.append(
            "core.py: expected at least %d x %r and no %r, found %d"
            % (CLI_MIN_COUNT, CLI_NEW, CLI_OLD, found)
        )
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


def _write(path, content):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def main():
    parser = argparse.ArgumentParser(
        description="Add the 44.1 kHz training sample rate (train tab and CLI)"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="tabs/train/train.py",
        help="Path to tabs/train/train.py, or the directory holding it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything",
    )
    args = parser.parse_args()

    train_path = Path(args.file)
    if train_path.is_dir():
        train_path = train_path / "train.py"
    parents = train_path.resolve().parents
    core_path = parents[2] / "core.py" if len(parents) > 2 else None

    def fail(message):
        print("[patch_train_44100] [FAIL] %s" % message)
        print("RESULT: FAILED (exit 2), nothing written")
        return EXIT_FAILED

    if not train_path.is_file():
        return fail("file not found: %s" % train_path)
    if core_path is None or not core_path.is_file():
        return fail(
            "core.py not found at the repository root relative to %s" % train_path
        )

    print("Patching: %s" % train_path)
    print("Patching: %s" % core_path)
    print("Mode: %s" % ("dry-run" if args.dry_run else "apply"))
    print("Results:")

    train_original = _read(train_path)
    core_original = _read(core_path)
    train_content, core_content = train_original, core_original
    try:
        for name, step in (
            ("sampling-rate widget choices", patch_widget_choices),
            ("toggle_vocoder HiFi-GAN choices", patch_toggle_vocoder_hifigan),
            ("toggle_vocoder RefineGAN choices", patch_toggle_vocoder_refinegan),
        ):
            train_content, status = step(train_content)
            print("  [%s] %s" % (status, name))
        core_content, status = patch_cli_choices(core_content)
        print("  [%s] core.py CLI --sample-rate choices" % status)
    except PatchError as error:
        return fail(error)

    problems = verify(train_content, core_content)
    for path, content in ((train_path, train_content), (core_path, core_content)):
        problem = syntax_problem(path, content)
        if problem:
            problems.append(problem)
    if problems:
        return fail("; ".join(problems))

    changed = [
        (path, content)
        for path, original, content in (
            (train_path, train_original, train_content),
            (core_path, core_original, core_content),
        )
        if content != original
    ]
    if args.dry_run:
        for path, _ in changed:
            print("  (dry-run) would write %s" % path)
        print(
            "RESULT: DRY-RUN OK, nothing written (%d file(s) would change)"
            % len(changed)
        )
        return EXIT_OK
    for path, content in changed:
        _write(path, content)
        print("  wrote %s" % path)
    print("RESULT: %s" % ("APPLIED" if changed else "ALREADY APPLIED"))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
