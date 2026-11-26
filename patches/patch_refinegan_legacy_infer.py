"""
Patch to add RefineGAN-Legacy architecture detection in infer.py (upstream 3.7.2).

This patch adds, both required:
1. A helper function `_detect_refinegan_legacy_from_weights()` to detect legacy
   model weights (module level, right after the logging configuration)
2. Logic in VoiceConverter.setup_network() that overrides the vocoder to
   "RefineGAN-Legacy" when legacy weights are detected

This enables loading models trained elsewhere with the legacy RefineGAN architecture
without producing garbage output.

Both edits are pure insertions, so everything upstream has around them is left byte
for byte, including the `isinstance(self.cpt, ONNXRVC)` early return and the
`self.net_g.float().to(self.config.device)` order.

Exit codes:
  0  applied, or already applied and verified
  2  a required anchor was not found, or verification failed (nothing is written)

Needs patches/patch_refinegan_legacy.py (the "RefineGAN-Legacy" vocoder) as well.
"""

import argparse
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 2

_IDEMPOTENCY_MARKER = "# RefineGAN-Legacy inference detection added"

HELPER_MARKER = "def _detect_refinegan_legacy_from_weights(weights: dict) -> bool:"
HELPER_ANCHOR = 'logging.getLogger("faiss.loader").setLevel(logging.WARNING)\n'
HELPER_FUNC = '''def _detect_refinegan_legacy_from_weights(weights: dict) -> bool:
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

DETECT_MARKER = 'self.vocoder = "RefineGAN-Legacy"'
DETECT_ANCHOR = (
    '            self.vocoder = self.cpt.get("vocoder", "HiFi-GAN")\n'
    "            self.net_g = Synthesizer(\n"
)
DETECT_BLOCK = """            # Detect legacy RefineGAN architecture from checkpoint weights
            if self.vocoder == "RefineGAN" and _detect_refinegan_legacy_from_weights(
                self.cpt["weight"]
            ):
                self.vocoder = "RefineGAN-Legacy"
                logging.info("Detected legacy RefineGAN architecture, using RefineGAN-Legacy vocoder")
"""
DETECT_NEW = (
    '            self.vocoder = self.cpt.get("vocoder", "HiFi-GAN")\n'
    + DETECT_BLOCK
    + "            self.net_g = Synthesizer(\n"
)

MARKERS = (
    ("helper _detect_refinegan_legacy_from_weights()", HELPER_MARKER),
    ("legacy detection in setup_network()", DETECT_MARKER),
)
# Upstream lines around the inserted block; they must survive untouched.
UPSTREAM_KEEP = (
    "            if isinstance(self.cpt, ONNXRVC):",
    '            self.net_g.load_state_dict(self.cpt["weight"], strict=False)',
    "            self.net_g = self.net_g.float().to(self.config.device)",
)


class PatchError(Exception):
    """A required anchor was not found, or did not behave as expected."""


def patch_content(content):
    """Return (patched content, [(status, sub-patch name), ...])."""
    notes = []

    if HELPER_MARKER in content:
        notes.append(("already", "helper _detect_refinegan_legacy_from_weights()"))
    elif content.count(HELPER_ANCHOR) == 1:
        content = content.replace(HELPER_ANCHOR, HELPER_ANCHOR + "\n\n" + HELPER_FUNC)
        notes.append(("applied", "helper _detect_refinegan_legacy_from_weights()"))
    else:
        raise PatchError("helper: anchor not found: %r" % HELPER_ANCHOR)

    if DETECT_MARKER in content:
        notes.append(("already", "legacy detection in setup_network()"))
    elif content.count(DETECT_ANCHOR) == 1:
        content = content.replace(DETECT_ANCHOR, DETECT_NEW)
        notes.append(("applied", "legacy detection in setup_network()"))
    else:
        raise PatchError("setup_network: anchor not found: %r" % DETECT_ANCHOR)

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


def patch_infer(base_path, dry_run=False):
    """Patch infer.py; returns the process exit code."""
    infer_path = Path(base_path) / "infer.py"
    tag = "[RefineGAN-Legacy infer.py]"

    def fail(message):
        print("  %s [FAIL] %s" % (tag, message))
        print("  %s RESULT: FAILED (exit 2), nothing written" % tag)
        return EXIT_FAILED

    if not infer_path.is_file():
        return fail("file not found: %s" % infer_path)

    print("%s Patching: %s" % (tag, infer_path))
    print("%s Mode: %s" % (tag, "dry-run" if dry_run else "apply"))
    original = _read(infer_path)
    try:
        content, notes = patch_content(original)
    except PatchError as error:
        return fail(error)
    for status, name in notes:
        print("  %s [%s] %s" % (tag, status, name))

    problems = verify(original, content)
    problem = syntax_problem(infer_path, content)
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
        with open(infer_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        print("  [RefineGAN-Legacy infer.py] wrote %s" % infer_path)
    print(
        "  [RefineGAN-Legacy infer.py] RESULT: %s"
        % ("APPLIED" if changed else "ALREADY APPLIED")
    )
    return EXIT_OK


def main():
    parser = argparse.ArgumentParser(
        description="Add RefineGAN-Legacy architecture detection to rvc/infer/infer.py"
    )
    parser.add_argument(
        "base_path",
        nargs="?",
        default="rvc/infer",
        help="Directory holding infer.py",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything",
    )
    args = parser.parse_args()
    return patch_infer(args.base_path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
