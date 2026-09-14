# tests/test_patcher_exit_codes.py
"""Anchor-miss exit codes: 0 = patched/already, 2 = anchor miss (fatal).
NEVER import build_macos here (module-level PyInstaller build).
Run: venv_macos/bin/python tests/test_patcher_exit_codes.py"""

import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# (patcher, source file, anchor text to mutate, arg convention). Arg
# conventions verified against each patcher's __main__:
#   "file" -> patcher takes the SOURCE FILE path (arbitrary location OK);
#   "dir"  -> patcher takes the DIRECTORY and joins a fixed filename inside
#             it (patch_train_paths looks for <base>/train.py).
# patch_browse_buttons is deliberately NOT a case: apply() rejects any target
# whose path relative to the REPO is not a registered tabs/... file (line
# 177), so it cannot be exercised on a temp copy at all.
CASES = [
    ("patches/patch_progress_routes.py", "app.py", "prevent_thread_lock=", "file"),
    ("patches/patch_web_a11y_payload.py", "app.py", "def launch_gradio(", "file"),
    (
        "patches/patch_train_paths.py",
        "rvc/train/train.py",
        "current_dir = os.getcwd()",
        "dir",
    ),
]
# All CASES anchors occur EXACTLY ONCE in their pristine source (verified
# 2026-08-21) — replace-all is still used defensively below.

EXEMPT = {"download_pretraineds.py"}  # downloader, not an anchor patcher


def _run(patcher, target):
    return subprocess.run(
        [PY, os.path.join(REPO, patcher), target], capture_output=True, text=True
    )


def test_patcher_exit_codes_behavioral():
    for patcher, source, anchor, convention in CASES:
        tmp = tempfile.mkdtemp()
        dst = os.path.join(tmp, os.path.basename(source))
        shutil.copy(os.path.join(REPO, source), dst)
        arg = dst if convention == "file" else tmp
        first = _run(patcher, arg)
        assert first.returncode == 0, (patcher, first.returncode, first.stdout)
        again = _run(patcher, arg)  # already-patched input
        assert again.returncode == 0, (patcher, again.returncode, again.stdout)
        # Mutate the anchor in a FRESH copy -> miss -> exit 2.
        shutil.copy(os.path.join(REPO, source), dst)
        with open(dst, encoding="utf8") as fh:
            content = fh.read()
        assert anchor in content, (patcher, anchor)
        with open(dst, "w", encoding="utf8") as fh:
            # Insert MID-anchor (not append): appending after the anchor text
            # would leave the anchor substring intact for substring matchers
            # (patch_web_a11y_payload's content.find, patch_train_paths' `in`),
            # so the patcher would still succeed. All CASES anchors are >= 8
            # chars, so the [:4]/[4:] split is safe.
            fh.write(content.replace(anchor, anchor[:4] + "_MUTATED_" + anchor[4:]))
        miss = _run(patcher, arg)
        assert miss.returncode == 2, (patcher, miss.returncode, miss.stdout)


def test_no_unclassified_exit1_remains():
    # Every remaining sys.exit(1) in patches/patch_*.py must be a usage guard
    # (argv check nearby) or live on a line that also closes a triple-quoted
    # injected block (the two known sites end with 'sys.exit(1)"""').
    violations = []
    patches_dir = os.path.join(REPO, "patches")
    for name in sorted(os.listdir(patches_dir)):
        if not (name.startswith("patch_") and name.endswith(".py")) or name in EXEMPT:
            continue
        with open(os.path.join(patches_dir, name), encoding="utf8") as fh:
            lines = fh.readlines()
        for i, line in enumerate(lines):
            if "sys.exit(1)" not in line:
                continue
            if '"""' in line:  # injected-string site
                continue
            context = "".join(lines[max(0, i - 4) : i + 1])
            if "argv" not in context and "argc" not in context:
                violations.append(f"{name}:{i + 1}")
    assert not violations, f"unclassified sys.exit(1) sites: {violations}"


def run_all():
    test_patcher_exit_codes_behavioral()
    test_no_unclassified_exit1_remains()
    print("All patcher exit-code tests passed (2).")


if __name__ == "__main__":
    run_all()
