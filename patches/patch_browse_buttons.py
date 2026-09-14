#!/usr/bin/env python3
"""Patch: a11y Browse buttons after each path field (a11y Phase 2).

Inserts one factory call after each of the 13 path-field definitions across
6 upstream tab files, plus a single module import:

    import applio_browse_ui  # after the existing i18n = I18nAuto() line
    ...
    _applio_browse_output_path = applio_browse_ui.browse_button(
        "file", output_path, elem_id="browse-output_path")
    applio_browse_ui.attach_path_validation(output_path, "file")

The two "Folder Name" embedder fields (tabs/train/train.py:574,
tabs/inference/inference.py:1148) are EXCLUDED by design: their handler takes
os.path.basename, so a picked full path would be silently truncated.

Run standalone from the repo root:
    venv_macos/bin/python patches/patch_browse_buttons.py tabs/train/train.py
build_macos.py invokes it once per file with the source path (type "file").
Exit codes: 0 patched/already, 2 anchor miss. Idempotent per file via the
trailing "# _APPLIO_BROWSE_<STEM>" marker (checked with `marker in content`,
so a manual marker-line strip is also honored).
"""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (file, marker tag) -> [(field_var, mode), ...]
FIELDS = {
    "tabs/train/train.py": [
        ("dataset_path", "folder"),
        ("g_pretrained_path", "pth"),
        ("d_pretrained_path", "pth"),
    ],
    "tabs/inference/inference.py": [
        ("output_path", "file"),
        ("input_folder_batch", "folder"),
        ("output_folder_batch", "folder"),
    ],
    "tabs/tts/tts.py": [
        ("input_tts_path", "file"),
        ("output_tts_path", "file"),
        ("output_rvc_path", "file"),
    ],
    "tabs/realtime/realtime.py": [
        ("record_audio_path", "file"),
    ],
    "tabs/voice_blender/voice_blender.py": [
        ("model_fusion_a", "pth"),
        ("model_fusion_b", "pth"),
    ],
    "tabs/extra/sections/processing.py": [
        ("model_view_model_path", "pth"),
    ],
}

MARKERS = {
    "tabs/train/train.py": "_APPLIO_BROWSE_TRAIN",
    "tabs/inference/inference.py": "_APPLIO_BROWSE_INFERENCE",
    "tabs/tts/tts.py": "_APPLIO_BROWSE_TTS",
    "tabs/realtime/realtime.py": "_APPLIO_BROWSE_REALTIME",
    "tabs/voice_blender/voice_blender.py": "_APPLIO_BROWSE_VOICE_BLENDER",
    "tabs/extra/sections/processing.py": "_APPLIO_BROWSE_PROCESSING",
}

IMPORT_LINE = "import applio_browse_ui  # _APPLIO_BROWSE_IMPORT_"
I18N_ANCHOR = re.compile(r"^(i18n = I18nAuto\(\))\s*$", re.MULTILINE)


def _find_statement_end(content, start_idx):
    """Index just past the balanced-paren statement starting at/after start_idx."""
    depth = 0
    seen_open = False
    i = start_idx
    while i < len(content):
        ch = content[i]
        if ch == "(":
            depth += 1
            seen_open = True
        elif ch == ")":
            depth -= 1
            if seen_open and depth == 0:
                # swallow a trailing newline
                j = i + 1
                if j < len(content) and content[j] == "\n":
                    j += 1
                return j
        i += 1
    return -1


def patch_file(content, fields, marker):
    if marker in content:
        return content, "already"
    if not I18N_ANCHOR.search(content):
        print(f"Pattern not found: i18n = I18nAuto() - {marker}")
        return content, "miss"
    patched = I18N_ANCHOR.sub(r"\1\n" + IMPORT_LINE, content, count=1)
    inserted = skipped = 0
    for var, mode in fields:
        m = re.search(
            rf"^(?P<indent>[ \t]*){re.escape(var)} = gr\.(?:Textbox|Dropdown)\(",
            patched,
            re.MULTILINE,
        )
        if not m:
            print(f"Pattern not found: {var} definition - skipped")
            skipped += 1
            continue
        # m.end()-1 points at the "(" the regex matched; balance from there.
        end = _find_statement_end(patched, m.end() - 1)
        if end == -1:
            print(f"Unbalanced statement: {var} - skipped")
            skipped += 1
            continue
        indent = m.group("indent")
        line = (
            f"\n{indent}_applio_browse_{var} = applio_browse_ui.browse_button("
            f'"{mode}", {var}, elem_id="browse-{var}")\n'
            f'{indent}applio_browse_ui.attach_path_validation({var}, "{mode}")\n'
        )
        patched = patched[:end] + line + patched[end:]
        inserted += 1
    if inserted == 0:
        print(f"No fields patched - {marker}")
        return content, "miss"
    patched += f"\n# {marker}\n"
    print(f"Browsed {inserted} field(s), skipped {skipped}")
    return patched, "patched"


def patch_train(content):
    return patch_file(
        content, FIELDS["tabs/train/train.py"], MARKERS["tabs/train/train.py"]
    )


def patch_inference(content):
    return patch_file(
        content,
        FIELDS["tabs/inference/inference.py"],
        MARKERS["tabs/inference/inference.py"],
    )


def patch_tts(content):
    return patch_file(content, FIELDS["tabs/tts/tts.py"], MARKERS["tabs/tts/tts.py"])


def patch_realtime(content):
    return patch_file(
        content,
        FIELDS["tabs/realtime/realtime.py"],
        MARKERS["tabs/realtime/realtime.py"],
    )


def patch_voice_blender(content):
    return patch_file(
        content,
        FIELDS["tabs/voice_blender/voice_blender.py"],
        MARKERS["tabs/voice_blender/voice_blender.py"],
    )


def patch_processing(content):
    return patch_file(
        content,
        FIELDS["tabs/extra/sections/processing.py"],
        MARKERS["tabs/extra/sections/processing.py"],
    )


def apply(path):
    """Patch one file (absolute or repo-relative); returns True on patched/already."""
    rel = os.path.relpath(os.path.abspath(path), REPO).replace(os.sep, "/")
    if rel not in FIELDS:
        print(f"Unknown browse-buttons target: {path} (rel {rel})")
        return False
    with open(path, encoding="utf-8") as f:
        content = f.read()
    patched, status = patch_file(content, FIELDS[rel], MARKERS[rel])
    if status == "patched":
        with open(path, "w", encoding="utf-8") as f:
            f.write(patched)
    print(f"  [browse_buttons] {rel}: {status}")
    return status in ("patched", "already")


if __name__ == "__main__":
    target = (
        sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "tabs/train/train.py")
    )
    sys.exit(0 if apply(target) else 2)
